"""Features of 2026-11-24: answer formats, effort per run, handoff, notes between runs, AI use per agent (no model
needed), plus the live API: sharing, test questions, notes, usage and automatic tool drafts."""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from agent_studio import director, learn  # noqa: E402

V1 = "/api/studio/v1"
PLAN = {"instructions": "check WEB02", "goals": ["Report WEB02 health"], "language": "en", "understood": "Check WEB02"}


def _prefs(**kw):
    return {"name": "T", "trigger": "chat", "cron": None, "capabilities": ["iis_health"], "acts": "read_only", "notify": "never",
            "channel": None, "detail": "short", "brain": "fast", "sub_agents": [], **kw}


def _prompt(built):
    return next(s["params"]["system_prompt"] for s in built["definition"]["steps"] if s["id"] == "agent")


def test_answer_formats_and_effort_reach_the_agent():
    built = director.build(PLAN, _prefs(detail="data", effort="deep"))
    agent = next(s for s in built["definition"]["steps"] if s["id"] == "agent")
    assert '"items"' in agent["params"]["system_prompt"] and "at most 8 times" in agent["params"]["system_prompt"]
    assert agent["params"]["max_iterations"] == 10
    assert "one table" in _prompt(director.build(PLAN, _prefs(detail="table")))
    assert "at most 4 times" in _prompt(director.build(PLAN, _prefs()))          # default: normal


def test_handoff_rule_comes_with_helper_agents():
    text = director.instructions(PLAN, _prefs(sub_agents=["x"]), ["the 'SQL' agent"])
    assert "Handoff:" in text and "which agent answered" in text


def test_notes_block_is_replaced_not_stacked():
    p = learn.with_notes(learn.with_notes("Base.", ["a"]), ["a", "b"])
    assert p.count(learn.NOTES_HEAD) == 1 and p.endswith("- a\n- b") and p.startswith("Base.")


def test_usage_adds_up_per_agent():
    from agent_studio.api import usage_by_agent
    runs = [{"agent_id": "a", "agent_name": "A", "last_at": "2026-11-24T08:00:00+00:00", "error": False, "tokens_in": 100, "tokens_out": 20},
            {"agent_id": "a", "agent_name": "A", "last_at": "2026-11-24T09:00:00+00:00", "error": True, "tokens_in": 50, "tokens_out": 0},
            {"agent_id": "b", "agent_name": "B", "last_at": "2026-11-01T09:00:00+00:00", "error": False, "tokens_in": 999, "tokens_out": 1}]
    rows = usage_by_agent(runs, "2026-11-17T00:00:00+00:00")
    assert rows == [{"agent_id": "a", "agent_name": "A", "runs": 2, "failed": 1, "tokens_in": 150, "tokens_out": 20}]


# ---------------------------------------------------------------- live API (running stack)
def test_tests_notes_usage_and_sharing_api(app):
    a = app.post(V1 + "/agents", json={"name": f"feature-check-{uuid.uuid4().hex[:6]}", "description": "test"}).json()
    try:
        r = app.post(f"{V1}/agents/{a['id']}/tests", json={"question": "How is WEB02?", "expect": "WEB02 status"})
        assert r.status_code == 201
        cases = app.get(f"{V1}/agents/{a['id']}/tests").json()
        assert [c["question"] for c in cases] == ["How is WEB02?"] and cases[0]["last"] is None
        assert app.delete(f"{V1}/agents/{a['id']}/tests/{cases[0]['id']}").status_code == 204
        assert app.get(f"{V1}/agents/{a['id']}/notes").json() == []
        assert app.post(f"{V1}/agents/{a['id']}/share", json={"on": True}).status_code == 409   # not live: cannot share
        assert app.get(f"{V1}/shared/{a['id']}").status_code == 404
        u = app.get(f"{V1}/usage").json()
        assert {"days", "agents", "tokens", "runs"} <= set(u)
    finally:
        app.delete(f"{V1}/agents/{a['id']}")


def test_auto_tool_answers_plainly(app):
    r = app.post(f"{V1}/tools/auto", json={"need": "list the open incidents of the IIS servers"})
    assert r.status_code == 200 and r.json()["outcome"] in ("drafted", "reuse", "none") and r.json()["text"]


def test_same_operation_is_recognised_under_any_host_name():
    from agent_studio.tools import endpoint
    assert endpoint("http://host.docker.internal:9190/iis/", "api/v1/incidents") == \
        endpoint("http://127.0.0.1:9190/", "/iis/api/v1/incidents") == endpoint("http://localhost:9190", "/iis/api/v1/incidents/")
    assert endpoint("http://a:9190/", "/x") != endpoint("http://b:9190/", "/x")


def test_first_test_keeps_the_persons_exact_request():
    plan, prefs = {"goals": ["Answer about leave"]}, {"trigger": "chat"}
    assert director.first_test(plan, prefs, "Read my file policy-sample.pdf and summarise it") == "Read my file policy-sample.pdf and summarise it"
    assert director.first_test(plan, prefs, "Create an agent that reads policy files").startswith("Please do this now:")
    sampled = {**plan, "sample_questions": ["What does leave.pdf say about carry-over?"]}
    assert director.first_test(sampled, prefs, "I want to ask questions about policy documents in my files") ==         "What does leave.pdf say about carry-over?"
    assert director.first_test(plan, {"trigger": "schedule"}, "Every day read x").startswith("Test run requested")


def test_whenever_i_need_is_chat_not_watch():
    from agent_studio import designs
    assert not designs.WATCH_WORDS.search("I want to ask about SQL health whenever I need.")
    assert designs.WATCH_WORDS.search("Tell me whenever a new incident appears")
