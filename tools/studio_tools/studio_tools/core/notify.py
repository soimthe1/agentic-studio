"""Notifications to named channels: SMTP email or an internal chat webhook. Never auto-retried.

Recipients and webhook URLs are fixed per channel in tools.yaml; the LLM picks a channel name, never an address.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import http as H
from .config import secret
from .redact import redact
from .errors import ConfigError, NotAllowed, ToolTimeout, UpstreamError
from .spec import approval_gate

MAX_SUBJECT = 200
MAX_BODY = 20_000
SEVERITIES = ("info", "warning", "critical")


def _prefix(subject: str, severity: str) -> str:
    return subject if severity == "info" else f"[{severity.upper()}] {subject}"


def preview(channel: dict[str, Any], subject: str, body: str, severity: str) -> dict[str, Any]:
    kind = channel.get("type")
    target = channel.get("to") if kind == "smtp" else urlsplit(channel.get("url", "")).hostname
    return {"channel": channel["_name"], "type": kind, "to": target, "subject": _prefix(subject, severity),
            "body": body}


def send(channel: dict[str, Any], *, subject: str, body: str, severity: str = "info", approved: bool = False,
         dry_run: bool = True) -> dict[str, Any]:
    subject = redact((subject or "").strip())[:MAX_SUBJECT]
    body = redact((body or "").strip())       # secrets and personal identifiers never posted as they are
    if not subject or not body:
        raise NotAllowed("subject and body are required")
    if len(body) > MAX_BODY:
        raise NotAllowed(f"body exceeds {MAX_BODY} characters")
    severity = (severity or "info").lower()
    if severity not in SEVERITIES:
        raise NotAllowed(f"severity must be one of {SEVERITIES}")
    kind = channel.get("type")
    if kind not in ("smtp", "webhook"):
        raise ConfigError(f"channel '{channel['_name']}' has unknown type '{kind}' (smtp | webhook)")
    # A channel the admin marked requires_approval: false (e.g. the ops alert room for scheduled health checks)
    # is pre-approved by configuration; every other channel needs approved=true from the flow.
    pre_approved = channel.get("requires_approval", True) is False
    reason = approval_gate(approved=approved or pre_approved, dry_run=dry_run, write_allowed=True,
                           what=f"notify '{channel['_name']}'")
    info = preview(channel, subject, body, severity)
    if reason:
        return {"status": "dry_run" if dry_run else "not_approved", "reason": reason, "preview": info}
    if kind == "smtp":
        _send_smtp(channel, _prefix(subject, severity), body)
    else:
        _send_webhook(channel, subject, body, severity)
    return {"status": "sent", "preview": info}


def _send_smtp(ch: dict[str, Any], subject: str, body: str) -> None:
    to = ch.get("to") or []
    if isinstance(to, str):
        to = [to]
    if not to or not ch.get("from_addr") or not ch.get("host"):
        raise ConfigError(f"smtp channel '{ch['_name']}' needs host, from_addr and to")
    msg = EmailMessage()
    msg["From"] = ch["from_addr"]
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    timeout = float(ch.get("timeout_s", 15))
    ctx = ssl.create_default_context(cafile=ch.get("ca_bundle")) if (ch.get("ssl") or ch.get("starttls")) else None
    if ctx is not None and ch.get("verify_tls") is False:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        if ch.get("ssl"):
            server = smtplib.SMTP_SSL(ch["host"], int(ch.get("port", 465)), timeout=timeout, context=ctx)
        else:
            server = smtplib.SMTP(ch["host"], int(ch.get("port", 25)), timeout=timeout)
        with server:
            if ch.get("starttls") and not ch.get("ssl"):
                server.starttls(context=ctx)
            if ch.get("username"):
                server.login(ch["username"], secret(ch, "password"))
            server.send_message(msg)
    except (socket.timeout, TimeoutError):
        raise ToolTimeout(f"SMTP server {ch['host']} timed out (message not confirmed sent; not retried)") from None
    except smtplib.SMTPException as exc:
        raise UpstreamError(f"SMTP error: {type(exc).__name__}: {str(exc)[:300]} (not retried)") from None
    except OSError as exc:
        raise UpstreamError(f"cannot reach SMTP server {ch['host']}: {exc.strerror or exc} (not retried)") from None


def _send_webhook(ch: dict[str, Any], subject: str, body: str, severity: str) -> None:
    url = ch.get("url")
    if not url:
        raise ConfigError(f"webhook channel '{ch['_name']}' needs url")
    fmt = ch.get("format", "text")
    if fmt == "text":  # Mattermost / Rocket.Chat / Teams incoming-webhook compatible
        payload: dict[str, Any] = {"text": f"**{_prefix(subject, severity)}**\n\n{body}"}
    elif fmt == "json":
        payload = {"title": subject, "text": body, "severity": severity}
    else:
        raise ConfigError(f"webhook channel '{ch['_name']}' has unknown format '{fmt}' (text | json)")
    conn = {"_name": ch["_name"], "base_url": url, "timeout_s": ch.get("timeout_s", 15),
            "verify_tls": ch.get("verify_tls", True), "ca_bundle": ch.get("ca_bundle")}
    if ch.get("token_env"):
        conn["auth"] = {"type": "bearer", "token_env": ch["token_env"]}
    try:
        resp = H.request(conn, "POST", url, json_body=payload)  # POST: never retried
    except httpx.HTTPError as exc:  # pragma: no cover - request() already maps these
        raise UpstreamError(str(exc)) from None
    if resp.status_code >= 300:
        raise UpstreamError(f"webhook answered HTTP {resp.status_code} (not retried)")
