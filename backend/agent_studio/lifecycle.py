"""Agent lifecycle: Built -> Live -> Paused -> Retired, with versions.

One rule people can rely on: only a Live agent runs by itself. Publishing snapshots the agent as a new version in the engine's own version history and
arms its schedule/alert triggers in the engine; pausing disarms them and refuses runs; retiring also hides it from
the everyday lists (history and versions stay). Changing a live agent makes it Built again until it is published,
so a change is always proven and published on purpose. Any earlier version can be put back.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import activity, store
from agent_studio import roles
from agent_studio.engine import Engine

router = APIRouter(prefix="/api/studio/v1", tags=["Agent lifecycle"])
STATES = ("built", "live", "paused", "retired")


class NoteIn(BaseModel):
    note: str = Field("", max_length=300)


async def _mine(e: Engine, agent_id: str) -> dict:
    """The agent (404 if the engine says the person cannot see it) and the person."""
    await e.get_agent(agent_id)
    return await e.me()


def state_of(agent_id: str) -> dict:
    return store.life(agent_id) or {"state": "built", "live_version": None}


def _proven(owner: str, agent_id: str) -> bool:
    for row in store.list_designs(owner, limit=200):
        if row.get("agent_id") == agent_id:
            proof = ((store.get_design(owner, row["id"]) or {}).get("state") or {}).get("proof") or {}
            return proof.get("verdict") == "met" or bool(proof.get("approval"))
    return True   # agents made outside the designer (engine console) have no proof record; publishing is the admin's call


@router.post("/agents/{agent_id}/publish", summary="Publish: snapshot a new version and let it run by itself", dependencies=[roles.need("builder")])
async def publish(agent_id: str, body: NoteIn, request: Request):
    async with Engine(request) as e:
        me = await _mine(e, agent_id)
        if not await run_in_threadpool(_proven, me["id"], agent_id):
            raise HTTPException(409, "Test it first: its last test run did not show it doing the job.")
        n = (await e.snapshot(agent_id, body.note or "Published"))["version_number"]   # the engine's own history
        armed = await e.set_triggers(agent_id, True)
        await e.set_mcp(agent_id, True)          # published agents (only) are offered to other tools over MCP
    await run_in_threadpool(store.set_life, agent_id, me["id"], "live", n, me["username"])
    await activity.note(me["username"], "published an agent", agent_id, f"version {n}: {body.note or 'Published'}")
    return {"state": "live", "live_version": n, "triggers_armed": armed}


@router.post("/agents/{agent_id}/{action}", summary="Pause, resume or retire an agent", dependencies=[roles.need("builder")])
async def change(agent_id: str, action: str, request: Request):
    if action not in ("pause", "resume", "retire"):
        raise HTTPException(404, "Not found")
    async with Engine(request) as e:
        me = await _mine(e, agent_id)
        current = (await run_in_threadpool(state_of, agent_id))["state"]
        if action == "resume" and current not in ("paused", "retired"):
            raise HTTPException(409, "Only a paused or retired agent can be resumed")
        if action == "resume" and not (await run_in_threadpool(state_of, agent_id)).get("live_version"):
            raise HTTPException(409, "It was never published: publish it instead")
        await e.set_triggers(agent_id, action == "resume")
        await e.set_mcp(agent_id, action == "resume")
    new = {"pause": "paused", "resume": "live", "retire": "retired"}[action]
    await run_in_threadpool(store.set_life, agent_id, me["id"], new, None, me["username"])
    await activity.note(me["username"], {"pause": "paused an agent", "resume": "resumed an agent", "retire": "retired an agent"}[action], agent_id)
    return {"state": new}


@router.get("/agents/{agent_id}/mcp", summary="How other tools can use this agent over MCP (published agents only)")
async def mcp_info(agent_id: str, request: Request):
    async with Engine(request) as e:
        await _mine(e, agent_id)
        flow = await e._call("GET", f"/api/v1/flows/{agent_id}")
    from agent_studio.engine import _cfg

    return {"enabled": bool(flow.get("mcp_enabled")), "tool": flow.get("action_name"),
            "url": f"{_cfg()['public_url'].rstrip('/')}/api/v1/mcp/project/{flow.get('folder_id')}/streamable"}


@router.get("/agents/{agent_id}/versions", summary="Published versions of an agent")
async def list_versions(agent_id: str, request: Request):
    async with Engine(request) as e:
        await _mine(e, agent_id)
        native = await e.versions(agent_id)
    life = await run_in_threadpool(state_of, agent_id)
    rows = [{"version": v["version_number"], "note": v.get("description") or "", "created_by": v.get("username") or "",
             "created_at": v.get("created_at")} for v in native]
    if not rows:   # published before versions moved to the engine's history
        rows = await run_in_threadpool(store.versions, agent_id)
    return {"state": life["state"], "live_version": life.get("live_version"),
            "versions": sorted(rows, key=lambda r: -r["version"])}


@router.post("/agents/{agent_id}/versions/{n}/restore", summary="Put an earlier version back (it goes live again)", dependencies=[roles.need("builder")])
async def restore(agent_id: str, n: int, request: Request):
    async with Engine(request) as e:
        me = await _mine(e, agent_id)
        native = next((v for v in await e.versions(agent_id) if v["version_number"] == n), None)
        if native:
            await e.activate(agent_id, str(native["id"]))
        else:   # an older version kept in Agent Studio's own table
            row = await run_in_threadpool(store.version, agent_id, n)
            if not row:
                raise HTTPException(404, "No such version")
            await e.save_definition(agent_id, row["definition"])
        await e.set_triggers(agent_id, True)
        await e.set_mcp(agent_id, True)
    await run_in_threadpool(store.set_life, agent_id, me["id"], "live", n, me["username"])
    await activity.note(me["username"], "put back an earlier version", agent_id, f"version {n}")
    return {"state": "live", "live_version": n}
