"""Agent Studio extension inside the Langflow engine (entry point ``langflow.plugins``).

The Agent Studio app authenticates people against Active Directory. It then asks the engine to open a
normal engine session for that person, so the builder canvas and engine API calls run with the
person's own identity and ownership rules. Nothing else lives here: the app owns sign-in, UI and API.

  POST /studio-engine/session   (header X-Studio-Engine-Secret) -> cookies to set for that user
  GET  /                         browsers that land on the engine go to the Agent Studio app
  GET  /studio-auth/login        the canvas's sign-in gate sends people to the Agent Studio sign-in page
  console gate                   engine pages open only for engine.console_admins (and the break-glass superuser);
                                 everyone else is sent to Agent Studio. The engine API is unaffected.
"""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from studio_engine import config


class Identity(BaseModel):
    sub: str = Field(min_length=1, max_length=200)
    username: str = Field(min_length=1, max_length=120)
    email: str | None = None
    name: str | None = None


router = APIRouter(include_in_schema=False)


def _app_url() -> str:
    return config.load()["engine"]["app_url"].rstrip("/")


@router.post("/studio-engine/session")
async def open_session(identity: Identity, request: Request,
                       x_studio_engine_secret: str = Header("", alias="X-Studio-Engine-Secret")):
    secret = os.environ.get("STUDIO_ENGINE_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(secret.encode(), x_studio_engine_secret.encode()):
        raise HTTPException(401, "Not allowed")

    from langflow.initial_setup.setup import get_or_create_default_folder
    from langflow.services.auth.exceptions import InactiveUserError
    from langflow.services.deps import get_auth_service, get_settings_service, get_variable_service, session_scope

    s = get_settings_service().auth_settings
    auth = get_auth_service()
    try:
        async with session_scope() as db:
            user = await auth.get_or_create_user_from_claims(
                {"sub": identity.sub, "preferred_username": identity.username,
                 "email": identity.email, "name": identity.name}, db)
            tokens = await auth.create_user_tokens(user_id=user.id, db=db, update_last_login=True)
            await get_variable_service().initialize_user_variables(user.id, db)
            await get_or_create_default_folder(db, user.id)
    except InactiveUserError as exc:
        raise HTTPException(403, "Account disabled") from exc
    # Same cookies, flags and lifetimes as the engine's own /api/v1/login (langflow/api/v1/login.py).
    return {"user_id": str(user.id), "cookies": [
        {"name": "refresh_token_lf", "value": tokens["refresh_token"], "max_age": s.REFRESH_TOKEN_EXPIRE_SECONDS,
         "httponly": s.REFRESH_HTTPONLY, "samesite": s.REFRESH_SAME_SITE, "secure": s.REFRESH_SECURE},
        {"name": "access_token_lf", "value": tokens["access_token"], "max_age": s.ACCESS_TOKEN_EXPIRE_SECONDS,
         "httponly": s.ACCESS_HTTPONLY, "samesite": s.ACCESS_SAME_SITE, "secure": s.ACCESS_SECURE},
        {"name": "apikey_tkn_lflw", "value": str(user.store_api_key), "max_age": None,
         "httponly": s.ACCESS_HTTPONLY, "samesite": s.ACCESS_SAME_SITE, "secure": s.ACCESS_SECURE},
    ]}


class OwnerIn(BaseModel):
    user_id: str = Field(min_length=36, max_length=36)


@router.post("/studio-engine/code-test")
async def code_test(body: dict, x_studio_engine_secret: str = Header("", alias="X-Studio-Engine-Secret")):
    """A tool written by AI, tried here before approval: where approved tools will run (same Python, packages and
    network). Only Agent Studio may call it (shared secret); the tool runs in its own process with a time limit."""
    secret = os.environ.get("STUDIO_ENGINE_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(secret.encode(), x_studio_engine_secret.encode()):
        raise HTTPException(401, "Not allowed")
    import sys as _sys

    from fastapi.concurrency import run_in_threadpool
    from studio_tools.core import codetool, files

    own = str(files.user_dir(body["owner"])) if body.get("owner") else ""   # the tester's own files folder
    return await run_in_threadpool(lambda: codetool.run(
        str(body.get("code") or ""), str(body.get("method") or ""), body.get("args") or {}, body.get("secrets") or {},
        float(body.get("timeout") or 60), _sys.executable, str(body.get("user") or ""), own))


@router.post("/studio-engine/models")
async def models_changed(x_studio_engine_secret: str = Header("", alias="X-Studio-Engine-Secret")):
    """The studio saved new model servers (Settings): use them now. Each person's model addresses are
    environment-managed engine variables, refreshed from the environment for every user."""
    secret = os.environ.get("STUDIO_ENGINE_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(secret.encode(), x_studio_engine_secret.encode()):
        raise HTTPException(401, "Not allowed")
    from langflow.services.database.models.user.model import User
    from langflow.services.deps import get_variable_service, session_scope
    from sqlmodel import select

    from studio_engine.entrypoint import ai_profiles, model_endpoints

    env = model_endpoints(ai_profiles(config.load()))
    for gone in {"OLLAMA_BASE_URL", "OLLAMA_HOST", "VLLM_API_BASE", "VLLM_API_KEY"} - set(env):
        os.environ.pop(gone, None)   # a server no longer in use
    os.environ.update(env)
    # ponytail: updates this worker's environment only; with langflow.workers > 1 restart the engine after a change.
    async with session_scope() as db:
        for user in (await db.exec(select(User))).all():
            await get_variable_service().initialize_user_variables(user.id, db)
    return {"ok": True, "set": sorted(env)}


@router.get("/studio-engine/python")
async def engine_python(x_studio_engine_secret: str = Header("", alias="X-Studio-Engine-Secret")):
    """What a tool written by AI can use here: Python version, installed packages, command-line programs."""
    secret = os.environ.get("STUDIO_ENGINE_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(secret.encode(), x_studio_engine_secret.encode()):
        raise HTTPException(401, "Not allowed")
    import importlib.metadata as md
    import platform
    import shutil

    wanted = ("httpx", "requests", "ldap3", "pymssql", "psycopg", "openpyxl", "python-docx", "pypdf", "exchangelib",
              "pypsrp", "pywinrm", "paramiko", "cryptography", "beautifulsoup4", "lxml", "pandas")
    have = {}
    for name in wanted:
        try:
            have[name] = md.version(name)
        except md.PackageNotFoundError:
            pass
    programs = [p for p in ("pwsh", "powershell", "curl", "ssh", "smbclient", "ldapsearch") if shutil.which(p)]
    from studio_tools.core.codetool import TOOLKIT

    added = sorted({d.metadata["Name"] + " " + d.version for d in md.distributions(path=[str(TOOLKIT / "site")])}) \
        if (TOOLKIT / "site").is_dir() else []
    wheels = sorted(p.name for p in (TOOLKIT / "wheels").glob("*") if p.is_file()) if (TOOLKIT / "wheels").is_dir() else []
    return {"python": platform.python_version(), "os": platform.system(), "packages": have, "programs": programs,
            "added": added, "wheels": wheels, "toolkit": str(TOOLKIT)}


@router.post("/studio-engine/check-imports")
async def check_imports(body: dict, x_studio_engine_secret: str = Header("", alias="X-Studio-Engine-Secret")):
    """Libraries a tool's code needs that are not installed here, with the steps to bring them (air-gapped)."""
    secret = os.environ.get("STUDIO_ENGINE_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(secret.encode(), x_studio_engine_secret.encode()):
        raise HTTPException(401, "Not allowed")
    from studio_tools.core.codetool import bring_steps, missing_imports

    gone = missing_imports(str(body.get("code") or ""))
    return {"missing": gone, "steps": bring_steps([g["package"] for g in gone]) if gone else ""}


@router.post("/studio-engine/toolkit/install")
async def toolkit_install(body: dict, x_studio_engine_secret: str = Header("", alias="X-Studio-Engine-Secret")):
    """Install libraries people brought: ONLY from the files in <toolkit>/wheels (never the internet), into
    <toolkit>/site, which tools written by AI can import and which survives engine image updates."""
    secret = os.environ.get("STUDIO_ENGINE_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(secret.encode(), x_studio_engine_secret.encode()):
        raise HTTPException(401, "Not allowed")
    import re as _re
    import subprocess
    import sys as _sys

    from fastapi.concurrency import run_in_threadpool
    from studio_tools.core.codetool import TOOLKIT

    names = [n for n in str(body.get("packages") or "").replace(",", " ").split() if _re.fullmatch(r"[A-Za-z0-9._\-\[\]=<>~!]+", n)]
    wheels = TOOLKIT / "wheels"
    if not names:   # everything that was brought
        names = sorted({str(p) for p in wheels.glob("*.whl")} | {str(p) for p in wheels.glob("*.tar.gz")})
    if not names:
        return {"ok": False, "output": f"No library files found in {wheels}. Copy the .whl files there first."}
    (TOOLKIT / "site").mkdir(parents=True, exist_ok=True)
    cmd = [_sys.executable, "-m", "pip", "install", "--no-index", "--find-links", str(wheels), "--target",
           str(TOOLKIT / "site"), "--upgrade", "--disable-pip-version-check", *names]
    p = await run_in_threadpool(lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=600))
    return {"ok": p.returncode == 0, "output": (p.stdout + p.stderr)[-4000:]}


@router.post("/studio-engine/session-as-owner")
async def session_as_owner(body: OwnerIn, x_studio_engine_secret: str = Header("", alias="X-Studio-Engine-Secret")):
    """The Agent Studio watches (failures, goals) look at a live agent's runs as its owner: the engine shows each person
    only their own runs. Same secret as /session; returns an access token only (nothing is set in a browser)."""
    secret = os.environ.get("STUDIO_ENGINE_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(secret.encode(), x_studio_engine_secret.encode()):
        raise HTTPException(401, "Not allowed")
    import uuid as _uuid

    from langflow.services.database.models.user.crud import get_user_by_id
    from langflow.services.deps import get_auth_service, session_scope

    async with session_scope() as db:
        user = await get_user_by_id(db, _uuid.UUID(body.user_id))
        if not user or not user.is_active:
            raise HTTPException(404, "No such active user")
        tokens = await get_auth_service().create_user_tokens(user_id=user.id, db=db, update_last_login=False)
    return {"access_token": tokens["access_token"]}


# --------------------------------------------------------------------------- definitions <-> engine flows
# The Agent Studio app speaks in agent definitions (steps + connections). Converting them to and from engine
# flows uses the engine's own flow builder (lfx.graph.flow_builder) against the LIVE component registry,
# so wiring, type checks and tool mode are exactly what this engine version expects.

TOOL_ALIAS = "tool"                 # Agent Studio name for "use this step as a tool of an agent"
TOOL_OUTPUT = "component_as_tool"   # engine name (lfx.base.tools.constants.TOOL_OUTPUT_NAME)


class Step(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    component: str = Field(min_length=1, max_length=200)
    params: dict = Field(default_factory=dict)
    position: dict | None = None


class Connection(BaseModel):
    source: str = Field(alias="from")
    output: str
    to: str
    input: str

    model_config = {"populate_by_name": True}


class Definition(BaseModel):
    steps: list[Step]
    connections: list[Connection] = Field(default_factory=list)


async def _registry() -> dict[str, dict]:
    from langflow.interface.components import get_and_cache_all_types_dict
    from langflow.services.deps import get_settings_service

    all_types = await get_and_cache_all_types_dict(settings_service=get_settings_service())
    return {k: v for cat, comps in all_types.items() if cat != "component_display_names"
            and isinstance(comps, dict) for k, v in comps.items() if isinstance(v, dict) and "template" in v}


def _model_value(value):
    """Agent Studio gives {"provider", "name"}; the engine wants [{"provider", "name"}]."""
    if isinstance(value, dict) and value.get("name"):
        return [{"provider": value.get("provider", ""), "name": value["name"]}]
    return value


async def _current_user(request: Request):
    from langflow.services.auth.utils import get_current_user_from_access_token

    token = request.cookies.get("access_token_lf") or (request.headers.get("authorization", "").removeprefix("Bearer ").strip())
    if not token:
        raise HTTPException(401, "Not signed in")
    try:
        from langflow.services.deps import session_scope

        async with session_scope() as db:
            user = await get_current_user_from_access_token(token, db)
    except Exception as exc:
        raise HTTPException(401, "Not signed in") from exc
    if not user or not user.is_active:
        raise HTTPException(401, "Not signed in")
    return user


async def _expose_subflow_inputs(flow: dict, step_id: str, sub_flow_id: str, user) -> None:
    """A sub-agent step gets the called agent's input fields (its question), exactly as the editor adds them when a
    flow is picked (RunFlowComponent.update_build_config). Without them the calling agent has nothing to pass."""
    from lfx.components.flow_controls.run_flow import RunFlowComponent
    from lfx.schema.dotdict import dotdict

    node = next(n for n in flow["data"]["nodes"] if n["id"] == step_id)
    template = node["data"]["node"]["template"]
    comp = RunFlowComponent(_user_id=str(user.id))
    cfg = await comp.update_build_config(dotdict(template), sub_flow_id, "flow_id_selected")
    node["data"]["node"]["template"] = {k: dict(v) if isinstance(v, dict) else v for k, v in cfg.items()}
    order = node["data"]["node"].get("field_order") or []
    node["data"]["node"]["field_order"] = order + [k for k in cfg if k not in order and isinstance(cfg[k], dict) and "~" in k]


@router.post("/studio-engine/compile")
async def compile_definition(definition: Definition, request: Request):
    user = await _current_user(request)
    from lfx.graph.flow_builder import add_component, add_connection, configure_component, empty_flow, layout_flow

    registry = await _registry()
    flow = empty_flow()
    try:
        for step in definition.steps:
            add_component(flow, step.component, registry, component_id=step.id)
            template = registry[step.component]["template"]
            params = {k: (_model_value(v) if isinstance(template.get(k), dict) and template[k].get("type") == "model" else v)
                      for k, v in step.params.items()}
            if params:
                configure_component(flow, step.id, params)
                # The engine ignores values of hidden fields at run time (param_handler skips show=False),
                # e.g. LanguageModel's ollama_base_url; a value we set must be live.
                node = next(n for n in flow["data"]["nodes"] if n["id"] == step.id)
                for k in params:
                    node["data"]["node"]["template"][k]["show"] = True
        for step in definition.steps:
            if step.component == "RunFlow" and step.params.get("flow_id_selected"):
                await _expose_subflow_inputs(flow, step.id, step.params["flow_id_selected"], user)
        for c in definition.connections:
            output = TOOL_OUTPUT if c.output == TOOL_ALIAS else c.output
            add_connection(flow, c.source, output, c.to, c.input, registry=registry)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if all(s.position for s in definition.steps):
        for node, step in zip(flow["data"]["nodes"], definition.steps, strict=True):
            node["position"] = {"x": float(step.position.get("x", 0)), "y": float(step.position.get("y", 0))}
    else:
        layout_flow(flow)
    return {"data": flow["data"]}


@router.post("/studio-engine/decompile")
async def decompile_flow(body: dict, request: Request):
    await _current_user(request)
    registry = await _registry()
    data = body.get("data") or {}
    steps, connections = [], []
    for node in data.get("nodes", []):
        nd = node.get("data", {})
        key = nd.get("type")
        template = (nd.get("node") or {}).get("template", {})
        defaults = (registry.get(key) or {}).get("template", {})
        params = {}
        for name, spec in template.items():
            if not isinstance(spec, dict) or name == "code" or "value" not in spec:
                continue
            value = spec.get("value")
            if spec.get("type") == "model" and isinstance(value, list) and value:
                value = {"provider": value[0].get("provider"), "name": value[0].get("name")}
            if value in (None, "", [], {}) or value == (defaults.get(name) or {}).get("value"):
                continue
            params[name] = value
        steps.append({"id": nd.get("id", node.get("id")), "component": key, "params": params,
                      "position": node.get("position"), "tool": bool((nd.get("node") or {}).get("tool_mode"))})
    for e in data.get("edges", []):
        sh = (e.get("data") or {}).get("sourceHandle") or {}
        th = (e.get("data") or {}).get("targetHandle") or {}
        out = sh.get("name")
        connections.append({"from": e.get("source"), "output": TOOL_ALIAS if out == TOOL_OUTPUT else out,
                            "to": e.get("target"), "input": th.get("fieldName")})
    return {"steps": steps, "connections": connections}


@router.get("/")
async def to_app():
    return RedirectResponse(_app_url() + "/", status_code=302)


@router.get("/studio-auth/login")
async def to_sign_in():
    return RedirectResponse(_app_url() + "/auth/login", status_code=302)


async def _console_allowed(request: Request) -> bool:
    try:
        user = await _current_user(request)
    except HTTPException:
        return False
    admins = {str(u).lower() for u in config.load()["engine"].get("console_admins") or []}
    return bool(user.is_superuser or user.username.lower() in admins)


# --------------------------------------------------------------------------- what the engine can reach (System health)
async def _probe_http(client, url: str) -> dict:
    import time

    started = time.monotonic()
    try:
        r = await client.get(url)
        return {"ok": r.status_code < 500, "detail": f"HTTP {r.status_code}", "ms": round((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001 - any failure is "not reachable", reported in plain words
        return {"ok": False, "detail": type(exc).__name__, "ms": round((time.monotonic() - started) * 1000)}


async def _probe_tcp(host: str, port: int) -> dict:
    import asyncio
    import time

    started = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=4)
        writer.close()
        return {"ok": True, "detail": "port open", "ms": round((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": type(exc).__name__, "ms": round((time.monotonic() - started) * 1000)}


def _secret_envs(node) -> list[str]:
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k.endswith("_env") and isinstance(v, str):
                out.append(v)
            else:
                out += _secret_envs(v)
    return out


@router.get("/studio-engine/status")
async def engine_status(request: Request):
    """Seen from inside the engine, where agents run: versions, policy, model servers, every configured connection
    (reachable? secrets set?), internet switch, files folder. Never returns secret values."""
    import asyncio
    import importlib.metadata as md
    from pathlib import Path
    from urllib.parse import urlparse

    import httpx

    await _current_user(request)
    out: dict = {"engine_version": md.version("langflow-base"), "tools_version": md.version("studio-tools")}
    try:
        from langflow.services.deps import session_scope
        from langflow.services.policy_bundle import get_policy_bundle_state

        async with session_scope() as db:
            snap = await get_policy_bundle_state(db)
        blocked = getattr(snap, "blocked_component_keys", None) or getattr(getattr(snap, "bundle", None), "blocked_component_keys", [])
        out["policy"] = {"revision": getattr(snap, "revision", None), "blocked": len(blocked or [])}
    except Exception as exc:  # noqa: BLE001
        out["policy"] = {"revision": None, "blocked": 0, "error": type(exc).__name__}

    from studio_tools.core.config import load_config

    try:
        cfg = load_config()
    except Exception as exc:  # noqa: BLE001
        cfg, out["tools_config_error"] = {}, str(exc)[:300]
    jobs, rows = [], []
    async with httpx.AsyncClient(timeout=4, trust_env=False, follow_redirects=False) as client:
        for name, url in (("Ollama", os.environ.get("OLLAMA_BASE_URL")), ("vLLM", os.environ.get("VLLM_API_BASE"))):
            if url:
                rows.append({"kind": "model", "name": name, "address": url})
                jobs.append(_probe_http(client, url.rstrip("/") + ("/api/version" if name == "Ollama" else "/models")))
        for section in ("apps", "notify", "sql", "knowledge"):
            entries = cfg.get(section) or {}
            if section == "knowledge":
                entries = {"knowledge": entries} if isinstance(entries, dict) and entries.get("enabled") else {}
            for name, conn in entries.items():
                if not isinstance(conn, dict):
                    continue
                from studio_tools.core import vault as _vault   # sign-ins saved on the Tools page count as set

                missing = [e for e in _secret_envs(conn) if not os.environ.get(e) and not _vault.read(cfg.get("contracts_dir"), e)]
                first = next(iter((conn.get("instances") or {}).values()), {}) if isinstance(conn.get("instances"), dict) else {}
                url = conn.get("base_url") or conn.get("url") or first.get("base_url")
                row = {"kind": section, "name": name, "test_system": bool(conn.get("mock")), "missing_secrets": missing,
                       "address": f"{urlparse(url).scheme}://{urlparse(url).netloc}" if url else
                       (f"{conn.get('host')}:{conn.get('port')}" if conn.get("host") else "")}
                if section == "apps":   # the real operation names, so agents are told exactly what they can call
                    try:
                        from studio_tools.core import apps as _apps

                        named = {**conn, "_name": name}
                        row["reads"], row["actions"] = list(_apps.operations(named)), list(_apps.actions(named))
                    except Exception:  # noqa: BLE001
                        row["reads"], row["actions"] = [], []
                rows.append(row)
                if url:
                    jobs.append(_probe_http(client, url))
                elif conn.get("host"):
                    jobs.append(_probe_tcp(conn["host"], int(conn.get("port") or 0)))
                else:
                    jobs.append(asyncio.sleep(0, {"ok": None, "detail": "nothing to reach", "ms": 0}))
        results = await asyncio.gather(*jobs)
    for row, res in zip(rows, results, strict=True):
        row.update(res)
        if row.get("missing_secrets"):
            row["ok"], row["detail"] = False, "secret not set: " + ", ".join(row["missing_secrets"])
    out["connections"] = rows
    out["web_enabled"] = bool((cfg.get("web") or {}).get("enabled"))
    root = Path((cfg.get("files") or {}).get("root") or "/data/files")
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".agent-studio-write-check"
        probe.write_text("ok")
        probe.unlink()
        out["files_writable"] = True
    except OSError:
        out["files_writable"] = False
    return out


# Registered LAST: plugin routes come before the engine UI's static fallback, so every engine page (and the UI's
# files) passes here. Pages open only for engine.console_admins and the break-glass superuser; everyone else is
# sent to Agent Studio. Engine API routes are registered earlier and never reach this.
@router.get("/{path:path}")
async def console_gate(path: str, request: Request):
    from pathlib import Path

    from fastapi.responses import FileResponse, HTMLResponse
    from langflow.main import get_static_files_dir
    from langflow.utils.frontend import render_frontend_index

    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    from langflow.services.deps import get_settings_service

    configured = get_settings_service().settings.frontend_path  # the branded build (config langflow.frontend_path)
    static = Path(configured or get_static_files_dir()).resolve()
    if "." in path.rsplit("/", 1)[-1]:  # a file of the UI build (scripts, styles, fonts, images)
        f = (static / path).resolve()
        if static in f.parents and f.is_file():
            return FileResponse(f)
        raise HTTPException(404, "Not Found")
    if path != "login" and not await _console_allowed(request):  # /login stays open for break-glass sign-in
        return RedirectResponse(_app_url() + "/", status_code=302)
    html = render_frontend_index((static / "index.html").read_text(encoding="utf-8"), request.scope.get("root_path", ""))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _retry_model_connects() -> None:
    """Model servers on busy networks drop a share of new connections (measured: ~25% failed connects in bursts of 10-15 s to the
    Ollama host). Retry the CONNECT step a few times; a request that already reached the server is never repeated
    (httpx transport retries apply to connection failures only)."""
    import sys

    import httpx

    mod = sys.modules.get("ollama._client")
    if mod is None:
        import ollama  # noqa: F401  (the package shadows its own _client module name)

        mod = sys.modules["ollama._client"]
    for cls, transport in ((mod.Client, httpx.HTTPTransport), (mod.AsyncClient, httpx.AsyncHTTPTransport)):
        original = cls.__init__
        if getattr(original, "_studio", False):
            continue

        def init(self, host=None, *, _original=original, _transport=transport, **kwargs):
            kwargs.setdefault("transport", _transport(retries=7))  # backoff 0.5..32 s: rides out ~15 s outages
            _original(self, host, **kwargs)

        init._studio = True
        cls.__init__ = init


def _no_thinking_on_vllm() -> None:
    """Reasoning models on our vLLM server 'think' before every agent step (~55 s each), and the engine's model step
    has no field to switch that off. Calls to that server (VLLM_API_BASE) go without thinking unless a call sets
    its own extra_body - the same switch Agent Studio's own model calls use (chat_template_kwargs.enable_thinking)."""
    import os

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return
    base = (os.environ.get("VLLM_API_BASE") or "").rstrip("/")
    original = ChatOpenAI.__init__
    if not base or getattr(original, "_studio", False):
        return

    def init(self, *args, _original=original, **kwargs):
        url = str(kwargs.get("base_url") or kwargs.get("openai_api_base") or "").rstrip("/")
        if url == base and not kwargs.get("extra_body"):
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        _original(self, *args, **kwargs)

    init._studio = True
    ChatOpenAI.__init__ = init


def _allow_approved_mcp_servers() -> None:
    """SSRF protection stays on, but the hosts of MCP servers an administrator connected (approved contract files
    mcp_*.yaml in contracts_dir) are added to its allow-list - in an air-gapped network every MCP server is
    internal. Nothing else is allowed. Re-read when the folder changes, so connecting needs no restart."""
    import time
    from pathlib import Path
    from urllib.parse import urlparse

    import yaml
    from lfx.utils import ssrf_protection as ssrf

    original = ssrf.get_allowed_hosts
    if getattr(original, "_studio", False):
        return
    seen: dict = {"at": 0.0, "hosts": []}

    def approved() -> list[str]:
        if time.monotonic() - seen["at"] < 10:
            return seen["hosts"]
        hosts: list[str] = []
        try:
            from studio_tools.core.config import load_config

            folder = Path(load_config().get("contracts_dir") or "")
            for p in folder.glob("mcp_*.yaml") if folder.is_dir() else []:
                url = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("url") or ""
                if urlparse(url).hostname:
                    hosts.append(urlparse(url).hostname)
        except Exception:  # noqa: BLE001 - never widen access on an error
            hosts = []
        seen.update(at=time.monotonic(), hosts=hosts)
        return hosts

    def allowed() -> list[str]:
        return list(dict.fromkeys([*original(), *approved()]))

    allowed._studio = True
    ssrf.get_allowed_hosts = allowed


def register(app) -> None:
    _retry_model_connects()
    _no_thinking_on_vllm()
    _allow_approved_mcp_servers()
    app.include_router(router)
