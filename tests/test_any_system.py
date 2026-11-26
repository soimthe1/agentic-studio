"""Generic behaviour for every connected system (no model, no external system): big answers keep every item, a named
system is the only one read, and "I need a report" is delivered as a document."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "studio_tools"))


def test_big_answers_keep_every_item():
    from studio_tools.core.apps import MAX_JSON_CHARS, bounded

    items = [{"id": f"x{i:04d}-" + "a" * 20, "name": f"server-{i}", "used_percent": 50 + i % 50, "threshold": 90,
              "series": [{"t": f"2026-11-{d:02d}", "v": i + d} for d in range(1, 30)],
              "explanation": {"text": "long words " * 40}} for i in range(60)]
    out = bounded({"items": items})
    text = json.dumps(out)
    assert len(text) <= MAX_JSON_CHARS and "truncated" not in out
    assert all(f"server-{i}" in text for i in range(60))      # every item is still there


def test_identical_items_are_merged_with_a_count():
    from studio_tools.core.apps import _compact

    out = _compact([{"a": 1}, {"a": 1}, {"a": 2}], 2)
    assert {"a": 1, "_same_items": 2} in out and {"a": 2} in out


def test_named_system_only(monkeypatch):
    from agent_studio import capabilities, designs

    cat = {"apps": [{"id": "ops_portal", "name": "Ops Portal"}, {"id": "sales_crm", "name": "Sales CRM"}],
           "capabilities": [{"id": "ops_portal_read", "requires": "apps.ops_portal"},
                            {"id": "sales_crm_read", "requires": "apps.sales_crm"}, {"id": "date"}]}
    monkeypatch.setattr(capabilities, "catalog", lambda: cat)
    caps = ["ops_portal_read", "sales_crm_read", "date"]
    assert designs.named_systems_only(caps, "from ops portal bring low servers") == ["ops_portal_read", "date"]
    assert designs.named_systems_only(caps, "in the sales-crm list open deals") == ["sales_crm_read", "date"]
    assert designs.named_systems_only(caps, "check everything") == caps        # nothing named: nothing removed


def test_a_report_is_delivered(monkeypatch):
    from agent_studio import capabilities, designs

    monkeypatch.setattr(capabilities, "by_id", lambda: {"document": {"id": "document"}})
    plan = designs.report_is_delivered({"capabilities": ["x_read"]}, "every morning i need a report")
    assert "document" in plan["capabilities"] and plan["detail"] == "report"
    kept = designs.report_is_delivered({"capabilities": ["x_read", "notify"]}, "send me a report")
    assert kept["capabilities"] == ["x_read", "notify"]
    assert designs.report_is_delivered({"capabilities": ["x_read"]}, "how many servers")["capabilities"] == ["x_read"]
