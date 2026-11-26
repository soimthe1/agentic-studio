"""lfx-level checks: the bundle loads through the real lfx loader, tool schemas hide policy inputs, components run."""

import json
import sqlite3
from pathlib import Path

import pytest

lfx = pytest.importorskip("lfx")

PKG = Path(__file__).resolve().parents[1] / "studio_tools"
EXPECTED = {"AppActionComponent", "AppQueryComponent", "BundleCheckComponent", "DocumentCreateComponent",
            "KnowledgeSearchComponent", "NotifyComponent", "RecordWriteComponent", "SqlReadonlyComponent",
            "SaveDataComponent", "FilesBundleComponent", "WebReadComponent", "CodeToolComponent"}
OWN_FILES = {"document_create", "save_data", "bundle_files"}   # write only into the person's own files: no approval
POLICY_INPUTS = {"approved", "dry_run", "acting_user", "allowed_connections", "allowed_apps", "allowed_channels",
                 "allowed_systems", "allowed_scopes"}


def test_bundle_loads_with_lfx_loader():
    from lfx.extension.loader import load_extension_bundles

    results = load_extension_bundles(PKG, module_namespace="_pgtools_test")
    errors = [e for r in results for e in r.errors]
    assert not errors, errors
    names = {c.class_name for r in results for c in r.components}
    assert names == EXPECTED


def test_extension_json_and_versions():
    from studio_tools.components.studio.bundle_check import VERSION

    manifest = json.loads((PKG / "extension.json").read_text())
    assert manifest["version"] == VERSION == "0.3.0"
    pyproject = (PKG.parent / "pyproject.toml").read_text()
    assert 'version = "0.3.0"' in pyproject


def _components():
    import studio_tools.components.studio as t

    return [getattr(t, n) for n in sorted(EXPECTED)]


@pytest.mark.parametrize("cls", _components(), ids=lambda c: c.__name__)
def test_declares_spec_and_hides_policy_from_llm(cls):
    spec = cls.tool_spec
    assert spec.side_effects in ("none", "read", "write") and spec.timeout_s > 0 and spec.retry
    assert cls.description == spec.description
    if spec.side_effects == "write" and spec.name not in OWN_FILES:
        assert spec.approval_required and spec.retry.startswith("never")
    tool_inputs = {i.name for i in cls.inputs if getattr(i, "tool_mode", False)}
    assert tool_inputs, "an agent must be able to fill at least one input"
    assert not (tool_inputs & POLICY_INPUTS), "approval / scope / identity inputs must never be LLM-settable"
    for i in cls.inputs:
        if i.name == "dry_run":
            assert i.value is True
        if i.name == "approved":
            assert i.value is False


@pytest.mark.parametrize("cls", _components(), ids=lambda c: c.__name__)
def test_tool_name_matches_catalog(cls):
    tool_outputs = [o for o in cls.outputs if o.tool_mode]
    assert len(tool_outputs) == 1
    if cls.tool_spec.name != "bundle_check":
        assert tool_outputs[0].method == cls.tool_spec.name


def test_toolkit_schema_excludes_policy_inputs():
    from lfx.base.tools.component_tool import ComponentToolkit
    from studio_tools.components.studio import AppActionComponent

    tools = ComponentToolkit(component=AppActionComponent()).get_tools()
    assert [t.name for t in tools] == ["app_action"]
    fields = set(tools[0].args_schema.model_json_schema()["properties"])
    assert fields == {"app", "action", "target", "params", "reason"}


@pytest.fixture
def sql_cfg(tmp_path, write_cfg):
    path = tmp_path / "c.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (a INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(5)])
    con.commit()
    con.close()
    return write_cfg({"sql": {"local": {"dialect": "sqlite", "database": str(path), "max_rows": 3}},
                      "notify": {"ops": {"type": "webhook", "url": "http://chat.local/h", "requires_approval": False}}})


def test_sql_readonly_component_envelope(sql_cfg):
    from studio_tools.components.studio import SqlReadonlyComponent

    c = SqlReadonlyComponent()
    c.set(connection="local", sql="SELECT a FROM t WHERE a >= :m", params='{"m": 1}', max_rows=10)
    env = c.sql_readonly().data
    assert env["ok"] and env["data"]["row_count"] == 3 and env["data"]["truncated"] is True
    assert env["source"]["tool"] == "sql_readonly" and env["fetched_at"]
    c.set(sql="DROP TABLE t")
    env = c.sql_readonly().data
    assert env["ok"] is False and env["error"]["code"] == "not_allowed"
    c.set(connection="prod", sql="SELECT 1")
    assert c.sql_readonly().data["error"]["code"] == "config"
    c.set(connection="local", allowed_connections="other,another")
    assert "not enabled for this agent" in c.sql_readonly().data["error"]["message"]
    # exactly one allowed: the flow's choice wins over what the model asked for
    c.set(connection="whatever-the-model-said", allowed_connections="local", sql="SELECT a FROM t")
    assert c.sql_readonly().data["ok"]


def test_notify_component_defaults_to_dry_run(sql_cfg, mock_http):
    from studio_tools.components.studio import NotifyComponent

    _, calls = mock_http
    c = NotifyComponent()
    c.set(channel="ops", subject="s", body="b")
    env = c.notify().data
    assert env["ok"] and env["data"]["status"] == "dry_run" and calls == []
