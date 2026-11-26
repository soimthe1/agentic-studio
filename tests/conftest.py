r"""Shared fixtures: the running stack (.\scripts\dev.ps1 start): engine on :7860, Agent Studio app on :8095,
and the engine's local admin from .env."""

import os
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = os.environ.get("STUDIO_ENGINE_URL", "http://127.0.0.1:7860")
APP = os.environ.get("STUDIO_APP_URL", "http://127.0.0.1:8095")
BASE = ENGINE  # engine-level tests


def _env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _login() -> str:
    env = _env()
    with httpx.Client(base_url=BASE, timeout=120, trust_env=False) as c:
        for _ in range(6):  # the engine allows 5 logins a minute
            r = c.post("/api/v1/login", data={"username": env["LANGFLOW_SUPERUSER"], "password": env["LANGFLOW_SUPERUSER_PASSWORD"]})
            if r.status_code != 429:
                break
            time.sleep(15)
    r.raise_for_status()
    return r.json()["access_token"]


class _Session(httpx.Auth):
    """The engine session lasts about an hour and the full suite runs longer: sign in again on 401, once."""

    def __init__(self):
        self.token = _login()

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        response = yield request
        if response.status_code == 401:
            self.token = _login()
            request.headers["Authorization"] = f"Bearer {self.token}"
            yield request


SESSION = None


def _session() -> _Session:
    global SESSION
    SESSION = SESSION or _Session()
    return SESSION


@pytest.fixture(scope="session")
def admin() -> httpx.Client:
    c = httpx.Client(base_url=BASE, timeout=120, trust_env=False, auth=_session())
    c.headers["Authorization"] = f"Bearer {_session().token}"   # tests that copy the header still work
    return c


@pytest.fixture(scope="session")
def app(admin) -> httpx.Client:
    """The Agent Studio app, called with the admin's engine session (the app forwards it to the engine). Long waits:
    planning and first test runs use the model servers (minutes on a slow or thinking model)."""
    return httpx.Client(base_url=APP, timeout=600, trust_env=False, auth=_session())


@pytest.fixture(scope="session")
def catalog(admin) -> dict:
    """{component key: template node} for everything the server can build."""
    return {k: v for cat, comps in admin.get("/api/v1/all").json().items()
            if cat != "component_display_names" for k, v in comps.items()}


def node(catalog: dict, key: str, node_id: str) -> dict:
    tpl = catalog[key]
    return {"id": node_id, "type": "genericNode", "position": {"x": 0, "y": 0},
            "data": {"id": node_id, "type": key, "node": tpl}}


def edge(src: str, src_out: str, src_types: list, dst: str, dst_field: str, dst_types: list) -> dict:
    sh = {"dataType": src.split("-")[0], "id": src, "name": src_out, "output_types": src_types}
    th = {"fieldName": dst_field, "id": dst, "inputTypes": dst_types, "type": "str"}
    return {"id": f"e-{src}-{dst}", "source": src, "target": dst, "data": {"sourceHandle": sh, "targetHandle": th},
            "sourceHandle": str(sh), "targetHandle": str(th)}


@pytest.fixture(scope="session")
def admin_key(admin) -> str:
    """A fresh API key for the admin (/api/v1/run requires x-api-key); revoked at the end."""
    r = admin.post("/api/v1/api_key/", json={"name": "pytest"})
    r.raise_for_status()
    body = r.json()
    yield body["api_key"]
    admin.delete(f"/api/v1/api_key/{body['id']}")


TEST_USER_PREFIXES = ("role-", "gate-test-", "policy-test-", "feedback-check", "agent_studio.smoketest")


@pytest.fixture(scope="session", autouse=True)
def _test_world():
    """The tests bring their own test systems and take everything they made away again, so people using Agent Studio
    never see test systems, test users or test agents. Test systems: tests/mocks/test_systems.yaml is placed in the
    contracts folder only while the tests run. Afterwards: engine users made by the tests and agents/drafts the
    tests' administrator made during the run are deleted."""
    import shutil
    import sys
    from datetime import datetime, timezone

    sys.path.insert(0, str(ROOT / "backend"))
    from agent_studio import capabilities, settings

    settings.load()
    systems = capabilities.contracts_dir() / "test_systems.yaml"
    systems.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "tests" / "mocks" / "test_systems.yaml", systems)
    started = datetime.now(timezone.utc)
    before: set[str] | None = None
    try:
        with httpx.Client(base_url=ENGINE, timeout=60, trust_env=False, auth=_session()) as c:
            before = {f["id"] for f in c.get("/api/v1/flows/", params={"get_all": True, "header_flows": True}).json()}
    except Exception:  # noqa: BLE001 - unit tests run without the stack
        pass
    try:
        yield
    finally:
        systems.unlink(missing_ok=True)
        if before is not None:
            _tidy(before, started)


def _tidy(before: set[str], started) -> None:
    from agent_studio.store import connect

    with httpx.Client(base_url=ENGINE, timeout=120, trust_env=False, auth=_session()) as c:
        me = c.get("/api/v1/users/whoami").json()["id"]
        for f in c.get("/api/v1/flows/", params={"get_all": True, "header_flows": True}).json():
            if f["id"] not in before:
                c.delete(f"/api/v1/flows/{f['id']}")
        skip = 0
        while True:
            page = c.get("/api/v1/users/", params={"limit": 200, "skip": skip}).json().get("users", [])
            for u in page:
                if u["username"].startswith(TEST_USER_PREFIXES):
                    c.delete(f"/api/v1/users/{u['id']}")   # the engine finishes deleting in the background
            if len(page) < 200:
                break
            skip += 200
    with connect() as db:
        db.execute("DELETE FROM designs WHERE owner = %s AND created_at >= %s", (me, started))
        db.execute("DELETE FROM people WHERE username LIKE ANY (%s)", ([p + "%" for p in TEST_USER_PREFIXES],))
