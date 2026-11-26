"""the knowledge platform client (POST /v1/search, POST /v1/ask with stream=false).

STATUS: UNAVAILABLE until the platform adds delegated auth. Its API accepts only its own signed session cookie
from an interactive AD login (its sign-in code: "Machine clients
therefore have no route in right now"). A shared service account would launder clearance (every Agent Studio user
would see what that account may see), so this tool deliberately does NOT log in as one.

When the platform ships the route its docstring anticipates (signed service token identifying the caller + the
human carried separately), set ``knowledge.enabled: true`` with ``auth.type: delegated``: the tool then sends
``Authorization: Bearer <service token>`` and ``<on_behalf_of_header>: <requesting user>``.
"""

from __future__ import annotations

from typing import Any

from . import http as H
from .config import secret
from .errors import ConfigError, NotAllowed, ToolError


class Unavailable(ToolError):
    pass


UNAVAILABLE_MSG = ("knowledge_search is not available yet: the knowledge platform has no delegated (on-behalf-of) "
                   "machine route, and Agent Studio will not use a shared account for classified documents")


def knowledge_query(conn: dict[str, Any] | None, *, mode: str, query: str, as_user: str | None,
                    top_k: int | None = None, doc_id: str | None = None, timeout_s: float | None = None
                    ) -> dict[str, Any]:
    if not conn or not conn.get("enabled"):
        raise Unavailable(UNAVAILABLE_MSG)
    auth = conn.get("auth") or {}
    if auth.get("type") != "delegated":
        raise ConfigError("knowledge.auth.type must be 'delegated' (a shared service account is not allowed)")
    if not as_user:
        raise NotAllowed("knowledge_search must act as the requesting user, but no acting user was provided")
    if not query or not query.strip():
        raise NotAllowed("query is empty")
    mode = (mode or "answer").lower()
    if mode not in ("search", "answer"):
        raise NotAllowed("mode must be 'search' or 'answer'")
    holder = {**auth, "_name": conn.get("_name", "knowledge")}
    headers = {"Authorization": f"Bearer {secret(holder, 'token')}",
               auth.get("on_behalf_of_header", "X-On-Behalf-Of"): as_user}
    bare = {**conn, "auth": None, "_name": "knowledge"}
    t = float(timeout_s or conn.get("timeout_s") or (60 if mode == "answer" else 20))
    extra: dict[str, Any] = {"top_k": max(1, min(int(top_k), 10))} if top_k else {}
    if mode == "search":
        data = H.body_of(H.request(bare, "POST", "/v1/search", headers=headers, timeout_s=t,
                                   json_body={"query": query, **extra}))
        results = []
        for r in data.get("results") or []:
            item = {k: r.get(k) for k in ("doc_id", "title", "text", "score", "source_uri", "page", "level_name")}
            if isinstance(item["text"], str) and len(item["text"]) > 2000:
                item["text"] = item["text"][:2000] + "..."
            results.append(item)
        return {"results": results, "max_level_seen": data.get("max_level_seen")}
    payload: dict[str, Any] = {"question": query, "stream": False, **extra}
    if doc_id:
        payload["doc_id"] = doc_id
    data = H.body_of(H.request(bare, "POST", "/v1/ask", headers=headers, timeout_s=t, json_body=payload))
    return {"answer": data.get("answer"), "citations": data.get("citations"),
            "max_level_seen": data.get("max_level_seen"), "banner": data.get("banner")}
