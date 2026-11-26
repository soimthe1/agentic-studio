"""DECLARED TEST DOUBLE (development and tests only; never shipped).

Serves the same paths and response shapes as the real apps' routers so Agent Studio agents can be built and tested
end to end when the real systems aren't reachable from the dev PC:
  /sqlmon/...  SQL Monitor   (sql-monitor/api/routers/health.py, findings.py)
  /iis/...     IIS Monitor   (iis-monitor/backend/app/api/routes.py, schemas.py)
  /remediation/...  Remediation-style action API (no real remediation API exists; see docs/agent-catalog.md)
  /chat/hook   chat webhook (records posts; GET /chat/posts lists them)
The data contains realistic problems (an AG replica not synchronized, a failed backup job, a slow IIS node) so
"notify only when something is wrong" is exercised. Run: python tests/mocks/apps.py  (port 9190)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="Agent Studio test double")
NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
POSTS: list[dict] = []
ACTIONS: list[dict] = []

# ---------------------------------------------------------------- SQL Monitor
FINDINGS = [
    {"id": 101, "category": "availability", "severity": "critical", "status": "open", "acknowledged": False,
     "title_en": "AG replica SQLPROD02 is NOT_SYNCHRONIZING", "object": "AG_PROD", "detected_at": None,
     "detail_en": "Secondary replica SQLPROD02 in availability group AG_PROD stopped synchronizing 47 minutes ago; redo queue 3.2 GB.",
     "recommendation_en": "Check network between replicas and the SQL Server error log on SQLPROD02; resume data movement once the cause is fixed."},
    {"id": 102, "category": "jobs", "severity": "warning", "status": "open", "acknowledged": False,
     "title_en": "SQL Agent job 'Nightly full backup - Finance' failed", "object": "Nightly full backup - Finance", "detected_at": None,
     "detail_en": "Job failed at step 2 (BACKUP DATABASE): disk F: has 1.1 GB free.",
     "recommendation_en": "Free space on F: or point the backup to another volume, then rerun the job."},
    {"id": 103, "category": "performance", "severity": "info", "status": "open", "acknowledged": True,
     "title_en": "Plan regression on query 0x4F2A", "object": "dbo.usp_GetOrders", "detected_at": None,
     "detail_en": "Average duration up 38% after a plan change.", "recommendation_en": "Review the new plan."},
]


def _findings():
    for i, f in enumerate(FINDINGS):
        f["detected_at"] = (NOW() - timedelta(minutes=47 + 30 * i)).isoformat()
    return FINDINGS


@app.get("/sqlmon/api/health-summary")
def sql_health_summary():
    crit = sum(f["severity"] == "critical" and f["status"] == "open" for f in _findings())
    warn = sum(f["severity"] == "warning" and f["status"] == "open" for f in FINDINGS)
    return {"server_name": "INTDB", "status": "critical" if crit else ("warning" if warn else "healthy"),
            "summary_en": f"{crit} critical and {warn} warning findings need attention.",
            "summary_ar": None, "critical_count": crit, "warning_count": warn,
            "info_count": sum(f["severity"] == "info" for f in FINDINGS), "narrative_source": "rules",
            "generated_at": NOW().isoformat()}


@app.get("/sqlmon/api/state")
def sql_state():
    return {"server_name": "INTDB", "version": "SQL Server 2022 (16.0.4135)", "uptime_hours": 412,
            "availability_groups": [{"name": "AG_PROD", "primary": "SQLPROD01",
                                     "replicas": [{"server": "SQLPROD01", "role": "PRIMARY", "sync_state": "SYNCHRONIZED"},
                                                  {"server": "SQLPROD02", "role": "SECONDARY", "sync_state": "NOT_SYNCHRONIZING"}]}],
            "cpu_percent": 41, "memory_used_gb": 58.2, "memory_total_gb": 64}


@app.get("/sqlmon/api/findings")
def sql_findings(severity: str | None = None, status: str | None = None, category: str | None = None):
    rows = _findings()
    return [f for f in rows if (not severity or f["severity"] == severity) and (not status or f["status"] == status)
            and (not category or f["category"] == category)]


@app.get("/sqlmon/api/findings/summary")
def sql_findings_summary():
    out: dict = {}
    for f in _findings():
        out.setdefault(f["severity"], 0)
        out[f["severity"]] += 1
    return out


@app.get("/sqlmon/api/findings/unacknowledged-alerts")
def sql_unacked():
    rows = [f for f in _findings() if not f["acknowledged"] and f["severity"] in ("critical", "warning")]
    return {"enabled": True, "count": len(rows), "findings": rows}


# ---------------------------------------------------------------- IIS Monitor
NODES = [
    {"id": str(uuid.UUID(int=1)), "hostname": "WEB01", "display_name": "WEB01", "cluster_id": None, "cluster_slug": "portal",
     "enabled": True, "state": "healthy"},
    {"id": str(uuid.UUID(int=2)), "hostname": "WEB02", "display_name": "WEB02", "cluster_id": None, "cluster_slug": "portal",
     "enabled": True, "state": "degraded"},
]


def _bearer(request: Request):
    if request.headers.get("authorization", "") != "Bearer mock-token":
        raise HTTPException(401, "Not authenticated")


@app.post("/iis/api/v1/auth/login")
async def iis_login(request: Request):
    body = await request.json() if "json" in request.headers.get("content-type", "") else dict(await request.form())
    if not body.get("username") or not body.get("password"):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": "mock-token", "token_type": "bearer"}


@app.get("/iis/api/v1/nodes")
def iis_nodes(request: Request, cluster: str | None = None):
    _bearer(request)
    return NODES


@app.get("/iis/api/v1/overview")
def iis_overview(request: Request, cluster: str | None = None):
    _bearer(request)
    return {"nodes": 2, "healthy": 1, "degraded": 1, "down": 0, "open_incidents": 1, "requests_per_minute": 1840,
            "p95_ms": 2210, "generated_at": NOW().isoformat()}


@app.get("/iis/api/v1/overview/health")
def iis_health(request: Request, cluster: str | None = None, node: str | None = None, days: int = 1, minutes: int = 60):
    _bearer(request)
    rows = [{"hostname": "WEB01", "state": "healthy", "p95_ms": 340, "error_rate": 0.002, "cpu_percent": 35},
            {"hostname": "WEB02", "state": "degraded", "p95_ms": 4080, "error_rate": 0.061, "cpu_percent": 92,
             "note_en": "App pool 'PortalPool' recycled 6 times in the last hour; worker process memory near limit."}]
    return [r for r in rows if not node or r["hostname"].lower() == node.lower()]


@app.get("/iis/api/v1/nodes/{node_id}/detail")
def iis_node_detail(node_id: str, request: Request):
    _bearer(request)
    node = next((n for n in NODES if n["id"] == node_id), None)
    if not node:
        raise HTTPException(404, "node not found")
    degraded = node["hostname"] == "WEB02"
    return {**node, "sites": [{"name": "Portal", "state": "Started", "bindings": ["https/*:443:portal.example.org"]}],
            "pools": [{"name": "PortalPool", "state": "Started", "recycles_last_hour": 6 if degraded else 0,
                       "private_memory_mb": 3890 if degraded else 910, "memory_limit_mb": 4096}],
            "services": [{"name": "W3SVC", "state": "Running"}, {"name": "WAS", "state": "Running"}]}


@app.get("/iis/api/v1/nodes/{node_id}/slow-requests")
def iis_slow(node_id: str, request: Request, hours: int = 1, limit: int = 20):
    _bearer(request)
    if node_id != str(uuid.UUID(int=2)):
        return []
    return [{"url": "/portal/reports/monthly", "avg_ms": 6120, "count": 214}, {"url": "/portal/search", "avg_ms": 3480, "count": 980}][:limit]


@app.get("/iis/api/v1/incidents")
def iis_incidents(request: Request, status_filter: str = "open", limit: int = 100):
    _bearer(request)
    return [{"id": str(uuid.UUID(int=77)), "correlation_key": "WEB02:PortalPool:recycle", "severity": "warning", "status": "open",
             "title_en": "PortalPool on WEB02 is recycling repeatedly", "title_ar": None,
             "narrative_en": "Memory pressure in PortalPool causes rapid recycles and slow responses for /portal.",
             "narrative_ar": None, "recommendations": ["Restart the W3SVC service on WEB02 after draining", "Investigate the memory leak in the Portal app"],
             "affected_entities": ["WEB02", "PortalPool"], "predicted_breach_at": None, "confidence": 0.82,
             "opened_at": (NOW() - timedelta(minutes=55)).isoformat(), "resolved_at": None, "findings": []}][:limit]


# ---------------------------------------------------------------- Remediation-style actions (declared mock)
@app.get("/remediation/api/v1/fleet/{host}")
def fleet(host: str):
    return {"host": host, "online": True, "services": [{"name": "W3SVC", "state": "Running"}]}


@app.post("/remediation/api/v1/actions")
async def action(request: Request):
    body = await request.json()
    rec = {"id": len(ACTIONS) + 1, "received_at": NOW().isoformat(), **body, "result": "done (mock)"}
    ACTIONS.append(rec)
    return rec


@app.get("/remediation/api/v1/actions")
def actions():
    return ACTIONS


# ---------------------------------------------------------------- chat webhook
@app.post("/chat/hook")
async def chat_hook(request: Request):
    body = await request.json()
    POSTS.append({"at": NOW().isoformat(), **body})
    return {"ok": True}


@app.get("/chat/posts")
def chat_posts():
    return POSTS


@app.delete("/chat/posts")
def clear():
    POSTS.clear()
    ACTIONS.clear()
    return {"cleared": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9190, log_level="warning")
