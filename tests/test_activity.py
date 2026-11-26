"""Activity log: the moments that matter are recorded in plain words (who, what, which) and administrators can read
and export them."""

import uuid

V1 = "/api/studio/v1"


def test_publish_pause_delete_are_recorded_and_exported(app):
    name = f"activity-check-{uuid.uuid4().hex[:6]}"
    a = app.post(V1 + "/agents", json={"name": name, "description": "test"}).json()
    try:
        assert app.post(f"{V1}/agents/{a['id']}/publish", json={"note": "first"}).status_code == 200
        assert app.post(f"{V1}/agents/{a['id']}/pause").status_code == 200
    finally:
        app.delete(f"{V1}/agents/{a['id']}")
    rows = app.get(f"{V1}/activity", params={"q": a["id"]}).json()
    actions = [r["action"] for r in rows]
    assert {"published an agent", "paused an agent", "deleted an agent"} <= set(actions), actions
    assert all(r["who"] and r["at"] for r in rows)
    csv = app.get(f"{V1}/activity.csv", params={"q": a["id"]})
    assert csv.status_code == 200 and "published an agent" in csv.text and csv.text.startswith("time (UTC),who,action")
