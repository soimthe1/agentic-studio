"""The raw engine console is for named technical admins only; everyone else lives in Agent Studio.

A normal user (an AD person Agent Studio opened an engine session for) is redirected from every engine page to the
Agent Studio app, gets no console link, and can still use the engine API through Agent Studio. The break-glass superuser
(local engine login) still reaches the console.
"""

import uuid

import httpx
import pytest
from conftest import APP, ENGINE, _env


@pytest.fixture(scope="module")
def person() -> httpx.Client:
    """A normal user, signed in the way Agent Studio signs people in (engine session endpoint + shared secret)."""
    name = f"gate-test-{uuid.uuid4().hex[:6]}"
    r = httpx.post(ENGINE + "/studio-engine/session", trust_env=False, timeout=30,
                   headers={"X-Studio-Engine-Secret": _env()["STUDIO_ENGINE_SECRET"]},
                   json={"sub": f"test:{name}", "username": name})
    assert r.status_code == 200, r.text
    jar = {c["name"]: c["value"] for c in r.json()["cookies"]}
    return httpx.Client(trust_env=False, timeout=30, cookies=jar, follow_redirects=False)


@pytest.mark.parametrize("path", ["/flows", "/flow/x", "/all", "/settings", "/settings/global-variables", "/admin", "/playground/x"])
def test_engine_pages_send_normal_users_to_the_app(person, path):
    r = person.get(ENGINE + path, headers={"Accept": "text/html"})
    assert r.status_code == 302, (path, r.status_code)
    assert "7860" not in r.headers["location"]


def test_signed_out_browser_is_sent_to_the_app():
    r = httpx.get(ENGINE + "/flows", trust_env=False, follow_redirects=False)
    assert r.status_code == 302


def test_engine_api_still_works_for_normal_users(person):
    assert person.get(ENGINE + "/api/v1/users/whoami").status_code == 200


def test_no_console_link_for_normal_users(person):
    me = httpx.get(APP + "/api/studio/v1/me", cookies=person.cookies, trust_env=False).json()
    assert me["engine_console_url"] is None


def test_break_glass_superuser_reaches_console(admin, app):
    token = admin.headers["Authorization"].removeprefix("Bearer ")
    r = httpx.get(ENGINE + "/flows", cookies={"access_token_lf": token}, trust_env=False, follow_redirects=False)
    assert r.status_code == 200
    assert app.get("/api/studio/v1/me").json()["engine_console_url"]
