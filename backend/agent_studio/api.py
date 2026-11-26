"""Agent Studio API v1: the contract the Agent Studio web app (and later the chat app) use. Engine-neutral.

Everything engine-specific is behind agent_studio.engine.Engine. OpenAPI: GET /api/studio/v1/openapi.json
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import re
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent_studio import settings
from agent_studio import roles
from agent_studio.engine import Engine

PREFIX = "/api/studio/v1"

router = APIRouter(prefix=PREFIX, tags=["Agent Studio"])


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=2000)


class AgentPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)


class RunIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str | None = None


@router.get("/me", summary="Signed-in user, with their Agent Studio role (user / builder / admin)")
async def me(request: Request):
    from fastapi.concurrency import run_in_threadpool

    from agent_studio import roles, store

    async with Engine(request) as e:
        who = await e.me()
    from agent_studio import accounts, setup

    role = roles.resolve(who, await run_in_threadpool(store.person_role, who["username"]))
    return {**who, "role": role, "local_accounts": accounts.local(),
            "needs_setup": role == "admin" and setup.needs_setup()}


def _prefs_by_agent(owner: str) -> dict[str, dict]:
    from agent_studio import store

    return store.prefs_by_agent(owner)


async def _with_health(e: Engine, agents: list[dict]) -> list[dict]:
    """Runtime watchkeeper: each agent gets {status, reason, last_run_at} from its real runs and schedule."""
    from fastapi.concurrency import run_in_threadpool

    from agent_studio.watch import runtime

    from agent_studio import store

    import asyncio

    me, msgs = await asyncio.gather(e.me(), e.messages())   # independent engine reads, side by side
    runs = _group_runs(msgs, {})

    def ours() -> tuple:
        ids = [a["id"] for a in agents]
        return _prefs_by_agent(me["id"]), store.lives(me["id"]), store.feedback_stats(ids), store.last_checks()

    prefs, lives, stats, checks = await run_in_threadpool(ours)   # one thread, one open connection
    for a in agents:
        a["health"] = runtime.health([r for r in runs if r["agent_id"] == a["id"]], prefs.get(a["id"]))
        life = lives.get(a["id"]) or {}
        a["state"], a["live_version"] = life.get("state", "built"), life.get("live_version")
        a["shared"] = bool(life.get("shared"))
        a["feedback"] = stats.get(a["id"], {"good": 0, "bad": 0, "corrections_waiting": 0})
        a["last_check"] = checks.get(a["id"])   # its last self-started run, checked against its goal
    return agents


@router.get("/agents", summary="Agents the user can use, each with its health (working well / needs attention)")
async def list_agents(request: Request):
    async with Engine(request) as e:
        return await _with_health(e, await e.list_agents())


@router.post("/agents", status_code=201, summary="Create an empty agent (then open it in the builder)", dependencies=[roles.need("builder")])
async def create_agent(body: AgentIn, request: Request):
    async with Engine(request) as e:
        return await e.create_agent(body.name, body.description)


@router.get("/agents/{agent_id}", summary="One agent")
async def get_agent(agent_id: str, request: Request):
    async with Engine(request) as e:
        return await e.get_agent(agent_id)


@router.patch("/agents/{agent_id}", summary="Rename / describe an agent", dependencies=[roles.need("builder")])
async def update_agent(agent_id: str, body: AgentPatch, request: Request):
    async with Engine(request) as e:
        return await e.update_agent(agent_id, **body.model_dump(exclude_none=True))


@router.delete("/agents/{agent_id}", status_code=204, summary="Delete an agent", dependencies=[roles.need("builder")])
async def delete_agent(agent_id: str, request: Request):
    from agent_studio import activity

    async with Engine(request) as e:
        await activity.note_as(e, "deleted an agent", agent_id)
        await e.delete_agent(agent_id)
    from fastapi.concurrency import run_in_threadpool

    from agent_studio import store
    await run_in_threadpool(store.forget_agent, agent_id)   # no live/shared record, notes or tests left behind


async def _runnable(agent_id: str) -> None:
    from fastapi.concurrency import run_in_threadpool

    from agent_studio import lifecycle

    state = (await run_in_threadpool(lifecycle.state_of, agent_id))["state"]
    if state in ("paused", "retired"):
        raise HTTPException(409, f"This agent is {state}. Resume it to use it again.")


def memory_session(agent_id: str, user_id: str) -> str:
    """One ongoing conversation per person and agent: what 'Remember our past chats' keeps (the engine's own chat
    history - no vector store)."""
    return f"memory-{agent_id}-{user_id}"


async def _remembers(agent_id: str) -> bool:
    from fastapi.concurrency import run_in_threadpool

    from agent_studio import store

    return bool((await run_in_threadpool(store.prefs_of_agent, agent_id)).get("remember"))


@router.post("/agents/{agent_id}/run", summary="Send a message to an agent and get its reply")
async def run_agent(agent_id: str, body: RunIn, request: Request):
    await _runnable(agent_id)
    async with Engine(request) as e:
        session = body.session_id
        if not session and await _remembers(agent_id):
            session = memory_session(agent_id, (await e.me())["id"])
        return await e.run_agent(agent_id, body.message, session)


@router.get("/agents/{agent_id}/memory", summary="Does this agent remember past chats, and what it remembers of mine")
async def memory(agent_id: str, request: Request):
    async with Engine(request) as e:
        if not await _remembers(agent_id):
            return {"remembers": False, "session_id": None, "messages": []}
        sid = memory_session(agent_id, (await e.me())["id"])
        msgs = sorted(await e.messages(session_id=sid), key=lambda m: m["timestamp"] or "")
    return {"remembers": True, "session_id": sid, "messages": msgs[-40:]}


@router.delete("/agents/{agent_id}/memory", status_code=204, summary="Forget my past chats with this agent")
async def forget(agent_id: str, request: Request):
    async with Engine(request) as e:
        await e._call("DELETE", f"/api/v1/monitor/messages/session/{memory_session(agent_id, (await e.me())['id'])}")


def _sse(event: str, data: dict) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/agents/{agent_id}/run/stream", summary="Same as run, streamed (Server-Sent Events): a `status` event "
             "every few seconds while the agent works, then one `result` (same body as run) or `error` event")
async def run_agent_stream(agent_id: str, body: RunIn, request: Request):
    import asyncio
    import time

    await _runnable(agent_id)

    async def events():
        t0 = time.monotonic()
        async with Engine(request) as e:
            session = body.session_id
            if not session and await _remembers(agent_id):
                session = memory_session(agent_id, (await e.me())["id"])
            task = asyncio.create_task(e.run_agent(agent_id, body.message, session))
            try:
                while True:
                    yield _sse("status", {"state": "working", "seconds": round(time.monotonic() - t0)})
                    done, _ = await asyncio.wait({task}, timeout=5)
                    if done:
                        break
                try:
                    yield _sse("result", task.result())
                except HTTPException as x:
                    yield _sse("error", {"status": x.status_code, "detail": x.detail})
                except Exception:  # noqa: BLE001 - the stream must end with an event, never a cut connection
                    yield _sse("error", {"status": 502, "detail": "The agent could not finish this run."})
            finally:
                task.cancel()  # client went away: stop waiting (a no-op when finished)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class FeedbackIn(BaseModel):
    session_id: str = Field("", max_length=200)
    good: bool
    answer: str = Field("", max_length=4000)
    correction: str = Field("", max_length=1000)


@router.post("/agents/{agent_id}/feedback", status_code=204, summary="Thumbs up or down on an answer; 'not right' may say how it should be")
async def feedback(agent_id: str, body: FeedbackIn, request: Request):
    from fastapi.concurrency import run_in_threadpool

    from agent_studio import activity, store

    async with Engine(request) as e:
        await e.get_agent(agent_id)
        who = (await e.me())["username"]
    await run_in_threadpool(store.add_feedback, who, agent_id, body.session_id, body.good, body.answer, body.correction.strip())
    if body.correction.strip():
        await activity.note(who, "corrected an agent", agent_id, body.correction.strip()[:200])
        # The agent's owner (or an administrator) teaches it at once; anyone else's correction waits for the owner,
        # so nobody can change what someone else's agent does just by typing a "correction".
        from agent_studio import learn, roles

        async with Engine(request) as e:
            me = await e.me()
            life = await run_in_threadpool(store.life, agent_id)
            if (life and life.get("owner") == me["id"]) or await roles.role_of(request) == "admin":
                if await learn.apply_now(e, agent_id):
                    await activity.note(who, "taught an agent (correction applied at once)", agent_id)


@router.get("/agents/{agent_id}/corrections", summary="How people said this agent should answer (applied when it is rebuilt)")
async def agent_corrections(agent_id: str, request: Request):
    from fastapi.concurrency import run_in_threadpool

    from agent_studio import store

    async with Engine(request) as e:
        await e.get_agent(agent_id)
    return await run_in_threadpool(store.corrections, agent_id)


class DecisionIn(BaseModel):
    agent_id: str
    decision: str = Field(pattern="^(approve|reject)$")


@router.get("/approvals", summary="Agent actions waiting for a person's approval")
async def approvals(request: Request):
    async with Engine(request) as e:
        agents = [a for a in await e.list_agents() if a["needs_approval"]]
        rows = []
        for a in agents:
            rows += [{**p, "agent_name": a["name"]} for p in await e.pending_approvals(a["id"])]
    return sorted(rows, key=lambda r: r["asked_at"] or "", reverse=True)


@router.post("/approvals/{approval_id}", summary="Approve or reject a waiting action; returns the run's result")
async def decide(approval_id: str, body: DecisionIn, request: Request):
    from agent_studio import activity

    async with Engine(request) as e:
        await activity.note_as(e, "approved an action" if body.decision == "approve" else "refused an action", body.agent_id, approval_id)
        return await e.decide(body.agent_id, approval_id, body.decision)


# ---------------------------------------------------------------- files (what agents produced for this person)
def _my_files(owner_id: str) -> Path:
    """Same folder the engine's tools write to: <files_dir>/<owner id>/ (tools.yaml files.root)."""
    return settings.path(settings.load()["app"]["files_dir"]) / re.sub(r"[^A-Za-z0-9-]", "", owner_id)


def _my_file(owner_id: str, name: str) -> Path:
    p = _my_files(owner_id) / Path(name).name
    if Path(name).name != name or not p.is_file():
        raise HTTPException(404, "Not found")
    return p


def list_files(owner_id: str) -> list[str]:
    folder = _my_files(owner_id)
    return [p.name for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []


@router.get("/files", summary="Files your agents produced (data sets, documents, archives, downloads)")
async def files(request: Request):
    async with Engine(request) as e:
        me = await e.me()
    folder = _my_files(me["id"])
    rows = [{"name": p.name, "bytes": p.stat().st_size, "format": p.suffix.lstrip("."),
             "modified_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()}
            for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []
    return sorted(rows, key=lambda r: r["modified_at"], reverse=True)


MAX_UPLOAD = 50 * 1024 * 1024


@router.post("/files", status_code=201, summary="Add a file to your files (agents and their tools can then read it)")
async def upload(request: Request, file: UploadFile):
    from agent_studio import activity

    async with Engine(request) as e:
        me = await e.me()
    name = Path(file.filename or "").name.strip()
    if not name or name.startswith("."):
        raise HTTPException(422, "The file needs a name")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Files up to 50 MB can be added")
    folder = _my_files(me["id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    await activity.note(me["username"], "added a file", name)
    return {"name": name, "bytes": len(data)}


@router.get("/files/{name}", summary="Download one of your files")
async def download(name: str, request: Request):
    async with Engine(request) as e:
        me = await e.me()
    return FileResponse(_my_file(me["id"], name), filename=name)


@router.delete("/files/{name}", status_code=204, summary="Delete one of your files")
async def delete_file(name: str, request: Request):
    async with Engine(request) as e:
        me = await e.me()
    _my_file(me["id"], name).unlink()


@router.get("/estimates", summary="Measured run times per thinking mode and whether each model is answering now")
async def estimates(request: Request):
    """For the Create cards: time vs quality, from this server's real runs (median of recent runs), not guesses."""
    from statistics import median

    from fastapi.concurrency import run_in_threadpool

    async with Engine(request) as e:
        me = await e.me()
        runs = _group_runs(await e.messages(), {})
        try:
            status = await e.status()
        except HTTPException:
            status = {}
    prefs = await run_in_threadpool(_prefs_by_agent, me["id"])
    durations: dict[str, list[float]] = {"fast": [], "thorough": []}
    for r in runs:
        brain = (prefs.get(r["agent_id"]) or {}).get("brain", "fast")
        seconds = (_ts(r["last_at"]) - _ts(r["started_at"])).total_seconds()
        if 1 < seconds < 1800:
            durations.setdefault(brain, []).append(seconds)
    models = {c["name"]: c for c in status.get("connections") or [] if c.get("kind") == "model"}
    default = {"fast": 25, "thorough": 120}             # first-day fallback until real runs exist
    out = {}
    for brain, model in (("fast", "Ollama"), ("thorough", "vLLM")):
        d = durations.get(brain) or []
        m = models.get(model) or {}
        out[brain] = {"seconds": round(median(d[:30])) if d else default[brain], "measured_runs": len(d[:30]),
                      "available": m.get("ok") is not False, "detail": m.get("detail", "")}
    return out


@router.get("/executions", summary="Recent agent runs (one per conversation session)")
async def executions(request: Request, agent_id: str | None = None, limit: int = 50):
    async with Engine(request) as e:
        names = {a["id"]: a["name"] for a in await e.list_agents()}
        msgs = await e.messages(agent_id=agent_id)
    return _group_runs(msgs, names)[:limit]


@router.get("/executions/{session_id}", summary="Messages of one run")
async def execution(session_id: str, request: Request):
    async with Engine(request) as e:
        msgs = await e.messages(session_id=session_id)
    return sorted(msgs, key=lambda m: m["timestamp"] or "")


def usage_by_agent(runs: list[dict], since: str) -> list[dict]:
    """Runs and AI tokens per agent since an ISO time, busiest first."""
    by: dict[str, dict] = {}
    for r in runs:
        if (r["last_at"] or "") < since:
            continue
        u = by.setdefault(r["agent_id"], {"agent_id": r["agent_id"], "agent_name": r["agent_name"], "runs": 0, "failed": 0,
                                          "tokens_in": 0, "tokens_out": 0})
        u["runs"] += 1
        u["failed"] += int(bool(r["error"]))
        u["tokens_in"] += r.get("tokens_in") or 0
        u["tokens_out"] += r.get("tokens_out") or 0
    return sorted(by.values(), key=lambda u: (u["tokens_in"] + u["tokens_out"], u["runs"]), reverse=True)


@router.get("/usage", summary="Runs and AI tokens per agent over the last days (what each agent costs the model servers)")
async def usage(request: Request, days: int = 7):
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))).isoformat()
    async with Engine(request) as e:
        names = {a["id"]: a["name"] for a in await e.list_agents()}
        runs = _group_runs(await e.messages(limit=2000), names)
    rows = usage_by_agent(runs, since)
    return {"days": days, "agents": rows, "tokens": sum(r["tokens_in"] + r["tokens_out"] for r in rows),
            "runs": sum(r["runs"] for r in rows)}


@router.get("/dashboard", summary="Counts for the home screen")
async def dashboard(request: Request):
    async with Engine(request) as e:
        agents = await e.list_agents()
        msgs = await e.messages()
        waiting = sum([len(await e.pending_approvals(a["id"])) for a in agents if a["needs_approval"]])
    runs = _group_runs(msgs, {a["id"]: a["name"] for a in agents})
    since = datetime.now(timezone.utc) - timedelta(days=7)
    recent = [r for r in runs if _ts(r["last_at"]) >= since]
    async with Engine(request) as e:
        agents = await _with_health(e, agents)
    attention = [a for a in agents if a["health"]["status"] == "needs_attention"]
    ok = [r for r in recent if not r["error"]]
    today = datetime.now(timezone.utc).date()
    by_day = [sum(1 for r in runs if _ts(r["last_at"]).date() == today - timedelta(days=13 - i)) for i in range(14)]
    return {"agents": len(agents), "runs_7d": len(recent), "approvals_waiting": waiting, "runs_by_day": by_day,
            "needs_attention": len(attention),
            "failed_7d": len(recent) - len(ok),
            "success_rate_7d": round(100 * len(ok) / len(recent), 1) if recent else None,
            "recent_agents": sorted(agents, key=lambda a: (a["health"]["status"] != "needs_attention", -_ts(a["updated_at"]).timestamp()))[:8]}


@router.get("/abilities", summary="What Agent Studio can do here, each claim with its live proof (counts from this system)")
async def abilities(request: Request):
    """The home screen's 'What I can do': only real abilities, each with numbers read now - never a promise."""
    from fastapi.concurrency import run_in_threadpool

    from agent_studio import capabilities, skills, store

    async with Engine(request) as e:
        me = await e.me()
        agents = await e.list_agents()

    def facts() -> dict:
        cfg = settings.load()
        apps = capabilities.tools_config().get("apps") or {}
        lives = store.lives(me["id"])
        models = sorted({str(p.get("model")) for p in (cfg.get("ai") or {}).values()
                         if isinstance(p, dict) and p.get("model") and p.get("enabled", True) and p.get("provider") in ("ollama", "openai")})
        return {"agents": len(agents),
                "live": sum(1 for a in agents if (lives.get(a["id"]) or {}).get("state") == "live"),   # existing agents only
                "with_approval": sum(1 for a in agents if a.get("needs_approval")),
                "systems": sum(1 for a in apps.values() if isinstance(a, dict) and not a.get("mock")),
                "test_systems": sum(1 for a in apps.values() if isinstance(a, dict) and a.get("mock")),
                "known_addresses": len(cfg["app"].get("discover") or []),
                "skills": len(skills.approved()),
                "files": len(list_files(me["id"])),
                "channels": len(capabilities.notify_channels()),
                "internet": bool((capabilities.tools_config().get("web") or {}).get("enabled")),
                "models": models}

    return await run_in_threadpool(facts)


def _ts(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _group_runs(msgs: list[dict], names: dict[str, str]) -> list[dict]:
    by = defaultdict(list)
    for m in msgs:
        by[(m["agent_id"], m["session_id"])].append(m)
    runs = []
    for (agent_id, session_id), items in by.items():
        items.sort(key=lambda m: m["timestamp"] or "")
        first_user = next((m["text"] for m in items if m["sender"] == "User"), "")
        runs.append({"session_id": session_id, "agent_id": agent_id, "agent_name": names.get(agent_id, "(deleted agent)"),
                     "started_at": items[0]["timestamp"], "last_at": items[-1]["timestamp"], "messages": len(items),
                     # a run that never answered is a failed run, even when the engine reported no error
                     "error": any(m["error"] for m in items) or not any(m["sender"] != "User" and m["text"].strip() for m in items),
                     "first_message": first_user[:200],
                     "tokens_in": sum(m.get("tokens_in") or 0 for m in items),
                     "tokens_out": sum(m.get("tokens_out") or 0 for m in items)})
    return sorted(runs, key=lambda r: r["last_at"] or "", reverse=True)


def contract() -> dict:
    """OpenAPI document of the Agent Studio API only."""
    from agent_studio import designs, health, lifecycle, quality, sharing, tools

    spec = FastAPI(title="Agent Studio API", version="1.0.0")
    spec.include_router(router)
    spec.include_router(designs.router)
    spec.include_router(tools.router)
    spec.include_router(health.router)
    spec.include_router(sharing.router)
    spec.include_router(quality.router)
    spec.include_router(lifecycle.router)
    return spec.openapi()


@router.get("/openapi.json", include_in_schema=False)
async def openapi_json():
    return contract()
