"""Agent Studio must look home-grown: no visible "Langflow" anywhere a user can reach, and the browser
never contacts another origin (air gap). Renders the real pages with a signed-in admin session."""

import re

import pytest
from conftest import APP, ENGINE, _env

playwright = pytest.importorskip("playwright.sync_api")

STUDIO_PAGES = ["/", "/agents", "/builder", "/executions", "/settings"]
WORD = re.compile(r"langflow", re.I)

from agent_studio.brand import brand as _brand, title as _title  # noqa: E402  (the expected name comes from brand.json)

BRAND, BRAND_TITLE = _brand()["name"], _title()


@pytest.fixture(scope="module")
def page():
    env = _env()
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-proxy-server"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        r = ctx.request.post(ENGINE + "/api/v1/login", form={"username": env["LANGFLOW_SUPERUSER"], "password": env["LANGFLOW_SUPERUSER_PASSWORD"]})
        assert r.ok
        page = ctx.new_page()
        page.external = []
        page.on("request", lambda q: page.external.append(q.url) if not q.url.startswith((APP, ENGINE)) and not q.url.startswith(("data:", "blob:")) else None)
        yield page
        browser.close()


def visible_text(page) -> str:
    return page.evaluate("document.body.innerText + ' ' + document.title")


@pytest.mark.parametrize("path", STUDIO_PAGES)
def test_studio_pages(page, path):
    page.goto(APP + path)
    page.wait_for_load_state("networkidle")
    assert not WORD.search(visible_text(page)), path
    assert page.title() in (BRAND_TITLE, BRAND), page.title()   # English - Arabic (older engine images: English only)


def test_builder_canvas_is_branded(page):
    r = page.request.post(APP + "/api/studio/v1/agents", data={"name": "branding-check"})
    agent = r.json()
    try:
        page.goto(ENGINE + f"/flow/{agent['id']}")  # the console admin's view; the test user is the superuser
        page.wait_for_load_state("load")  # not networkidle: the canvas keeps live requests open (model lists, events)
        page.wait_for_timeout(3000)
        text = visible_text(page)
        assert not WORD.search(text), [m.start() for m in WORD.finditer(text)][:5]
        assert BRAND in page.title()
    finally:
        page.request.delete(APP + f"/api/studio/v1/agents/{agent['id']}", timeout=120_000)


def test_no_external_requests(page):
    assert page.external == []


def test_sign_in_page_branded(page):
    page.goto(APP + "/auth/login")
    assert not WORD.search(visible_text(page))
    assert BRAND in visible_text(page)
