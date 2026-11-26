"""Reading the web: only where the deployment allows it (tools.yaml web.enabled; off by default, air-gap safe)."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .config import load_config
from .errors import NotAllowed, UpstreamError

MODES = ("text", "links", "feed", "json", "raw")


def _cfg() -> dict[str, Any]:
    cfg = load_config().get("web") or {}
    if not cfg.get("enabled"):
        raise NotAllowed("internet access is switched off in this deployment (tools.yaml web.enabled)")
    return cfg


def _check_url(url: str, cfg: dict) -> str:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise NotAllowed("only http(s) addresses can be read")
    host = u.hostname.lower()
    allow = [d.lower() for d in cfg.get("allow_domains") or []]
    if allow and not any(host == d or host.endswith("." + d) for d in allow):
        raise NotAllowed(f"{host} is not in the allowed sites for this deployment")
    if any(host == d or host.endswith("." + d) for d in (x.lower() for x in cfg.get("deny_domains") or [])):
        raise NotAllowed(f"{host} is blocked in this deployment")
    if not cfg.get("allow_private"):  # the web tool must not become a way into internal systems
        try:
            for info in socket.getaddrinfo(host, None):
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise NotAllowed("internal addresses are not reachable through the web tool")
        except socket.gaierror:
            raise UpstreamError(f"cannot resolve {host}") from None
    return u.geturl()


def fetch(url: str, mode: str = "text", max_chars: int = 20000) -> tuple[dict[str, Any], bytes]:
    """Return (result for the model, raw bytes)."""
    cfg = _cfg()
    if mode not in MODES:
        raise NotAllowed(f"mode must be one of {MODES}")
    limit = int(cfg.get("max_bytes", 10_000_000))
    url = _check_url(url, cfg)
    try:
        with httpx.Client(timeout=float(cfg.get("timeout_s", 30)), follow_redirects=True, trust_env=True,
                          headers={"User-Agent": cfg.get("user_agent", "Agent Studio-agent/1.0")}) as c:
            with c.stream("GET", url) as r:
                _check_url(str(r.url), cfg)  # redirects are checked too
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise NotAllowed(f"the page is larger than {limit} bytes")
                    chunks.append(chunk)
                status, ctype, final = r.status_code, r.headers.get("content-type", ""), str(r.url)
    except httpx.HTTPError as exc:
        raise UpstreamError(f"could not read {url}: {exc.__class__.__name__}") from None
    raw = b"".join(chunks)
    if status >= 400:
        raise UpstreamError(f"{url} answered {status}")
    out: dict[str, Any] = {"url": final, "status": status, "content_type": ctype, "bytes": len(raw)}
    text = raw.decode(r.encoding or "utf-8", errors="replace")
    if mode == "json":
        import json

        out["json"] = json.loads(text)
    elif mode == "feed":
        out["items"] = _feed(raw, final)[:200]
    elif mode == "links":
        out["links"] = _links(text, final)[:500]
    elif mode == "text":
        out["text"] = _text(text)[:max_chars]
    return out, raw


def _soup(text: str, xml: bool = False):
    from bs4 import BeautifulSoup

    return BeautifulSoup(text, "xml" if xml else "lxml")


def _text(html: str) -> str:
    s = _soup(html)
    for t in s(["script", "style", "noscript", "nav", "footer", "header"]):
        t.decompose()
    return "\n".join(line.strip() for line in s.get_text("\n").splitlines() if line.strip())


def _links(html: str, base: str) -> list[dict]:
    return [{"text": a.get_text(" ", strip=True)[:200], "url": urljoin(base, a["href"])}
            for a in _soup(html).find_all("a", href=True) if not a["href"].startswith(("#", "javascript:", "mailto:"))]


def _feed(raw: bytes, base: str) -> list[dict]:
    """RSS / Atom items, or the page/sitemap URLs of a sitemap."""
    s = _soup(raw.decode("utf-8", errors="replace"), xml=True)
    if s.find("urlset") or s.find("sitemapindex"):
        return [{"url": loc.get_text(strip=True), "updated": (u.find("lastmod").get_text(strip=True) if u.find("lastmod") else None)}
                for u in s.find_all(["url", "sitemap"]) if (loc := u.find("loc"))]
    items = []
    for it in s.find_all(["item", "entry"]):
        link = it.find("link")
        href = (link.get("href") or link.get_text(strip=True)) if link else None
        date = it.find(["pubDate", "published", "updated"])
        items.append({"title": it.find("title").get_text(strip=True) if it.find("title") else "",
                      "url": urljoin(base, href) if href else None,
                      "published": date.get_text(strip=True) if date else None,
                      "summary": _text(it.find(["description", "summary"]).get_text())[:500] if it.find(["description", "summary"]) else ""})
    return items
