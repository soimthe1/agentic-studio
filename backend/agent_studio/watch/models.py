"""Model failover watchkeeper: when an agent's model server is down, live agents think with the backup model
(ai.<profile>.fallback in config.yaml) until it is back, then return to their own model. Nobody has to act.

Runs in the failure watch's loop, before its look at runs, so a retry of a failed run already uses the backup.
A server counts as down/back only after DOWN_AFTER looks in a row, so one dropped connection never moves agents.
Only agents made by the designer whose model step still holds their own or the backup model are touched.
"""

from __future__ import annotations

import logging

from fastapi.concurrency import run_in_threadpool

from agent_studio import activity, ai_providers, director, settings, store

log = logging.getLogger("agent_studio.watch.models")
DOWN_AFTER = 2
_streak: dict[str, int] = {}   # profile -> +n looks down in a row / -n looks up in a row
_using_backup: set[str] | None = None   # None until the first move: after a restart agents may still be on the backup


def note_look(profile: str, ok: bool) -> int:
    s = _streak.get(profile, 0)
    _streak[profile] = (min(s, 0) - 1) if ok else (max(s, 0) + 1)
    return _streak[profile]


def target(profile: str, streak: int, backup_ok: bool) -> str | None:
    """Which profile agents on `profile` should think with now; None = leave them as they are."""
    fb = ai_providers.profile(profile)["fallback"]
    if not fb:
        return None
    if streak >= DOWN_AFTER and backup_ok:
        return fb
    if streak <= -DOWN_AFTER:
        return profile
    return None


def swap(definition: dict, known: set[str], want: dict) -> bool:
    """Point the model step at `want` when it holds one of the `known` models; True when the definition changed."""
    changed = False
    for st in definition.get("steps") or []:
        if st.get("component") != director.MODEL_STEP:
            continue
        params = st.setdefault("params", {})
        name = (params.get("model") or {}).get("name") if isinstance(params.get("model"), dict) else None
        if name == want["name"] or name is not None and name not in known:
            continue   # already there, or a model someone chose by hand
        for k in ("model", "ollama_base_url"):
            params.pop(k, None)
        params.update(director.brain_params(want))
        changed = True
    return changed


async def check_once() -> int:
    """One look; returns how many agents were moved."""
    global _using_backup
    from agent_studio.engine import Engine
    from agent_studio.watch import failures

    ai = settings.load()["ai"]
    ai_providers.configure(ai, base_dir=settings.REPO)
    used = {p for p in ("default", "reasoning") if p in ai and ai_providers.profile(p)["fallback"]}
    if not used:
        return 0
    ok = {}
    for p in used | {ai_providers.profile(p)["fallback"] for p in used}:
        ok[p] = (await run_in_threadpool(ai_providers.check, p)).get("ok", False)
    plan = {p: target(p, note_look(p, ok[p]), ok[ai_providers.profile(p)["fallback"]]) for p in used}
    plan = {p: t for p, t in plan.items() if t and (_using_backup is None or (t != p) != (p in _using_backup))}
    if not plan:
        return 0

    moved = 0
    for row in await run_in_threadpool(store.live_agents):
        prefs = (await run_in_threadpool(store.design_of_agent, row["agent_id"])).get("prefs") or {}
        own_profile = director.profile_for(prefs.get("brain") or "fast")
        if not prefs or own_profile not in plan:
            continue
        fb = ai_providers.profile(own_profile)["fallback"]
        known = {director.model_of(own_profile)["name"], director.model_of(fb)["name"]}
        want = director.model_of(plan[own_profile])
        request = await failures.owner_request(row["owner"])
        if request is None:
            continue
        try:
            async with Engine(request) as e:
                definition = await e.get_definition(row["agent_id"])
                if swap(definition, known, want):
                    await e.save_definition(row["agent_id"], definition)
                    moved += 1
        except Exception:  # noqa: BLE001 - the next agent still gets moved
            log.exception("model failover: could not move %s", row["agent_id"])

    ch = failures._channel()
    was = _using_backup or set()
    _using_backup = set(was)
    for p, t in plan.items():
        to_backup = t != p
        (_using_backup.add if to_backup else _using_backup.discard)(p)
        if not to_backup and p not in was and not moved:
            continue   # first look after a start, nothing was on the backup: nothing to tell
        what = "AI model server down - agents use the backup model" if to_backup else "AI model server back - agents use their own model"
        text = (f"The AI model server for '{p}' ({ai_providers.profile(p)['base_url']}) "
                + (f"cannot be reached. Live agents now think with the backup model '{director.model_of(t)['name']}' "
                   "until it is back; answers may be slower or simpler." if to_backup else
                   "is working again. Live agents think with their own model again."))
        await activity.note("system", what, p, f"{moved} agent(s) moved")
        if ch:
            try:
                await failures._post(ch, text, what)
            except Exception as exc:  # noqa: BLE001
                log.warning("model failover: could not post: %s", exc)
    return moved


if __name__ == "__main__":
    _streak.clear()
    assert [note_look("x", False), note_look("x", False), note_look("x", True), note_look("x", True)] == [1, 2, -1, -2]
    d = {"steps": [{"component": director.MODEL_STEP, "params": {"model": {"provider": "vLLM", "name": "a1"}, "temperature": 0.1}}]}
    backup = {"provider": "Ollama", "name": "q3", "base_url": "http://o:11434"}
    assert swap(d, {"a1", "q3"}, backup) and d["steps"][0]["params"]["ollama_base_url"] == "http://o:11434"
    assert not swap(d, {"a1", "q3"}, backup)                                     # already there
    assert swap(d, {"a1", "q3"}, {"provider": "vLLM", "name": "a1", "base_url": ""})
    assert "ollama_base_url" not in d["steps"][0]["params"]                       # back, no stale address
    hand = {"steps": [{"component": director.MODEL_STEP, "params": {"model": {"provider": "vLLM", "name": "custom"}}}]}
    assert not swap(hand, {"a1", "q3"}, backup)                                  # chosen by hand: left alone
    print("models ok")
