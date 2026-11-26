import json

import httpx
import pytest

from studio_tools.core import apps
from studio_tools.core.errors import NotAllowed, UpstreamError

# Contracts shaped like real monitoring apps (generic connector; options: instances, resolve, extra_headers, optional).
SQLMON = {"_name": "sqlmon", "type": "generic",
          "instances": {"SQLPROD01": {"base_url": "http://sqlmon1.local:8000",
                                      "extra_headers": [{"name": "X-Agent-Tools-Key", "value_env": "STUDIO_TOOL_AT"}]},
                        "SQLPROD02": {"base_url": "http://sqlmon2.local:8000"}},
          "operations": {"health_summary": {"path": "/api/health-summary"},
                         "findings": {"path": "/api/findings", "query": ["category", "severity", "status"]},
                         "query_plan": {"path": "/api/queries/{query_hash}/plan"},
                         "index_usage": {"path": "/api/agent-tools/index-usage", "query": ["table", "database"], "optional": True},
                         "plan_instability": {"path": "/api/agent-tools/plan-instability/{query_hash}", "optional": True}},
          "actions": {"acknowledge_finding": {"method": "POST", "path": "/api/findings/{finding_id}/acknowledge"}}}
IIS = {"_name": "iis", "type": "generic", "base_url": "http://iis.local:8000",
       "auth": {"type": "ad_login", "username": "svc_ro", "password_env": "STUDIO_TOOL_IIS"},
       "resolve": {"placeholder": "node_id", "list_path": "/api/v1/nodes", "match": ["hostname", "display_name"], "id": "id",
                   "label": "IIS node"},
       "operations": {"node_detail": {"path": "/api/v1/nodes/{node_id}/detail"},
                      "slow_requests": {"path": "/api/v1/nodes/{node_id}/slow-requests", "query": ["hours", "limit"]},
                      "fleet_health": {"path": "/api/v1/overview/health", "query": ["cluster", "days", "minutes"], "target": "query:node"},
                      "incidents": {"path": "/api/v1/incidents", "query": ["status_filter", "limit", "cluster"],
                                    "defaults": {"status_filter": "open"}, "target": "filter"}},
       "actions": {"acknowledge_incident": {"method": "POST", "path": "/api/v1/incidents/{incident_id}/acknowledge"}}}
NODES = [{"id": "11111111-1111-1111-1111-111111111111", "hostname": "WEB01", "display_name": None},
         {"id": "22222222-2222-2222-2222-222222222222", "hostname": "WEB02", "display_name": "web two"}]


def test_sqlmon_target_selects_instance(mock_http):
    set_handler, calls = mock_http
    set_handler(lambda r: httpx.Response(200, json={"server_name": "SQLPROD02", "status": "ok"}))
    out = apps.query(SQLMON, "health_summary", target="SQLPROD02")
    assert out["status"] == "ok"
    assert str(calls[0].url) == "http://sqlmon2.local:8000/api/health-summary"


def test_sqlmon_unknown_instance_and_operation():
    with pytest.raises(NotAllowed, match="not a registered instance"):
        apps.query(SQLMON, "health_summary", target="SQLPROD99")
    with pytest.raises(NotAllowed, match="needs a target"):
        apps.query(SQLMON, "health_summary")
    with pytest.raises(NotAllowed, match="unknown operation"):
        apps.query(SQLMON, "acknowledge_finding", target="SQLPROD01")  # writes are not query operations


def test_sqlmon_filters_and_agent_tools_key(mock_http, monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_AT", "agent-key")
    set_handler, calls = mock_http
    set_handler(lambda r: httpx.Response(200, json=[{"i": n} for n in range(80)]))
    out = apps.query(SQLMON, "findings", target="SQLPROD01", filters={"severity": "critical", "junk": "x"}, limit=5)
    assert out["truncated"] and len(out["items"]) == 5 and out["total"] == 80
    assert calls[0].url.params.get("severity") == "critical" and "junk" not in calls[0].url.params
    apps.query(SQLMON, "index_usage", target="SQLPROD01", filters={"table": "Orders", "database": "Sales"})
    assert calls[-1].headers["X-Agent-Tools-Key"] == "agent-key"
    assert calls[-1].url.path == "/api/agent-tools/index-usage"


def test_path_injection_rejected(mock_http):
    _, calls = mock_http
    with pytest.raises(NotAllowed, match="invalid"):
        apps.query(SQLMON, "query_plan", target="SQLPROD01", filters={"query_hash": "../../admin"})
    with pytest.raises(NotAllowed, match="invalid"):
        apps.query(IIS, "node_detail", target="WEB01/../x")
    assert calls == []


def test_agent_tools_disabled_404(mock_http):
    set_handler, _ = mock_http
    set_handler(lambda r: httpx.Response(404, json={"detail": "Not found"}))
    with pytest.raises(UpstreamError, match="switched off on this system"):
        apps.query(SQLMON, "plan_instability", target="SQLPROD02", filters={"query_hash": "0xABC"})


def _iis_handler(r):
    if r.url.path == "/api/v1/auth/login":
        assert json.loads(r.content) == {"username": "svc_ro", "password": "pw"}
        return httpx.Response(200, json={"access_token": "jwt-1"})
    assert r.headers["Authorization"] == "Bearer jwt-1"
    if r.url.path == "/api/v1/nodes":
        return httpx.Response(200, json=NODES)
    if r.url.path.endswith("/detail"):
        return httpx.Response(200, json={"node": r.url.path.split("/")[4]})
    if r.url.path == "/api/v1/incidents":
        return httpx.Response(200, json=[{"id": 1, "correlation_key": "WEB01:pool"},
                                         {"id": 2, "correlation_key": "WEB02:disk"}])
    return httpx.Response(200, json={"path": r.url.path, "params": dict(r.url.params)})


def test_iis_login_and_node_resolution(mock_http, monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_IIS", "pw")
    set_handler, _ = mock_http
    set_handler(_iis_handler)
    assert apps.query(IIS, "node_detail", target="web02") == {"node": NODES[1]["id"]}
    assert apps.query(IIS, "incidents", target="WEB01") == [{"id": 1, "correlation_key": "WEB01:pool"}]
    out = apps.query(IIS, "fleet_health", target="WEB01", filters={"days": 7})
    assert out["params"] == {"days": "7", "node": "WEB01"}
    with pytest.raises(UpstreamError, match="not a registered IIS node"):
        apps.query(IIS, "node_detail", target="WEB99")
    with pytest.raises(NotAllowed, match="needs a target"):
        apps.query(IIS, "slow_requests")


def test_iis_target_allowlist():
    with pytest.raises(NotAllowed, match="allowlist"):
        apps.query({**IIS, "allowed_targets": ["WEB01"]}, "node_detail", target="WEB02")


GENERIC = {"_name": "sqlcatalog", "type": "generic", "base_url": "http://cat.local:8200",
           "auth": {"type": "service_key", "header": "X-Service-Key", "token_env": "STUDIO_TOOL_CAT",
                    "on_behalf_of_header": "X-On-Behalf-Of"},
           "operations": {"ask": {"method": "POST", "read": True, "path": "/v1/ask", "body": ["question"]},
                          "bad": {"method": "POST", "path": "/v1/write"}}}


def test_generic_on_behalf_of(mock_http, monkeypatch):
    monkeypatch.setenv("STUDIO_TOOL_CAT", "svc-key")
    set_handler, calls = mock_http
    set_handler(lambda r: httpx.Response(200, json={"answer": "42"}))
    with pytest.raises(NotAllowed, match="no acting user"):
        apps.query(GENERIC, "ask", filters={"question": "q"})
    assert apps.query(GENERIC, "ask", filters={"question": "q"}, as_user="ali") == {"answer": "42"}
    assert calls[-1].headers["X-Service-Key"] == "svc-key" and calls[-1].headers["X-On-Behalf-Of"] == "ali"
    assert json.loads(calls[-1].content) == {"question": "q"}
    with pytest.raises(NotAllowed, match="not declared read-only"):
        apps.query(GENERIC, "bad", as_user="ali")


# ------------------------------------------------------------------------------------------------ actions

MOCK = {"_name": "remediation_mock", "type": "generic", "mock": True, "base_url": "http://mock.local:9000",
        "allow_write": True, "allowed_targets": ["WEB01"],
        "actions": {"restart_service": {"method": "POST", "path": "/api/v1/actions", "target_field": "host",
                                        "fixed": {"action": "restart"}, "body": ["service"]}}}


def _act(app=MOCK, **kw):
    args = {"target": "WEB01", "params": {"service": "W3SVC"}, "reason": "pool hung", "approved": False,
            "dry_run": True}
    args.update(kw)
    return apps.action(app, "restart_service", **args)


def test_action_dry_run_by_default_sends_nothing(mock_http):
    _, calls = mock_http
    out = _act()
    assert out["status"] == "planned" and calls == []
    assert out["plan"]["body"] == {"action": "restart", "service": "W3SVC", "host": "WEB01"}


def test_action_needs_approval(mock_http):
    _, calls = mock_http
    assert _act(dry_run=False)["status"] == "pending_approval" and calls == []


def test_action_needs_write_enabled_connection(mock_http):
    _, calls = mock_http
    out = _act({**MOCK, "allow_write": False}, dry_run=False, approved=True)
    assert out["status"] == "rejected" and calls == []


def test_action_executes_once_when_approved_never_retried(mock_http):
    set_handler, calls = mock_http
    set_handler(lambda r: httpx.Response(503, json={"detail": "busy"}))
    with pytest.raises(UpstreamError, match="503"):
        _act(dry_run=False, approved=True)
    assert len(calls) == 1
    set_handler(lambda r: httpx.Response(200, json={"job": 7}))
    out = _act(dry_run=False, approved=True)
    assert out["status"] == "done" and out["result"] == {"job": 7}


def test_action_policy_checks(mock_http):
    with pytest.raises(NotAllowed, match="unknown action"):
        apps.action(MOCK, "format_disk", target="WEB01", params={}, reason="x", approved=True, dry_run=False)
    with pytest.raises(NotAllowed, match="not accepted"):
        _act(params={"service": "W3SVC", "command": "rm -rf"})
    with pytest.raises(NotAllowed, match="reason"):
        _act(reason=" ")
    with pytest.raises(NotAllowed, match="allowlist"):
        _act(target="DC01")


def test_only_actions_in_the_contract_exist():
    with pytest.raises(NotAllowed, match="unknown action"):
        apps.action({**SQLMON, "allow_write": True}, "resolve_finding", target="SQLPROD01",
                    params={"finding_id": 3}, reason="seen", approved=True, dry_run=True)
    out = apps.action({**SQLMON, "allow_write": True}, "acknowledge_finding",
                      target="SQLPROD01", params={"finding_id": 3}, reason="seen", approved=True, dry_run=True)
    assert out["plan"]["path"] == "/api/findings/3/acknowledge" and out["status"] == "planned"
