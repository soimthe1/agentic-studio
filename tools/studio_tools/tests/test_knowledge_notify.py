import json
import socket

import httpx
import pytest

from studio_tools.core import envelope
from studio_tools.core import notify as N
from studio_tools.core.errors import ConfigError, NotAllowed, ToolTimeout, UpstreamError
from studio_tools.core.knowledge import Unavailable, knowledge_query

KP = {"_name": "knowledge", "enabled": True, "base_url": "http://kp.local:8082",
      "auth": {"type": "delegated", "token_env": "STUDIO_TOOL_KP", "on_behalf_of_header": "X-On-Behalf-Of"}}


# ------------------------------------------------------------------------------------------------ knowledge

def test_knowledge_unavailable_by_default(mock_http):
    _, calls = mock_http
    with pytest.raises(Unavailable, match="not available"):
        knowledge_query({"enabled": False}, mode="answer", query="q", as_user="ali")
    env = envelope.run(lambda: knowledge_query(None, mode="answer", query="q", as_user="ali"), source={})
    assert env["ok"] is False and env["error"]["code"] == "unavailable"
    assert calls == []


def test_knowledge_refuses_shared_account():
    with pytest.raises(ConfigError, match="delegated"):
        knowledge_query({**KP, "auth": {"type": "service_account"}}, mode="search", query="q", as_user="ali")
    with pytest.raises(NotAllowed, match="requesting user"):
        knowledge_query(KP, mode="search", query="q", as_user=None)


def test_knowledge_delegated_calls_real_endpoints(mock_http, monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_KP", "svc-token")
    set_handler, calls = mock_http

    def handler(r):
        if r.url.path == "/v1/search":
            return httpx.Response(200, json={"results": [{"doc_id": "d1", "title": "Runbook", "text": "x" * 3000,
                                                          "score": 0.9, "level_name": "Internal"}],
                                             "max_level_seen": 1})
        return httpx.Response(200, json={"answer": "Do X", "citations": [{"doc_id": "d1"}], "max_level_seen": 1,
                                         "banner": "INTERNAL"})
    set_handler(handler)
    s = knowledge_query(KP, mode="search", query="iis pool recycle", as_user="ali", top_k=50)
    assert s["results"][0]["text"].endswith("...") and len(s["results"][0]["text"]) == 2003
    assert json.loads(calls[0].content) == {"query": "iis pool recycle", "top_k": 10}
    a = knowledge_query(KP, mode="answer", query="how?", as_user="ali")
    assert a["answer"] == "Do X"
    body = json.loads(calls[1].content)
    assert calls[1].url.path == "/v1/ask" and body["stream"] is False
    assert calls[1].headers["Authorization"] == "Bearer svc-token" and calls[1].headers["X-On-Behalf-Of"] == "ali"


# --------------------------------------------------------------------------------------------------- notify

class FakeSMTP:
    sent: list = []
    fail: Exception | None = None

    def __init__(self, host, port, timeout=None, **kw):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        self.host, self.port, self.timeout = host, port, timeout
        self.logged_in = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, pw):
        self.logged_in = (user, pw)

    def send_message(self, msg):
        FakeSMTP.sent.append((self, msg))


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.fail = [], None
    monkeypatch.setattr(N.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


EMAIL = {"_name": "dba_email", "type": "smtp", "host": "relay.local", "port": 25, "starttls": True,
         "username": "svc", "password_env": "STUDIO_TOOL_SMTP", "from_addr": "agent-studio@example.org", "to": ["dba@example.org"]}


def test_notify_dry_run_default_sends_nothing(smtp):
    out = N.send(EMAIL, subject="s", body="b")
    assert out["status"] == "dry_run" and smtp.sent == []
    assert out["preview"]["to"] == ["dba@example.org"]


def test_notify_requires_approval(smtp):
    out = N.send(EMAIL, subject="s", body="b", dry_run=False)
    assert out["status"] == "not_approved" and smtp.sent == []


def test_notify_sends_with_approval_and_env_secret(smtp, monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_SMTP", "mail-pw")
    out = N.send(EMAIL, subject="Disk low", body="WEB01 C: 3%", severity="critical", approved=True, dry_run=False)
    assert out["status"] == "sent" and len(smtp.sent) == 1
    server, msg = smtp.sent[0]
    assert msg["Subject"] == "[CRITICAL] Disk low" and msg["To"] == "dba@example.org"
    assert server.logged_in == ("svc", "mail-pw") and server.tls and server.timeout == 15


def test_notify_preapproved_channel(smtp):
    ch = {**EMAIL, "username": None, "requires_approval": False}
    assert N.send(ch, subject="s", body="b", dry_run=False)["status"] == "sent"


def test_notify_smtp_timeout_clean_and_not_retried(smtp):
    smtp.fail = socket.timeout("timed out")
    with pytest.raises(ToolTimeout, match="not retried"):
        N.send({**EMAIL, "username": None}, subject="s", body="b", approved=True, dry_run=False)
    smtp.fail = ConnectionRefusedError(111, "refused")
    with pytest.raises(UpstreamError, match="cannot reach"):
        N.send({**EMAIL, "username": None}, subject="s", body="b", approved=True, dry_run=False)


def test_notify_input_limits(smtp):
    with pytest.raises(NotAllowed):
        N.send(EMAIL, subject="", body="b")
    with pytest.raises(NotAllowed):
        N.send(EMAIL, subject="s", body="b", severity="panic")
    with pytest.raises(NotAllowed):
        N.send(EMAIL, subject="s", body="x" * 20001)


CHAT = {"_name": "ops_chat", "type": "webhook", "url": "https://chat.local/hooks/abc", "format": "text",
        "requires_approval": False}


def test_webhook_posts_once_never_retried(mock_http):
    set_handler, calls = mock_http
    set_handler(lambda r: httpx.Response(503))
    with pytest.raises(UpstreamError, match="not retried"):
        N.send(CHAT, subject="s", body="b", dry_run=False)
    assert len(calls) == 1
    set_handler(lambda r: httpx.Response(200))
    assert N.send(CHAT, subject="s", body="b", dry_run=False)["status"] == "sent"
    assert json.loads(calls[-1].content) == {"text": "**s**\n\nb"}
    assert str(calls[-1].url) == "https://chat.local/hooks/abc"
