"""'Remembers our past chats': with the switch on, each person keeps one ongoing conversation with the agent (the
engine's own chat history - no vector store); 'Forget our chats' clears it. Uses the model server."""

import uuid

V1 = "/api/studio/v1"


def test_agent_remembers_then_forgets(app):
    agents = [a for a in app.get(V1 + "/agents").json() if a.get("state") == "live"]
    designs = {d["agent_id"]: d["id"] for d in app.get(V1 + "/designs").json() if d.get("agent_id")}
    agent = next((a for a in agents if a["id"] in designs), None)
    if not agent:
        import pytest
        pytest.skip("no live agent made from a description")
    aid, did = agent["id"], designs[agent["id"]]
    before = app.get(f"{V1}/designs/{did}").json()["prefs"].get("remember", False)
    app.patch(f"{V1}/designs/{did}/prefs", json={"prefs": {"remember": True}})
    word = "zebra" + uuid.uuid4().hex[:4]
    try:
        app.delete(f"{V1}/agents/{aid}/memory")
        first = app.post(f"{V1}/agents/{aid}/run", json={"message": f"Remember this code word: {word}. Just say OK."}).json()
        second = app.post(f"{V1}/agents/{aid}/run", json={"message": "What code word did I give you? Answer from our chat, no tools."}).json()
        assert first["session_id"] == second["session_id"], "both runs continue one conversation"
        assert word in (second["reply"] or ""), second
        assert app.get(f"{V1}/agents/{aid}/memory").json()["messages"]
    finally:
        app.delete(f"{V1}/agents/{aid}/memory")
        app.patch(f"{V1}/designs/{did}/prefs", json={"prefs": {"remember": before}})
    assert app.get(f"{V1}/agents/{aid}/memory").json()["messages"] == []
