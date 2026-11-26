"""Watchkeepers (no model, no engine): intake keeps exact details, duplicates are caught by facts, the build check
holds the director to what was promised, readiness turns engine status into plain blockers, runtime judges health."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from agent_studio import director  # noqa: E402
from agent_studio.watch import buildcheck, duplicate, intake, readiness, runtime  # noqa: E402


def test_intake_keeps_names_times_formats():
    f = intake.facts("Please check WEB02 and SQLPROD01 at 07:30 and give me an Excel file and a 7z", [])
    assert f["targets"] == ["SQLPROD01", "WEB02"] and f["times"] == ["07:30"] and f["formats"] == ["7z", "excel"]
    plan, prefs, found = intake.check({"instructions": "check iis"}, {"capabilities": ["iis_health"]}, f)
    assert {"save_data", "bundle_files"} <= set(prefs["capabilities"]) and "SQLPROD01" in plan["instructions"] and found


def test_intake_ignores_common_words():
    assert intake.facts("Check SQL and IIS health via the API", [])["targets"] == []


def test_duplicate_by_facts_not_wording():
    p = {"capabilities": ["sql_health"], "trigger": "chat", "acts": "read_only", "notify": "never"}
    r = duplicate.compare(duplicate.fingerprint(p), [{"design_id": "d", "agent_id": "a", "name": "SQL", "prefs": p}])
    assert r[0]["kind"] == "duplicate"
    other = dict(p, capabilities=["iis_health"])
    assert duplicate.compare(duplicate.fingerprint(p), [{"design_id": "d", "agent_id": "a", "name": "IIS", "prefs": other}]) == []


def _approval_build():
    plan = {"instructions": "check WEB02 and restart if needed", "goals": ["x"], "language": "en"}
    prefs = {"name": "Restarter", "trigger": "chat", "cron": None, "capabilities": ["iis_health", "server_action"],
             "acts": "with_approval", "notify": "never", "channel": None, "detail": "short", "brain": "fast", "sub_agents": []}
    return director.build(plan, prefs, {}), prefs


def test_build_check_passes_real_director_output():
    built, prefs = _approval_build()
    found = buildcheck.check(built["definition"], prefs, built["left_out"])
    assert not [f for f in found if f["level"] == "block"], found


def test_build_check_catches_write_tool_outside_approval():
    built, prefs = _approval_build()
    d = built["definition"]
    d["connections"].append({"from": "tool-server_action", "output": "tool", "to": "agent", "input": "tools"})
    assert any(f["level"] == "block" and "approval" in f["text"] for f in buildcheck.check(d, prefs, built["left_out"]))


def test_build_check_catches_unapproved_component():
    built, prefs = _approval_build()
    built["definition"]["steps"].append({"id": "x", "component": "PythonREPLComponent", "params": {}})
    assert any("Not approved" in f["text"] for f in buildcheck.check(built["definition"], prefs, built["left_out"]))


def test_readiness_blocks_missing_secret_and_offline_web(monkeypatch):
    from agent_studio import vault
    monkeypatch.setattr(vault, "has", lambda name: False)   # no sign-in saved on the Tools page either
    status = {"web_enabled": False, "connections": [
        {"kind": "model", "name": "Ollama", "ok": True, "ms": 50},
        {"kind": "apps", "name": "iis", "ok": True, "missing_secrets": ["STUDIO_TOOL_IIS_PASSWORD"]}]}
    out = readiness.check({"capabilities": ["iis_health", "web_read"], "brain": "fast"}, status)
    blocks = [f["text"] for f in out if f["level"] == "block"]
    assert any("STUDIO_TOOL_IIS_PASSWORD" in b for b in blocks) and any("internet" in b for b in blocks)


def test_runtime_health():
    now = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)
    assert runtime.health([{"last_at": "2026-11-17T03:01:00+00:00", "error": False}],
                          {"trigger": "schedule", "cron": "0 7 * * *"}, now)["status"] == "working_well"
    assert runtime.health([{"last_at": "2026-11-15T03:01:00+00:00", "error": False}],
                          {"trigger": "schedule", "cron": "0 7 * * *"}, now)["status"] == "needs_attention"


def test_failure_watch_message_is_plain_and_points_to_runs():
    from agent_studio.watch.failures import QUIET, message
    text = message("SQL watch", "2026-11-18T07:00:12+00:00", "The AI model server could not be reached")
    assert "SQL watch" in text and "2026-11-18 07:00" in text and "Runs" in text and "{" not in text
    assert QUIET.total_seconds() == 24 * 3600, "at most one alert per agent per day"


def test_model_fallback_answers_when_main_server_is_down(monkeypatch):
    from agent_studio import ai_providers
    ai_providers.configure({"default": {"provider": "openai", "base_url": "http://a/v1", "model": "a1", "fallback": "backup"},
                            "backup": {"provider": "ollama", "base_url": "http://b:11434", "model": "q3"}})
    calls = []

    def fake(messages, profile, **kw):
        calls.append(profile)
        if profile == "default":
            raise ai_providers.AIError("http://a/v1/chat/completions -> <urlopen error [WinError 10061] refused>")
        return "ok from " + profile
    monkeypatch.setattr(ai_providers, "_chat", fake)
    assert ai_providers.chat([{"role": "user", "content": "hi"}]) == "ok from backup" and calls == ["default", "backup"]

    def rejected(messages, profile, **kw):
        raise ai_providers.AIError("http://a/v1/chat/completions -> HTTP 400: bad request")
    monkeypatch.setattr(ai_providers, "_chat", rejected)
    try:
        ai_providers.chat([{"role": "user", "content": "hi"}])
        raise AssertionError("a rejected request must not move to the backup")
    except ai_providers.AIError as exc:
        assert "HTTP 400" in str(exc)


def test_model_failover_needs_two_looks_each_way():
    from agent_studio import ai_providers
    from agent_studio.watch import models
    ai_providers.configure({"default": {"provider": "openai", "base_url": "http://a/v1", "model": "a1", "fallback": "backup"},
                            "backup": {"provider": "ollama", "base_url": "http://b:11434", "model": "q3"}})
    models._streak.clear()
    assert models.target("default", models.note_look("default", False), True) is None      # one dropped look: stay
    assert models.target("default", models.note_look("default", False), True) == "backup"
    assert models.target("default", models.note_look("default", False), False) is None     # backup down too: stay
    assert models.target("default", models.note_look("default", True), True) is None
    assert models.target("default", models.note_look("default", True), True) == "default"


def test_agents_check_their_own_work_and_retries_carry_what_went_wrong():
    from agent_studio.watch import failures, goals
    loop = director.work_loop({"goals": ["List failed SQL jobs", "Count them"]})
    assert "before you answer, check every goal" in loop and "- Count them" in loop
    assert "found this missing: totals" in goals.with_feedback("Check SQL", ["totals"])
    assert goals.with_feedback("Check SQL", []) == "Check SQL"
    assert "previous attempt at this failed: login refused" in failures.retry_message("Check SQL", "login refused")
    bad = [{"session_id": "s", "error": True}] * 3
    assert failures.should_park(bad, "login refused", "login refused")
    from agent_studio.engine import MODEL_DOWN
    assert not failures.should_park(bad, MODEL_DOWN, ""), "a model outage never pauses agents"


def test_missed_goal_becomes_a_suggestion_for_the_owner():
    from agent_studio.watch import goals
    assert goals.suggestion(["The total of failed jobs.", "", "Which server"]) == \
        "Always make sure your answer covers: The total of failed jobs; Which server."
    assert goals.suggestion([]) == ""
