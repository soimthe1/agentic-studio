"""New tools from a system's published contract: learn -> request (draft) -> admin approves -> reusable tool that
agents can use at once, without duplicates and without secrets in any file. Uses the declared test double (its
FastAPI app publishes /openapi.json) on port 9190, reached from the engine as host.docker.internal."""

import sys
import uuid
from pathlib import Path

import httpx
import pytest
import yaml
from conftest import ROOT

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

V1 = "/api/studio/v1"
SYSTEM = "http://host.docker.internal:9190"


@pytest.fixture(scope="module")
def learned(app):
    try:
        r = app.post(V1 + "/tools/learn", json={"address": SYSTEM, "need": "fleet status of a host"}, timeout=60)
    except httpx.HTTPError:
        pytest.skip("test double not reachable")
    if r.status_code == 404:
        pytest.skip("test double not running (python tests/mocks/apps.py)")
    assert r.status_code == 200, r.text
    return r.json()


def test_learn_lists_reads_and_changes_in_plain_words(learned):
    ops = {o["path"]: o for o in learned["operations"]}
    assert ops["/remediation/api/v1/fleet/{host}"]["kind"] == "read"
    assert any(o["kind"] == "change" for o in learned["operations"])
    assert ops["/remediation/api/v1/fleet/{host}"]["matches_need"]
    assert learned["existing"], "the same host is already connected (sqlmon/iis/remediation test systems) - offered for reuse"


def test_request_approve_and_use(app, learned):
    name = f"fleet {uuid.uuid4().hex[:5]}"
    fleet = next(o for o in learned["operations"] if o["path"] == "/remediation/api/v1/fleet/{host}")
    r = app.post(V1 + "/tools/requests", json={"name": name, "purpose": "Fleet status", "base_url": learned["base_url"],
                                                "contract_url": learned["contract_url"], "operations": [fleet],
                                                "sign_in": "ad_login", "account": "svc_test"})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "draft"
    tool_id = req["tool_id"]
    caps = {c["id"] for c in app.get(V1 + "/capabilities").json()["capabilities"]}
    assert f"{tool_id}_read" not in caps, "a draft must not be usable"
    assert app.post(V1 + "/tools/requests", json={**r.json()["spec"], "operations": [fleet]}).status_code == 409, "no duplicates"

    assert app.post(f"{V1}/tools/requests/{req['id']}/approve").status_code == 409, "approval needs a passed test call"
    tried = app.post(f"{V1}/tools/requests/{req['id']}/test").json()
    assert tried["results"] and tried["results"][0]["ok"] is None  # /fleet/{host} needs a value: listed, not guessed
    assert tried["passed"], tried                                 # ... and the system itself answers
    d = app.post(f"{V1}/tools/requests/{req['id']}/approve")
    assert d.status_code == 200 and d.json()["status"] == "approved", d.text
    path = ROOT / "data" / "contracts" / f"{tool_id}.yaml"
    try:
        text = path.read_text(encoding="utf-8")
        contract = yaml.safe_load(text)
        conn = contract["tools"]["apps"][tool_id]
        assert conn["operations"][fleet["id"]]["path"] == fleet["path"] and conn["allow_write"] is False
        assert conn["auth"]["password_env"].startswith("STUDIO_TOOL_") and "password:" not in text
        cat = app.get(V1 + "/capabilities").json()
        assert f"{tool_id}_read" in {c["id"] for c in cat["capabilities"]}
        assert tool_id in {a["id"] for a in cat["apps"]}
        assert contract["version"] == 1
        # a new version of the same tool: same id, the old version kept in history
        v2 = app.post(V1 + "/tools/requests", json={**req["spec"], "update_of": tool_id})
        assert v2.status_code == 201, v2.text
        assert app.post(f"{V1}/tools/requests/{v2.json()['id']}/approve?force=true").json()["status"] == "approved"
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["version"] == 2
        assert (path.parent / "history" / f"{tool_id}.v1.yaml").exists()
        (path.parent / "history" / f"{tool_id}.v1.yaml").unlink()
    finally:
        path.unlink(missing_ok=True)
        from agent_studio import store       # the test's own requests are not left in people's lists
        with store.connect() as c:
            c.execute("DELETE FROM tool_requests WHERE tool_id = %s", (tool_id,))


def test_only_admins_approve(app):
    # the test client is the superuser (an admin); a normal user's view says it cannot approve
    assert app.get(V1 + "/tools").json()["can_approve"] is True


def test_discover_checks_only_the_listed_systems(app):
    # config app.discover lists known addresses; Agent Studio only reads what each one publishes (never scans)
    listed = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))["app"]["discover"]
    systems = app.get(V1 + "/tools/discover", timeout=120).json()["systems"]
    assert [s["address"] for s in systems] == listed, "exactly the listed systems, nothing else"
    for s in systems:
        assert s["found"] or s["detail"], s
        if s["found"]:
            assert s["reads"] + s["changes"] > 0 and s["title"]


def test_starter_ideas_come_from_the_real_operations(app):
    # sql_server_monitor (approved earlier from the real SQL Monitor) or any connected system: ideas by rule, no model
    tools = app.get(V1 + "/tools").json()["connected"]
    some = next(c for c in tools if c["reads"])
    ideas = app.get(f"{V1}/tools/{some['id']}/starters").json()["ideas"]
    assert {"chat", "schedule"} <= {i["kind"] for i in ideas}
    assert ("act" in {i["kind"] for i in ideas}) == bool(some["changes"]), "change ideas only for systems that can change"
    assert all(some["name"] in i["text"] for i in ideas)
    assert app.get(V1 + "/tools/no_such_system/starters").status_code == 404
