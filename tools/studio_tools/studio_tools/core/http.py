"""HTTP to registered internal services (httpx). Host allowlist, auth from env, no redirects, bounded retries.

Retry policy: idempotent reads (GET) retry once on a connection error or 502/503/504; writes (POST) never retry.
Tests inject an ``httpx.MockTransport`` via the module-level ``TRANSPORT`` hook.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .config import secret
from .errors import ConfigError, NotAllowed, ToolTimeout, UpstreamError

TRANSPORT: httpx.BaseTransport | None = None  # test hook
DEFAULT_TIMEOUT_S = 20.0
MAX_RESPONSE_CHARS = 200_000
_RETRY_STATUS = {502, 503, 504}


def allowed_hosts(conn: dict[str, Any]) -> set[str]:
    base = conn.get("base_url")
    if not base:
        raise ConfigError(f"connection '{conn.get('_name')}' has no base_url")
    hosts = {(urlsplit(base).hostname or "").lower()}
    hosts |= {str(h).lower() for h in conn.get("allowed_hosts") or []}
    hosts.discard("")
    return hosts


def resolve_url(conn: dict[str, Any], path: str) -> str:
    """Join a caller-supplied path onto the connection's base_url and check the host allowlist."""
    base = str(conn["base_url"]).rstrip("/") + "/"
    path = (path or "").strip()
    if "\\" in path or any(ord(ch) < 32 for ch in path):
        raise NotAllowed("invalid characters in path")
    url = urljoin(base, path.lstrip("/")) if not urlsplit(path).scheme and not path.startswith("//") else path
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise NotAllowed(f"scheme '{parts.scheme}' not allowed")
    if (parts.hostname or "").lower() not in allowed_hosts(conn):
        raise NotAllowed(f"host '{parts.hostname}' is not in the allowlist of connection '{conn.get('_name')}'")
    if parts.username or parts.password:
        raise NotAllowed("credentials in URL are not allowed")
    return url


def auth_headers(conn: dict[str, Any]) -> dict[str, str]:
    auth = conn.get("auth") or {"type": "none"}
    kind = str(auth.get("type", "none")).lower()
    holder = {**auth, "_name": conn.get("_name")}
    if kind == "none":
        return {}
    if kind == "bearer":
        return {"Authorization": f"Bearer {secret(holder, 'token')}"}
    if kind == "header":
        name = auth.get("header")
        if not name:
            raise ConfigError(f"connection '{conn.get('_name')}' auth.header is missing")
        return {str(name): secret(holder, "token")}
    if kind == "basic":
        import base64
        raw = f"{auth.get('username', '')}:{secret(holder, 'password')}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
    raise ConfigError(f"connection '{conn.get('_name')}' has unknown auth type '{kind}'")


def client(conn: dict[str, Any], timeout_s: float | None = None) -> httpx.Client:
    t = float(timeout_s or conn.get("timeout_s") or DEFAULT_TIMEOUT_S)
    verify: Any = conn.get("ca_bundle") or bool(conn.get("verify_tls", True))
    kwargs: dict[str, Any] = {"timeout": httpx.Timeout(t, connect=min(t, 10.0)), "follow_redirects": False,
                              "trust_env": False}  # air-gapped: never pick up proxy env vars
    if TRANSPORT is not None:
        kwargs["transport"] = TRANSPORT
    else:
        kwargs["verify"] = verify
    return httpx.Client(**kwargs)


def request(conn: dict[str, Any], method: str, path: str, *, params: dict | None = None,
            json_body: Any = None, headers: dict[str, str] | None = None, timeout_s: float | None = None,
            retries: int | None = None, http: httpx.Client | None = None) -> httpx.Response:
    method = method.upper()
    url = resolve_url(conn, path)
    is_write = method not in ("GET", "HEAD")
    attempts = 1 if is_write else 1 + int(conn.get("retries", 1) if retries is None else retries)
    hdrs = {"Accept": "application/json", "User-Agent": "agent-studio-tools", **auth_headers(conn), **(headers or {})}
    own = http is None
    http = http or client(conn, timeout_s)
    try:
        for attempt in range(attempts):
            try:
                resp = http.request(method, url, params=params, json=json_body, headers=hdrs)
            except httpx.TimeoutException:
                if attempt + 1 < attempts:
                    continue
                raise ToolTimeout(f"{method} {urlsplit(url).path} timed out") from None
            except httpx.TransportError as exc:
                if attempt + 1 < attempts:
                    time.sleep(0.5)
                    continue
                raise UpstreamError(f"cannot reach {urlsplit(url).hostname}: {type(exc).__name__}") from None
            if resp.status_code in _RETRY_STATUS and attempt + 1 < attempts:
                time.sleep(0.5)
                continue
            if resp.is_redirect:
                raise UpstreamError(f"{method} {urlsplit(url).path} redirected (redirects are not followed)")
            return resp
    finally:
        if own:
            http.close()
    raise UpstreamError("request failed")  # pragma: no cover


def body_of(resp: httpx.Response) -> Any:
    """Decode a response for the LLM: JSON if possible, else truncated text. Raises on HTTP errors."""
    try:
        data: Any = resp.json()
    except (json.JSONDecodeError, ValueError):
        data = resp.text[:MAX_RESPONSE_CHARS]
    if resp.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        raise UpstreamError(f"HTTP {resp.status_code}: {str(detail)[:500]}")
    return data
