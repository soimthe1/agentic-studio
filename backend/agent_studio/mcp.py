"""Use agents from other tools (MCP, the Model Context Protocol standard).

Every published agent is offered as an MCP tool by the engine's own MCP server (one server per project; lifecycle.py
switches the offer on at publish and off at pause/retire/change). Here a person gets everything to connect a tool:
the address, their own access key (created in the engine, shown once, revocable) and ready-to-paste settings.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent_studio.engine import Engine, _cfg

router = APIRouter(prefix="/api/studio/v1", tags=["MCP"])
KEY_PREFIX = "MCP access"


class KeyIn(BaseModel):
    label: str = Field("", max_length=60)


def settings_for(server: str, url: str, key: str = "<your access key>") -> dict:
    """Ready-to-paste settings for MCP clients that speak the standard's HTTP transport."""
    return {
        "json": {"mcpServers": {server: {"type": "streamable-http", "url": url, "headers": {"x-api-key": key}}}},
        "curl": (f"curl -s -X POST '{url}' -H 'Content-Type: application/json' -H 'Accept: application/json, "
                 f"text/event-stream' -H 'x-api-key: {key}' -d '{{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}}'"),
    }


@router.get("/agents/{agent_id}/mcp/connect", summary="Everything another tool needs to use this agent over MCP")
async def connect_info(agent_id: str, request: Request):
    async with Engine(request) as e:
        flow = await e._call("GET", f"/api/v1/flows/{agent_id}")
    url = f"{_cfg()['public_url'].rstrip('/')}/api/v1/mcp/project/{flow.get('folder_id')}/streamable"
    server = (flow.get("action_name") or "agents").split("_")[0] + "_agents"
    return {"enabled": bool(flow.get("mcp_enabled")), "tool": flow.get("action_name"), "url": url,
            "settings": settings_for(server, url)}


@router.get("/mcp/keys", summary="My MCP access keys (names and dates only; the key itself is shown once at creation)")
async def my_keys(request: Request):
    async with Engine(request) as e:
        rows = await e._call("GET", "/api/v1/api_key/")
    keys = rows.get("api_keys", rows) if isinstance(rows, dict) else rows
    return [{"id": k["id"], "name": k.get("name"), "created_at": k.get("created_at"), "last_used_at": k.get("last_used_at"),
             "shown": k.get("api_key")} for k in keys or [] if str(k.get("name") or "").startswith(KEY_PREFIX)]


@router.post("/mcp/keys", status_code=201, summary="Create my MCP access key (shown once; keep it like a password)")
async def create_key(body: KeyIn, request: Request):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    async with Engine(request) as e:
        row = await e._call("POST", "/api/v1/api_key/", json={"name": f"{KEY_PREFIX} - {body.label or 'my tools'} - {stamp}"})
    if not row or not row.get("api_key"):
        raise HTTPException(502, "The engine did not return a key")
    return {"id": row["id"], "name": row.get("name"), "key": row["api_key"]}


@router.delete("/mcp/keys/{key_id}", status_code=204, summary="Revoke one of my MCP access keys")
async def revoke_key(key_id: str, request: Request):
    async with Engine(request) as e:
        await e._call("DELETE", f"/api/v1/api_key/{key_id}")


# ------------------------------------------------------------------------------------------- MCP servers Agent Studio uses
# The other direction: an MCP server (another team's tools) becomes a connected system. Checked first (initialize +
# tools/list), connected by an administrator as one ability "Use <name> (MCP)". Its access key, when it needs one,
# stays in an environment variable named here (never in a file).

import os
import re

import httpx
import yaml
from fastapi.concurrency import run_in_threadpool

from agent_studio import capabilities, roles


class ServerIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    url: str = Field(min_length=8, max_length=500)
    purpose: str = Field("", max_length=400)
    key_header: str = Field("", max_length=60)          # e.g. x-api-key or Authorization
    key_env: str = Field("", max_length=80)             # environment variable that holds the key
    changes: bool = False                               # its tools may change things: a person approves each use
    key: str = Field("", max_length=400)                # only to CHECK a server once; never stored


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "mcp"


def _headers(header: str, env: str) -> dict:
    if not header or not env:
        return {}
    value = os.environ.get(env, "")
    if not value:
        raise HTTPException(422, f"Set the environment variable {env} on the server first (the key is never stored in a file)")
    return {header: value}


def list_tools(url: str, headers: dict) -> list[dict]:
    """MCP over HTTP (streamable-http): initialize, then tools/list. Plain errors for people."""
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **headers}

    def rpc(c: httpx.Client, body: dict) -> dict:
        r = c.post(url, headers=h, json=body)
        if r.status_code in (401, 403):
            raise HTTPException(422, "The MCP server refused the access key")
        r.raise_for_status()
        if r.headers.get("mcp-session-id"):
            h["mcp-session-id"] = r.headers["mcp-session-id"]
        text = r.text
        data = next((ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")), text) if "data:" in text else text
        return yaml.safe_load(data) if data.strip() else {}

    try:
        with httpx.Client(timeout=20, trust_env=False) as c:
            rpc(c, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "agent-studio", "version": "1"}}})
            c.post(url, headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            out = rpc(c, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    except httpx.HTTPError as exc:
        raise HTTPException(422, f"Could not talk to that MCP server ({type(exc).__name__}). Check the address.") from exc
    tools = ((out or {}).get("result") or {}).get("tools") or []
    return [{"name": t.get("name"), "description": (t.get("description") or "")[:300]} for t in tools if t.get("name")]


@router.post("/mcp/servers/check", summary="Check an MCP server: connect and list its tools (nothing is saved)", dependencies=[roles.need("builder")])
async def check_server(body: ServerIn, request: Request):
    async with Engine(request) as e:
        await e.me()
    headers = {body.key_header: body.key} if body.key_header and body.key else _headers(body.key_header, body.key_env)
    tools = await run_in_threadpool(list_tools, body.url.strip(), headers)
    return {"tools": tools}


@router.get("/mcp/servers", summary="MCP servers connected as systems")
async def servers(request: Request):
    async with Engine(request) as e:
        await e.me()
    out = []
    for p in sorted(capabilities.contracts_dir().glob("mcp_*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cap = (doc.get("capabilities") or [{}])[0]
        out.append({"id": cap.get("id"), "name": doc.get("name"), "url": doc.get("url"), "tools": doc.get("mcp_tools", []),
                    "changes": cap.get("side_effect") == "write"})
    return out


@router.post("/mcp/servers", status_code=201, summary="Connect an MCP server as a system (administrators)", dependencies=[roles.need("admin")])
async def connect_server(body: ServerIn, request: Request):
    async with Engine(request) as e:
        me = await e.me()
    tools = await run_in_threadpool(list_tools, body.url.strip(), _headers(body.key_header, body.key_env))
    sid = "mcp_" + _slug(body.name)
    path = capabilities.contracts_dir() / f"{sid}.yaml"
    if path.exists() or sid in {c["id"] for c in capabilities.catalog()["capabilities"]}:
        raise HTTPException(409, f"An MCP server called '{body.name}' is already connected")
    cap = {"id": sid, "label": f"Use {body.name} (MCP)", "side_effect": "write" if body.changes else "read",
           "description": (body.purpose or body.name) + ": " + "; ".join(f"{t['name']} - {t['description']}" for t in tools)[:900],
           "tool": {"component": "MCPTools", "params": {"mcp_server": {"name": sid, "config": {"url": body.url.strip()}}}},
           "mcp": {"key_header": body.key_header, "key_env": body.key_env}}
    if body.changes:
        cap["approval"] = "required"
    doc = {"version": 1, "kind": "mcp", "name": body.name, "url": body.url.strip(), "mcp_tools": tools, "capabilities": [cap]}   # not "tools:" (that key means connector settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# MCP server '{body.name}' connected by {me['username']} on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. "
                    "No secrets here: the access key stays in the environment variable named under mcp.\n"
                    + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    from agent_studio import activity
    await activity.note(me["username"], "connected an MCP server", body.name, f"{len(tools)} tools")
    return {"id": sid, "tools": tools}


@router.delete("/mcp/servers/{server_id}", status_code=204, summary="Disconnect an MCP server (administrators)", dependencies=[roles.need("admin")])
async def disconnect_server(server_id: str, request: Request):
    async with Engine(request) as e:
        me = await e.me()
    p = capabilities.contracts_dir() / f"mcp_{_slug(server_id.removeprefix('mcp_'))}.yaml"
    if not p.is_file():
        raise HTTPException(404, "Not connected")
    p.unlink()
    from agent_studio import activity
    await activity.note(me["username"], "disconnected an MCP server", server_id)
