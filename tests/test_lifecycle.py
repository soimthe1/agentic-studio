"""Agent lifecycle: Built -> Live -> Paused -> Retired, with versions. Only a Live agent runs by itself; a paused or
retired agent refuses runs; every publish is a version that can be put back."""

import pytest

V1 = "/api/studio/v1"


@pytest.fixture
def agent(app):
    a = app.post(V1 + "/agents", json={"name": "lifecycle-check", "description": "test"}).json()
    yield a
    app.delete(f"{V1}/agents/{a['id']}")


def state(app, agent_id):
    return next(x for x in app.get(V1 + "/agents").json() if x["id"] == agent_id)["state"]


def test_lifecycle(app, agent):
    aid = agent["id"]
    assert state(app, aid) == "built"
    r = app.post(f"{V1}/agents/{aid}/publish", json={"note": "v1"})
    assert r.status_code == 200 and r.json()["live_version"] == 1
    assert state(app, aid) == "live"

    assert app.post(f"{V1}/agents/{aid}/pause").json()["state"] == "paused"
    refused = app.post(f"{V1}/agents/{aid}/run", json={"message": "hello"})
    assert refused.status_code == 409 and "paused" in refused.text

    assert app.post(f"{V1}/agents/{aid}/resume").json()["state"] == "live"
    assert app.post(f"{V1}/agents/{aid}/publish", json={"note": "v2"}).json()["live_version"] == 2
    v = app.get(f"{V1}/agents/{aid}/versions").json()
    assert [x["version"] for x in v["versions"]] == [2, 1] and v["live_version"] == 2

    assert app.post(f"{V1}/agents/{aid}/versions/1/restore").json() == {"state": "live", "live_version": 1}
    assert app.post(f"{V1}/agents/{aid}/retire").json()["state"] == "retired"
    assert app.post(f"{V1}/agents/{aid}/run", json={"message": "hello"}).status_code == 409


def test_resume_needs_a_published_version(app, agent):
    assert app.post(f"{V1}/agents/{agent['id']}/resume").status_code == 409
