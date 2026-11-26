"""Activity log (administrators): who did what, when - in plain words, with a CSV export.

The engine's own audit log only records authorization and privacy events, so Agent Studio records the moments that matter
for people itself: an agent created, published, paused, resumed, retired, restored or deleted; an approval given or
refused; a connected system or a know-how card approved or rejected; a sign-in. One row each, never secrets.
"""

from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from agent_studio import roles, store

router = APIRouter(prefix="/api/studio/v1", tags=["Activity"])
log = logging.getLogger("agent_studio.activity")


async def note(who: str, action: str, target: str = "", detail: str = "") -> None:
    """Record one event; a failure to record never breaks the action itself."""
    try:
        await run_in_threadpool(store.add_activity, who or "?", action, target[:200], detail[:500])
    except Exception:  # noqa: BLE001
        log.exception("activity not recorded: %s %s", action, target)


async def note_as(e, action: str, target: str = "", detail: str = "") -> None:
    """Same, for endpoints that do not already know who is acting."""
    try:
        who = (await e.me())["username"]
    except Exception:  # noqa: BLE001
        who = "?"
    await note(who, action, target, detail)


@router.get("/activity", summary="Who did what, when (administrators)", dependencies=[roles.need("admin")])
async def activity(q: str = "", limit: int = 200):
    return await run_in_threadpool(store.list_activity, q.strip(), max(1, min(limit, 1000)))


@router.get("/activity.csv", summary="The activity log as a CSV file (administrators)", dependencies=[roles.need("admin")])
async def activity_csv(q: str = ""):
    rows = await run_in_threadpool(store.list_activity, q.strip(), 10000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time (UTC)", "who", "action", "what", "details"])
    for r in rows:
        w.writerow([r["at"], r["who"], r["action"], r["target"], r["detail"]])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="agent-studio-activity.csv"'})
