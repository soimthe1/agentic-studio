"""Build-check watchkeeper: the built agent is checked against what was promised, before it is saved.

- only approved components (config/policy/catalog.yaml), whatever the director produced;
- every chosen, available capability is really wired in;
- anything that changes systems sits behind the human approval step, and is never given to the first agent;
- a promised notification has its notify step; a schedule has its trigger with the agreed time.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_studio import capabilities, settings


def _allowed() -> set[str]:
    cat = yaml.safe_load((capabilities._config_dir() / "policy" / "catalog.yaml").read_text(encoding="utf-8"))
    return {k for g in cat["groups"] for k in g["components"]}


def check(definition: dict, prefs: dict, left_out: list[dict]) -> list[dict]:
    steps = {s["id"]: s for s in definition["steps"]}
    links = definition["connections"]
    caps = capabilities.by_id()
    findings: list[dict] = []

    bad = sorted({s["component"] for s in steps.values()} - _allowed())
    if bad:
        findings.append({"level": "block", "text": "Not approved for agents: " + ", ".join(bad)})

    skipped = {x["capability"] for x in left_out}
    for cid in prefs.get("capabilities") or []:
        if cid in skipped or cid == "notify" or cid not in caps:
            continue
        if f"tool-{cid}" not in steps:
            findings.append({"level": "block", "text": f"'{caps[cid]['label']}' was chosen but is not in the built agent."})

    writes = [sid for sid in steps if sid.startswith("tool-") and caps.get(sid[5:], {}).get("side_effect") == "write"]
    for sid in writes:
        users = {c["to"] for c in links if c["from"] == sid}
        if "approval" not in steps or users - {"executor"}:
            findings.append({"level": "block", "text": f"'{caps[sid[5:]]['label']}' changes systems but is not behind the approval step."})

    if prefs.get("notify") in ("problems", "always") and "notify" not in skipped and "notify" not in steps:
        findings.append({"level": "block", "text": "A notification was promised but the agent has no notify step."})
    if prefs.get("trigger") == "schedule" or (prefs.get("trigger") == "watch" and prefs.get("cron")):
        trig = steps.get("trigger")
        if not trig or trig["params"].get("cron_expression") != prefs.get("cron"):
            findings.append({"level": "block", "text": "The schedule in the built agent differs from the one agreed."})
    if not any(f["level"] == "block" for f in findings):
        findings.append({"level": "ok", "text": f"Built with {len(steps)} approved steps; changes stay behind approval."
                         if writes else f"Built with {len(steps)} approved steps; it cannot change any system."})
    return findings
