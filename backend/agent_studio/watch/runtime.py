"""Runtime watchkeeper: is each live agent working well? Judged from its real runs and its schedule.

  working_well     last run finished without error (and a scheduled agent ran when it was due)
  needs_attention  last run failed, several recent runs failed, or a scheduled run did not happen
  not_run_yet      no runs so far
Each comes with one plain reason, shown as a badge on Agents and the Dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

GRACE = timedelta(minutes=30)


def _field(spec: str, value: int, low: int) -> bool:
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part == "*":
            lo, hi = low, 10**6
        elif "-" in part:
            lo, hi = (int(x) for x in part.split("-"))
        else:
            lo = hi = int(part)
        if lo <= value <= hi and (value - lo) % step == 0:
            return True
    return False


def previous_fire(cron: str, now: datetime, tz: str = "Asia/Dubai", horizon_days: int = 35) -> datetime | None:
    """Most recent time a 5-field cron fired at or before now (minute resolution; ponytail: brute-force walk
    of at most horizon_days minutes, ~50k checks; swap for croniter if schedules ever need more)."""
    try:
        minute, hour, dom, month, dow = cron.split()
    except ValueError:
        return None
    local = now.astimezone(ZoneInfo(tz)).replace(second=0, microsecond=0)
    t = local
    for _ in range(horizon_days * 24 * 60):
        cron_dow = (t.weekday() + 1) % 7
        if (_field(minute, t.minute, 0) and _field(hour, t.hour, 0) and _field(dom, t.day, 1)
                and _field(month, t.month, 1) and _field(dow, cron_dow, 0)):
            return t.astimezone(timezone.utc)
        t -= timedelta(minutes=1)
    return None


def health(runs: list[dict], prefs: dict | None, now: datetime | None = None) -> dict:
    """runs: this agent's runs, newest first: [{"last_at": iso, "error": bool}]."""
    now = now or datetime.now(timezone.utc)
    if not runs:
        due = prefs and prefs.get("trigger") in ("schedule", "watch") and prefs.get("cron") and previous_fire(prefs["cron"], now, prefs.get("timezone") or "Asia/Dubai")
        return {"status": "not_run_yet", "reason": "waiting for its first scheduled run" if due is None or not due else "not run yet",
                "last_run_at": None, "recent_ok": 0, "recent_failed": 0}
    recent = runs[:5]
    failed = sum(1 for r in recent if r["error"])
    last = recent[0]
    out = {"last_run_at": last["last_at"], "recent_ok": len(recent) - failed, "recent_failed": failed}
    if last["error"]:
        return {**out, "status": "needs_attention", "reason": "its last run failed"}
    if failed >= 2:
        return {**out, "status": "needs_attention", "reason": f"{failed} of its last {len(recent)} runs failed"}
    if prefs and prefs.get("trigger") in ("schedule", "watch") and prefs.get("cron"):
        due = previous_fire(prefs["cron"], now, prefs.get("timezone") or "Asia/Dubai")
        last_at = datetime.fromisoformat(last["last_at"].replace("Z", "+00:00"))
        if due and now - due > GRACE and last_at < due - GRACE:
            return {**out, "status": "needs_attention", "reason": "a scheduled run did not happen"}
    return {**out, "status": "working_well", "reason": "recent runs finished well"}


if __name__ == "__main__":
    now = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)                     # 10:00 Dubai
    assert previous_fire("0 7 * * *", now) == datetime(2026, 11, 17, 3, 0, tzinfo=timezone.utc)
    assert previous_fire("0 0 1 * *", now) == datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
    ok = {"last_at": "2026-11-17T03:01:00+00:00", "error": False}
    assert health([ok], {"trigger": "schedule", "cron": "0 7 * * *"}, now)["status"] == "working_well"
    old = {"last_at": "2026-11-16T03:01:00+00:00", "error": False}
    assert health([old], {"trigger": "schedule", "cron": "0 7 * * *"}, now)["reason"] == "a scheduled run did not happen"
    assert health([{**ok, "error": True}], None, now)["status"] == "needs_attention"
    assert health([], None, now)["status"] == "not_run_yet"
    print("runtime ok")
