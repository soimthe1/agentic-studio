import sqlite3
import time

import pytest

from studio_tools.core import sqlexec
from studio_tools.core.config import get_connection
from studio_tools.core.errors import ConfigError, NotAllowed, ToolTimeout, UpstreamError


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE servers (name TEXT, cpu REAL)")
    con.executemany("INSERT INTO servers VALUES (?, ?)", [(f"WEB{i:02d}", i * 1.5) for i in range(30)])
    con.commit()
    con.close()
    return {"_name": "local", "dialect": "sqlite", "database": str(path), "max_rows": 10, "timeout_s": 5}


def test_select_with_params(db):
    out = sqlexec.run_select(db, "SELECT name, cpu FROM servers WHERE cpu > :min ORDER BY cpu DESC", {"min": 40})
    assert out["columns"] == ["name", "cpu"]
    assert out["rows"][0] == {"name": "WEB29", "cpu": 43.5}
    assert out["truncated"] is False


def test_row_cap_and_truncation(db):
    out = sqlexec.run_select(db, "SELECT * FROM servers", max_rows=500)  # capped by connection max_rows=10
    assert out["row_count"] == 10 and out["truncated"] is True


def test_rejects_write_before_touching_db(db):
    with pytest.raises(NotAllowed):
        sqlexec.run_select(db, "DELETE FROM servers")
    assert sqlexec.run_select(db, "SELECT count(*) AS n FROM servers")["rows"][0]["n"] == 30


def test_database_level_read_only_even_if_validator_bypassed(db):
    # Second layer: the read path opens the session read-only (sqlite: PRAGMA query_only).
    with pytest.raises(UpstreamError, match="readonly|read-only|query_only|attempt to write"):
        sqlexec._read_sqlalchemy(db, "INSERT INTO servers VALUES ('X', 1)", {}, 10, 5)
    assert sqlexec.run_select(db, "SELECT count(*) AS n FROM servers")["rows"][0]["n"] == 30


def test_missing_and_non_scalar_params(db):
    with pytest.raises(NotAllowed, match="missing value"):
        sqlexec.run_select(db, "SELECT * FROM servers WHERE name = :n", {})
    with pytest.raises(NotAllowed, match="scalar"):
        sqlexec.run_select(db, "SELECT * FROM servers WHERE name = :n", {"n": [1, 2]})


def test_timeout_is_clean_error(db, monkeypatch):
    monkeypatch.setattr(sqlexec, "GRACE_S", 0.0)
    monkeypatch.setattr(sqlexec, "_read_sqlalchemy", lambda *a, **k: time.sleep(3))
    t0 = time.monotonic()
    with pytest.raises(ToolTimeout, match="timed out"):
        sqlexec.run_select(db, "SELECT 1", timeout_s=1)
    assert time.monotonic() - t0 < 2.5


def test_db_error_is_clean(db):
    with pytest.raises(UpstreamError, match="no such table"):
        sqlexec.run_select(db, "SELECT * FROM nope")


def test_unknown_connection_is_rejected(write_cfg):
    cfg = write_cfg({"sql": {"a": {"dialect": "sqlite", "database": "x"}}})
    with pytest.raises(ConfigError, match="not an approved sql connection"):
        get_connection("sql", "other", cfg)


def test_unsupported_dialect():
    with pytest.raises(ConfigError):
        sqlexec.run_select({"_name": "x", "dialect": "oracle"}, "SELECT 1")


def test_clickhouse_uses_readonly_settings_and_bound_params():
    seen = {}

    class Res:
        column_names = ("a",)
        result_rows = [(1,), (2,), (3,)]

    class Client:
        def query(self, sql, parameters=None, settings=None):
            seen.update(sql=sql, parameters=parameters, settings=settings)
            return Res()

        def close(self):
            seen["closed"] = True

    conn = {"_name": "ch", "dialect": "clickhouse", "max_rows": 2}
    out = sqlexec.run_select(conn, "SELECT a FROM t WHERE b = :b", {"b": "x'; DROP"},
                             clickhouse_factory=lambda c, t: Client())
    assert seen["sql"] == "SELECT a FROM t WHERE b = %(b)s"
    assert seen["parameters"] == {"b": "x'; DROP"}
    assert seen["settings"]["readonly"] == 2 and seen["settings"]["max_result_rows"] == 3
    assert out["truncated"] is True and out["row_count"] == 2 and seen["closed"]


def test_postgres_engine_is_read_only_with_statement_timeout(monkeypatch):
    import sqlalchemy

    captured = {}
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda url, **kw: captured.update(url=url, **kw))
    monkeypatch.setenv("STUDIO_TOOL_PW", "s3cret")
    sqlexec.sqlalchemy_engine({"_name": "p", "dialect": "postgres", "host": "h", "database": "d",
                               "username": "u", "password_env": "STUDIO_TOOL_PW"}, 12, read_only=True)
    opts = captured["connect_args"]["options"]
    assert "default_transaction_read_only=on" in opts and "statement_timeout=12000" in opts
    assert captured["url"].password == "s3cret"  # secret comes from the environment


def test_missing_secret_env_is_config_error(monkeypatch):
    monkeypatch.delenv("STUDIO_TOOL_NOPE", raising=False)
    with pytest.raises(ConfigError, match="STUDIO_TOOL_NOPE"):
        sqlexec.sqlalchemy_engine({"_name": "p", "dialect": "postgres", "host": "h", "password_env": "STUDIO_TOOL_NOPE"},
                                  5, read_only=True)
