"""Designer rules enforced in code (no model needed): whatever the model proposes, the plan keeps exactly what the
person asked for - nothing narrowed, nothing extra, nothing that changes systems without approval."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from agent_studio.designer import validate  # noqa: E402


def plan(**kw):
    base = {"understood": "x", "name": "n", "goals": ["g"], "capabilities": ["sql_health"], "trigger": "chat",
            "acts": "read_only", "notify": "never", "detail": "short", "instructions": "i", "questions": [],
            "evidence": {"goal": None}}
    base.update(kw)
    return base


def test_schedule_is_not_narrowed_to_weekdays():
    said = "Every morning at 7, check the IIS servers."
    out = validate(plan(trigger="schedule", cron="0 7 * * 1-5", schedule_text="every weekday at 7",
                        evidence={"goal": "check the IIS servers", "schedule": "Every morning at 7"}), [], said)
    assert out["cron"] == "0 7 * * *" and out["schedule_text"] == "Every morning at 7"


def test_weekdays_kept_when_asked():
    said = "Every weekday at 7 check SQL health"
    out = validate(plan(trigger="schedule", cron="0 7 * * 1-5",
                        evidence={"goal": "check SQL health", "schedule": "Every weekday at 7"}), [], said)
    assert out["cron"] == "0 7 * * 1-5"


def test_vague_request_only_asks():
    out = validate(plan(capabilities=["sql_health", "iis_health"], goals=["Check everything"]), [], "Make me an agent.")
    assert out["capabilities"] == [] and out["goals"] == [] and out["questions"]


def test_unasked_notify_and_schedule_become_suggestions():
    said = "Tell me how our SQL Servers are doing when I ask"
    out = validate(plan(capabilities=["sql_health", "notify"], notify="problems", trigger="schedule", cron="0 7 * * *",
                        evidence={"goal": said}), [], said)
    assert out["notify"] == "never" and "notify" not in out["capabilities"] and out["trigger"] == "chat"
    assert out["suggestions"]


def test_approval_only_when_something_changes_systems():
    said = "every day save the SQL findings into a sqlite file"
    out = validate(plan(capabilities=["sql_health", "save_data"], acts="with_approval",
                        evidence={"goal": said, "acts": "save the SQL findings"}), [], said)
    assert out["acts"] == "read_only"


def test_write_capability_forces_approval():
    said = "restart the IIS service on WEB02 when it is unhealthy"
    out = validate(plan(capabilities=["iis_health", "server_action"], acts="read_only",
                        evidence={"goal": said, "acts": "restart the IIS service"}), [], said)
    assert out["acts"] == "with_approval" and "server_action" in out["capabilities"]


def test_unknown_capabilities_are_dropped():
    said = "check SQL health and give me shell access"
    out = validate(plan(capabilities=["sql_health", "shell", "admin_rights"], evidence={"goal": said}), [], said)
    assert out["capabilities"] == ["sql_health"]


def test_goal_check_does_not_call_returned_facts_invented():
    # the judge sees only part of a big tool result; a complaint about a fact the tools did return is dropped,
    # a named thing the tools never mentioned and a wrong total are kept
    from agent_studio.designer import _found_in
    seen = '{"finding": "database tarrabutinternet is offline", "x": "high write latency on tempdb_mssql_3"}'
    assert _found_in("Database TarrabutInternet is offline (not in tool results)", seen)
    assert _found_in("High write latency on tempdb (not confirmed by tool_results)", seen)
    assert not _found_in("Database PayrollDB is offline (not in tool results)", seen)
    assert not _found_in("24 critical findings (should be 23)", seen)


def test_one_system_message_first_for_strict_model_servers():
    # vLLM/Qwen reject a system message after other messages; every model call sends one system message, first
    from agent_studio.ai_providers import one_system_first
    out = one_system_first([{"role": "system", "content": "A"}, {"role": "user", "content": "u"},
                            {"role": "system", "content": "B"}, {"role": "assistant", "content": "a"}])
    assert [m["role"] for m in out] == ["system", "user", "assistant"] and out[0]["content"] == "A\n\nB"


def test_totals_must_match_their_own_breakdown():
    # arithmetic is checked by code, not left to the model that judges
    from agent_studio.designer import bad_totals
    assert bad_totals("INTDB1 has 32 critical findings (21 immediate, 11 from query analysis).") == []
    wrong = bad_totals("INTDB1 has 40 critical findings (21 immediate, 11 from query analysis).")
    assert len(wrong) == 1 and "40" in wrong[0] and "32" in wrong[0]
    assert bad_totals("Checked 3 servers (all fine) at 7am (Dubai time).") == []      # no breakdown, nothing to add up
    assert bad_totals("Backups missing on 10 databases (oldest 1405 days).") == []     # one number is not a breakdown
