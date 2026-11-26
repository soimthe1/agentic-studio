"""The whole Create journey clicked through in a real browser, the way a person does it, then a scheduled agent
proven to run BY ITSELF. Needs the full dev stack (dev.ps1 start: engine, app, Vite UI) and a working model server.

Covers: describe -> plan panels; every option in every option group saves (aria-checked round-trip); Agent Studio's
questions answered by clicking; an ability toggled off and on; rename; review -> create -> first test run -> publish;
the published schedule fires on its own (a new run appears that nobody started); clean-up (retire + delete).
Slow (~10 minutes) and model-dependent: STUDIO_CLICKTHROUGH=1 pytest tests/test_create_clickthrough.py -s
"""

import os
import re
import time

import pytest
from conftest import _env

playwright = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.skipif(os.environ.get("STUDIO_CLICKTHROUGH") != "1",
                                reason="slow full journey: set STUDIO_CLICKTHROUGH=1 to run it")

UI = os.environ.get("STUDIO_UI_URL", "http://127.0.0.1:5195")
ENGINE = os.environ.get("STUDIO_ENGINE_URL", "http://127.0.0.1:7860")
V1 = "/api/studio/v1"
ASK = ("Every day at 7am read the findings summary from the SQL Server Monitor and tell me in the ops chat how many "
       "critical findings there are, only if there are any.")
MODEL_WAIT = 420_000          # ms: planning and the first test run use the model server


def _radios(page):
    return page.locator('[role="radiogroup"]')


def test_create_journey_every_option_then_schedule_runs_by_itself(app):
    env = _env()
    runs_before = {r["session_id"] for r in app.get(V1 + "/executions").json()}
    made: dict = {}
    try:
        _journey(app, env, runs_before, made)
    finally:                                   # nothing the test made is left in anyone's lists
        if made.get("agent"):
            app.post(f"{V1}/agents/{made['agent']}/retire")
            app.delete(f"{V1}/agents/{made['agent']}")
        if made.get("design"):
            app.delete(f"{V1}/designs/{made['design']}")


def _journey(app, env, runs_before, made):
    design_id = agent_id = None
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-proxy-server"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        assert ctx.request.post(ENGINE + "/api/v1/login", form={"username": env["LANGFLOW_SUPERUSER"],
                                                                "password": env["LANGFLOW_SUPERUSER_PASSWORD"]}).ok
        page = ctx.new_page()
        try:
            # 1. Describe
            page.goto(UI + "/create")
            page.locator("textarea").first.fill(ASK)
            page.get_by_role("button", name="Send").click()
            page.wait_for_url(re.compile(r"/create/[0-9a-f-]{36}"), timeout=MODEL_WAIT)
            design_id = made["design"] = page.url.rsplit("/", 1)[-1]
            ready = page.locator('[role="radiogroup"], .rp-questions, .notice.err')
            for attempt in range(3):          # a model hiccup: say it again, as a person would
                ready.first.wait_for(timeout=MODEL_WAIT)
                if not page.locator(".notice.err").count():
                    break
                print("  model hiccup, saying it again")
                page.locator("textarea").first.fill(ASK)
                page.get_by_role("button", name="Send").click()
                page.wait_for_timeout(5000)

            # 2. Agent Studio's questions, answered by clicking the first choice of each
            if page.locator(".rp-questions").count():
                groups = page.locator(".rp-questions [aria-pressed]")
                seen = set()
                for i in range(groups.count()):
                    b = groups.nth(i)
                    q = b.evaluate("e => e.parentElement.textContent")[:40]
                    if q not in seen:
                        seen.add(q)
                        b.click()
                page.get_by_role("button", name="Answer").click()
                page.wait_for_timeout(2000)
                print("  questions answered")
            _radios(page).first.wait_for(timeout=MODEL_WAIT)

            # 3. Every option in every option group saves (the card shows the server's answer)
            checked = 0
            for g in range(_radios(page).count()):
                group = _radios(page).nth(g)
                label = group.get_attribute("aria-label")
                for i in range(group.locator('[role="radio"]').count()):
                    radio = _radios(page).nth(g).locator('[role="radio"]').nth(i)
                    if radio.is_disabled():
                        continue
                    radio.click()
                    playwright.expect(_radios(page).nth(g).locator('[role="radio"]').nth(i)).to_have_attribute(
                        "aria-checked", "true", timeout=60_000)
                    checked += 1
                print(f"  option group '{label}': all options saved")
            assert checked >= 4, "the plan shows option groups to choose from"

            # 4. An ability off and on again; a new name
            box = page.locator(".prefs-panel input[type=checkbox]:not([disabled])").first
            if box.count():
                was = box.is_checked()
                box.click(); page.wait_for_timeout(1500)
                playwright.expect(page.locator(".prefs-panel input[type=checkbox]:not([disabled])").first).to_be_checked(checked=not was, timeout=60_000)
                page.locator(".prefs-panel input[type=checkbox]:not([disabled])").first.click(); page.wait_for_timeout(1500)
            name = page.locator("#agent-name")
            if name.count():
                name.fill("Clickthrough SQL watch"); name.blur(); page.wait_for_timeout(1500)

            # 5. The schedule this test can watch fire: every 2 minutes (set through the same API the card uses)
            d = app.patch(f"{V1}/designs/{design_id}/prefs", json={"prefs": {
                "trigger": "schedule", "cron": "*/2 * * * *", "schedule_text": "every 2 minutes (test)",
                "brain": os.environ.get("STUDIO_CLICKTHROUGH_BRAIN", "fast"), "skills": []}}).json()   # abilities: the plan's own
            assert d["prefs"]["trigger"] == "schedule" and d["prefs"]["cron"] == "*/2 * * * *"
            page.reload()
            _radios(page).first.wait_for(timeout=60_000)

            # 6. Review -> Create -> first test run
            page.locator("button.nc-create").first.click()
            page.locator("dialog.review").get_by_role("button", name=re.compile("Create agent|Update")).click()
            publish = page.locator("button.nc-create", has_text="Publish")
            deadline = time.time() + MODEL_WAIT * 2 / 1000
            design = {}
            while time.time() < deadline:      # the first test run's verdict, as the page will show it
                design = app.get(f"{V1}/designs/{design_id}").json()
                if design.get("proof") or page.locator(".notice.err").count():
                    break
                time.sleep(10)
            err = page.locator(".notice.err")
            assert not err.count(), "Create or the first test run reported: " + err.first.inner_text()
            agent_id = made["agent"] = design["agent_id"]
            proof = design.get("proof") or {}
            print("  first test run:", proof.get("verdict"), "| missing:", proof.get("missing"), "| reply:", (proof.get("reply") or "")[:300])
            assert proof.get("verdict") == "met", proof
            publish.wait_for(timeout=60_000)

            # 7. Publish: the schedule is armed
            publish.click()
            page.get_by_text(re.compile("Live")).first.wait_for(timeout=60_000)
            assert app.get(f"{V1}/agents/{agent_id}").json()  # still there
        finally:
            browser.close()

    # 8. It runs by itself: a run nobody started appears within ~5 minutes
    proof_session = (app.get(f"{V1}/designs/{design_id}").json().get("proof") or {}).get("session_id")
    deadline = time.time() + 330
    own = []
    while time.time() < deadline and not own:
        time.sleep(30)
        own = [r for r in app.get(V1 + "/executions").json()
               if r["agent_id"] == agent_id and r["session_id"] not in runs_before and r["session_id"] != proof_session]
    assert own, "the published schedule did not start a run by itself within 5.5 minutes"
    print("  ran by itself:", own[0]["started_at"], "error" if own[0]["error"] else "ok")
