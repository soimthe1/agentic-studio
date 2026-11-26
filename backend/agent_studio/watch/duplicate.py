"""Duplicate watchkeeper: before a new agent is built, compare it with the person's agents by facts, not wording.

An agent's fingerprint: what it can use (capabilities + sub-agents), when it starts (trigger + schedule), whether it
acts, whether it notifies, and the targets named in it. Same fingerprint = the same agent -> reuse or change it
(building anyway needs an explicit choice). Same abilities and start but different details = similar -> offered.
"""

from __future__ import annotations


def _core(caps: list[str]) -> frozenset:
    """What the agent reads from and changes (its job). Outputs (files, documents, notifications) and helpers
    (date, calculator) vary with wording and do not make a different agent."""
    try:
        from agent_studio import capabilities

        side = {c: cap.get("side_effect") for c, cap in capabilities.by_id().items()}
    except Exception:  # noqa: BLE001 - self-check without config
        side = {}
    return frozenset(c for c in caps if side.get(c, "read") in ("read", "write") and c not in ("notify", "date", "calculate"))


def fingerprint(prefs: dict, targets: list[str] | None = None) -> dict:
    return {"caps": _core(prefs.get("capabilities") or []),
            "subs": frozenset(prefs.get("sub_agents") or []), "trigger": prefs.get("trigger"),
            "cron": prefs.get("cron") if prefs.get("trigger") == "schedule" else None,
            "acts": prefs.get("acts"), "notify": prefs.get("notify"),
            "targets": frozenset(t.lower() for t in targets or [])}


def compare(mine: dict, others: list[dict]) -> list[dict]:
    """others: [{"design_id", "agent_id", "name", "prefs", "targets"}] of this person's built agents."""
    out = []
    for o in others:
        theirs = fingerprint(o["prefs"], o.get("targets"))
        if not mine["caps"] or mine["caps"] != theirs["caps"] or mine["subs"] != theirs["subs"]:
            continue
        same_start = mine["trigger"] == theirs["trigger"] and mine["cron"] == theirs["cron"]
        same = same_start and mine["acts"] == theirs["acts"] and mine["targets"] == theirs["targets"]
        out.append({"level": "warn" if same else "info", "kind": "duplicate" if same else "similar",
                    "agent_id": o["agent_id"], "design_id": o["design_id"], "name": o["name"],
                    "text": (f"'{o['name']}' already does exactly this. Use it or change it instead of making a copy."
                             if same else f"'{o['name']}' uses the same systems{' on the same schedule' if same_start else ''}. "
                                         "You could change it instead.")})
    return sorted(out, key=lambda f: f["kind"] != "duplicate")


if __name__ == "__main__":
    a = {"capabilities": ["iis_health", "date"], "trigger": "schedule", "cron": "0 7 * * *", "acts": "read_only", "notify": "problems"}
    others = [{"design_id": "d1", "agent_id": "a1", "name": "Morning IIS", "prefs": dict(a, capabilities=["iis_health"]), "targets": []},
              {"design_id": "d2", "agent_id": "a2", "name": "IIS on demand", "prefs": dict(a, trigger="chat"), "targets": []},
              {"design_id": "d3", "agent_id": "a3", "name": "SQL", "prefs": dict(a, capabilities=["sql_health"]), "targets": []}]
    r = compare(fingerprint(a), others)
    assert [x["kind"] for x in r] == ["duplicate", "similar"] and r[0]["agent_id"] == "a1", r
    print("duplicate ok")
