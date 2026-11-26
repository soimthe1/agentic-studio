"""'Not right? Tell it how': thumbs on answers are counted per agent, a correction waits on the agent until it is
rebuilt, and the rebuilt agent's instructions carry every correction (no model needed here)."""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

V1 = "/api/studio/v1"


def test_thumbs_and_corrections_are_kept_and_shown(app):
    a = app.post(V1 + "/agents", json={"name": f"feedback-check-{uuid.uuid4().hex[:6]}", "description": "test"}).json()
    try:
        assert app.post(f"{V1}/agents/{a['id']}/feedback", json={"good": True, "answer": "ok"}).status_code == 204
        assert app.post(f"{V1}/agents/{a['id']}/feedback", json={
            "good": False, "answer": "21 critical", "correction": "Always give the total from the findings summary"}).status_code == 204
        me = next(x for x in app.get(V1 + "/agents").json() if x["id"] == a["id"])
        assert me["feedback"] == {"good": 1, "bad": 1, "corrections_waiting": 1}
        fixes = app.get(f"{V1}/agents/{a['id']}/corrections").json()
        assert [f["correction"] for f in fixes] == ["Always give the total from the findings summary"]
        assert any(r["action"] == "corrected an agent" for r in app.get(f"{V1}/activity", params={"q": a["id"]}).json())
    finally:
        app.delete(f"{V1}/agents/{a['id']}")


def test_corrections_go_into_the_instructions():
    from agent_studio import director
    text = director.instructions({"instructions": "", "language": "en"},
                                 {"detail": "short", "notify": "never", "acts": "read_only", "capabilities": [],
                                  "corrections": ["Always give the total from the findings summary"]}, [])
    assert "corrected earlier answers" in text and "Always give the total from the findings summary" in text
