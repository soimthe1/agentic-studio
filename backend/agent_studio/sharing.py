"""Sharing: an owner shares a live agent; anyone signed in can then chat with it (share link /chat/<id>, also
embeddable in another internal page as an iframe) without being able to change it.

The engine shows each person only their own agents, so a shared agent runs in its OWNER's engine session (the same
owner session the watchkeepers use). Each conversation gets its own "run-shared-…" session, so people never see each
other's chats and the goal watch treats these like any person-started run. Changes still wait for the owner's approval.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import activity, roles, store
from agent_studio.engine import Engine

router = APIRouter(prefix="/api/studio/v1", tags=["Sharing"])
SESSION_PREFIX = "run-shared-"


class ShareIn(BaseModel):
    on: bool


class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str | None = Field(None, max_length=200)


@router.post("/agents/{agent_id}/share", summary="Share a live agent with everyone signed in (or stop sharing)",
             dependencies=[roles.need("builder")])
async def share(agent_id: str, body: ShareIn, request: Request):
    async with Engine(request) as e:
        await e.get_agent(agent_id)          # 404 unless it is the person's own agent
        me = await e.me()
    life = await run_in_threadpool(store.life, agent_id)
    if body.on and (not life or life["state"] != "live"):
        raise HTTPException(409, "Publish the agent first: only live agents can be shared.")
    await run_in_threadpool(store.set_shared, agent_id, body.on)
    await activity.note(me["username"], "shared an agent" if body.on else "stopped sharing an agent", agent_id)
    return {"shared": body.on, "link": f"/chat/{agent_id}"}


async def _shared(agent_id: str) -> tuple[dict, Request]:
    from agent_studio.watch.failures import owner_request

    row = next((r for r in await run_in_threadpool(store.shared_agents) if r["agent_id"] == agent_id), None)
    if not row:
        raise HTTPException(404, "This agent is not shared (or no longer live).")
    req = await owner_request(row["owner"])
    if req is None:
        raise HTTPException(503, "The agent's owner session could not be opened. Try again in a minute.")
    return row, req


@router.get("/shared", summary="Agents shared with everyone")
async def shared_list(request: Request):
    async with Engine(request):            # signed in
        pass
    out = []
    for row in await run_in_threadpool(store.shared_agents):
        state = await run_in_threadpool(store.design_of_agent, row["agent_id"])
        plan = state.get("plan") or {}
        out.append({"id": row["agent_id"], "name": (state.get("prefs") or {}).get("name") or plan.get("name") or "Agent",
                    "description": plan.get("understood") or "", "owner_name": row.get("owner_name") or "",
                    "samples": plan.get("sample_questions") or []})
    return out


@router.get("/shared/{agent_id}", summary="One shared agent (for its chat page)")
async def shared_one(agent_id: str, request: Request):
    hit = next((a for a in await shared_list(request) if a["id"] == agent_id), None)
    if not hit:
        raise HTTPException(404, "This agent is not shared (or no longer live).")
    return hit


@router.post("/shared/{agent_id}/run", summary="Ask a shared agent (it runs as its owner; your chat stays your own)")
async def shared_run(agent_id: str, body: AskIn, request: Request):
    async with Engine(request) as mine:
        who = (await mine.me())["username"]
    _, owner_req = await _shared(agent_id)
    session = body.session_id if (body.session_id or "").startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{uuid.uuid4()}"
    async with Engine(owner_req) as e:
        out = await e.run_agent(agent_id, body.message, session)
    await activity.note(who, "asked a shared agent", agent_id)
    return {**out, "session_id": session}
