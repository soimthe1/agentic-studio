"""New tools from a system's own contract: "I don't have a tool for this" -> "Create one?" -> a few choices -> a
reusable, parameterised tool in the repository.

1. learn   Agent Studio reads the system's published contract (OpenAPI /openapi.json, an agent-studio.yaml, or the yaml inside a
           AGENT-STUDIO.md) and lists its
           operations in plain words: reads and changes. Systems already connected are offered for reuse first.
2. draft   The person picks operations and names the tool. Stored as a draft; nothing can use it yet.
3. approve An administrator approves: Agent Studio writes one contract file <contracts_dir>/<id>.yaml with the connector
           (generic app connector, same shape as tools.yaml) and its capabilities. Agents can use it at once; changes
           still go through a human approval in every agent. A sign-in (user id + password) is entered on the
           Tools page, checked against the system at once and kept encrypted (vault.py); never in a contract file.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import capabilities, store, vault
from agent_studio import roles
from agent_studio.engine import Engine

router = APIRouter(prefix="/api/studio/v1", tags=["Tools"])

API_PATHS = ("", "/openapi.json", "/api/openapi.json", "/docs/openapi.json", "/api/v1/openapi.json")


def contract_paths() -> tuple[str, ...]:
    """Where a system's contract may be published: its OpenAPI description, then the contract files named in config
    app.contract_files (an organisation may use its own names, e.g. in config/local)."""
    from agent_studio import settings

    names = settings.load()["app"].get("contract_files") or ["agent-studio.yaml", "AGENT-STUDIO.md"]
    return API_PATHS + tuple("/" + str(n).lstrip("/") for n in names)
MD_YAML = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*$|^```ya?ml[ \t]*\r?\n(.*?)^```", re.S | re.M)


def _md_contract(text: str) -> object:
    """AGENT-STUDIO.md: prose for people, plus the contract as YAML front-matter or a ```yaml block (first one with
    `operations:` wins). Anything else in the file is ignored."""
    for m in MD_YAML.finditer(text):
        try:
            doc = yaml.safe_load(m.group(1) or m.group(2))
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and "operations" in doc:
            return doc
    return None
MAX_BYTES = 5_000_000
SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str, n: int = 40) -> str:
    return SLUG.sub("_", (text or "").lower()).strip("_")[:n] or "op"


# ------------------------------------------------------------------------------------------- learning a contract


def _fetch(url: str, verify: bool = True, why: list | None = None) -> tuple[str, object] | None:
    """The contract at url, or None; `why` collects what happened (answered / certificate / not reachable)."""
    why = why if why is not None else []
    try:
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=True, verify=verify) as c:
            r = c.get(url)
    except httpx.ConnectError as exc:
        why.append("certificate" if "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper() else "unreachable")
        return None
    except httpx.HTTPError:
        why.append("unreachable")
        return None
    why.append("answered")
    if r.status_code != 200 or len(r.content) > MAX_BYTES:
        return None
    try:
        if url.lower().endswith(".md"):
            data = _md_contract(r.text)
        elif "json" in r.headers.get("content-type", "") or url.endswith(".json"):
            data = r.json()
        else:
            data = yaml.safe_load(r.text)
    except (ValueError, yaml.YAMLError):
        return None
    return (str(r.url), data) if isinstance(data, dict) and ("paths" in data or "operations" in data) else None


def _fields(schema: dict, spec: dict) -> list[str]:
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        schema = ((spec.get("components") or {}).get("schemas") or {}).get(ref) or {}
    return list((schema.get("properties") or {}).keys())[:20]


def _from_openapi(spec: dict) -> list[dict]:
    ops = []
    for path, item in (spec.get("paths") or {}).items():
        for method, op in item.items():
            if method not in ("get", "post", "put", "patch", "delete") or not isinstance(op, dict):
                continue
            params = [p for p in (op.get("parameters") or []) + (item.get("parameters") or []) if isinstance(p, dict)]
            body = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
            ops.append({
                "id": _slug(op.get("operationId") or f"{method}_{path}"),
                "method": method.upper(), "path": path,
                "summary": (op.get("summary") or op.get("description") or f"{method.upper()} {path}").strip()[:200],
                "kind": "read" if method == "get" else "change",
                "query": [p["name"] for p in params if p.get("in") == "query"][:20],
                "path_params": [p["name"] for p in params if p.get("in") == "path"],
                "body": _fields(body, spec),
            })
    return ops


def _from_contract_yaml(doc: dict) -> list[dict]:
    """agent-studio.yaml: operations: [{id, method, path, summary, kind?, query?, body?}] - an app describing itself."""
    out = []
    for op in doc.get("operations") or []:
        if isinstance(op, dict) and op.get("path"):
            method = str(op.get("method", "GET")).upper()
            out.append({"id": _slug(op.get("id") or op["path"]), "method": method, "path": op["path"],
                        "summary": str(op.get("summary") or op["path"])[:200],
                        "kind": op.get("kind") or ("read" if method == "GET" else "change"),
                        "query": list(op.get("query") or []), "body": list(op.get("body") or []),
                        "path_params": re.findall(r"\{(\w+)\}", op["path"])})
    return out


def learn(address: str, need: str = "", trust_cert: bool = False) -> dict:
    u = urlparse(address.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise HTTPException(422, "Give the system's web address, e.g. http://server:8000")
    base = f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"
    found = None
    why: list[str] = []
    for suffix in contract_paths():
        found = _fetch(base + suffix if suffix else address.strip(), verify=not trust_cert, why=why)
        if found or (why and why[-1] != "answered" and suffix == ""):
            break
    if not found:
        if "certificate" in why:
            raise HTTPException(422, {"reason": "certificate", "text":
                "This system uses its own HTTPS certificate, which this server does not trust yet. If it is one of "
                "your organisation's systems, tick 'Trust this system's certificate' and read it again."})
        if "answered" not in why:
            raise HTTPException(404, {"reason": "unreachable", "text":
                "Nothing answered at that address. Check the address and port, and that this server can reach it."})
        raise HTTPException(404, {"reason": "no_contract", "text":
            "The system answered, but it does not publish a description of what it can do, so there is nothing to "
            "learn from. Ask its owners to switch on its API description (/openapi.json - one setting in most web "
            "frameworks) or to add a contract file. Looked for: openapi.json, " + ", ".join(p.lstrip("/") for p in contract_paths()[5:]) + "."})
    url, doc = found
    ops = _from_openapi(doc) if "paths" in doc else _from_contract_yaml(doc)
    servers = doc.get("servers") or []
    api_base = urljoin(url, servers[0]["url"]) if servers and isinstance(servers[0], dict) and servers[0].get("url") else base
    words = {w for w in re.findall(r"\w{4,}", need.lower())}
    for op in ops:
        op["matches_need"] = bool(words & set(re.findall(r"\w{4,}", (op["summary"] + " " + op["path"]).lower())))
    host = urlparse(api_base).netloc
    existing = [{"id": name, "base_url": a.get("base_url")}
                for name, a in (capabilities.tools_config().get("apps") or {}).items()
                if isinstance(a, dict) and urlparse(str(a.get("base_url", ""))).netloc == host]
    info = doc.get("info") or {}
    login = next((o for o in ops if o["method"] == "POST" and re.search(r"(log|sign)[-_]?in|/token$", o["path"], re.I)
                  and {"username", "password"} <= set(o.get("body") or [])), None)
    return {"sign_in": {"type": "ad_login", "login_path": login["path"]} if login else None, "trust_cert": trust_cert,
            "title": str(info.get("title") or doc.get("name") or host)[:80], "description": str(info.get("description") or "")[:400],
            "base_url": api_base.rstrip("/") + "/", "contract_url": url, "operations": ops[:300], "existing": existing}


def discover() -> list[dict]:
    """Discover: look only at the systems an administrator listed (config app.discover) for a published contract and
    say what each could become. Never scans networks, ranges or ports: unknown systems stay unknown."""
    from concurrent.futures import ThreadPoolExecutor

    from agent_studio import settings

    addresses = [str(a).strip() for a in settings.load()["app"].get("discover") or [] if str(a).strip()][:50]

    def one(address: str) -> dict:
        try:
            got = learn(address)
        except HTTPException as exc:
            return {"address": address, "found": False, "detail": exc.detail}
        reads = sum(1 for o in got["operations"] if o["kind"] == "read")
        return {"address": address, "found": True, "title": got["title"], "description": got["description"][:200],
                "reads": reads, "changes": len(got["operations"]) - reads, "connected": [e["id"] for e in got["existing"]]}

    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(one, addresses))


# ------------------------------------------------------------------------------------------- drafts and approval


class LearnIn(BaseModel):
    address: str = Field(min_length=8, max_length=500)
    need: str = Field("", max_length=1000)
    trust_cert: bool = False          # the system's own (organisation) HTTPS certificate is accepted


class DraftIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    purpose: str = Field("", max_length=400)
    base_url: str = Field(min_length=8, max_length=500)
    contract_url: str = Field("", max_length=500)
    operations: list[dict] = Field(min_length=1, max_length=60)
    sign_in: str = Field("none", pattern="^(none|ad_login|token)$")
    account: str = Field("", max_length=120)          # the user id Agent Studio signs in with
    password: str = Field("", max_length=300)         # kept encrypted (vault), never in the request or contract
    login_path: str = Field("", max_length=200)       # where the system signs people in (found when learning)
    trust_cert: bool = False                          # accept the system's own HTTPS certificate
    update_of: str = Field("", max_length=40)         # an approved tool this request is a new version of


def contract_for(draft: dict, tool_id: str) -> dict:
    """The approved contract file: connector (tools.apps.<id>) + capabilities + app entry for the Designer."""
    reads = {o["id"]: {"path": o["path"], "method": o["method"], **({"query": o["query"]} if o.get("query") else {}),
                       **({"read": True, "body": o["body"]} if o["method"] != "GET" else {})}
             for o in draft["operations"] if o["kind"] == "read"}
    changes = {o["id"]: {"method": o["method"], "path": o["path"], **({"body": o["body"]} if o.get("body") else {})}
               for o in draft["operations"] if o["kind"] == "change"}
    auth: dict = {"type": "none"}
    env = vault.env_name(tool_id)
    if draft["sign_in"] == "ad_login":
        auth = {"type": "ad_login", "username": draft.get("account") or "", "password_env": env,
                **({"login_path": draft["login_path"]} if draft.get("login_path") else {})}
    elif draft["sign_in"] == "token":
        auth = {"type": "service_key", "token_env": env}
    label = draft["name"]
    caps = []
    if reads:
        caps.append({"id": f"{tool_id}_read", "label": f"Read from {label}", "side_effect": "read",
                     "description": f"{draft.get('purpose') or label}: " + "; ".join(o["summary"] for o in draft["operations"] if o["kind"] == "read")[:600],
                     "tool": {"component": "ext:studio:AppQueryComponent@official", "params": {"app": tool_id}},
                     "requires": f"apps.{tool_id}"})
    if changes:
        caps.append({"id": f"{tool_id}_change", "label": f"Make changes in {label} (with approval)", "side_effect": "write",
                     "approval": "required",
                     "description": "; ".join(o["summary"] for o in draft["operations"] if o["kind"] == "change")[:600],
                     "tool": {"component": "ext:studio:AppActionComponent@official", "params": {"app": tool_id}},
                     "requires": f"apps.{tool_id}"})
    return {
        "capabilities": caps,
        "apps": [{"id": tool_id, "name": label, "purpose": draft.get("purpose") or label, "already_does": []}],
        "tools": {"apps": {tool_id: {"type": "generic", "base_url": draft["base_url"], "auth": auth,
                                     **({"verify_tls": False} if draft.get("trust_cert") else {}),
                                     "allow_write": bool(changes), "operations": reads, "actions": changes}}},
    }


async def _me(request: Request) -> dict:
    async with Engine(request) as e:
        return await e.me()


def _admin(me: dict) -> bool:
    return roles.resolve(me, store.person_role(me["username"])) == "admin"


@router.post("/tools/learn", summary="Read a system's published contract and list what it can do", dependencies=[roles.need("builder")])
async def learn_endpoint(body: LearnIn, request: Request):
    await _me(request)
    got = await run_in_threadpool(learn, body.address, body.need, body.trust_cert)
    if body.need.strip():   # the model pre-ticks what the description needs; the person only reviews
        try:
            choice = await run_in_threadpool(pick, body.need, [got], True)
            ids = set(choice.get("operations") or []) if choice.get("system") == 0 else set()
            if ids:
                for o in got["operations"]:
                    o["matches_need"] = o["id"] in ids
        except Exception:  # noqa: BLE001 - word matching stays as the pre-selection
            pass
    return got


@router.get("/tools/discover", summary="Check the known systems (administrator's list) for published contracts", dependencies=[roles.need("builder")])
async def discover_endpoint(request: Request):
    await _me(request)
    return {"systems": await run_in_threadpool(discover)}


def starters(tool_id: str) -> list[dict]:
    """Starter agent ideas for a connected system, written by rule from what the system really offers (its read and
    change operations) - no model, nothing invented. Each is a sentence the person can take to Create and edit."""
    apps = capabilities.tools_config().get("apps") or {}
    app = apps.get(tool_id)
    if not isinstance(app, dict):
        raise HTTPException(404, "No connected system with that name")
    cat = capabilities.catalog()
    name = next((a["name"] for a in cat["apps"] if a["id"] == tool_id), tool_id)
    reads = list(app.get("operations") or {}) if isinstance(app.get("operations"), dict) else []
    changes = list(app.get("actions") or {}) if isinstance(app.get("actions"), dict) else []
    # what the reads are about, in the system's own words (from the approved contract's summaries)
    read_cap = next((c for c in cat["capabilities"] if ((c.get("tool") or {}).get("params") or {}).get("app") == tool_id
                     and c.get("side_effect") == "read"), None)
    about = [s.strip().rstrip(".") for s in (read_cap or {}).get("description", "").split(": ", 1)[-1].split(";") if s.strip()][:2]
    what = f" ({', '.join(a.lower() for a in about)})" if about else ""
    ready = {c["id"] for c in cat["capabilities"] if c.get("status") != "needs_setup"}
    out = []
    if reads:
        out.append({"kind": "chat", "text": f"Answer my questions about {name}, using only what {name} reports right now."})
        out.append({"kind": "schedule", "text": f"Every weekday at 7am check {name}{what} and tell me only if something needs attention."})
        if "save_data" in ready:
            out.append({"kind": "files", "text": f"Every Monday at 8am save {name} data{what} to an Excel file for me."})
    if changes:
        out.append({"kind": "act", "text": f"When I ask, propose the right change in {name} and make it only after I approve."})
    return out


@router.get("/tools/{tool_id}/starters", summary="Starter agent ideas for a connected system (by rule, from its real operations)")
async def starters_endpoint(tool_id: str, request: Request):
    await _me(request)
    return {"tool_id": tool_id, "ideas": await run_in_threadpool(starters, tool_id)}


@router.get("/tools", summary="Connected systems (reusable tools) and tool requests")
async def list_tools(request: Request):
    me = await _me(request)
    cat = capabilities.catalog()
    apps = capabilities.tools_config().get("apps") or {}
    drafts = await run_in_threadpool(store.list_tool_drafts, None if _admin(me) else me["id"])
    learned = {d["tool_id"] for d in drafts if d["status"] == "approved"}
    connected = [{"id": name, "kind": "system", "name": next((a["name"] for a in cat["apps"] if a["id"] == name), name),
                  "test_system": bool(a.get("mock")), "built_in": a.get("type", "generic") != "generic", "reads": list((a.get("operations") or {}) if isinstance(a.get("operations"), dict) else []),
                  "changes": list(a.get("actions") or {}) if isinstance(a.get("actions"), dict) else [],
                  "sign_in": _sign_in_state(name, a), "base_url": a.get("base_url", ""),
                  "managed": name in learned}       # learned and approved here: can be changed and removed here
                 for name, a in apps.items() if isinstance(a, dict)]
    spec_of = {d["tool_id"]: d["spec"] for d in sorted(drafts, key=lambda d: d["updated_at"]) if d["status"] == "approved"}
    for name, m in (capabilities.tools_config().get("code") or {}).items():     # tools written by AI
        if isinstance(m, dict):
            connected.append({"id": name, "kind": "code", "name": (spec_of.get(name) or {}).get("name") or name,
                              "purpose": m.get("purpose", ""), "risk_level": m.get("risk_level", ""), "test_system": False,
                              "built_in": False, "reads": [k for k in m.get("methods") or {} if k not in (m.get("changes") or [])],
                              "changes": list(m.get("changes") or []), "sign_in": None, "managed": name in learned})
    app_of = {c["id"]: ((c.get("tool") or {}).get("params") or {}).get("app") or ((c.get("tool") or {}).get("params") or {}).get("tool_id")
              for c in cat["capabilities"]}
    used = await run_in_threadpool(_used_by, me["id"], app_of)
    for c in connected:
        c["used_by"] = used.get(c["id"], [])
        c["version"] = sum(1 for d in drafts if d["tool_id"] == c["id"] and d["status"] == "approved") or None
    return {"connected": connected, "requests": drafts, "can_approve": _admin(me)}


def _sign_in_state(name: str, app: dict) -> dict | None:
    auth = app.get("auth") or {}
    if not isinstance(auth, dict) or auth.get("type") != "ad_login":
        return None
    return {"account": auth.get("username") or "", "saved": vault.has(auth.get("password_env") or vault.env_name(name))}


def _used_by(owner: str, app_of: dict) -> dict[str, list[dict]]:
    """Which of the person's agents rely on each tool (from the agents' agreed abilities, one query)."""
    out: dict[str, list[dict]] = {}
    names = {r["agent_id"]: r for r in store.agents_using(list(app_of))}
    for agent_id, prefs in store.prefs_by_agent(owner).items():
        for cap in prefs.get("capabilities") or []:
            app = app_of.get(cap)
            if app and all(a["id"] != agent_id for a in out.get(app, [])):
                out.setdefault(app, []).append({"id": agent_id, "name": prefs.get("name") or (names.get(agent_id) or {}).get("name") or agent_id})
    return out


def caps_of(tool_id: str) -> list[str]:
    """The capabilities a connected tool brings (read and change)."""
    return [c["id"] for c in capabilities.catalog()["capabilities"]
            if ((c.get("tool") or {}).get("params") or {}).get("app") == tool_id
            or ((c.get("tool") or {}).get("params") or {}).get("tool_id") == tool_id]


@router.post("/tools/requests", status_code=201, summary="Ask for a new tool (a draft until an administrator approves)", dependencies=[roles.need("builder")])
async def request_tool(body: DraftIn, request: Request):
    me = await _me(request)
    rows = await run_in_threadpool(store.list_tool_drafts, None)
    if body.update_of:
        # a new version of a tool that exists: same id, one open request at a time
        tool_id = body.update_of
        if not any(d["tool_id"] == tool_id and d["status"] == "approved" for d in rows):
            raise HTTPException(404, "There is no approved tool with that name to update")
        if any(d["tool_id"] == tool_id and d["status"] == "draft" for d in rows):
            raise HTTPException(409, "A change to this tool is already waiting for approval")
    else:
        tool_id = _slug(body.name, 30)
        known = set((capabilities.tools_config().get("apps") or {})) | {d["tool_id"] for d in rows if d["status"] != "rejected"}
        if tool_id in known:
            raise HTTPException(409, f"A tool called '{tool_id}' already exists or is requested; reuse it, or request a new version of it")
    for o in body.operations:
        if not {"id", "method", "path", "summary", "kind"} <= set(o) or o["kind"] not in ("read", "change"):
            raise HTTPException(422, "Each operation needs id, method, path, summary and kind (read or change)")
    draft = {**body.model_dump(exclude={"password"}), "requested_by": me["username"]}
    if body.sign_in == "ad_login" and body.password:
        await run_in_threadpool(vault.put, vault.env_name(tool_id), body.password)
        draft["sign_in_saved"] = True
    return await run_in_threadpool(store.create_tool_draft, me["id"], tool_id, draft)


def sign_in(base: str, login_path: str, account: str, password: str, verify: bool = True) -> tuple[httpx.Client | None, str]:
    """Sign in to a system the way its own web page does (user id + password -> token or session cookie).
    Returns a signed-in client, or None and a plain reason."""
    c = httpx.Client(timeout=10, trust_env=False, follow_redirects=False, verify=verify)
    try:
        r = c.post(base.rstrip("/") + "/" + (login_path or "/api/v1/auth/login").lstrip("/"),
                   json={"username": account, "password": password})
    except httpx.HTTPError as exc:
        c.close()
        return None, f"the system did not answer ({type(exc).__name__})"
    if r.status_code in (401, 403):
        c.close()
        return None, "the user id or password was refused"
    if r.status_code >= 300:
        c.close()
        return None, f"sign-in failed (HTTP {r.status_code})"
    try:
        body = r.json() or {}
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    token = next((body.get(f) for f in ("access_token", "token", "jwt", "id_token") if body.get(f)), None)
    if token:
        c.headers["Authorization"] = f"Bearer {token}"
    elif not c.cookies:
        c.close()
        return None, "signed in, but the system gave back no token or session"
    return c, f"signed in as {body.get('display_name') or body.get('username') or account}"


def try_tool(spec: dict, tool_id: str = "") -> dict:
    """Call each read operation of the requested tool once, for real (GET, no side effects), before approval.
    Operations needing a value in their path are listed as 'needs a value'. With a saved sign-in Agent Studio signs in
    first and reads real data; without one, a 401/403 only proves the system is there."""
    import time

    results = []
    base = spec["base_url"].rstrip("/")
    signed = None
    if spec.get("sign_in") == "ad_login" and tool_id:
        password = vault.get(vault.env_name(tool_id))
        if password:
            signed, note = sign_in(base, spec.get("login_path") or "", spec.get("account") or "", password,
                                   verify=not spec.get("trust_cert"))
            if signed is None:
                return {"at": datetime.now(timezone.utc).isoformat(), "passed": False, "signed_in": False,
                        "results": [{"id": "sign_in", "summary": "Sign in", "ok": False, "detail": note}]}
            results.append({"id": "sign_in", "summary": "Sign in", "ok": True, "detail": note})
    from contextlib import closing

    with closing(signed or httpx.Client(timeout=8, trust_env=False, follow_redirects=False, verify=not spec.get("trust_cert"))) as c:
        for o in spec["operations"]:
            if o["kind"] != "read" or o["method"] != "GET":
                results.append({"id": o["id"], "summary": o["summary"], "ok": None, "detail": "changes things: not called in a test"})
                continue
            if "{" in o["path"]:
                results.append({"id": o["id"], "summary": o["summary"], "ok": None, "detail": "needs a value (e.g. a server name): checked when an agent uses it"})
                continue
            started = time.monotonic()
            try:
                r = c.get(base + "/" + o["path"].lstrip("/"))
                ok = r.status_code < 400 or (not signed and spec["sign_in"] != "none" and r.status_code in (401, 403))
                detail = f"HTTP {r.status_code}" + (" (sign-in required, as declared)" if ok and r.status_code in (401, 403) else "")
                if r.status_code < 400:
                    detail += f" - real data, {len(r.content):,} bytes"
            except httpx.HTTPError as exc:
                ok, detail = False, f"not reachable ({type(exc).__name__})"
            results.append({"id": o["id"], "summary": o["summary"], "ok": ok, "detail": detail, "ms": round((time.monotonic() - started) * 1000)})
    tested = [r for r in results if r["ok"] is not None]
    passed = bool(tested) and all(r["ok"] for r in tested)
    if not tested:   # nothing callable without values: at least the system must answer
        try:
            with httpx.Client(timeout=8, trust_env=False, verify=not spec.get("trust_cert")) as c:
                passed = c.get(base).status_code < 500
        except httpx.HTTPError:
            passed = False
    return {"at": datetime.now(timezone.utc).isoformat(), "passed": passed, "signed_in": bool(signed), "results": results}


@router.post("/tools/requests/{request_id}/test", summary="Try the requested tool's read operations for real before approval", dependencies=[roles.need("builder")])
async def test_tool(request_id: str, request: Request):
    await _me(request)
    row = await run_in_threadpool(store.get_tool_draft, request_id)
    if not row or row["status"] != "draft":
        raise HTTPException(404, "This request is not waiting")
    if row["spec"].get("kind") == "code":
        from agent_studio import codetools
        result = await run_in_threadpool(codetools.try_code, row["spec"], row["tool_id"])
    else:
        result = await run_in_threadpool(try_tool, row["spec"], row["tool_id"])
    await run_in_threadpool(store.update_tool_draft_spec, request_id, {**row["spec"], "test": result})
    return result


def write_contract(row: dict, approver: str) -> None:
    """Approve: write the contract file agents use (older versions kept in history/)."""
    folder = capabilities.contracts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    approved = [d for d in store.list_tool_drafts(None) if d["tool_id"] == row["tool_id"] and d["status"] == "approved"]
    version = len(approved) + 1
    target = folder / f"{row['tool_id']}.yaml"
    if target.exists():                         # keep every approved version; only the newest is in use
        (folder / "history").mkdir(exist_ok=True)
        target.replace(folder / "history" / f"{row['tool_id']}.v{version - 1}.yaml")
    if row["spec"].get("kind") == "code":          # a tool written by AI: its reviewed code next to the contract
        from agent_studio import codetools
        (folder / "code").mkdir(exist_ok=True)
        code_file = folder / "code" / f"{row['tool_id']}.py"
        if code_file.exists():
            (folder / "history").mkdir(exist_ok=True)
            code_file.replace(folder / "history" / f"{row['tool_id']}.v{version - 1}.py")
        code_file.write_text(row["spec"]["code"], encoding="utf-8")
        contract = {"version": version, **codetools.contract(row["spec"], row["tool_id"])}
    else:
        contract = {"version": version, **contract_for(row["spec"], row["tool_id"])}
    header = (f"# System contract '{row['tool_id']}' v{version} - learned from {row['spec'].get('contract_url') or row['spec']['base_url']}\n"
              f"# requested by {row['spec']['requested_by']}, approved by {approver} on "
              f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Secrets: set the *_env variables named below.\n")
    target.write_text(header + yaml.safe_dump(contract, sort_keys=False, allow_unicode=True), encoding="utf-8")


@router.post("/tools/requests/{request_id}/{decision}", summary="Approve or reject a tool request (administrators)", dependencies=[roles.need("admin")])
async def decide_tool(request_id: str, decision: str, request: Request, force: bool = False):
    me = await _me(request)
    if not _admin(me):
        raise HTTPException(403, "Only an administrator can approve new tools")
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "Not found")
    row = await run_in_threadpool(store.get_tool_draft, request_id)
    if not row or row["status"] != "draft":
        raise HTTPException(404, "This request is not waiting")
    if decision == "approve":
        if not (row["spec"].get("test") or {}).get("passed") and not force:
            raise HTTPException(409, "Try it first: the tool has not passed a test call. (An administrator can approve anyway.)")
        await run_in_threadpool(write_contract, row, me["username"])
    from agent_studio import activity
    await activity.note(me["username"], "approved a connected system" if decision == "approve" else "rejected a connected system", row["tool_id"])
    if decision == "reject" and row["spec"].get("sign_in_saved") and not any(
            d["tool_id"] == row["tool_id"] and d["status"] == "approved" for d in await run_in_threadpool(store.list_tool_drafts, None)):
        await run_in_threadpool(vault.drop, vault.env_name(row["tool_id"]))   # nothing will use it
    return await run_in_threadpool(store.set_tool_draft_status, request_id, "approved" if decision == "approve" else "rejected",
                                   me["username"])


@router.delete("/tools/{tool_id}", summary="Remove a connected tool (administrators); agents using it are named first",
               dependencies=[roles.need("admin")])
async def remove_tool(tool_id: str, request: Request, force: bool = False):
    from agent_studio import activity

    me = await _me(request)
    rows = await run_in_threadpool(store.list_tool_drafts, None)
    if not any(d["tool_id"] == tool_id and d["status"] == "approved" for d in rows):
        raise HTTPException(409, "Only tools connected on this page can be removed here; this one is set up in the "
                                 "deployment's configuration by an administrator.")
    using = await run_in_threadpool(store.agents_using, await run_in_threadpool(caps_of, tool_id))
    if using and not force:
        raise HTTPException(409, {"reason": "in_use", "agents": [u["name"] for u in using], "text":
                                  "These agents use it and would lose this ability: " + ", ".join(u["name"] for u in using)
                                  + ". Remove anyway, or change those agents first."})
    folder = capabilities.contracts_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    (folder / "history").mkdir(parents=True, exist_ok=True)
    for src, ext in ((folder / f"{tool_id}.yaml", "yaml"), (folder / "code" / f"{tool_id}.py", "py")):
        if src.exists():          # kept, not deleted: an administrator can put it back
            src.replace(folder / "history" / f"{tool_id}.removed-{stamp}.{ext}")
    spec = next((d["spec"] for d in sorted(rows, key=lambda d: d["updated_at"], reverse=True)
                 if d["tool_id"] == tool_id and d["status"] == "approved"), {})
    envs = [vault.env_name(tool_id)]
    if spec.get("kind") == "code":
        from agent_studio.codetools import secret_env
        envs += [secret_env(tool_id, n) for n in (spec.get("inspect") or {}).get("secrets") or []]
    for env in envs:
        await run_in_threadpool(vault.drop, env)
    for d in rows:
        if d["tool_id"] == tool_id and d["status"] in ("approved", "draft"):
            await run_in_threadpool(store.set_tool_draft_status, d["id"], "removed", me["username"])
    await activity.note(me["username"], "removed a connected tool", tool_id, ", ".join(u["name"] for u in using))
    return {"removed": tool_id, "agents_affected": [u["name"] for u in using]}


class SignInIn(BaseModel):
    account: str = Field("", max_length=120)
    password: str = Field(min_length=1, max_length=300)


def _signed_tool(tool_id: str) -> dict:
    app = (capabilities.tools_config().get("apps") or {}).get(tool_id)
    auth = (app or {}).get("auth") or {}
    if not isinstance(app, dict) or auth.get("type") != "ad_login":
        raise HTTPException(404, "This system does not sign in with a user id and password")
    return app


def check_sign_in(tool_id: str, account: str = "", password: str = "") -> dict:
    app = _signed_tool(tool_id)
    auth = app["auth"]
    password = password or vault.get(auth.get("password_env") or vault.env_name(tool_id)) or ""
    account = account or auth.get("username") or ""
    if not password:
        return {"ok": False, "detail": "no password saved yet", "account": account}
    c, note = sign_in(str(app.get("base_url") or ""), auth.get("login_path") or "", account, password,
                      verify=app.get("verify_tls", True) is not False)
    if c:
        c.close()
    return {"ok": c is not None, "detail": note, "account": account}


def _set_account(tool_id: str, account: str) -> None:
    """A new user id goes into the contract (not secret); the comment header is kept."""
    path = capabilities.contracts_dir() / f"{tool_id}.yaml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    header = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    doc = yaml.safe_load(text) or {}
    app = ((doc.get("tools") or {}).get("apps") or {}).get(tool_id)
    if isinstance(app, dict) and isinstance(app.get("auth"), dict) and app["auth"].get("username") != account:
        app["auth"]["username"] = account
        path.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


@router.post("/tools/{tool_id}/sign-in", summary="Save (or update) the user id and password Agent Studio signs in to a system with",
             dependencies=[roles.need("builder")])
async def save_sign_in(tool_id: str, body: SignInIn, request: Request):
    me = await _me(request)
    result = await run_in_threadpool(check_sign_in, tool_id, body.account, body.password)
    if not result["ok"]:
        raise HTTPException(400, f"Not saved: {result['detail']}")
    app = _signed_tool(tool_id)
    await run_in_threadpool(vault.put, app["auth"].get("password_env") or vault.env_name(tool_id), body.password)
    if body.account and body.account != app["auth"].get("username"):
        await run_in_threadpool(_set_account, tool_id, body.account)
    from agent_studio import activity
    await activity.note(me["username"], "updated the sign-in of a connected system", tool_id)
    return result


class TrySignInIn(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    trust_cert: bool = False
    login_path: str = Field("", max_length=200)
    account: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=300)


@router.post("/tools/sign-in/try", summary="Try a user id and password on a system before asking for the tool (nothing saved)",
             dependencies=[roles.need("builder")])
async def try_sign_in(body: TrySignInIn, request: Request):
    await _me(request)
    c, note = await run_in_threadpool(sign_in, body.base_url, body.login_path, body.account, body.password, not body.trust_cert)
    if c:
        c.close()
    return {"ok": c is not None, "detail": note}


@router.post("/tools/{tool_id}/sign-in/check",summary="Check that the saved sign-in to a system still works")
async def check_sign_in_endpoint(tool_id: str, request: Request):
    await _me(request)
    return await run_in_threadpool(check_sign_in, tool_id)


# ------------------------------------------------------------------------------------------- automatic tool drafts
AUTO_PICK = """You choose API operations for a tool an AI agent needs. The need is below, with the operations each known
system publishes. Pick the ONE system that covers the need best and only the operations the need requires (at most 8):
reads for anything it must look at; changes (kind "change") only when the need clearly asks to change, create, restart
or send something. If no system covers it, answer {"system": null}. Answer JSON:
{"system": <index>, "operations": ["operation id", ...], "name": "short tool name", "purpose": "one plain line"}"""


class AutoIn(BaseModel):
    need: str = Field(min_length=3, max_length=1000)
    address: str = Field("", max_length=500)       # the system's web address, when the person gave it
    trust_cert: bool = False


_SAME_HOST = {"localhost": "127.0.0.1", "host.docker.internal": "127.0.0.1"}   # one machine, three names (dev)


def endpoint(base: str, path: str) -> str:
    """One comparable address per operation: base + path, host aliases folded, no trailing slash."""
    u = urlparse(base.rstrip("/") + "/" + path.lstrip("/"))
    host = _SAME_HOST.get(u.hostname or "", u.hostname or "")
    return f"{host}:{u.port or (443 if u.scheme == 'https' else 80)}{u.path.rstrip('/')}".lower()


def _known_routes() -> dict[tuple[str, str], str]:
    """(method, endpoint) -> connected tool offering it: never drafted twice, whatever name or base path it used."""
    out = {}
    for name, app in (capabilities.tools_config().get("apps") or {}).items():
        if not isinstance(app, dict):
            continue
        for o in list((app.get("operations") or {}).values()) + list((app.get("actions") or {}).values()):
            if isinstance(o, dict):
                out[(str(o.get("method", "GET")).upper(), endpoint(str(app.get("base_url", "")), str(o.get("path", ""))))] = name
    return out


def _built_in_cover(ep: str) -> str | None:
    """A built-in connector (its operations live in code, not in settings) covers everything under its base address."""
    for name, app in (capabilities.tools_config().get("apps") or {}).items():
        if isinstance(app, dict) and app.get("base_url") and not app.get("operations") and not app.get("actions"):
            base = endpoint(str(app["base_url"]), "")
            if ep == base or ep.startswith(base + "/"):
                return name
    return None


def pick(need: str, systems: list[dict], changes: bool = False) -> dict:
    """The model picks a system and the operations the need requires (word overlap is only the shortlist). Changes
    are offered only when asked for (the Connect page); automatic drafts stay read-only."""
    import json

    from agent_studio import ai_providers, settings

    menu = [{"index": i, "system": s["title"], "operations": [{"id": o["id"], "kind": o["kind"], "summary": o["summary"], "path": o["path"]}
                                                              for o in s["operations"] if changes or o["kind"] == "read"][:120]}
            for i, s in enumerate(systems)]
    ai_providers.configure(settings.load()["ai"], base_dir=settings.REPO)
    raw = ai_providers.chat([{"role": "system", "content": AUTO_PICK},
                             {"role": "user", "content": json.dumps({"need": need, "systems": menu}, ensure_ascii=False)}],
                            profile=settings.load()["app"]["designer_profile"], json_mode=True)
    try:
        return json.loads(raw) or {}
    except ValueError:
        return {}


def auto_draft(need: str, owner: str, who: str, address: str = "", trust_cert: bool = False) -> dict:
    """Need -> reuse what exists, or draft + live-test a read-only tool from a system's own contract (the address the
    person gave, else the administrator's list of known systems). Never writes code. If no known system covers it
    and no address was given, the person is asked for the system's address."""
    systems = []
    if address.strip():
        systems.append({**learn(address, need, trust_cert), "address": address})   # plain reason to the person if it fails
    else:
        for d in discover():
            if d.get("found"):
                try:
                    systems.append({**learn(d["address"], need), "address": d["address"]})
                except HTTPException:
                    continue
    systems = sorted(systems, key=lambda s: -sum(o["matches_need"] for o in s["operations"]))[:4]
    ask = {"outcome": "ask_address", "text": "None of the known systems covers this. What is the system's web address? "
           "Agent Studio reads what it offers from there."}
    if not systems:
        return ask
    choice = pick(need, systems)
    idx = choice.get("system")
    if not isinstance(idx, int) or not 0 <= idx < len(systems):
        return ask if not address.strip() else {"outcome": "none", "text": "That system does not offer what is needed "
                                                "(read from its own description). Check the address or ask its owners."}
    s = systems[idx]
    known = _known_routes()
    chosen = [o for o in s["operations"] if o["id"] in set(choice.get("operations") or []) and o["kind"] == "read"][:8]
    def covered_by(o: dict) -> str | None:
        ep = endpoint(s["base_url"], o["path"])
        return known.get((o["method"], ep)) or _built_in_cover(ep)

    reuse = sorted({c for o in chosen if (c := covered_by(o))})
    ops = [o for o in chosen if not covered_by(o)]
    if not chosen:
        return {"outcome": "none", "text": "None of the known systems offers this. Ask the system's owners to publish it."}
    if not ops:
        return {"outcome": "reuse", "tools": reuse,
                "text": f"Already available: use {', '.join(reuse)} (it offers what is needed). Nothing new was drafted."}
    tool_id = _slug(choice.get("name") or s["title"], 30)
    rows = store.list_tool_drafts(None)
    taken = set(capabilities.tools_config().get("apps") or {}) | {d["tool_id"] for d in rows if d["status"] != "rejected"}
    if tool_id in taken:
        tool_id = _slug(f"{tool_id}_{len(rows) + 1}", 30)
    draft = {"name": str(choice.get("name") or s["title"])[:60], "purpose": str(choice.get("purpose") or need)[:400],
             "base_url": s["base_url"], "contract_url": s["contract_url"], "operations": ops,
             "sign_in": "ad_login" if s["sign_in"] else "none", "account": "",
             "login_path": (s["sign_in"] or {}).get("login_path", ""), "trust_cert": bool(s.get("trust_cert")), "update_of": "",
             "requested_by": who, "auto": {"need": need}}
    row = store.create_tool_draft(owner, tool_id, draft)
    test = try_tool(draft, tool_id)
    store.update_tool_draft_spec(row["id"], {**draft, "test": test})
    tried = [r for r in test["results"] if r["ok"] is not None]
    locked = tried and all(not r["ok"] and r["detail"].startswith(("HTTP 401", "HTTP 403")) for r in tried)
    verdict = "passed" if test["passed"] else ("the system asks for a sign-in: enter it on the Systems page" if locked else "needs a look")
    return {"outcome": "drafted", "request_id": row["id"], "tool_id": tool_id, "name": draft["name"], "system": s["title"],
            "operations": [o["summary"] for o in ops], "test_passed": test["passed"], "reused": reuse,
            "text": f"Drafted '{draft['name']}' from {s['title']} ({len(ops)} read operation{'s' if len(ops) != 1 else ''}; "
                    f"live test: {verdict})." + (f" Also reuses {', '.join(reuse)}." if reuse else "")
                    + " An administrator approves it on the Systems page."}


@router.post("/tools/auto", summary="Need a tool? Reuse one that exists, or draft and test one from a known system's contract",
             dependencies=[roles.need("builder")])
async def auto_endpoint(body: AutoIn, request: Request):
    from agent_studio import activity

    me = await _me(request)
    out = await run_in_threadpool(auto_draft, body.need, me["id"], me["username"], body.address, body.trust_cert)
    if out["outcome"] == "drafted":
        await activity.note(me["username"], "had Agent Studio draft a tool", out["tool_id"], body.need[:200])
        if out["test_passed"] and await run_in_threadpool(_admin, me):
            # an administrator's own request that passed its live test needs no second person: connect it now
            row = await run_in_threadpool(store.get_tool_draft, out["request_id"])
            await run_in_threadpool(write_contract, row, me["username"])
            await run_in_threadpool(store.set_tool_draft_status, out["request_id"], "approved", me["username"])
            await activity.note(me["username"], "approved a connected system", out["tool_id"], "own request, live test passed")
            out = {**out, "outcome": "connected",
                   "text": f"Connected '{out['name']}' from {out['system']} ({len(out['operations'])} read operations, live test passed)."}
    return out
