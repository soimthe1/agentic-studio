"""Agent Studio API contract (/api/studio/v1). The web app and the chat app depend on exactly this surface;
the engine adapter (backend/agent_studio/engine.py) must keep it working across Langflow upgrades."""

import httpx
import pytest
from conftest import APP, edge, node

V1 = "/api/studio/v1"
CHECK = "ext:studio:BundleCheckComponent@official"


@pytest.fixture(scope="module")
def check_agent(admin, catalog):
    """An agent whose graph is ChatInput -> Agent Studio Bundle Check -> ChatOutput (no model needed)."""
    nodes = [node(catalog, "ChatInput", "ChatInput-a1"), node(catalog, CHECK, "StudioBundleCheck-b2"),
             node(catalog, "ChatOutput", "ChatOutput-c3")]
    edges = [edge("ChatInput-a1", "message", ["Message"], "StudioBundleCheck-b2", "input_value", ["Message"]),
             edge("StudioBundleCheck-b2", "result", ["Message"], "ChatOutput-c3", "input_value", ["Data", "DataFrame", "Message"])]
    r = admin.post("/api/v1/flows/", json={"name": "contract-check-agent", "data": {"nodes": nodes, "edges": edges}})
    r.raise_for_status()
    yield r.json()["id"]
    admin.delete(f"/api/v1/flows/{r.json()['id']}")


def test_contract_published():
    spec = httpx.get(APP + V1 + "/openapi.json", trust_env=False).json()
    paths = set(spec["paths"])
    for p in ("/me", "/agents", "/agents/{agent_id}", "/agents/{agent_id}/run", "/executions", "/executions/{session_id}", "/dashboard"):
        assert V1 + p in paths, p
    assert not any("/api/v1/" in p for p in paths), "contract must not expose engine routes"


def test_signed_out_is_401():
    assert httpx.get(APP + V1 + "/me", trust_env=False).status_code == 401


def test_me(app):
    me = app.get(V1 + "/me").json()
    assert me["username"] and me["is_admin"] is True


def test_agent_lifecycle(app):
    a = app.post(V1 + "/agents", json={"name": "contract-empty", "description": "created by tests"})
    assert a.status_code == 201, a.text
    agent = a.json()
    assert "builder_url" not in agent and "7860" not in str(agent)  # normal users never get engine addresses
    assert any(x["id"] == agent["id"] for x in app.get(V1 + "/agents").json())
    assert app.patch(f"{V1}/agents/{agent['id']}", json={"description": "changed"}).json()["description"] == "changed"
    assert app.delete(f"{V1}/agents/{agent['id']}").status_code == 204
    assert app.get(f"{V1}/agents/{agent['id']}").status_code == 404


def test_run_and_executions(app, check_agent):
    r = app.post(f"{V1}/agents/{check_agent}/run", json={"message": "contract"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reply"] == "studio_tools 0.3.0 ok: contract" and out["session_id"]
    runs = app.get(V1 + "/executions").json()
    run = next(x for x in runs if x["session_id"] == out["session_id"])
    assert run["agent_name"] == "contract-check-agent" and run["messages"] >= 2 and not run["error"]
    msgs = app.get(f"{V1}/executions/{out['session_id']}").json()
    assert [m["text"] for m in msgs][-1] == "studio_tools 0.3.0 ok: contract"
    dash = app.get(V1 + "/dashboard").json()
    assert dash["agents"] >= 1 and dash["runs_7d"] >= 1


def test_validation(app):
    assert app.post(V1 + "/agents", json={"name": ""}).status_code == 422
    assert app.post(f"{V1}/agents/00000000-0000-0000-0000-000000000000/run", json={"message": "x"}).status_code == 404
