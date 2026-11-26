"""Failure watchkeeper: a live agent whose run fails tells people, without anyone setting it up. Each run that did
not fail is also checked against the agent's goal (watch/goals.py).

Every few minutes (config app.failure_check_minutes; 0 = off) Agent Studio reads each LIVE agent's runs by id (read-only,
as the engine's administrator), finds runs that failed since the last look, and posts
one short message to the deployment's pre-approved alert channel (a failed run it started by itself is first run
once more; only if that also fails are people told) - at most once per agent per day, so a model
outage cannot flood the channel. Read-only on the engine; the only write is that one message.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.concurrency import run_in_threadpool
from starlette.requests import Request

from agent_studio import activity, capabilities, settings, store

log = logging.getLogger("agent_studio.watch.failures")
QUIET = timedelta(hours=24)


def _ts(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _channel() -> dict | None:
    """The first pre-approved notification channel of this deployment (tools.yaml notify)."""
    for name, ch in (capabilities.tools_config().get("notify") or {}).items():
        if isinstance(ch, dict) and ch.get("url") and not ch.get("requires_approval", True):
            return {"name": name, **ch}
    return None


def message(agent_name: str, when: str, reason: str) -> str:
    from agent_studio.brand import brand

    return (f"{brand()['name']}: the agent '{agent_name}' could not finish its run at {when[:16].replace('T', ' ')} UTC. "
            f"Reason: {reason[:300] or 'no answer'}. Open Runs to see what happened.")


def _title() -> str:
    from agent_studio.brand import brand

    return brand()["name"]


async def _post(ch: dict, text: str, what: str = "agent run failed") -> None:
    payload = {"text": f"**{_title()} - {what}**\n\n{text}"} if ch.get("format", "text") == "text" else \
        {"title": f"{_title()} - {what}", "text": text, "severity": "warning"}
    async with httpx.AsyncClient(timeout=float(ch.get("timeout_s", 10)), trust_env=False) as c:
        r = await c.post(ch["url"], json=payload)
    r.raise_for_status()


async def owner_request(user_id: str) -> Request | None:
    """A request carrying the agent owner's engine session: the engine shows each person only their own runs."""
    from agent_studio.engine import _cfg

    cfg = _cfg()
    async with httpx.AsyncClient(base_url=cfg["url"], timeout=30, trust_env=False) as c:
        r = await c.post("/studio-engine/session-as-owner", json={"user_id": user_id},
                         headers={"X-Studio-Engine-Secret": settings.secret(cfg["secret_env"])})
    if r.status_code != 200:
        log.warning("failure watch: no engine session for owner %s (%s)", user_id, r.status_code)
        return None
    return Request({"type": "http", "headers": [(b"authorization", f"Bearer {r.json()['access_token']}".encode())]})


PARK_AFTER = 3   # failed self-started runs in a row (each already retried) before the agent is paused


def retry_message(message_in: str, why: str) -> str:
    """The same request, plus what went wrong, so the agent can choose another way instead of repeating itself."""
    base = message_in or "Run your task now."
    if not why:
        return base
    return (f"{base}\n\n(Your previous attempt at this failed: {why[:300]}. Try again. If a tool failed, check its "
            "arguments or use another of your tools; if a system cannot be reached, say exactly which one.)")


def should_park(runs: list[dict], why: str, retry_reply: str) -> bool:
    """Pause an agent only for its own repeated failures - never for a model outage, which hits every agent."""
    from agent_studio.engine import MODEL_DOWN
    from agent_studio.watch.goals import by_trigger

    if MODEL_DOWN in (why, retry_reply):
        return False
    mine = [r for r in runs if by_trigger(r["session_id"])][:PARK_AFTER]
    return len(mine) == PARK_AFTER and all(r["error"] for r in mine)


async def _reason(e, session_id: str) -> str:
    from agent_studio.engine import _plain_error

    msgs = await e.messages(session_id=session_id)
    reason = next((m["text"] for m in msgs if m["error"] and m["text"].strip()), "")
    return _plain_error(reason) if reason else ""


async def _try(e, agent_id: str, text: str) -> dict:
    try:
        return await e.run_agent(agent_id, text)
    except Exception as exc:  # noqa: BLE001 - reported by the caller
        return {"status": "failed", "reply": str(exc)[:200]}


async def _park(e, row: dict, name: str, why: str, post) -> None:
    """Stop an agent that keeps failing from running by itself; its owner resumes it from Agents once fixed."""
    await e.set_triggers(row["agent_id"], False)
    await e.set_mcp(row["agent_id"], False)
    await run_in_threadpool(store.set_life, row["agent_id"], row["owner"], "paused", None, row.get("owner_name"))
    await activity.note("system", "paused an agent that kept failing", row["agent_id"], why[:300])
    text = (f"The agent '{name}' failed {PARK_AFTER} times in a row by itself, and once more when tried again, so it "
            f"was paused. Last reason: {why[:300] or 'no answer'}. Fix the cause, then resume it on the Agents page.")
    try:
        await post(text, "agent paused after repeated failures")
    except Exception as exc:  # noqa: BLE001
        log.warning("failure watch: could not post: %s", exc)


async def check_once() -> int:
    """One look at every live agent, as its owner; returns how many failure alerts were sent."""
    from agent_studio import api
    from agent_studio.engine import Engine
    from agent_studio.watch import goals, runtime

    rows = await run_in_threadpool(store.live_agents)
    ch = _channel()
    sent = 0
    now = datetime.now(timezone.utc)

    async def post(text: str, what: str) -> None:
        if ch:
            await _post(ch, text, what)

    for row in rows:
        request = await owner_request(row["owner"])
        if request is None:
            continue
        async with Engine(request) as e:
            try:
                name = (await e.get_agent(row["agent_id"]))["name"]
            except Exception:  # noqa: BLE001 - deleted in the engine meanwhile
                continue
            seen = row.get("seen_until") or row["updated_at"]
            seen = seen if isinstance(seen, datetime) else _ts(str(seen))
            runs = api._group_runs(await e.messages(agent_id=row["agent_id"], limit=200), {row["agent_id"]: name})
            new = [x for x in runs if _ts(x["last_at"]) > seen]
            if new:   # mark first: a retry made below is itself a new run, and must not be looked at again
                await run_in_threadpool(store.set_seen, row["agent_id"], max(_ts(x["last_at"]) for x in new))
            failed = [x for x in new if x["error"]]
            # a run it started by itself (schedule/alert/watch) that failed is run once more before anyone is told:
            # most failures are a model or system hiccup. The retry is a Agent Studio run ("run-…"), so it is never retried.
            own = [x for x in failed if goals.by_trigger(x["session_id"])]
            if own:
                message_in, _, _ = await goals._run_of(e, own[0]["session_id"])
                why = await _reason(e, own[0]["session_id"])
                out = await _try(e, row["agent_id"], retry_message(message_in, why))
                if out["status"] in ("done", "waiting_approval"):
                    await activity.note("system", "an agent's failed run was retried and then worked", row["agent_id"])
                    failed = [x for x in failed if x not in own]
                elif should_park(runs, why, out.get("reply", "")):
                    await _park(e, row, name, why or out.get("reply", ""), post)
                    continue
            elif not new:
                # a scheduled run that never happened (engine or app was down at that time) is made up once
                prefs = (await run_in_threadpool(store.design_of_agent, row["agent_id"])).get("prefs")
                if runtime.health(runs, prefs, now).get("reason") == "a scheduled run did not happen":
                    out = await _try(e, row["agent_id"], "Run your task now. (This run makes up a scheduled run that did not happen.)")
                    await activity.note("system", "a missed scheduled run was made up" if out["status"] != "failed"
                                        else "a missed scheduled run was made up but failed", row["agent_id"])
            quiet = row.get("alerted_at") and now - row["alerted_at"] < QUIET
            if failed and not quiet and ch:
                run = failed[0]
                try:
                    await _post(ch, message(name, run["last_at"] or "", await _reason(e, run["session_id"])))
                    await run_in_threadpool(store.mark_alerted, row["agent_id"])
                    sent += 1
                except httpx.HTTPError as exc:
                    log.warning("failure watch: could not post to %s: %s", ch["name"], exc)
            # every run it did by itself is checked against its goal (once more on a miss, then people are told)
            try:
                await goals.check_runs(e, row["agent_id"], name, new, post)
            except Exception:  # noqa: BLE001 - the watch keeps going
                log.exception("goal watch failed for %s", row["agent_id"])
    return sent


_sign_in_ok: dict[str, bool] = {}
SIGN_IN_EVERY = timedelta(hours=1)
_sign_in_last = datetime.min.replace(tzinfo=timezone.utc)


async def check_sign_ins() -> list[str]:
    """Saved sign-ins (Tools page) that stopped working since the last look: one message each, when it breaks."""
    from agent_studio import tools

    broken = []
    for name, app in (capabilities.tools_config().get("apps") or {}).items():
        state = tools._sign_in_state(name, app) if isinstance(app, dict) else None
        if not state or not state["saved"]:
            continue
        result = await run_in_threadpool(tools.check_sign_in, name)
        was = _sign_in_ok.get(name, True)
        _sign_in_ok[name] = result["ok"]
        if was and not result["ok"]:
            broken.append(name)
            text = (f"The saved sign-in for '{name}' stopped working ({result['detail']}). Agents that read from it will fail "
                    "until someone updates the password on the Tools page.")
            await activity.note("system", "sign-in of a connected system stopped working", name)
            ch = _channel()
            if ch:
                try:
                    await _post(ch, text, "sign-in needs updating")
                except httpx.HTTPError as exc:
                    log.warning("sign-in watch: could not post to %s: %s", ch["name"], exc)
    return broken


async def loop() -> None:
    from agent_studio.watch import models

    minutes = float(settings.load()["app"].get("failure_check_minutes") or 0)
    if minutes <= 0:
        return
    while True:
        await asyncio.sleep(minutes * 60)
        global _sign_in_last
        if datetime.now(timezone.utc) - _sign_in_last >= SIGN_IN_EVERY:
            _sign_in_last = datetime.now(timezone.utc)
            try:
                await check_sign_ins()
            except Exception:  # noqa: BLE001
                log.exception("sign-in watch round failed")
        try:
            await models.check_once()   # first: a retry below then already uses the backup model if needed
        except Exception:  # noqa: BLE001
            log.exception("model failover round failed")
        try:
            n = await check_once()
            if n:
                log.info("failure watch: %s alert(s) sent", n)
        except Exception:  # noqa: BLE001 - the watch keeps going
            log.exception("failure watch round failed")


if __name__ == "__main__":
    assert "could not finish its run at 2026-11-18 07:00" in message("SQL watch", "2026-11-18T07:00:12+00:00", "The AI model server could not be reached")
    assert message("x", "", "")
    assert retry_message("", "") == "Run your task now." and "failed: tool x broke" in retry_message("Check SQL", "tool x broke")
    bad = [{"session_id": "s", "error": True}] * 3
    assert should_park(bad + [{"session_id": "run-1", "error": False}], "tool x broke", "tool x broke")
    assert not should_park(bad, "The AI model server could not be reached, so the agent could not think. Try again in a minute.", "")
    assert not should_park(bad[:2] + [{"session_id": "s", "error": False}], "x", "x")
    print("failures ok")
