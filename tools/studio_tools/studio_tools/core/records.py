"""record_write: one record into an allowlisted SQL table, or into a registered app record endpoint (REST POST).

Approval is enforced here (not only by a flow node), dry-run is the default, nothing is ever retried.
"""

from __future__ import annotations

from typing import Any

from . import apps
from .config import get_connection, load_config
from .errors import NotAllowed
from .spec import approval_gate
from .sqlexec import build_insert, run_insert


def write_record(system: str, record_type: str, fields: dict[str, Any], *, approved: bool, dry_run: bool,
                 reason: str = "", as_user: str | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_config() if cfg is None else cfg
    in_sql = system in (cfg.get("sql") or {})
    in_apps = system in (cfg.get("apps") or {})
    if not (in_sql or in_apps):
        raise NotAllowed(f"'{system}' is not a registered record system (sql connection or app)")
    if in_sql:
        conn = get_connection("sql", system, cfg)
        sql, params = build_insert(conn, record_type, fields)  # allowlist + identifier checks first
        plan = {"system": system, "kind": "sql", "sql": sql, "params": params}
        gate = approval_gate(approved=approved, dry_run=dry_run, write_allowed=bool(conn.get("allow_write")),
                             what=f"insert into '{record_type}'")
        if gate:
            status = "rejected" if not conn.get("allow_write") else ("planned" if dry_run else "pending_approval")
            return {"status": status, "reason": gate, "plan": plan}
        rowcount = run_insert(conn, sql, params)
        return {"status": "done", "plan": plan, "rows_inserted": rowcount}
    app = get_connection("apps", system, cfg)
    return apps.action(app, record_type, target=None, params=fields, reason=reason or f"record_write {record_type}",
                       approved=approved, dry_run=dry_run, as_user=as_user, registry="records")
