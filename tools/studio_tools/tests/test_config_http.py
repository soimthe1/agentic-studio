import httpx
import pytest

from studio_tools.core import config as C
from studio_tools.core import http as H
from studio_tools.core.errors import ConfigError, NotAllowed, ToolTimeout, UpstreamError
from studio_tools.core.util import check_agent_scope

API = {"_name": "hr", "base_url": "https://hr.example.org/api", "auth": {"type": "bearer", "token_env": "STUDIO_TOOL_HR"}}


def test_inline_secret_rejected(write_cfg):
    with pytest.raises(ConfigError, match="inline secret"):
        write_cfg({"sql": {"a": {"dialect": "sqlite", "password": "hunter2"}}})


def test_unknown_section_rejected(write_cfg):
    with pytest.raises(ConfigError, match="unknown sections"):
        write_cfg({"servers": {}})


def test_missing_config_file(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_TOOLS_CONFIG", str(tmp_path / "none.yaml"))
    C._cache.clear()
    with pytest.raises(ConfigError, match="not found"):
        C.load_config()


def test_config_dir_default(monkeypatch, tmp_path):
    monkeypatch.delenv("STUDIO_TOOLS_CONFIG", raising=False)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    assert C.config_path() == tmp_path / "tools.yaml"
    monkeypatch.delenv("CONFIG_DIR")
    assert C.config_path().as_posix() == "/app/config/tools.yaml"


def test_secret_from_env_and_missing_env_message_has_no_value(monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_HR", "tok-123")
    assert H.auth_headers(API) == {"Authorization": "Bearer tok-123"}
    monkeypatch.delenv("STUDIO_TOOL_HR")
    with pytest.raises(ConfigError) as e:
        H.auth_headers(API)
    assert "STUDIO_TOOL_HR" in str(e.value) and "tok-123" not in str(e.value)


def test_example_yaml_is_valid(monkeypatch):
    from pathlib import Path
    monkeypatch.setenv("STUDIO_TOOLS_CONFIG", str(Path(__file__).resolve().parents[1] / "tools.example.yaml"))
    C._cache.clear()
    cfg = C.load_config()
    assert {"sql", "apps", "knowledge", "notify", "documents"} <= set(cfg)
    C._cache.clear()


@pytest.mark.parametrize("path", ["https://evil.example/x", "//evil.example/x", "http://hr.example.org.evil/x",
                                  "file:///etc/passwd", "https://user:pw@hr.example.org/x"])
def test_host_allowlist(path):
    with pytest.raises(NotAllowed):
        H.resolve_url(API, path)


def test_relative_and_allowed_hosts():
    assert H.resolve_url(API, "/v1/people") == "https://hr.example.org/api/v1/people"
    conn = {**API, "allowed_hosts": ["hr2.example.org"]}
    assert H.resolve_url(conn, "https://hr2.example.org/x") == "https://hr2.example.org/x"


def test_get_retried_once_on_503_post_never(mock_http, monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_HR", "t")
    set_handler, calls = mock_http
    set_handler(lambda r: httpx.Response(503))
    assert H.request(API, "GET", "/x").status_code == 503
    assert len(calls) == 2
    calls.clear()
    assert H.request(API, "POST", "/x", json_body={}).status_code == 503
    assert len(calls) == 1


def test_redirect_not_followed(mock_http, monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_HR", "t")
    set_handler, calls = mock_http
    set_handler(lambda r: httpx.Response(302, headers={"Location": "http://evil.example/"}))
    with pytest.raises(UpstreamError, match="redirect"):
        H.request(API, "GET", "/x")
    assert all(c.url.host == "hr.example.org" for c in calls)


def test_timeout_is_clean_error(mock_http, monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_HR", "t")
    set_handler, calls = mock_http

    def boom(r):
        raise httpx.ReadTimeout("slow", request=r)
    set_handler(boom)
    with pytest.raises(ToolTimeout, match="timed out"):
        H.request(API, "GET", "/x")
    calls.clear()
    with pytest.raises(ToolTimeout):
        H.request(API, "POST", "/x")
    assert len(calls) == 1  # writes never retried, not even on timeout


def test_http_error_body_is_clean(mock_http):
    set_handler, _ = mock_http
    set_handler(lambda r: httpx.Response(500, json={"detail": "boom"}))
    resp = H.request({"_name": "a", "base_url": "http://a.local"}, "GET", "/x", retries=0)
    with pytest.raises(UpstreamError, match="HTTP 500: boom"):
        H.body_of(resp)


def test_agent_scope():
    check_agent_scope("a", "")
    check_agent_scope("a", "a, b")
    with pytest.raises(NotAllowed, match="not enabled for this agent"):
        check_agent_scope("c", "a,b")
