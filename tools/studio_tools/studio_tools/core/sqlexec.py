"""SQL execution on named connections: read-only SELECT (sql_read) and allowlisted INSERT (record_write).

Dialects: postgres (psycopg 3), mssql (pymssql), clickhouse (clickhouse-connect), sqlite (dev/tests only).
Read-only is enforced in three layers: statement validation (sqlguard), a read-only transaction / session
setting where the database supports one, and (operationally) a login that only has read grants.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import uuid
from typing import Any, Callable

from .config import secret
from .errors import ConfigError, NotAllowed, ToolTimeout, UpstreamError
from .sqlguard import check_identifier, param_names, to_pyformat, validate_select
from .timeouts import run_with_timeout

DIALECTS = ("postgres", "mssql", "clickhouse", "sqlite")
DEFAULT_MAX_ROWS = 1000
HARD_MAX_ROWS = 10000
DEFAULT_TIMEOUT_S = 30.0
GRACE_S = 5.0  # wall-clock grace on top of server-side timeouts (connect time)


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, decimal.Decimal):
        return float(v) if v.is_finite() else str(v)
    if isinstance(v, (_dt.date, _dt.datetime, _dt.time)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return v.total_seconds()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    return str(v)


def _dialect(conn: dict[str, Any]) -> str:
    d = str(conn.get("dialect", "")).lower()
    if d in ("postgresql", "pg"):
        d = "postgres"
    if d in ("sqlserver", "mssql"):
        d = "mssql"
    if d not in DIALECTS:
        raise ConfigError(f"connection '{conn.get('_name')}' has unsupported dialect '{d}' (use one of {DIALECTS})")
    return d


def _limits(conn: dict[str, Any], max_rows: int | None, timeout_s: float | None) -> tuple[int, float]:
    cap = int(conn.get("max_rows", DEFAULT_MAX_ROWS))
    rows = min(int(max_rows or cap), cap, HARD_MAX_ROWS)
    ctimeout = float(conn.get("timeout_s", DEFAULT_TIMEOUT_S))
    t = min(float(timeout_s or ctimeout), ctimeout)
    return max(rows, 1), max(t, 1.0)


def _check_params(sql: str, params: dict[str, Any] | None) -> dict[str, Any]:
    params = dict(params or {})
    for k, v in params.items():
        check_identifier(k, "parameter name")
        if isinstance(v, (dict, list, tuple, set)):
            raise NotAllowed(f"parameter '{k}' must be a scalar value")
    missing = [n for n in param_names(sql) if n not in params]
    if missing:
        raise NotAllowed(f"missing value for SQL parameter(s): {', '.join(sorted(set(missing)))}")
    return params


def sqlalchemy_engine(conn: dict[str, Any], timeout_s: float, *, read_only: bool):
    """Build a NullPool engine (one connection per call; nothing lingers holding a session)."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from sqlalchemy.pool import NullPool

    d = _dialect(conn)
    t = int(max(timeout_s, 1))
    if d == "sqlite":
        return create_engine(f"sqlite:///{conn['database']}", poolclass=NullPool)
    password = secret(conn, "password", required=False) if conn.get("password_env") else None
    if d == "postgres":
        url = URL.create("postgresql+psycopg", username=conn.get("username"), password=password,
                         host=conn.get("host"), port=conn.get("port"), database=conn.get("database"))
        opts = f"-c statement_timeout={t * 1000}"
        if read_only:
            opts += " -c default_transaction_read_only=on"
        args: dict[str, Any] = {"connect_timeout": min(t, 15), "options": opts}
        if conn.get("sslmode"):
            args["sslmode"] = conn["sslmode"]
        return create_engine(url, poolclass=NullPool, connect_args=args)
    if d == "mssql":
        try:
            import pymssql  # noqa: F401
        except ImportError:
            raise ConfigError("SQL Server driver pymssql is not installed in the engine image") from None
        url = URL.create("mssql+pymssql", username=conn.get("username"), password=password,
                         host=conn.get("host"), port=conn.get("port"), database=conn.get("database"))
        return create_engine(url, poolclass=NullPool,
                             connect_args={"login_timeout": min(t, 15), "timeout": t, "appname": "agent-studio-tools"})
    raise ConfigError(f"dialect '{d}' is not served through SQLAlchemy")


def _read_sqlalchemy(conn, sql, params, max_rows, timeout_s):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, SQLAlchemyError

    d = _dialect(conn)
    engine = sqlalchemy_engine(conn, timeout_s, read_only=True)
    try:
        with engine.connect() as c:
            if d == "postgres":
                c.execute(text("SET TRANSACTION READ ONLY"))
            elif d == "sqlite":
                c.exec_driver_sql("PRAGMA query_only = ON")
            res = c.execute(text(sql), params)
            cols = list(res.keys())
            fetched = res.fetchmany(max_rows + 1)
            c.rollback()  # never commit anything from the read path
    except DBAPIError as exc:
        msg = str(exc.orig).strip().splitlines()[0] if exc.orig else "database error"
        if "timeout" in msg.lower() or "canceling statement" in msg.lower():
            raise ToolTimeout(f"query exceeded {timeout_s:.0f}s") from None
        raise UpstreamError(f"database error: {msg[:500]}") from None
    except SQLAlchemyError as exc:
        raise UpstreamError(f"database error: {str(exc).splitlines()[0][:500]}") from None
    finally:
        engine.dispose()
    return cols, [tuple(r) for r in fetched]


def _clickhouse_client(conn: dict[str, Any], timeout_s: float):
    try:
        import clickhouse_connect
    except ImportError:
        raise ConfigError("clickhouse-connect is not installed in the engine image") from None
    password = secret(conn, "password", required=False) if conn.get("password_env") else ""
    return clickhouse_connect.get_client(
        host=conn.get("host"), port=conn.get("port") or (8443 if conn.get("secure") else 8123),
        username=conn.get("username") or "default", password=password or "",
        database=conn.get("database") or "default", secure=bool(conn.get("secure", False)),
        connect_timeout=min(timeout_s, 15), send_receive_timeout=timeout_s,
    )


def _read_clickhouse(conn, sql, params, max_rows, timeout_s, client_factory=None):
    settings = {"readonly": 2, "max_execution_time": int(timeout_s),
                "max_result_rows": max_rows + 1, "result_overflow_mode": "break"}
    settings.update(conn.get("clickhouse_settings") or {})
    client = (client_factory or _clickhouse_client)(conn, timeout_s)
    try:
        res = client.query(to_pyformat(sql) if params else sql, parameters=params or None, settings=settings)
        cols = list(res.column_names)
        rows = [tuple(r) for r in res.result_rows[: max_rows + 1]]
    except Exception as exc:  # clickhouse-connect raises its own hierarchy
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        if "TIMEOUT" in msg.upper():
            raise ToolTimeout(f"query exceeded {timeout_s:.0f}s") from None
        raise UpstreamError(f"clickhouse error: {msg[:500]}") from None
    finally:
        try:
            client.close()
        except Exception:
            pass
    return cols, rows


def run_select(conn: dict[str, Any], sql: str, params: dict[str, Any] | None = None, *,
               max_rows: int | None = None, timeout_s: float | None = None,
               clickhouse_factory: Callable | None = None) -> dict[str, Any]:
    """Validate + execute a read-only query. Returns {columns, rows (list of dicts), row_count, truncated}."""
    sql = validate_select(sql)
    params = _check_params(sql, params)
    rows_cap, t = _limits(conn, max_rows, timeout_s)
    d = _dialect(conn)

    def work():
        if d == "clickhouse":
            return _read_clickhouse(conn, sql, params, rows_cap, t, clickhouse_factory)
        return _read_sqlalchemy(conn, sql, params, rows_cap, t)

    # Wall-clock guard on top of the driver/server timeouts (a few seconds of grace for connect).
    cols, rows = run_with_timeout(work, t + GRACE_S, what=f"query on '{conn.get('_name')}'")
    truncated = len(rows) > rows_cap
    rows = rows[:rows_cap]
    return {
        "connection": conn.get("_name"),
        "columns": cols,
        "rows": [{c: _jsonable(v) for c, v in zip(cols, r)} for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


# ----------------------------------------------------------------------------------------------- writes


def _split_table(table: str) -> list[str]:
    parts = table.split(".")
    if not 1 <= len(parts) <= 3:
        raise NotAllowed(f"invalid table name '{table}'")
    return [check_identifier(p, "table name part") for p in parts]


def build_insert(conn: dict[str, Any], table: str, record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """INSERT for an allowlisted table (connection.writable_tables). Column names are validated identifiers,
    values are always bound parameters."""
    writable = conn.get("writable_tables") or {}
    if isinstance(writable, list):
        writable = {t: None for t in writable}
    if table not in writable:
        raise NotAllowed(f"table '{table}' is not in the write allowlist of connection '{conn.get('_name')}'")
    if not isinstance(record, dict) or not record:
        raise NotAllowed("record must be a non-empty JSON object of column: value")
    allowed_cols = (writable.get(table) or {}).get("columns") if isinstance(writable.get(table), dict) else None
    cols = [check_identifier(c, "column name") for c in record]
    if allowed_cols is not None:
        bad = [c for c in cols if c not in allowed_cols]
        if bad:
            raise NotAllowed(f"column(s) {bad} not allowed for table '{table}'")
    for c, v in record.items():
        if isinstance(v, (dict, list, tuple, set)):
            raise NotAllowed(f"value for column '{c}' must be a scalar")
    _split_table(table)
    params = {f"p{i}": record[c] for i, c in enumerate(cols)}
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + p for p in params)})"
    return sql, params


def run_insert(conn: dict[str, Any], sql: str, params: dict[str, Any], timeout_s: float | None = None) -> int:
    """Execute one INSERT in its own transaction. No retry, ever."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    if _dialect(conn) == "clickhouse":
        raise NotAllowed("record_write does not write to ClickHouse")
    _, t = _limits(conn, 1, timeout_s)

    def work():
        engine = sqlalchemy_engine(conn, t, read_only=False)
        try:
            with engine.begin() as c:
                return c.execute(text(sql), params).rowcount
        except SQLAlchemyError as exc:
            orig = getattr(exc, "orig", None) or exc
            raise UpstreamError(f"insert failed: {str(orig).splitlines()[0][:500]}") from None
        finally:
            engine.dispose()

    return run_with_timeout(work, t + GRACE_S, what=f"insert on '{conn.get('_name')}'")
