"""Goal watchkeeper: every run a live agent does by itself is checked against the goal the person agreed - not only
the first test run. A run that misses its goal is tried once more; if the second try also misses, people are told.

Called by the failure watch (same loop, same read-only engine view) for each new run that finished without an error.
Runs started from Agent Studio itself (chat, test runs, retries: session "run-…"/"memory-…") are not judged here: a person
was there to see them. The result is kept per agent (agent_life.last_check) and shown on the agent's tile.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool

from agent_studio import activity, capabilities, designer, store

log = logging.getLogger("agent_studio.watch.goals")
SUGGESTER = "Agent Studio (goal check)"
MAX_PER_ROUND = 3          # runs judged per agent per round (a burst of runs cannot flood the model server)


def by_trigger(session_id: str) -> bool:
    return not str(session_id or "").startswith(("run-", "memory-"))


def delivery(prefs: dict) -> str | None:
    if prefs.get("notify", "never") != "never" and "notify" in (prefs.get("capabilities") or []):
        chan = prefs.get("channel") or next((c["id"] for c in capabilities.notify_channels()), "the channel")
        return (f"Agent Studio posts the agent's answer to '{chan}' " +
                ("when the answer's last line is 'STATUS: PROBLEM'." if prefs["notify"] == "problems" else "after every run."))
    return None


def with_feedback(message: str, missing: list[str]) -> str:
    gaps = [m for m in missing if m][:3]
    if not gaps:
        return message
    return (f"{message or 'Run your task now.'}\n\n(A check of your previous attempt found this missing: "
            + "; ".join(gaps) + ". Cover it this time, using your tools; if it cannot be done, say why.)")


def suggestion(missing: list[str]) -> str:
    gaps = [m.strip().rstrip(".") for m in missing if m and m.strip()][:3]
    return ("Always make sure your answer covers: " + "; ".join(gaps) + ".") if gaps else ""


async def suggest(agent_id: str, session_id: str, reply: str, missing: list[str]) -> None:
    """A miss that survived the retry becomes a suggested correction. It waits for the owner (the agent list shows
    "to apply"), who takes it in by rebuilding: the agent proposes how to improve, a person decides."""
    text = suggestion(missing)
    if not text:
        return
    waiting = await run_in_threadpool(store.corrections, agent_id, True)
    if any(w["correction"] == text for w in waiting):
        return
    await run_in_threadpool(store.add_feedback, SUGGESTER, agent_id, session_id, False, reply, text)


def _judge(plan: dict, prefs: dict, message: str, reply: str, tools: list[dict]) -> dict:
    check = designer.check_result(plan, message, reply, None, tools, delivery(prefs))
    uses_tools = any(c not in ("date", "calculate") for c in prefs.get("capabilities") or [])
    if uses_tools and not tools and check["verdict"] in ("met", "partly", "unknown"):
        check = {**check, "verdict": "not_met",
                 "missing": ["It answered without using any of its tools, so the answer is not based on real data."] + check["missing"]}
    return check


async def _run_of(e, session_id: str) -> tuple[str, str, list[dict]]:
    msgs = sorted(await e.messages(session_id=session_id), key=lambda m: m["timestamp"] or "")
    first = next((m["text"] for m in msgs if m["sender"] == "User"), "")
    reply = next((m["text"] for m in reversed(msgs) if m["sender"] != "User" and m["text"].strip()), "")
    return first, reply, [t for m in msgs for t in m["tools"]]


async def check_runs(e, agent_id: str, name: str, runs: list[dict], post) -> int:
    """Judge new self-started runs of one live agent; returns how many still missed after a retry (alerts sent)."""
    state = await run_in_threadpool(store.design_of_agent, agent_id)
    plan, prefs = state.get("plan") or {}, state.get("prefs") or {}
    if not plan.get("goals") and not plan.get("understood"):
        return 0
    missed = 0
    todo = sorted([r for r in runs if not r["error"] and by_trigger(r["session_id"])], key=lambda r: r["last_at"] or "")
    for run in todo[-MAX_PER_ROUND:]:
        message, reply, tools = await _run_of(e, run["session_id"])
        check = await run_in_threadpool(_judge, plan, prefs, message, reply, tools)
        retried = None
        if check["verdict"] == "not_met":
            # one more try, told what the check found missing, so it can do it another way (not repeat itself)
            try:
                out = await e.run_agent(agent_id, with_feedback(message, check["missing"]))
                if out["status"] == "done":
                    _, reply2, tools2 = await _run_of(e, out["session_id"])
                    check2 = await run_in_threadpool(_judge, plan, prefs, message, reply2 or out["reply"], tools2)
                    retried = {"session_id": out["session_id"], "verdict": check2["verdict"]}
                    if check2["verdict"] != "not_met":
                        check = check2
                else:
                    retried = {"session_id": out.get("session_id"), "verdict": out["status"]}
            except Exception as exc:  # noqa: BLE001 - the check goes on; the miss is still reported
                retried = {"error": str(exc)[:200]}
        result = {"at": datetime.now(timezone.utc).isoformat(), "session_id": run["session_id"], "verdict": check["verdict"],
                  "missing": check["missing"][:3], "retried": retried}
        await run_in_threadpool(store.set_last_check, agent_id, result)
        if check["verdict"] == "not_met":
            missed += 1
            text = (f"The agent '{name}' ran by itself but did not do what it is for, even after one more try. "
                    f"What was missing: {'; '.join(check['missing'][:3]) or 'see Runs'}. Open Runs to see what it did.")
            await activity.note("system", "an agent missed its goal", agent_id, "; ".join(check["missing"][:2]))
            await suggest(agent_id, run["session_id"], reply, check["missing"])
            try:
                await post(text, "agent missed its goal")
            except Exception as exc:  # noqa: BLE001
                log.warning("goal watch: could not post: %s", exc)
        elif retried:
            await activity.note("system", "an agent's run was retried and then met its goal", agent_id)
        if check["verdict"] == "met" and prefs.get("learn_notes", True):
            try:   # long-term memory: what is worth knowing next time goes into its instructions
                from agent_studio import learn
                if await learn.remember_run(e, agent_id, (retried or {}).get("reply") or reply):
                    await activity.note("system", "an agent noted something for its next runs", agent_id)
            except Exception:  # noqa: BLE001 - notes are a bonus; the check result stands
                log.exception("notes failed for %s", agent_id)
    return missed
