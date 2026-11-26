"""System health: everything Agent Studio depends on, checked now, in plain words. Two views are combined:

- seen from the app: database, Active Directory, the designer's AI models, the engine, the files folders;
- seen from the engine, where agents actually run (GET /studio-engine/status): model servers, every configured
  connection (reachable? secrets set?), the approved-components policy, the internet switch.

Each item: {group, name, ok: true|false|null, detail, ms, test_system}. ok=null means "not checked / not applicable".
The same checks feed the Readiness watchkeeper before an agent is built or run.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from agent_studio import capabilities, settings, store
from agent_studio.engine import Engine

router = APIRouter(prefix="/api/studio/v1", tags=["System health"])


def _item(group: str, name: str, ok, detail: str, ms: int = 0, **extra) -> dict:
    return {"group": group, "name": name, "ok": ok, "detail": detail, "ms": ms, **extra}


async def _http(group: str, name: str, url: str) -> dict:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as c:
            r = await c.get(url)
        return _item(group, name, r.status_code < 500, f"HTTP {r.status_code}", round((time.monotonic() - started) * 1000))
    except httpx.HTTPError as exc:
        return _item(group, name, False, f"not reachable ({type(exc).__name__})", round((time.monotonic() - started) * 1000))


async def _tcp(group: str, name: str, host: str, port: int) -> dict:
    started = time.monotonic()
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5)
        w.close()
        return _item(group, name, True, f"{host}:{port} answers", round((time.monotonic() - started) * 1000))
    except (OSError, asyncio.TimeoutError) as exc:
        return _item(group, name, False, f"{host}:{port} not reachable ({type(exc).__name__})", round((time.monotonic() - started) * 1000))


def _database() -> dict:
    started = time.monotonic()
    try:
        with store.connect() as c:
            c.execute("SELECT 1")
        return _item("app", "Database (PostgreSQL)", True, "connected", round((time.monotonic() - started) * 1000))
    except Exception as exc:  # noqa: BLE001
        return _item("app", "Database (PostgreSQL)", False, f"cannot connect ({type(exc).__name__})")


def _folder(name: str, key: str) -> dict:
    path = settings.path(settings.load()["app"][key])
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".agent-studio-write-check"
        probe.write_text("ok")
        probe.unlink()
        return _item("app", name, True, "writable")
    except OSError as exc:
        return _item("app", name, False, f"not writable ({type(exc).__name__})")


async def check(request: Request) -> dict:
    cfg = settings.load()
    jobs = [run_in_threadpool(_database)]
    if cfg["ldap"].get("enabled"):
        ldap = urlparse(cfg["ldap"]["server_uri"])
        jobs.append(_tcp("app", "Active Directory", ldap.hostname, ldap.port or (636 if ldap.scheme == "ldaps" else 389)))
    for prof, p in (cfg.get("ai") or {}).items():
        if p.get("enabled", True) is False or p.get("provider") == "comfyui":
            continue
        url = p["base_url"].rstrip("/") + ("/api/version" if p.get("provider") == "ollama" else "/models")
        jobs.append(_http("models", f"Designer AI - {prof} ({p.get('model')})", url))
    jobs.append(_http("app", "Agent engine", cfg["engine"]["url"].rstrip("/") + "/health_check"))
    items = list(await asyncio.gather(*jobs))
    items += [_folder("People's files folder", "files_dir"), _folder("Learned systems folder", "contracts_dir")]

    engine: dict = {}
    try:
        async with Engine(request) as e:
            engine = await e.status()
    except Exception as exc:  # noqa: BLE001 - shown as an item, never a page error
        items.append(_item("engine", "Engine details", False, f"not available ({getattr(exc, 'detail', type(exc).__name__)})"))
    names = {a["id"]: a["name"] for a in capabilities.catalog()["apps"]}
    for cap in capabilities.catalog()["capabilities"]:   # connector name -> what people call it
        app = ((cap.get("tool") or {}).get("params") or {}).get("app")
        if app and app not in names:
            names[app] = cap["label"]
    group = {"model": "models", "apps": "systems", "sql": "systems", "knowledge": "systems", "notify": "channels"}
    for c in engine.get("connections") or []:
        label = names.get(c["name"], c["name"])
        items.append(_item(group.get(c["kind"], "systems"), label if c["kind"] != "model" else f"Agents' AI - {label}",
                           c.get("ok"), c.get("detail", ""), c.get("ms", 0), test_system=c.get("test_system", False),
                           address=c.get("address", "")))
    if engine:
        pol = engine.get("policy") or {}
        items.append(_item("engine", "Approved components policy", bool(pol.get("revision")),
                           f"revision {pol.get('revision')}, {pol.get('blocked')} components blocked" if pol.get("revision")
                           else "not applied - run the seed (dev.ps1 seed)"))
        items.append(_item("engine", "Engine and tools versions", True,
                           f"engine {engine.get('engine_version')}, tools {engine.get('tools_version')}"))
        items.append(_item("engine", "Internet access for agents", None,
                           "switched on" if engine.get("web_enabled") else "switched off (air-gapped setting)"))
        items.append(_item("engine", "Files folder (engine side)", engine.get("files_writable"),
                           "writable" if engine.get("files_writable") else "not writable"))
    bad = [i for i in items if i["ok"] is False]
    return {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ok": not bad,
            "problems": len(bad), "items": items}


@router.get("/system", summary="System health: everything Agent Studio and its agents depend on, checked now")
async def system(request: Request):
    return await check(request)
