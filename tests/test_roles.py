"""Roles (user < builder < admin) are enforced by the Agent Studio API, not just hidden in the UI."""

import sys
import uuid

import httpx
import pytest
from conftest import APP, ENGINE, ROOT, _env

sys.path.insert(0, str(ROOT / "backend"))
V1 = "/api/studio/v1"


def person(role: str | None) -> httpx.Client:
    from agent_studio import store

    name = f"role-{role or 'none'}-{uuid.uuid4().hex[:5]}"
    r = httpx.post(ENGINE + "/studio-engine/session", trust_env=False, timeout=30,
                   headers={"X-Studio-Engine-Secret": _env()["STUDIO_ENGINE_SECRET"]}, json={"sub": f"test:{name}", "username": name})
    r.raise_for_status()
    if role:
        store.set_person(name, role)
    return httpx.Client(base_url=APP, trust_env=False, timeout=60, cookies={c["name"]: c["value"] for c in r.json()["cookies"]})


@pytest.fixture(scope="module")
def user():
    return person("user")


@pytest.fixture(scope="module")
def builder():
    return person("builder")


def test_role_is_reported(user, builder):
    assert user.get(V1 + "/me").json()["role"] == "user"
    assert builder.get(V1 + "/me").json()["role"] == "builder"


def test_unknown_person_gets_the_configured_everybody_role():
    # not signed in since roles were recorded: ldap.group_map decides (dev config: builder = everybody)
    assert person(None).get(V1 + "/me").json()["role"] in ("user", "builder")


def test_user_cannot_build_or_change(user):
    for method, path, body in [("POST", "/designs", {"text": "check SQL"}), ("POST", "/agents", {"name": "x"}),
                               ("POST", "/tools/learn", {"address": "http://127.0.0.1:9190"}),
                               ("POST", f"/agents/{uuid.uuid4()}/publish", {})]:
        r = user.request(method, V1 + path, json=body)
        assert r.status_code == 403 and "role (user)" in r.text, (path, r.status_code, r.text[:200])


def test_user_can_use(user):
    assert user.get(V1 + "/agents").status_code == 200
    assert user.get(V1 + "/approvals").status_code == 200
    assert user.get(V1 + "/files").status_code == 200


def test_builder_builds_but_does_not_approve_tools(builder):
    a = builder.post(V1 + "/agents", json={"name": "role-check"})
    assert a.status_code == 201
    builder.delete(f"{V1}/agents/{a.json()['id']}")
    r = builder.post(f"{V1}/tools/requests/{uuid.uuid4()}/approve")
    assert r.status_code == 403
