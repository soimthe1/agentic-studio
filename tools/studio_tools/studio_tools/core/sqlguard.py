"""Read-only SQL validation (defence in depth; the real boundary is a read-only login + read-only transaction).

The text is tokenised so that keywords inside string literals, quoted identifiers and comments neither trigger
nor hide a rejection. Only a single SELECT / WITH statement passes.
"""

from __future__ import annotations

import re

from .errors import NotAllowed

# Statement-level commands are already excluded by "single statement starting with SELECT/WITH"; this list
# covers what can still hide INSIDE such a statement (data-modifying CTEs, SELECT INTO, side-effect functions).
_FORBIDDEN_WORDS = {
    "insert", "update", "delete", "merge", "into", "drop", "alter", "create", "truncate", "grant", "revoke",
    "exec", "execute", "declare", "set", "begin", "commit", "rollback", "waitfor",
    "openrowset", "openquery", "opendatasource", "openxml",
    # dangerous built-ins (postgres)
    "pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file", "lo_import", "lo_export",
    "dblink", "dblink_exec", "pg_terminate_backend", "pg_cancel_backend", "set_config", "nextval", "setval",
    "pg_reload_conf", "pg_rotate_logfile", "query_to_xml",
}
# ClickHouse table functions that reach files, URLs, other servers or run programs.
_FORBIDDEN_CALLS = {"url", "file", "s3", "s3cluster", "gcs", "azureblobstorage", "hdfs", "remote", "remotesecure",
                    "mysql", "postgresql", "jdbc", "odbc", "mongodb", "redis", "executable", "input", "sqlite",
                    "deltalake", "hudi", "iceberg", "urlcluster", "filecluster"}
_FORBIDDEN_PREFIX = re.compile(r"^(xp_|sp_)", re.I)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def tokenize(sql: str) -> list[tuple[str, str]]:
    """Split into (kind, text) with kinds: code, string, ident, comment."""
    out: list[tuple[str, str]] = []
    i, n, buf = 0, len(sql), []

    def flush() -> None:
        if buf:
            out.append(("code", "".join(buf)))
            buf.clear()

    while i < n:
        c = sql[i]
        two = sql[i:i + 2]
        if two == "--":
            j = sql.find("\n", i)
            j = n if j < 0 else j
            flush(); out.append(("comment", sql[i:j])); i = j
        elif two == "/*":
            j = sql.find("*/", i + 2)
            if j < 0:
                raise NotAllowed("unterminated /* comment */ in SQL")
            flush(); out.append(("comment", sql[i:j + 2])); i = j + 2
        elif c in "'\"`[":
            close = {"'": "'", '"': '"', "`": "`", "[": "]"}[c]
            j = i + 1
            while True:
                k = sql.find(close, j)
                if k < 0:
                    raise NotAllowed("unterminated quoted string or identifier in SQL")
                if close != "]" and sql[k + 1:k + 2] == close:  # doubled quote escape
                    j = k + 2
                    continue
                if close == "'" and k > 0 and sql[k - 1] == "\\" and sql[k - 2:k] != "\\\\":
                    j = k + 1  # backslash escape (ClickHouse / MySQL)
                    continue
                break
            flush(); out.append(("string" if c == "'" else "ident", sql[i:k + 1])); i = k + 1
        elif c == "$":
            m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if m:  # postgres dollar-quoted string
                tag = m.group(0)
                k = sql.find(tag, i + len(tag))
                if k < 0:
                    raise NotAllowed("unterminated dollar-quoted string in SQL")
                flush(); out.append(("string", sql[i:k + len(tag)])); i = k + len(tag)
            else:
                buf.append(c); i += 1
        else:
            buf.append(c); i += 1
    flush()
    return out


def validate_select(sql: str) -> str:
    """Return the statement (without a trailing ';') if it is a single read-only SELECT/WITH, else raise."""
    if not sql or not sql.strip():
        raise NotAllowed("empty SQL")
    tokens = tokenize(sql)
    code = " ".join(t for k, t in tokens if k == "code")
    body = code.strip().rstrip(";").strip()
    if ";" in body:
        raise NotAllowed("only a single SQL statement is allowed")
    first = _WORD.search(body.lstrip("( \t\r\n"))
    if not first or first.group(0).lower() not in ("select", "with"):
        raise NotAllowed("only SELECT or WITH ... SELECT queries are allowed")
    for m in _WORD.finditer(code):
        w = m.group(0).lower()
        if w in _FORBIDDEN_WORDS or _FORBIDDEN_PREFIX.match(w):
            raise NotAllowed(f"keyword or function '{m.group(0)}' is not allowed in a read-only query")
        if w in _FORBIDDEN_CALLS and code[m.end():].lstrip().startswith("("):
            raise NotAllowed(f"table function '{m.group(0)}()' is not allowed")
    # Rebuild without trailing semicolons, keeping comments out of what is sent.
    text = "".join(t for k, t in tokens if k != "comment").strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return text


_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")


def param_names(sql: str) -> list[str]:
    names: list[str] = []
    for kind, text in tokenize(sql):
        if kind == "code":
            names += [m.group(1) for m in _PARAM.finditer(text)]
    return names


def to_pyformat(sql: str) -> str:
    """':name' -> '%(name)s' outside literals (ClickHouse client-side binding); literal % doubled."""
    parts = []
    for kind, text in tokenize(sql):
        if kind == "code":
            text = text.replace("%", "%%")
            text = _PARAM.sub(lambda m: f"%({m.group(1)})s", text)
        elif kind in ("string", "ident"):
            text = text.replace("%", "%%")
        parts.append(text)
    return "".join(parts)


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def check_identifier(name: str, what: str = "identifier") -> str:
    if not isinstance(name, str) or not _IDENT.match(name):
        raise NotAllowed(f"invalid {what} '{name}'")
    return name
