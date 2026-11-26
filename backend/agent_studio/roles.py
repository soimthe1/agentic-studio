"""Roles: user < builder < admin, decided at sign-in from Active Directory groups (config ldap.group_map) and
remembered per person; checked on every Agent Studio API call that needs more than using agents.

  user     use agents, approve their own agents' actions, see their runs and files
  builder  + create, change, test, publish, pause and retire agents; ask for new tools
  admin    + approve new tools; the engine's break-glass superuser and engine.console_admins are admins
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from agent_studio import settings, store
from agent_studio.engine import Engine

ORDER = {"user": 1, "builder": 2, "admin": 3}


def resolve(me: dict, remembered: str | None) -> str:
    admins = {str(u).lower() for u in settings.load()["engine"].get("console_admins") or []}
    if me.get("is_admin") or me["username"].lower() in admins:
        return "admin"
    if remembered in ORDER:
        return remembered
    # Not signed in since roles were recorded: the role everybody gets by configuration (ldap.group_map "everybody").
    gm = settings.load()["ldap"].get("group_map") or {}
    from agent_studio.auth import EVERYBODY, wanted_groups

    return next((r for r in ("admin", "builder", "user") if EVERYBODY in wanted_groups(gm.get(r))), "user")


async def role_of(request: Request) -> str:
    async with Engine(request) as e:
        me = await e.me()
    return resolve(me, await run_in_threadpool(store.person_role, me["username"]))


def need(role: str):
    """FastAPI dependency: at least this role."""
    async def check(request: Request) -> str:
        mine = await role_of(request)
        if ORDER[mine] < ORDER[role]:
            raise HTTPException(403, f"Your role ({mine}) cannot do this. Ask an administrator for {role} access.")
        return mine
    return Depends(check)


if __name__ == "__main__":
    import os
    os.environ.setdefault("STUDIO_DB_PASSWORD", "x")
    assert resolve({"username": "a", "is_admin": True}, "user") == "admin"
    assert resolve({"username": "b", "is_admin": False}, "builder") == "builder"
    assert resolve({"username": "c", "is_admin": False}, None) in ORDER
    print("roles ok")
