import pytest

from studio_tools.core.errors import NotAllowed
from studio_tools.core.sqlguard import param_names, to_pyformat, validate_select

OK = [
    "SELECT 1",
    "select * from t where a = :a;",
    "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
    "(SELECT 1) UNION (SELECT 2)",
    "SELECT 'insert into t; drop table x' AS s",          # keywords inside a string literal
    'SELECT "update" FROM t',                               # quoted identifier
    "SELECT [delete] FROM dbo.t",                           # T-SQL bracket identifier
    "SELECT name FROM system.tables",                       # ClickHouse system db is fine
    "SELECT replace(a, 'x', 'y') FROM t -- trailing comment drop table",
    "SELECT $$ delete $$ AS s",                             # postgres dollar quoting
]

BAD = [
    ("", "empty"),
    ("DELETE FROM t", "only SELECT"),
    ("UPDATE t SET a=1", "only SELECT"),
    ("SELECT 1; DROP TABLE t", "single"),
    ("SELECT 1; SELECT 2", "single"),
    ("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "delete"),
    ("SELECT * INTO new_t FROM t", "into"),
    ("SELECT pg_sleep(100)", "pg_sleep"),
    ("SELECT * FROM t; EXEC xp_cmdshell 'dir'", "single"),
    ("SELECT xp_cmdshell('dir')", "xp_cmdshell"),
    ("SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'y')", "openrowset"),
    ("SELECT * FROM url('http://evil/', CSV)", "url()"),
    ("SELECT nextval('s')", "nextval"),
    ("SELECT 1 /* unterminated", "unterminated"),
    ("SELECT 'unterminated", "unterminated"),
    ("/* hide */ DELETE FROM t", "only SELECT"),
    ("SELECT * FROM t FOR UPDATE", "update"),
    ("EXPLAIN ANALYZE DELETE FROM t", "only SELECT"),
]


@pytest.mark.parametrize("sql", OK)
def test_accepts_read_only(sql):
    assert validate_select(sql)


@pytest.mark.parametrize(("sql", "why"), BAD)
def test_rejects_non_select(sql, why):
    with pytest.raises(NotAllowed) as e:
        validate_select(sql)
    assert why.split("(")[0].lower() in str(e.value).lower()


def test_strips_trailing_semicolon_and_comments():
    assert validate_select("SELECT 1 -- c\n;") == "SELECT 1"


def test_param_names_ignore_strings_and_casts():
    assert param_names("SELECT ':nope', a::int FROM t WHERE b = :b AND c = :c") == ["b", "c"]


def test_to_pyformat():
    assert to_pyformat("SELECT '%x', a FROM t WHERE b = :b AND c LIKE 'a%'") == \
        "SELECT '%%x', a FROM t WHERE b = %(b)s AND c LIKE 'a%%'"
