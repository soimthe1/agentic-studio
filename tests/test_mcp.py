"""MCP (standard): other tools can use PUBLISHED agents as MCP tools through the engine's own MCP server; drafts,
paused and retired agents are never offered."""

import uuid

V1 = "/api/studio/v1"


def tools_in(admin, url: str) -> set[str]:
    project = url.split("/mcp/project/")[1].split("/")[0]
    meta = admin.get(f"/api/v1/mcp/project/{project}").json()
    return {t.get("name") for t in (meta.get("tools") or [])}


def test_only_published_agents_are_mcp_tools(app, admin):
    name = f"mcp check {uuid.uuid4().hex[:6]}"
    a = app.post(V1 + "/agents", json={"name": name, "description": "answers a test question"}).json()
    try:
        assert app.get(f"{V1}/agents/{a['id']}/mcp").json()["enabled"] is False, "a draft is not offered"
        assert app.post(f"{V1}/agents/{a['id']}/publish", json={"note": "v1"}).status_code == 200
        info = app.get(f"{V1}/agents/{a['id']}/mcp").json()
        assert info["enabled"] and info["url"].endswith("/streamable") and info["tool"]
        assert {info["tool"], name} & tools_in(admin, info["url"])
        assert app.post(f"{V1}/agents/{a['id']}/pause").status_code == 200
        assert app.get(f"{V1}/agents/{a['id']}/mcp").json()["enabled"] is False
        assert not {info["tool"], name} & tools_in(admin, info["url"])
    finally:
        app.delete(f"{V1}/agents/{a['id']}")


def test_an_mcp_client_connects_with_a_personal_key(app):
    """What another tool does: initialize, list tools (the published agent is one), then the key is revoked."""
    import httpx

    name = f"mcp client check {uuid.uuid4().hex[:6]}"
    a = app.post(V1 + "/agents", json={"name": name, "description": "answers a test question"}).json()
    key = None
    try:
        assert app.post(f"{V1}/agents/{a['id']}/publish", json={"note": "v1"}).status_code == 200
        info = app.get(f"{V1}/agents/{a['id']}/mcp/connect").json()
        assert info["enabled"] and info["settings"]["json"]["mcpServers"]
        key = app.post(V1 + "/mcp/keys", json={"label": "test"}).json()
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "x-api-key": key["key"]}
        with httpx.Client(trust_env=False, timeout=60) as mc:
            r = mc.post(info["url"], headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
            assert r.status_code == 200 and '"result"' in r.text
            if r.headers.get("mcp-session-id"):
                h["mcp-session-id"] = r.headers["mcp-session-id"]
            mc.post(info["url"], headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            tools = mc.post(info["url"], headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert info["tool"] in tools.text or name in tools.text
            assert app.delete(f"{V1}/mcp/keys/{key['id']}").status_code == 204
            key = None
            assert mc.post(info["url"], headers=h, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"}).status_code in (401, 403)
    finally:
        if key:
            app.delete(f"{V1}/mcp/keys/{key['id']}")
        app.delete(f"{V1}/agents/{a['id']}")


def test_an_mcp_server_becomes_a_connected_system(app):
    """The other direction: an MCP server (here: this platform's own MCP endpoint) is checked, connected by an
    administrator as one ability, and disconnected. The access key stays in an environment variable (MCP_SELFTEST_KEY
    in .env); without it the test is skipped."""
    import os
    import pytest
    from conftest import _env

    if not _env().get("MCP_SELFTEST_KEY"):
        pytest.skip("MCP_SELFTEST_KEY not set (an access key of this platform, see My access keys)")
    live = [x for x in app.get(V1 + "/agents").json() if x.get("state") == "live"]
    if not live:
        pytest.skip("no published agent to list over MCP")
    url = app.get(f"{V1}/agents/{live[0]['id']}/mcp/connect").json()["url"]
    name = f"mcp srv {uuid.uuid4().hex[:6]}"
    body = {"name": name, "url": url, "purpose": "test", "key_header": "x-api-key", "key_env": "MCP_SELFTEST_KEY"}
    checked = app.post(V1 + "/mcp/servers/check", json=body)
    assert checked.status_code == 200 and checked.json()["tools"], checked.text
    made = app.post(V1 + "/mcp/servers", json=body)
    assert made.status_code == 201, made.text
    sid = made.json()["id"]
    try:
        caps = {c["id"]: c for c in app.get(V1 + "/capabilities").json()["capabilities"]}
        assert caps[sid]["label"].endswith("(MCP)") and caps[sid]["status"] == "ready"
        assert app.post(V1 + "/mcp/servers", json=body).status_code == 409, "no duplicates"
        saved = open(os.path.join(os.path.dirname(__file__), "..", "data", "contracts", f"{sid}.yaml"), encoding="utf-8").read()
        assert _env()["MCP_SELFTEST_KEY"] not in saved and "MCP_SELFTEST_KEY" in saved, "only the variable name is stored"
    finally:
        assert app.delete(f"{V1}/mcp/servers/{sid}").status_code == 204
    assert sid not in {c["id"] for c in app.get(V1 + "/capabilities").json()["capabilities"]}
