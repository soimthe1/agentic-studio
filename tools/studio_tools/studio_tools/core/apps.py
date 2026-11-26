"""Registered apps: generic read connector (app_query) and approval-gated actions (app_action).

Each app (tools.yaml ``apps:`` or an approved contract) declares its operations and actions in YAML: path templates
with ``{target}`` or named values, allowed query filters, optional defaults. Options for systems shaped differently:
  * ``instances: {name: {base_url, ...}}`` - one deployment per target (e.g. one monitor per server);
  * ``resolve: {placeholder, list_path, match, id, label}`` - look a target's id up by its name;
  * ``extra_headers: [{name, value_env}]`` - secret headers some endpoints need.
The LLM picks app + operation + target; it never supplies a URL or host.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from . import http as H
from .config import secret
from .errors import ConfigError, NotAllowed, UpstreamError
from .spec import approval_gate

MAX_JSON_CHARS = 12_000   # one result must leave room in a 32k-token model for several calls
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


def segment(value: Any, what: str) -> str:
    if value is None or not _SAFE_SEGMENT.match(str(value)):
        raise NotAllowed(f"invalid {what} '{value}'")
    return str(value)


def bounded(data: Any, limit: int | None = None) -> Any:
    """Keep responses LLM-sized: cap list length and total JSON size."""
    out: Any = data
    if limit and isinstance(data, list) and len(data) > limit:
        out = {"items": data[:limit], "truncated": True, "total": len(data)}
    text = json.dumps(out, ensure_ascii=False, default=str)
    if len(text) > MAX_JSON_CHARS:
        # Too big: first keep every item but drop the bulk inside them (long series such as forecast points, long
        # texts) and merge identical items - the agent then still sees ALL items, which is what totals need.
        for level in (1, 2, 3, 4):
            small = _as_tables(_compact(out, 3)) if level == 4 else _compact(out, level)
            text = json.dumps(small, ensure_ascii=False, default=str)
            if len(text) <= MAX_JSON_CHARS:
                return small
    if len(text) > MAX_JSON_CHARS:
        # the note steers the agent to ask for less, not to fetch the same big answer again
        return {"truncated": True, "shown_chars": MAX_JSON_CHARS, "total_chars": len(text),
                "note": "Only the first part is shown. Use what is shown - do not stop or fetch the same thing again - "
                        "and say in your answer that the list was longer. For exact totals use a summary operation, or "
                        "ask for fewer items next time (filters, a smaller limit).",
                "preview": text[:MAX_JSON_CHARS]}
    return out


def _compact(data: Any, level: int, depth: int = 0) -> Any:
    """Shrink an answer without dropping items (totals need every item). Level 1: inner lists keep 1 entry (+ how many
    there were), texts <= 200 chars. Level 2: items keep only their plain fields (no nested details), no empty ones.
    Level 3: also texts <= 60 chars and no item ids. Identical items are merged with a count."""
    cut = 200 if level < 3 else 60
    if isinstance(data, str):
        return data if len(data) <= cut else data[:cut] + "…"
    if level >= 3 and isinstance(data, float):
        return float(f"{data:.3g}")
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if level >= 2 and depth >= 2 and isinstance(v, (dict, list)):
                continue
            if level >= 2 and v in (None, "", [], {}):
                continue
            if level >= 3 and depth >= 2 and k == "id":   # an item's own id; references to other things stay
                continue
            out[k] = _compact(v, level, depth + 1)
        return out
    if isinstance(data, list):
        if depth >= 2 and len(data) > 1:
            return [_compact(data[0], level, depth + 1), f"(+{len(data) - 1} more)"]
        merged: dict[str, Any] = {}
        for x in data:
            item = _compact(x, level, depth + 1)
            key = json.dumps(item, sort_keys=True, default=str)
            if key in merged:
                if isinstance(merged[key], dict):
                    merged[key]["_same_items"] = merged[key].get("_same_items", 1) + 1
            else:
                merged[key] = dict(item) if isinstance(item, dict) else item
        return list(merged.values())
    return data


def _as_tables(data: Any) -> Any:
    """Lists of records -> {columns, rows}: the field names are written once instead of once per item."""
    if isinstance(data, dict):
        return {k: _as_tables(v) for k, v in data.items()}
    if isinstance(data, list) and len(data) > 2 and all(isinstance(x, dict) for x in data):
        cols: list[str] = []
        for x in data:
            cols += [k for k in x if k not in cols]
        same = {k: data[0].get(k) for k in cols if all(x.get(k) == data[0].get(k) for x in data)}
        cols = [k for k in cols if k not in same]
        return {**({"same_for_all_rows": same} if same else {}), "columns": cols,
                "rows": [[x.get(k) for k in cols] for x in data]}
    return data


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "")}


def operations(app: dict[str, Any]) -> dict[str, dict[str, Any]]:
    kind = app.get("type", "generic")
    if kind != "generic":
        raise ConfigError(f"app '{app.get('_name')}' has unknown type '{kind}' (only 'generic': operations in its contract)")
    return dict(app.get("operations") or {})


def actions(app: dict[str, Any], registry: str = "actions") -> dict[str, dict[str, Any]]:
    if registry == "records":  # record_write targets
        return dict(app.get("records") or {})
    return dict(app.get("actions") or {})


# ------------------------------------------------------------------------------------------------ targets


def _endpoint(app: dict[str, Any], target: str | None) -> dict[str, Any]:
    """Return the connection dict (base_url + auth) to call. An app with `instances` (one deployment per target,
    e.g. one monitor per server) picks the deployment by target."""
    if app.get("instances"):
        instances = app.get("instances") or {}
        if not target:
            raise NotAllowed(f"app '{app['_name']}' needs a target (one of: {', '.join(sorted(instances))})")
        if target not in instances:
            raise NotAllowed(f"'{target}' is not a registered instance of '{app['_name']}' "
                             f"(registered: {', '.join(sorted(instances)) or 'none'})")
        inst = instances[target] or {}
        return {**{k: v for k, v in app.items() if k != "instances"}, **inst, "_name": f"{app['_name']}:{target}"}
    allowed = {str(t).lower() for t in app.get("allowed_targets") or []}
    if target and allowed and target.lower() not in allowed:
        raise NotAllowed(f"target '{target}' is not in the allowlist of app '{app['_name']}'")
    return app


def _auth(conn: dict[str, Any], http: httpx.Client, as_user: str | None) -> dict[str, str]:
    auth = conn.get("auth") or {"type": "none"}
    kind = str(auth.get("type", "none")).lower()
    holder = {**auth, "_name": conn.get("_name")}
    headers: dict[str, str] = {}
    if kind == "ad_login":  # directory sign-in -> token or session (the saved account)
        bare = {**conn, "auth": None}
        resp = H.request(bare, "POST", auth.get("login_path", "/api/v1/auth/login"), http=http,
                         json_body={"username": auth.get("username"), "password": secret(holder, "password")})
        if resp.status_code in (401, 403):
            raise UpstreamError(f"sign-in to '{conn.get('_name')}' failed: the saved user id or password was refused. "
                                "Update the password on the Tools page.")
        if resp.status_code >= 300:
            raise UpstreamError(f"sign-in to '{conn.get('_name')}' failed (HTTP {resp.status_code})")
        try:
            body = resp.json() or {}
        except ValueError:
            body = {}
        fields = [auth["token_field"]] if auth.get("token_field") else ["access_token", "token", "jwt", "id_token"]
        token = next((body.get(f) for f in fields if isinstance(body, dict) and body.get(f)), None)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif not http.cookies:   # no token and no session cookie: nothing to sign in with
            raise UpstreamError(f"sign-in to '{conn.get('_name')}' returned no token or session")
    elif kind == "service_key":  # service key header (+ the requesting user, where the system supports on-behalf-of)
        headers[auth.get("header", "X-Service-Key")] = secret(holder, "token")
        obo = auth.get("on_behalf_of_header")
        if obo:
            if not as_user:
                raise NotAllowed(f"app '{conn.get('_name')}' acts on behalf of the requesting user, "
                                 "but no acting user was provided to the tool")
            headers[obo] = as_user
    else:
        headers.update(H.auth_headers(conn))
    for h in conn.get("extra_headers") or []:   # [{name, env}]: extra secret headers some endpoints need
        headers[h["name"]] = secret({**h, "_name": conn.get("_name")}, "value") if h.get("value_env") else ""
    return headers


def _fill_path(path: str, target: str | None, args: dict[str, Any]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key == "target":
            if not target:
                raise NotAllowed("this operation needs a target")
            return segment(target, "target")
        if key in args.get("__resolve_keys", ()):
            return m.group(0)  # resolved later (looked up by name)
        if key not in args:
            raise NotAllowed(f"this operation needs '{key}'")
        return segment(args.pop(key), key)
    return re.sub(r"\{([a-z_]+)\}", repl, path)


def _resolve(app: dict[str, Any], conn, http, headers, target: str) -> str:
    """Look a target's id up by its name (contract `resolve`: list_path, match fields, id field)."""
    r = app.get("resolve") or {}
    items = H.body_of(H.request({**conn, "auth": None}, "GET", r["list_path"], http=http, headers=headers))
    for n in items if isinstance(items, list) else []:
        if target.lower() in {str(n.get(f) or "").lower() for f in r.get("match") or ["name"]}:
            return segment(n.get(r.get("id", "id")), "id")
    raise UpstreamError(f"'{target}' is not a registered {r.get('label', 'target')} of '{app.get('_name')}'")


def source(app: str, op: str, target: str | None, as_user: str | None, mock: bool = False) -> dict[str, Any]:
    out = {"app": app, "operation": op, "target": target, "as_user": as_user}
    if mock:
        out["mock"] = True
    return out


# ---------------------------------------------------------------------------------------------- app_query


def query(app: dict[str, Any], operation: str, *, target: str | None = None, filters: dict[str, Any] | None = None,
          limit: int = 50, as_user: str | None = None, timeout_s: float | None = None) -> Any:
    ops = operations(app)
    if operation not in ops:
        raise NotAllowed(f"unknown operation '{operation}' for app '{app['_name']}' (one of: {', '.join(ops) or 'none'})")
    op = ops[operation]
    method = str(op.get("method", "GET")).upper()
    if method != "GET" and not op.get("read"):
        raise NotAllowed(f"operation '{operation}' is not declared read-only")
    target = (target or "").strip() or None
    if target:
        segment(target, "target")
    conn = _endpoint(app, target)
    limit = max(1, min(int(limit or 50), 200))
    args = dict(filters or {})
    rkey = (app.get("resolve") or {}).get("placeholder")
    for k, v in args.items():
        segment(k, "filter name")
        if isinstance(v, (dict, list)):
            raise NotAllowed(f"filter '{k}' must be a scalar")
    path = _fill_path(op["path"], target, {**args, "__resolve_keys": (rkey,) if rkey else ()})
    tmode = op.get("target", "path" if "{target}" in op["path"] else None)
    allowed_q = list(op.get("query") or [])
    params = _clean({k: args.get(k) for k in allowed_q})
    if "limit" in allowed_q:
        params["limit"] = limit
    for k, v in (op.get("defaults") or {}).items():   # contract defaults for filters the model leaves out
        params.setdefault(k, v)
    if tmode and tmode.startswith("query:") and target:
        params[tmode.split(":", 1)[1]] = target
    body = None
    if method == "POST":
        body = _clean({k: args.get(k) for k in op.get("body") or []})
        if op.get("target_field") and target:
            body[op["target_field"]] = target
    if rkey and "{" + rkey + "}" in path and not target:
        raise NotAllowed(f"operation '{operation}' needs a target ({(app.get('resolve') or {}).get('label', 'name')})")
    bare = {**conn, "auth": None}
    with H.client(conn, timeout_s) as http:
        headers = _auth(conn, http, as_user)
        if rkey and "{" + rkey + "}" in path:
            path = path.replace("{" + rkey + "}", _resolve(app, conn, http, headers, target))
        resp = H.request(bare, method, path, params=params or None, json_body=body, headers=headers, http=http,
                         retries=None if method == "GET" else 0)
        if resp.status_code == 404 and op.get("optional"):
            raise UpstreamError(f"operation '{operation}' is switched off on this system")
        data = H.body_of(resp)
    if tmode == "filter" and target and isinstance(data, list):
        needle = target.lower()  # the system has no filter for it: keep items that mention the target (best effort)
        data = [i for i in data if needle in json.dumps(i, default=str).lower()]
    return bounded(data, limit)


# --------------------------------------------------------------------------------------------- app_action


def action(app: dict[str, Any], name: str, *, target: str | None, params: dict[str, Any] | None, reason: str,
           approved: bool, dry_run: bool, as_user: str | None = None, timeout_s: float | None = None,
           registry: str = "actions") -> dict[str, Any]:
    """Plan, and only with approval execute, one registered action. Never retried."""
    acts = actions(app, registry)
    if name not in acts:
        raise NotAllowed(f"unknown action '{name}' for app '{app['_name']}' (registered: {', '.join(acts) or 'none'})")
    if not (reason or "").strip():
        raise NotAllowed("a reason is required for every action")
    spec = acts[name]
    target = (target or "").strip() or None
    if target:
        segment(target, "target")
    conn = _endpoint(app, target)
    args = dict(params or {})
    allowed = set(spec.get("body") or []) | set(re.findall(r"\{([a-z_]+)\}", spec["path"])) - {"target"}
    extra = set(args) - allowed
    if extra:
        raise NotAllowed(f"parameter(s) {sorted(extra)} are not accepted by action '{name}'")
    for k, v in args.items():
        if isinstance(v, (dict, list)):
            raise NotAllowed(f"parameter '{k}' must be a scalar")
    path = _fill_path(spec["path"], target, args)
    body = {**(spec.get("fixed") or {}), **_clean({k: args.get(k) for k in spec.get("body") or []})}
    if spec.get("target_field") and target:
        body[spec["target_field"]] = target
    method = str(spec.get("method", "POST")).upper()
    plan = {"method": method, "path": path, "body": body or None, "reason": reason.strip(),
            "base_url": conn.get("base_url")}
    gate = approval_gate(approved=approved, dry_run=dry_run, write_allowed=bool(app.get("allow_write")),
                         what=f"action '{name}' on '{app['_name']}'")
    if gate:
        status = "planned" if dry_run and app.get("allow_write") else (
            "pending_approval" if app.get("allow_write") else "rejected")
        return {"status": status, "reason": gate, "plan": plan}
    with H.client(conn, timeout_s) as http:
        headers = _auth(conn, http, as_user)
        resp = H.request({**conn, "auth": None}, method, path, json_body=body or None, headers=headers, http=http,
                         retries=0)
        result = H.body_of(resp)
    return {"status": "done", "plan": plan, "result": bounded(result)}
