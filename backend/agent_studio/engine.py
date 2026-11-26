"""Engine adapter: the ONLY module of the Agent Studio app that knows the Langflow engine's API.

Agent Studio's own API (agent_studio.api) and the web app speak in Agent Studio terms (agents, runs, executions).
Replacing or upgrading the engine means changing this file (and tests/test_api_contract.py keeps
it honest), nothing else. The engine runs as its own container (config engine.url).

Calls carry the caller's own engine session (cookies set at sign-in), so the engine applies that
user's identity and ownership rules. No shared service account.
Langflow 1.13.2 endpoints used (session-authenticated unless noted):
  POST /studio-engine/session   open a session for an AD-verified user (engine extension, shared secret)
  POST /api/v1/logout            end a session
  GET  /api/v1/users/whoami      current user
  GET/POST /api/v1/flows/, GET/PATCH/DELETE /api/v1/flows/{id}
  POST /api/v1/run/session/{id}  run with the session (langflow/api/v1/endpoints.py:1269)
  GET  /api/v1/monitor/messages  user's chat messages (langflow/api/v1/monitor.py:306)
  GET  /api/v1/all               installed components
"""

from __future__ import annotations

import logging
import asyncio
import re
import uuid

from typing import Any

import httpx
from fastapi import HTTPException, Request

from agent_studio import settings
from agent_studio.guard import redact

SESSION_COOKIES = ("access_token_lf", "refresh_token_lf", "apikey_tkn_lflw")

log = logging.getLogger("agent_studio.engine")


def _cfg() -> dict:
    return settings.load()["engine"]


async def open_session(identity: dict) -> list[dict]:
    """Ask the engine to open a session for a user Agent Studio has authenticated. Returns cookies to set."""
    cfg = _cfg()
    body = {k: identity.get(k) for k in ("sub", "username", "email", "name")}
    try:
        async with httpx.AsyncClient(base_url=cfg["url"], timeout=30, trust_env=False) as c:
            r = await c.post("/studio-engine/session", json=body,
                             headers={"X-Studio-Engine-Secret": settings.secret(cfg["secret_env"])})
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"engine unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text[:200])
    return r.json()["cookies"]


async def close_session(request: Request) -> None:
    cookies = {k: v for k, v in request.cookies.items() if k in SESSION_COOKIES}
    if not cookies:
        return
    try:
        async with httpx.AsyncClient(base_url=_cfg()["url"], cookies=cookies, timeout=10, trust_env=False) as c:
            await c.post("/api/v1/logout")
    except httpx.HTTPError:
        pass  # cookies are cleared by the caller regardless


_TRANSPORT: httpx.AsyncHTTPTransport | None = None


def _transport() -> httpx.AsyncHTTPTransport:
    global _TRANSPORT
    if _TRANSPORT is None:
        _TRANSPORT = httpx.AsyncHTTPTransport(limits=httpx.Limits(max_connections=50, max_keepalive_connections=20,
                                                                  keepalive_expiry=4))   # engine drops idle ones at ~5 s
    return _TRANSPORT


class Engine:
    """Per-request engine client bound to the caller's session."""

    def __init__(self, request: Request):
        headers = {}
        if auth := request.headers.get("authorization"):
            headers["Authorization"] = auth
        cookies = {k: v for k, v in request.cookies.items() if k in SESSION_COOKIES}
        self._signed_in = bool(headers or cookies.get("access_token_lf") or cookies.get("refresh_token_lf"))
        # One connection pool for all requests (opening a connection per request costs a round trip through the
        # container network); the client itself is per request, so each person's cookies stay their own.
        self._client = httpx.AsyncClient(base_url=_cfg()["url"], headers=headers, cookies=cookies, timeout=900,
                                         trust_env=False, transport=_transport())   # a thorough (thinking) model can work for minutes

    async def __aenter__(self) -> Engine:
        return self

    async def __aexit__(self, *exc) -> None:
        pass   # the shared pool stays open; this request's client holds nothing else

    async def _call(self, method: str, path: str, **kw) -> Any:
        if not self._signed_in:
            raise HTTPException(401, "Not signed in")
        try:
            try:
                r = await self._client.request(method, path, **kw)
            except httpx.TransportError:
                if method != "GET":
                    raise
                # The engine closes idle keep-alive connections (~5 s); a read is safe to repeat once.
                r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise HTTPException(503, "The agent engine is not reachable") from exc
        if r.status_code == 401 or (r.status_code == 403 and path == "/api/v1/users/whoami"):
            raise HTTPException(401, "Not signed in")
        if r.status_code == 403:
            raise HTTPException(403, "Not allowed")
        if r.status_code == 404:
            raise HTTPException(404, "Not found")
        if r.status_code >= 400:
            raise HTTPException(r.status_code, _detail(r))
        return r.json() if r.content else None

    # ---------------------------------------------------------------- identity
    async def me(self) -> dict:
        u = await self._call("GET", "/api/v1/users/whoami")
        admins = {str(x).lower() for x in _cfg().get("console_admins") or []}
        console = bool(u.get("is_superuser")) or u["username"].lower() in admins
        return {"id": u["id"], "username": u["username"], "is_admin": bool(u.get("is_superuser")),
                # raw engine console: named technical admins only (deep fixes); the engine enforces the same list
                "engine_console_url": f"{_cfg()['public_url'].rstrip('/')}/flows" if console else None}

    # ---------------------------------------------------------------- agents
    async def list_agents(self) -> list[dict]:
        flows = await self._call("GET", "/api/v1/flows/", params={"get_all": "true", "remove_example_flows": "true"})
        return [_agent(f) for f in flows if not f.get("is_component")]

    async def get_agent(self, agent_id: str) -> dict:
        return _agent(await self._call("GET", f"/api/v1/flows/{agent_id}"))

    async def create_agent(self, name: str, description: str = "", data: dict | None = None) -> dict:
        body = {"name": name, "description": description, "data": data or {"nodes": [], "edges": []}}
        return _agent(await self._call("POST", "/api/v1/flows/", json=body))

    async def update_agent(self, agent_id: str, **fields) -> dict:
        return _agent(await self._call("PATCH", f"/api/v1/flows/{agent_id}", json=fields))

    async def set_mcp(self, agent_id: str, on: bool) -> dict:
        """Offer (or withdraw) the agent as a standard MCP tool in its project's MCP server. Only published agents
        are offered; the tool's name and description come from the agent's own name and description."""
        flow = await self._call("GET", f"/api/v1/flows/{agent_id}")
        name = re.sub(r"[^a-z0-9]+", "_", (flow.get("name") or "agent").lower()).strip("_")[:60] or "agent"
        body = {"mcp_enabled": on, "action_name": name,
                "action_description": (flow.get("description") or flow.get("name") or "")[:500]}
        await self._call("PATCH", f"/api/v1/flows/{agent_id}", json=body)
        return {"enabled": on, "tool": name, "project_id": flow.get("folder_id"),
                "url": f"{_cfg()['public_url'].rstrip('/')}/api/v1/mcp/project/{flow.get('folder_id')}/streamable"}

    async def delete_agent(self, agent_id: str) -> None:
        await self._call("DELETE", f"/api/v1/flows/{agent_id}")

    # ---------------------------------------------------------------- definitions (engine extension compiles)
    async def compile(self, definition: dict) -> dict:
        """Agent Studio definition -> engine flow data (validated by the engine's own flow builder)."""
        return (await self._call("POST", "/studio-engine/compile", json=definition))["data"]

    async def decompile(self, data: dict) -> dict:
        return await self._call("POST", "/studio-engine/decompile", json={"data": data})

    async def get_definition(self, agent_id: str) -> dict:
        flow = await self._call("GET", f"/api/v1/flows/{agent_id}")
        return await self.decompile(flow.get("data") or {})

    async def save_definition(self, agent_id: str, definition: dict) -> dict:
        data = await self.compile(definition)
        return _agent(await self._call("PATCH", f"/api/v1/flows/{agent_id}", json={"data": data}))

    async def model_options(self) -> list[dict]:
        rows = await self._call("GET", "/api/v1/model_options/language")
        return [{"provider": r.get("provider"), "name": r.get("name")} for r in rows if r.get("name")]

    # ---------------------------------------------------------------- runs
    async def run_agent(self, agent_id: str, message: str, session_id: str | None = None) -> dict:
        """Run an agent. Result: {status: done|waiting_approval|failed, reply, session_id, approval?}.
        The model server sometimes refuses connections for ~20 s at a time; a run that fails for that reason (or
        ends without any answer) is run again after a pause, up to three more times."""
        result: dict = {}
        for pause in (0, 15, 25, 40):
            if pause:
                log.warning("run of %s failed (%s); trying again in %ss", agent_id, result.get("reply", "")[:80], pause)
                await asyncio.sleep(pause)
            result = await self._run_once(agent_id, message, session_id)
            if result["status"] != "failed" or result["reply"] not in (MODEL_DOWN, NO_ANSWER):
                break
        return _guarded(result)

    async def _run_once(self, agent_id: str, message: str, session_id: str | None = None) -> dict:
        flow = await self._call("GET", f"/api/v1/flows/{agent_id}")
        # A new conversation gets its own session; otherwise the engine reuses the agent id and every run
        # would share one chat memory.
        session_id = session_id or f"run-{uuid.uuid4()}"   # "run-": started from Agent Studio (not by a trigger)
        if _has_approval(flow):
            # Human approval steps pause the run; only the engine's workflow jobs can pause and resume.
            body = {"flow_id": agent_id, "mode": "background", "input_value": message, "session_id": session_id}
            job = await self._call("POST", "/api/v2/workflows", json=body)
            return await self._job_result(agent_id, job["job_id"], session_id=session_id)
        body = {"input_value": message, "input_type": "chat", "output_type": "chat", "session_id": session_id}
        out = await self._call("POST", f"/api/v1/run/session/{agent_id}", json=body)
        sid = out.get("session_id") or session_id
        reply = _reply_text(out)
        if not reply.strip() and not [m for m in await self.messages(session_id=sid) if m["error"]]:
            # Local models sometimes write a tool call the model server cannot read and drop it (an empty answer).
            # One retry with a plain nudge recovers it; a second empty answer is reported as a failure.
            body["input_value"] = message + "\n\n(Your previous reply was empty. Use your tools with valid arguments, then answer in plain words.)"
            out = await self._call("POST", f"/api/v1/run/session/{agent_id}", json=body)
            reply = _reply_text(out)
        if engine_error(reply):          # the engine put its own error where the answer goes
            return {"status": "failed", "session_id": sid, "reply": _plain_error(reply)}
        if not reply.strip():
            # The engine answers 200 with no output when a step failed; the reason is in the run's messages.
            errors = [m["text"] for m in await self.messages(session_id=sid) if m["error"] and m["text"].strip()]
            return {"status": "failed", "session_id": sid,
                    "reply": _plain_error(errors[0]) if errors else NO_ANSWER}
        return {"status": "done", "session_id": sid, "reply": reply}

    async def _job_result(self, agent_id: str, job_id: str, wait_s: int = 600, session_id: str | None = None) -> dict:
        for _ in range(wait_s // 2):
            try:
                j = await self._call("GET", "/api/v2/workflows", params={"job_id": job_id})
            except HTTPException as exc:  # a failed job answers with an error body
                return {"status": "failed", "reply": _plain_error(str(exc.detail)), "session_id": None, "job_id": job_id}
            status = j.get("status")
            if status == "suspended":
                pending = [p for p in await self.pending_approvals(agent_id) if p["id"] == job_id]
                return {"status": "waiting_approval", "reply": pending[0]["proposal"] if pending else "",
                        "session_id": j.get("session_id"), "job_id": job_id, "approval": pending[0] if pending else None}
            if status == "completed":
                return {"status": "done", "reply": ((j.get("output") or {}).get("text")) or "",
                        "session_id": j.get("session_id") or session_id, "job_id": job_id}
            if status in ("failed", "cancelled", "error", "timed_out"):
                return {"status": "failed", "reply": _plain_error("; ".join(str(e) for e in j.get("errors") or []) or status),
                        "session_id": j.get("session_id"), "job_id": job_id}
            await asyncio.sleep(2)
        return {"status": "running", "reply": "", "session_id": None, "job_id": job_id}

    # ---------------------------------------------------------------- versions (the engine's own history)
    async def snapshot(self, agent_id: str, note: str) -> dict:
        """Save the agent as it is now as a new version; returns {id, version_number, ...}."""
        return await self._call("POST", f"/api/v1/flows/{agent_id}/versions/", json={"description": note[:500]})

    async def versions(self, agent_id: str) -> list[dict]:
        rows = await self._call("GET", f"/api/v1/flows/{agent_id}/versions/")
        return rows if isinstance(rows, list) else (rows or {}).get("entries") or []   # {"entries": [...], "max_entries": 50}

    async def activate(self, agent_id: str, version_id: str) -> None:
        """Put an earlier version back as the agent itself (no extra auto-saved copy)."""
        await self._call("POST", f"/api/v1/flows/{agent_id}/versions/{version_id}/activate", params={"save_draft": "false"})

    async def set_triggers(self, agent_id: str, on: bool) -> int:
        """Arm or pause the agent's own schedule/alert triggers (engine trigger states). Returns how many changed."""
        rows = await self._call("GET", "/api/v1/triggers", params={"flow_id": agent_id})
        changed = 0
        for r in rows:
            want = "active" if on else "paused"
            if r.get("state") != want:
                await self._call("POST", f"/api/v1/triggers/{r['id']}/{'enable' if on else 'disable'}")
                changed += 1
        return changed

    async def status(self) -> dict:
        """What the engine can reach, seen from where agents run (System health, Readiness)."""
        return await self._call("GET", "/studio-engine/status")

    async def pending_approvals(self, agent_id: str) -> list[dict]:
        rows = await self._call("GET", "/api/v2/workflows/pending", params={"flow_id": agent_id})
        return [{"id": r["job_id"], "agent_id": str(r["flow_id"]), "request_id": r["request_id"],
                 "proposal": redact(r.get("prompt") or ""), "asked_at": _iso(r.get("created_at")),
                 "choices": [o["action_id"] for o in r.get("options") or []]} for r in rows]

    async def decide(self, agent_id: str, job_id: str, decision: str) -> dict:
        pending = [p for p in await self.pending_approvals(agent_id) if p["id"] == job_id]
        if not pending:
            raise HTTPException(404, "This approval is no longer waiting")
        if decision not in pending[0]["choices"]:
            raise HTTPException(422, f"Choose one of: {', '.join(pending[0]['choices'])}")
        await self._call("POST", f"/api/v2/workflows/{job_id}/resume",
                         json={"request_id": pending[0]["request_id"], "decision": {"action_id": decision}})
        out = await self._job_result(agent_id, job_id)
        if decision == "reject" and out["status"] == "done":
            out["reply"] = ""  # the rejected branch only echoes the proposal; nothing ran
        return _guarded(out)

    async def messages(self, agent_id: str | None = None, session_id: str | None = None, limit: int = 500) -> list[dict]:
        params: dict[str, Any] = {"order": "DESC", "limit": limit}
        if agent_id:
            params["flow_id"] = agent_id
        if session_id:
            params["session_id"] = session_id
        rows = await self._call("GET", "/api/v1/monitor/messages", params=params)
        out = []
        for m in rows:
            text, error = m.get("text") or "", bool(m.get("error"))
            if m.get("sender") != "User" and engine_error(text):   # the engine saved its own error as a reply
                text, error = _plain_error(text), True
            usage = (m.get("properties") or {}).get("usage") or {}
            out.append({"id": m.get("id"), "agent_id": m.get("flow_id"), "session_id": m.get("session_id"),
                        "sender": m.get("sender"), "sender_name": m.get("sender_name"),
                        "text": text if m.get("sender") == "User" else redact(text),
                        "tokens_in": usage.get("input_tokens") or 0, "tokens_out": usage.get("output_tokens") or 0,
                        "timestamp": _iso(m.get("timestamp")), "error": error, "tools": _tools_used(m)})
        return out

    # ---------------------------------------------------------------- components
    async def components(self) -> dict[str, dict]:
        allc = await self._call("GET", "/api/v1/all")
        return {key: {"category": cat, "display_name": c.get("display_name") or key,
                      "description": c.get("description") or "", "icon": c.get("icon")}
                for cat, comps in allc.items() if cat != "component_display_names" for key, c in comps.items()}


def _guarded(result: dict) -> dict:
    """Answer guardrail on everything a run hands back (guard.py)."""
    out = {**result, "reply": redact(result.get("reply") or "")}
    if isinstance(out.get("approval"), dict):
        out["approval"] = {**out["approval"], "proposal": redact(out["approval"].get("proposal") or "")}
    return out


def _iso(value: str | None) -> str | None:
    """Engine timestamps look like '2026-11-13 06:11:56.741374 UTC' (or ISO); return ISO-8601 with offset."""
    if not value:
        return None
    from datetime import datetime, timezone

    v = value.strip().replace(" UTC", "+00:00").replace("Z", "+00:00").replace(" ", "T", 1)
    dt = datetime.fromisoformat(v)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
        return d if isinstance(d, str) else str(d)
    except Exception:
        return r.text[:300]


MODEL_DOWN = "The AI model server could not be reached, so the agent could not think. Try again in a minute."
NO_ANSWER = "The agent finished without an answer."
TOO_MUCH = ("The agent read more data than its AI model can hold at once. Ask for less (for example one server or only "
            "critical findings), or use the model with the larger memory.")


ENGINE_ERRORS = ("maximum context length", "context_length_exceeded", "connection attempts failed", "connection refused",
                 "error running graph", "error building component", "notfounderror",
                 "model call limits exceeded")


def engine_error(text: str) -> bool:
    """An engine failure stored as if it were the agent's answer (model errors, build errors)."""
    low = (text or "")[:600].lower()
    return any(x in low for x in ENGINE_ERRORS)


def _plain_error(text: str) -> str:
    """Engine error text -> one plain sentence for people (details stay in Executions)."""
    if any(x in text.lower() for x in ("connection attempts failed", "connection refused", "timed out")):
        return MODEL_DOWN
    if "maximum context length" in text.lower() or "context_length_exceeded" in text.lower():
        return TOO_MUCH
    if "model call limits exceeded" in text.lower():
        return ("The agent needed more steps than its AI model allows in one run. Ask for less at a time, or use the "
                "Fast thinking mode.")
    if "does not exist" in text.lower() and "model" in text.lower():
        return "The AI model this agent uses is not available on the model server. An administrator must check the model name."
    return text.strip().splitlines()[0][:300]


def _tools_used(m: dict) -> list[dict]:
    """Tool calls recorded on an agent message: [{name, ok, input}] (the run's evidence trail)."""
    out = []
    for block in m.get("content_blocks") or []:
        for c in block.get("contents") or []:
            if c.get("type") == "tool_use":
                res = c.get("output")
                ok = not c.get("error") and not (isinstance(res, dict) and res.get("ok") is False)
                out.append({"name": c.get("name"), "ok": ok, "input": c.get("tool_input"), "output": str(res)[:24000]})   # all the agent saw (studio_tools caps a result at 24k): evidence for the goal check
    return out


def _has_approval(f: dict) -> bool:
    return any((n.get("data") or {}).get("type") == "HumanInput" for n in ((f.get("data") or {}).get("nodes")) or [])


def _agent(f: dict) -> dict:
    nodes = ((f.get("data") or {}).get("nodes")) or []
    desc = re.sub(r"^(the user wants|you want|user wants)( an agent)?( that)?( to)?\s*", "", f.get("description") or "", flags=re.I)
    return {"id": f["id"], "name": f.get("name"), "description": desc if desc == (f.get("description") or "") else desc[:1].upper() + desc[1:],
            "updated_at": _iso(f.get("updated_at")), "steps": len(nodes), "needs_approval": _has_approval(f)}


def _reply_text(out: dict) -> str:
    """Pull the chat text out of the engine's run response (outputs -> outputs -> results.message.text)."""
    texts = []
    for run in out.get("outputs") or []:
        for o in run.get("outputs") or []:
            msg = ((o.get("results") or {}).get("message")) or {}
            text = msg.get("text") if isinstance(msg, dict) else None
            if text is None:
                for m in o.get("messages") or []:
                    text = m.get("message")
            if text:
                texts.append(str(text))
    return "\n\n".join(texts)
