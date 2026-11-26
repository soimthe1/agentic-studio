"""Engine policy (config/policy/catalog.yaml, applied by `dev.ps1 seed`): what is not approved cannot be used
through ANY path - not hidden-but-callable. Checked as a normal user straight against the engine API."""

import subprocess
import sys
import uuid

import httpx
import pytest
import yaml
from conftest import ENGINE, ROOT, _env

ALLOWED = {k for g in yaml.safe_load((ROOT / "config/policy/catalog.yaml").read_text(encoding="utf-8"))["groups"]
           for k in g["components"]}
RISKY_WORDS = ("Python", "Code", "Shell", "Interpreter", "Exec", "Bash", "SQL", "API Request", "APIRequest", "Directory", "File")


@pytest.fixture(scope="module")
def person() -> httpx.Client:
    name = f"policy-test-{uuid.uuid4().hex[:6]}"
    r = httpx.post(ENGINE + "/studio-engine/session", trust_env=False, timeout=30,
                   headers={"X-Studio-Engine-Secret": _env()["STUDIO_ENGINE_SECRET"]},
                   json={"sub": f"test:{name}", "username": name})
    r.raise_for_status()
    return httpx.Client(base_url=ENGINE, trust_env=False, timeout=60,
                        cookies={c["name"]: c["value"] for c in r.json()["cookies"]})


def test_live_policy_matches_the_file():
    r = subprocess.run([sys.executable, "-m", "agent_studio.seed", "--check"], cwd=ROOT / "backend",
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_policy_blocks_everything_not_approved(admin):
    pb = admin.get("/api/v1/policy-bundle").json()
    blocked = set(pb.get("blocked_component_keys") or pb.get("policy", {}).get("blocked_component_keys") or [])
    assert blocked and not (blocked & ALLOWED)
    risky = [k for k in blocked if any(w.lower() in k.lower() for w in RISKY_WORDS)]
    assert risky, "expected code/shell/file/raw-request components among the blocked ones"


@pytest.mark.parametrize("key", ["PythonREPLComponent", "PythonFunction", "APIRequest", "Directory", "SaveToFile"])
def test_blocked_component_cannot_be_saved(person, key):
    # Blocked components are not even listed, so the flow is written by hand - like an attacker would.
    node = {"id": "x", "type": "genericNode", "position": {"x": 0, "y": 0},
            "data": {"id": "x", "type": key, "node": {"template": {}, "outputs": []}}}
    r = person.post("/api/v1/flows/", json={"name": f"blocked-{key}", "data": {"nodes": [node], "edges": []}})
    assert r.status_code == 400 and "blocks components" in r.text, r.text[:300]


def test_normal_user_cannot_change_policy(person):
    r = person.put("/api/v1/policy-bundle", json={"blocked_component_keys": [], "approved_provider_ids": [],
                                                   "blocked_template_keys": []})
    assert r.status_code in (401, 403, 405, 422)
