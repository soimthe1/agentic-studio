"""Agent Studio's own tables in the existing PostgreSQL (schema from config app.database.schema).

designs: the smart-contract conversations (drafts). One row per design; `state` holds the conversation,
the current plain agent spec and the preferences card. Owner = the engine user id of the person (designs
are private to their owner). Created on first use (idempotent).
"""

from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from agent_studio import settings


@lru_cache(maxsize=1)
def _conninfo() -> tuple[str, str]:
    db = settings.load()["app"]["database"]
    conninfo = psycopg.conninfo.make_conninfo(host=db["host"], port=db["port"], dbname=db["name"], user=db["user"],
                                              password=settings.secret(db["password_env"]), connect_timeout=10)
    schema = db["schema"]
    if not schema.replace("_", "").isalnum():
        raise SystemExit(f"app.database.schema must be a plain identifier, got {schema!r}")
    return conninfo, schema


_ready = False
_local = threading.local()   # one open connection per worker thread, reused (opening one costs a round trip + auth)


@contextmanager
def connect():
    """The thread's open connection (reconnects when it broke); tables are created on first use."""
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed or conn.broken:
        conn = _open()
        _local.conn = conn
    try:
        yield conn
    except psycopg.OperationalError:
        _local.conn = None            # the server dropped it: the next call opens a fresh one
        conn.close()
        raise


def _open():
    global _ready
    conninfo, schema = _conninfo()
    conn = psycopg.connect(conninfo, row_factory=dict_row, autocommit=True)
    if True:
        if not _ready:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.designs (
                    id uuid PRIMARY KEY,
                    owner text NOT NULL,
                    title text NOT NULL DEFAULT '',
                    status text NOT NULL DEFAULT 'draft',      -- draft | created
                    agent_id text,
                    state jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now())""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS designs_owner ON {schema}.designs (owner, updated_at DESC)")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.people (
                    username text PRIMARY KEY,
                    role text NOT NULL,
                    signed_in_at timestamptz NOT NULL DEFAULT now())""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.agent_life (
                    agent_id text PRIMARY KEY,
                    owner text NOT NULL,
                    state text NOT NULL DEFAULT 'built',      -- built | live | paused | retired
                    live_version int,
                    updated_at timestamptz NOT NULL DEFAULT now())""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.agent_versions (
                    agent_id text NOT NULL,
                    version int NOT NULL,
                    definition jsonb NOT NULL,
                    note text NOT NULL DEFAULT '',
                    created_by text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (agent_id, version))""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.tool_requests (
                    id uuid PRIMARY KEY,
                    owner text NOT NULL,
                    tool_id text NOT NULL,
                    status text NOT NULL DEFAULT 'draft',      -- draft | approved | rejected | removed
                    spec jsonb NOT NULL,
                    decided_by text,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now())""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.skills (
                    id uuid PRIMARY KEY,
                    owner text NOT NULL,
                    skill_id text NOT NULL,
                    status text NOT NULL DEFAULT 'draft',      -- draft | approved | rejected | removed (each row = one version)
                    spec jsonb NOT NULL,
                    decided_by text,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now())""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.activity (
                    id bigserial PRIMARY KEY,
                    at timestamptz NOT NULL DEFAULT now(),
                    who text NOT NULL,
                    action text NOT NULL,
                    target text NOT NULL DEFAULT '',
                    detail text NOT NULL DEFAULT '')""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.feedback (
                    id bigserial PRIMARY KEY,
                    at timestamptz NOT NULL DEFAULT now(),
                    who text NOT NULL,
                    agent_id text NOT NULL,
                    session_id text NOT NULL DEFAULT '',
                    good boolean NOT NULL,
                    answer text NOT NULL DEFAULT '',
                    correction text NOT NULL DEFAULT '',
                    applied boolean NOT NULL DEFAULT false)""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.agent_notes (
                    id bigserial PRIMARY KEY,
                    at timestamptz NOT NULL DEFAULT now(),
                    agent_id text NOT NULL,
                    note text NOT NULL)""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.eval_cases (
                    id bigserial PRIMARY KEY,
                    at timestamptz NOT NULL DEFAULT now(),
                    agent_id text NOT NULL,
                    question text NOT NULL,
                    expect text NOT NULL,
                    last jsonb)""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.accounts (
                    username text PRIMARY KEY,
                    name text NOT NULL DEFAULT '',
                    pw_hash text NOT NULL,
                    role text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now())""")
            for col in ("owner_name text", "alerted_at timestamptz", "seen_until timestamptz", "last_check jsonb",   # watches
                        "shared boolean NOT NULL DEFAULT false"):
                conn.execute(f"ALTER TABLE {schema}.agent_life ADD COLUMN IF NOT EXISTS {col}")
            _ready = True
        conn.execute(f"SET search_path TO {schema}")
    return conn


def _row(r: dict | None) -> dict | None:
    if r is None:
        return None
    out = dict(r)
    out["id"] = str(out["id"])
    for k in ("created_at", "updated_at"):
        out[k] = out[k].isoformat()
    return out


def create_design(owner: str, title: str, state: dict) -> dict:
    with connect() as c:
        return _row(c.execute("INSERT INTO designs (id, owner, title, state) VALUES (%s, %s, %s, %s) RETURNING *",
                              (uuid.uuid4(), owner, title[:200], Jsonb(state))).fetchone())


def get_design(owner: str, design_id: str) -> dict | None:
    try:
        uuid.UUID(design_id)
    except ValueError:
        return None
    with connect() as c:
        return _row(c.execute("SELECT * FROM designs WHERE id = %s AND owner = %s", (design_id, owner)).fetchone())


def save_design(owner: str, design_id: str, *, state: dict | None = None, title: str | None = None,
                status: str | None = None, agent_id: str | None = None) -> dict | None:
    sets, args = ["updated_at = %s"], [datetime.now(timezone.utc)]
    for col, val in (("state", Jsonb(state) if state is not None else None), ("title", title[:200] if title else None),
                     ("status", status), ("agent_id", agent_id)):
        if val is not None:
            sets.append(f"{col} = %s")
            args.append(val)
    with connect() as c:
        return _row(c.execute(f"UPDATE designs SET {', '.join(sets)} WHERE id = %s AND owner = %s RETURNING *",
                              (*args, design_id, owner)).fetchone())


def prefs_by_agent(owner: str) -> dict[str, dict]:
    """agent id -> the preferences of the newest draft it was made from (one query)."""
    with connect() as c:
        rows = c.execute("SELECT DISTINCT ON (agent_id) agent_id, state->'prefs' AS prefs FROM designs "
                         "WHERE owner = %s AND agent_id IS NOT NULL ORDER BY agent_id, updated_at DESC", (owner,)).fetchall()
    return {r["agent_id"]: r["prefs"] or {} for r in rows}


def list_designs(owner: str, limit: int = 50) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT id, owner, title, status, agent_id, created_at, updated_at FROM designs "
                         "WHERE owner = %s ORDER BY updated_at DESC LIMIT %s", (owner, limit)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["id"] = str(r["id"])
        r["created_at"], r["updated_at"] = r["created_at"].isoformat(), r["updated_at"].isoformat()
        out.append(r)
    return out


def prefs_of_agent(agent_id: str) -> dict:
    """The agreed choices of the draft an agent was made from (any owner), {} when made elsewhere."""
    with connect() as c:
        r = c.execute("SELECT state FROM designs WHERE agent_id = %s ORDER BY updated_at DESC LIMIT 1", (agent_id,)).fetchone()
    return ((r or {}).get("state") or {}).get("prefs") or {}


def delete_design(owner: str, design_id: str) -> bool:
    try:
        uuid.UUID(design_id)
    except ValueError:
        return False
    with connect() as c:
        return c.execute("DELETE FROM designs WHERE id = %s AND owner = %s", (design_id, owner)).rowcount > 0


# ---------------------------------------------------------------- tool requests (drafts until an admin decides)
def create_tool_draft(owner: str, tool_id: str, spec: dict) -> dict:
    with connect() as c:
        return _row(c.execute("INSERT INTO tool_requests (id, owner, tool_id, spec) VALUES (%s, %s, %s, %s) RETURNING *",
                              (uuid.uuid4(), owner, tool_id, Jsonb(spec))).fetchone())


def get_tool_draft(request_id: str) -> dict | None:
    try:
        uuid.UUID(request_id)
    except ValueError:
        return None
    with connect() as c:
        return _row(c.execute("SELECT * FROM tool_requests WHERE id = %s", (request_id,)).fetchone())


def list_tool_drafts(owner: str | None) -> list[dict]:
    """owner=None: everyone's (administrators)."""
    with connect() as c:
        rows = (c.execute("SELECT * FROM tool_requests ORDER BY updated_at DESC LIMIT 200").fetchall() if owner is None else
                c.execute("SELECT * FROM tool_requests WHERE owner = %s ORDER BY updated_at DESC LIMIT 200", (owner,)).fetchall())
    return [_row(r) for r in rows]


def update_tool_draft_spec(request_id: str, spec: dict) -> None:
    with connect() as c:
        c.execute("UPDATE tool_requests SET spec = %s, updated_at = now() WHERE id = %s", (Jsonb(spec), request_id))


def set_tool_draft_status(request_id: str, status: str, decided_by: str) -> dict | None:
    with connect() as c:
        return _row(c.execute("UPDATE tool_requests SET status = %s, decided_by = %s, updated_at = now() WHERE id = %s "
                              "RETURNING *", (status, decided_by, request_id)).fetchone())


# ---------------------------------------------------------------- skills (know-how cards; drafts until an admin decides)
def create_skill(owner: str, skill_id: str, spec: dict) -> dict:
    with connect() as c:
        return _row(c.execute("INSERT INTO skills (id, owner, skill_id, spec) VALUES (%s, %s, %s, %s) RETURNING *",
                              (uuid.uuid4(), owner, skill_id, Jsonb(spec))).fetchone())


def get_skill(row_id: str) -> dict | None:
    try:
        uuid.UUID(row_id)
    except ValueError:
        return None
    with connect() as c:
        return _row(c.execute("SELECT * FROM skills WHERE id = %s", (row_id,)).fetchone())


def list_skills() -> list[dict]:
    with connect() as c:
        return [_row(r) for r in c.execute("SELECT * FROM skills ORDER BY created_at LIMIT 1000").fetchall()]


def set_skill_status(row_id: str, status: str, decided_by: str) -> dict | None:
    with connect() as c:
        return _row(c.execute("UPDATE skills SET status = %s, decided_by = %s, updated_at = now() WHERE id = %s "
                              "RETURNING *", (status, decided_by, row_id)).fetchone())


# ---------------------------------------------------------------- feedback on answers (thumbs + corrections)
def add_feedback(who: str, agent_id: str, session_id: str, good: bool, answer: str, correction: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO feedback (who, agent_id, session_id, good, answer, correction) VALUES (%s, %s, %s, %s, %s, %s)",
                  (who, agent_id, session_id, good, answer[:2000], correction[:1000]))


def feedback_stats(agent_ids: list[str]) -> dict[str, dict]:
    """agent_id -> {good, bad, corrections_waiting}"""
    if not agent_ids:
        return {}
    with connect() as c:
        rows = c.execute("SELECT agent_id, count(*) FILTER (WHERE good) AS good, count(*) FILTER (WHERE NOT good) AS bad, "
                         "count(*) FILTER (WHERE correction <> '' AND NOT applied) AS waiting FROM feedback "
                         "WHERE agent_id = ANY(%s) GROUP BY agent_id", (agent_ids,)).fetchall()
    return {r["agent_id"]: {"good": r["good"], "bad": r["bad"], "corrections_waiting": r["waiting"]} for r in rows}


def corrections(agent_id: str, waiting_only: bool = False) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM feedback WHERE agent_id = %s AND correction <> '' " + ("AND NOT applied " if waiting_only else "")
                         + "ORDER BY at", (agent_id,)).fetchall()
    return [{**dict(r), "at": r["at"].isoformat()} for r in rows]


def mark_corrections_applied(agent_id: str) -> None:
    with connect() as c:
        c.execute("UPDATE feedback SET applied = true WHERE agent_id = %s AND correction <> ''", (agent_id,))


# ---------------------------------------------------------------- activity log (who did what, when)
def add_activity(who: str, action: str, target: str = "", detail: str = "") -> None:
    with connect() as c:
        c.execute("INSERT INTO activity (who, action, target, detail) VALUES (%s, %s, %s, %s)", (who, action, target, detail))


def list_activity(q: str = "", limit: int = 200) -> list[dict]:
    with connect() as c:
        if q:
            like = f"%{q}%"
            rows = c.execute("SELECT * FROM activity WHERE who ILIKE %s OR action ILIKE %s OR target ILIKE %s OR detail ILIKE %s "
                             "ORDER BY at DESC LIMIT %s", (like, like, like, like, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM activity ORDER BY at DESC LIMIT %s", (limit,)).fetchall()
    return [{**dict(r), "at": r["at"].isoformat()} for r in rows]


# ---------------------------------------------------------------- agent lifecycle (built -> live -> paused -> retired)
def life(agent_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM agent_life WHERE agent_id = %s", (agent_id,)).fetchone()
    return {**r, "updated_at": r["updated_at"].isoformat()} if r else None


def lives(owner: str) -> dict[str, dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM agent_life WHERE owner = %s", (owner,)).fetchall()
    return {r["agent_id"]: {**r, "updated_at": r["updated_at"].isoformat()} for r in rows}


def set_life(agent_id: str, owner: str, state: str, live_version: int | None = None, owner_name: str | None = None) -> None:
    with connect() as c:
        c.execute("INSERT INTO agent_life (agent_id, owner, state, live_version, owner_name) VALUES (%s, %s, %s, %s, %s) "
                  "ON CONFLICT (agent_id) DO UPDATE SET state = EXCLUDED.state, "
                  "live_version = COALESCE(EXCLUDED.live_version, agent_life.live_version), "
                  "owner_name = COALESCE(EXCLUDED.owner_name, agent_life.owner_name), updated_at = now()",
                  (agent_id, owner, state, live_version, owner_name))


def live_agents() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM agent_life WHERE state = 'live'").fetchall()]


def mark_alerted(agent_id: str) -> None:
    with connect() as c:
        c.execute("UPDATE agent_life SET alerted_at = now() WHERE agent_id = %s", (agent_id,))


def design_of_agent(agent_id: str) -> dict:
    """The state (plan, prefs) of the draft an agent was made from, {} when made elsewhere."""
    with connect() as c:
        r = c.execute("SELECT state FROM designs WHERE agent_id = %s ORDER BY updated_at DESC LIMIT 1", (agent_id,)).fetchone()
    return (r or {}).get("state") or {}


def set_last_check(agent_id: str, check: dict) -> None:
    with connect() as c:
        c.execute("UPDATE agent_life SET last_check = %s WHERE agent_id = %s", (Jsonb(check), agent_id))


def last_checks() -> dict[str, dict]:
    with connect() as c:
        return {r["agent_id"]: r["last_check"] for r in
                c.execute("SELECT agent_id, last_check FROM agent_life WHERE last_check IS NOT NULL").fetchall()}


def set_seen(agent_id: str, until) -> None:
    with connect() as c:
        c.execute("UPDATE agent_life SET seen_until = %s WHERE agent_id = %s", (until, agent_id))


def add_version(agent_id: str, definition: dict, note: str, by: str) -> int:
    with connect() as c:
        n = c.execute("SELECT COALESCE(MAX(version), 0) + 1 AS n FROM agent_versions WHERE agent_id = %s", (agent_id,)).fetchone()["n"]
        c.execute("INSERT INTO agent_versions (agent_id, version, definition, note, created_by) VALUES (%s, %s, %s, %s, %s)",
                  (agent_id, n, Jsonb(definition), note[:300], by))
    return n


def versions(agent_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT agent_id, version, note, created_by, created_at FROM agent_versions WHERE agent_id = %s "
                         "ORDER BY version DESC", (agent_id,)).fetchall()
    return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]


def version(agent_id: str, n: int) -> dict | None:
    with connect() as c:
        return c.execute("SELECT * FROM agent_versions WHERE agent_id = %s AND version = %s", (agent_id, n)).fetchone()


def set_person(username: str, role: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO people (username, role) VALUES (%s, %s) ON CONFLICT (username) "
                  "DO UPDATE SET role = EXCLUDED.role, signed_in_at = now()", (username.lower(), role))


def person_role(username: str) -> str | None:
    with connect() as c:
        r = c.execute("SELECT role FROM people WHERE username = %s", (username.lower(),)).fetchone()
    return r["role"] if r else None


def drop_person(username: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM people WHERE username = %s", (username.lower(),))


# ---------------------------------------------------------------- local accounts (sign-in without a directory)
def accounts() -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT username, name, role, created_at FROM accounts ORDER BY username").fetchall()
    return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]


def account(username: str) -> dict | None:
    with connect() as c:
        return c.execute("SELECT * FROM accounts WHERE username = %s", (username.lower(),)).fetchone()


def add_account(username: str, name: str, pw_hash: str, role: str, only_if_none: bool = False) -> bool:
    """False when the name is taken (or, with only_if_none, when any account exists: first-run race)."""
    guard = "WHERE NOT EXISTS (SELECT 1 FROM accounts)" if only_if_none else ""
    with connect() as c:
        r = c.execute(f"INSERT INTO accounts (username, name, pw_hash, role) SELECT %s, %s, %s, %s {guard} "
                      "ON CONFLICT (username) DO NOTHING RETURNING username",
                      (username.lower(), name, pw_hash, role)).fetchone()
    return r is not None


def change_account(username: str, role: str | None = None, pw_hash: str | None = None) -> None:
    with connect() as c:
        if role:
            c.execute("UPDATE accounts SET role = %s WHERE username = %s", (role, username.lower()))
        if pw_hash:
            c.execute("UPDATE accounts SET pw_hash = %s WHERE username = %s", (pw_hash, username.lower()))


def drop_account(username: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM accounts WHERE username = %s", (username.lower(),))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------- sharing (anyone signed in may chat with a live agent)
def set_shared(agent_id: str, on: bool) -> None:
    with connect() as c:
        c.execute("UPDATE agent_life SET shared = %s WHERE agent_id = %s", (on, agent_id))


def shared_agents() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM agent_life WHERE state = 'live' AND shared").fetchall()]


# ---------------------------------------------------------------- notes an agent keeps between runs
NOTES_KEPT = 10


def notes(agent_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM agent_notes WHERE agent_id = %s ORDER BY at", (agent_id,)).fetchall()
    return [{"id": r["id"], "at": r["at"].isoformat(), "note": r["note"]} for r in rows]


def add_notes(agent_id: str, new: list[str]) -> None:
    """Add notes (exact repeats skipped) and keep only the newest NOTES_KEPT."""
    with connect() as c:
        have = {r["note"] for r in c.execute("SELECT note FROM agent_notes WHERE agent_id = %s", (agent_id,)).fetchall()}
        for n in new:
            if n not in have:
                c.execute("INSERT INTO agent_notes (agent_id, note) VALUES (%s, %s)", (agent_id, n[:300]))
        c.execute("DELETE FROM agent_notes WHERE agent_id = %s AND id NOT IN (SELECT id FROM agent_notes WHERE agent_id = %s "
                  "ORDER BY at DESC LIMIT %s)", (agent_id, agent_id, NOTES_KEPT))


def delete_note(agent_id: str, note_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM agent_notes WHERE agent_id = %s AND id = %s", (agent_id, note_id))


# ---------------------------------------------------------------- test questions (evaluation set) per agent
def eval_cases(agent_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM eval_cases WHERE agent_id = %s ORDER BY at", (agent_id,)).fetchall()
    return [{"id": r["id"], "question": r["question"], "expect": r["expect"], "last": r["last"]} for r in rows]


def add_eval_case(agent_id: str, question: str, expect: str) -> int:
    with connect() as c:
        return c.execute("INSERT INTO eval_cases (agent_id, question, expect) VALUES (%s, %s, %s) RETURNING id",
                         (agent_id, question[:2000], expect[:2000])).fetchone()["id"]


def delete_eval_case(agent_id: str, case_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM eval_cases WHERE agent_id = %s AND id = %s", (agent_id, case_id))


def set_eval_result(case_id: int, result: dict) -> None:
    with connect() as c:
        c.execute("UPDATE eval_cases SET last = %s WHERE id = %s", (Jsonb(result), case_id))


def forget_agent(agent_id: str) -> None:
    """An agent deleted in Agent Studio leaves no live/shared record, notes or test questions behind."""
    with connect() as c:
        for table in ("agent_life", "agent_notes", "eval_cases"):
            c.execute(f"DELETE FROM {table} WHERE agent_id = %s", (agent_id,))


def agents_using(cap_ids: list[str]) -> list[dict]:
    """Agents (anyone's) whose agreed abilities include any of these capabilities: [{agent_id, name, owner}]."""
    if not cap_ids:
        return []
    with connect() as c:
        rows = c.execute("SELECT DISTINCT ON (agent_id) agent_id, owner, coalesce(state->'prefs'->>'name', title) AS name "
                         "FROM designs WHERE agent_id IS NOT NULL AND (state->'prefs'->'capabilities') ?| %s "
                         "ORDER BY agent_id, updated_at DESC", (cap_ids,)).fetchall()
    return [dict(r) for r in rows]
