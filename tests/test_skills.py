"""Skills: reusable know-how cards. Request (draft) -> admin approves (a version) -> suggested while an agent is
described -> chosen skill brings its tools and its text into the agent's instructions. No model needed here."""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

V1 = "/api/studio/v1"


def test_skill_request_approve_suggest_and_use(app):
    word = "zq" + uuid.uuid4().hex[:6]          # unique word so suggestion matching is deterministic
    card = {"name": f"Triage {word}", "when_to_use": f"checking {word} database health findings",
            "steps": [f"Read the critical {word} findings first", "Group them by server", "Give the fix order"],
            "output_format": "A table: server, finding, fix", "tools": ["sql_health"], "example": ""}
    r = app.post(V1 + "/skills", json=card)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["status"] == "draft"
    sid = row["skill_id"]
    assert sid not in {s["id"] for s in app.get(V1 + "/skills").json()["skills"]}, "a draft is not usable"
    assert app.post(V1 + "/skills", json=card).status_code == 409, "no duplicates"
    assert app.post(V1 + "/skills", json={**card, "name": "Other " + word, "tools": ["no_such_tool"]}).status_code == 422

    try:
        _approve_and_use(app, card, row, sid, word)
    finally:
        from agent_studio import store
        with store.connect() as c:
            c.execute("DELETE FROM skills WHERE skill_id = %s", (sid,))


def _approve_and_use(app, card, row, sid, word):
    assert app.post(f"{V1}/skills/requests/{row['id']}/approve").json()["status"] == "approved"
    listed = {s["id"]: s for s in app.get(V1 + "/skills").json()["skills"]}
    assert listed[sid]["version"] == 1

    # a new version keeps the id; the newest approved one is in use
    v2 = app.post(V1 + "/skills", json={**card, "steps": card["steps"] + ["Say what changed since last time"], "update_of": sid})
    assert v2.status_code == 201, v2.text
    app.post(f"{V1}/skills/requests/{v2.json()['id']}/approve")
    assert {s["id"]: s for s in app.get(V1 + "/skills").json()["skills"]}[sid]["version"] == 2

    from agent_studio import director, skills
    assert sid in [s["id"] for s in skills.suggest(f"Every morning look at the {word} database health findings")]
    text = director.instructions({"instructions": "", "language": "en"},
                                 {"detail": "short", "notify": "never", "acts": "read_only", "capabilities": [], "skills": [sid]}, [])
    assert "Say what changed since last time" in text and "A table: server, finding, fix" in text
