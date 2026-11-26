"""Tools written by AI: "read my e-mail" -> Agent Studio writes a Python tool for it, tries it in the engine (where it will
run), shows an administrator the code with a plain risk report, and after approval every agent can reuse it.

Nothing the code may do is blocked (shell commands, PowerShell, files, any library or host): the safeguards are the
risk report (codetool.inspect_code), the administrator's approval of the code, and a person's approval on every call
of an operation that changes something or that the report found risky. Drafts are tool requests (kind "code") and
use the same approval flow as tools learned from a system's description (tools.py).
"""

from __future__ import annotations

import json
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import activity, capabilities, codetool, roles, settings, store, vault

router = APIRouter(prefix="/api/studio/v1", tags=["Tools written by AI"])

WRITE = """You write ONE Python tool for an AI agent in an organisation's private network. Rules:
- One class named Tool. Each public method is one operation the agent can call: simple typed arguments (str, int,
  float, bool, list, dict) with defaults where sensible, a one-line docstring saying what it does, and a JSON-friendly
  return value (dict/list/str/number). Keep results small (summaries, at most ~200 items).
- Class attributes: HOSTS = ["host:port", ...] it talks to; SECRETS = ["NAME", ...] for passwords/tokens (read them
  with self.secret("NAME"), never hard-code or print them); CHANGES = ["method", ...] for every method that changes,
  sends, deletes or runs commands.
- No constructor arguments. Provided on every call: self.user (the person's login, may be empty), self.files_dir
  (that person's own files folder: read their files and write results there), self.secret("NAME").
- Any library/program may be used, but only these exist where it runs: {env}. Prefer the standard library.
- Make it robust: timeouts on network calls, clear error messages (raise ValueError("plain words")).
- If one of the existing tools already covers the need, do not write code: answer {{"reuse": "<tool id>"}}.
Existing tools: {existing}
Answer JSON only: {{"reuse": null, "name": "short tool name", "purpose": "one plain line", "code": "<the python file>"}}"""


class DraftIn(BaseModel):
    need: str = Field(min_length=3, max_length=2000)
    details: str = Field("", max_length=2000)       # e.g. the mail server's address, the account to use
    update_of: str = Field("", max_length=40)        # a tool written earlier: change it (new version) instead of a new one


class TryIn(BaseModel):
    method: str = Field(min_length=1, max_length=80)
    args: dict = Field(default_factory=dict)


class SecretIn(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_]+$")
    value: str = Field(min_length=1, max_length=2000)


def secret_env(tool_id: str, name: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", f"STUDIO_CODE_{tool_id}_{name}".upper())[:120]


def _engine(method: str, path: str, body: dict | None = None, timeout: float = 120) -> dict:
    from agent_studio.engine import _cfg

    cfg = _cfg()
    with httpx.Client(base_url=cfg["url"], timeout=timeout, trust_env=False) as c:
        r = c.request(method, path, json=body, headers={"X-Studio-Engine-Secret": settings.secret(cfg["secret_env"])})
    r.raise_for_status()
    return r.json()


def existing() -> dict[str, dict]:
    return {k: v for k, v in (capabilities.tools_config().get("code") or {}).items() if isinstance(v, dict)}


def write(need: str, details: str, repair: str = "", current: str = "") -> dict:
    from agent_studio import ai_providers

    env = _engine("GET", "/studio-engine/python", timeout=20)
    env_text = (f"Python {env['python']} on {env['os']}; packages: " + ", ".join(f"{k} {v}" for k, v in env["packages"].items())
                + "; programs: " + (", ".join(env["programs"]) or "none (no PowerShell, no shell tools)"))
    tools = "; ".join(f"{k}: {v.get('purpose', '')}" for k, v in existing().items()) or "none"
    msgs = [{"role": "system", "content": WRITE.format(env=env_text, existing=tools)},
            {"role": "user", "content": json.dumps({"need": need, "details": details}, ensure_ascii=False)}]
    if current:   # a change to an existing tool: keep what works, keep operation names unless asked otherwise
        msgs.append({"role": "user", "content": "This is the tool's current code. Change it as asked above; keep the "
                     "same class and existing operation names unless the change asks otherwise; never answer reuse.\n\n" + current})
    if repair:
        msgs.append({"role": "user", "content": "Your previous code was not a valid tool: " + repair + " Write it again."})
    ai_providers.configure(settings.load()["ai"], base_dir=settings.REPO)
    raw = ai_providers.chat(msgs, profile=settings.load()["app"]["designer_profile"], json_mode=True, max_tokens=6000)
    try:
        return json.loads(raw) or {}
    except ValueError:
        return {}


def try_code(spec: dict, tool_id: str, method: str | None = None, args: dict | None = None, owner: str = "", user: str = "") -> dict:
    """Run one operation in the engine with its saved secrets; without a method, the first safe one needing no values."""
    from datetime import datetime, timezone

    info = spec["inspect"]
    if method is None:
        m = next((m for m in info["methods"] if not m["change"] and not m["required"]), None)
        if not m:
            return {"at": datetime.now(timezone.utc).isoformat(), "passed": False, "results": [{"id": "-", "summary": "Try it",
                    "ok": None, "detail": "every operation needs values or changes something: try one by hand"}]}
        method = m["name"]
    secrets = {n: vault.get(secret_env(tool_id, n)) for n in info.get("secrets") or []}
    missing = [n for n, v in secrets.items() if not v]
    if missing:
        return {"at": datetime.now(timezone.utc).isoformat(), "passed": False, "results": [{"id": method, "summary": method,
                "ok": False, "detail": f"enter {', '.join(missing)} first (kept encrypted)"}]}
    try:
        out = _engine("POST", "/studio-engine/code-test", {"code": spec["code"], "method": method, "args": args or {},
                                                            "secrets": secrets, "timeout": 60, "owner": owner, "user": user}, timeout=90)
    except httpx.HTTPError as exc:
        out = {"ok": False, "error": f"the engine could not run it ({type(exc).__name__})"}
    detail = (json.dumps(out.get("result"), default=str)[:300] if out.get("ok") else out.get("error", "failed"))
    return {"at": datetime.now(timezone.utc).isoformat(), "passed": bool(out.get("ok")),
            "results": [{"id": method, "summary": method, "ok": bool(out.get("ok")), "detail": detail}]}


def draft(need: str, details: str, owner: str, who: str, update_of: str = "") -> dict:
    from agent_studio.tools import _slug

    rows = store.list_tool_drafts(None)
    current = ""
    if update_of:
        approved = [d for d in sorted(rows, key=lambda d: d["updated_at"]) if d["tool_id"] == update_of and d["status"] == "approved"]
        if not approved or approved[-1]["spec"].get("kind") != "code":
            return {"outcome": "none", "text": f"There is no approved tool written by AI called '{update_of}'."}
        if any(d["tool_id"] == update_of and d["status"] == "draft" for d in rows):
            return {"outcome": "none", "text": "A change to this tool is already waiting for approval."}
        current = approved[-1]["spec"]["code"]
    got = write(need, details, current=current)
    if not update_of and got.get("reuse") and got["reuse"] in existing():
        return {"outcome": "reuse", "tools": [got["reuse"]], "text": f"Already available: use the tool '{got['reuse']}'."}
    info = codetool.inspect_code(str(got.get("code") or ""))
    if not info["ok"]:                                      # one repair round with the exact problem
        got = write(need, details, info["error"], current)
        info = codetool.inspect_code(str(got.get("code") or ""))
        if not info["ok"]:
            return {"outcome": "none", "text": "No working tool could be written for this: " + info["error"]}
    tool_id = update_of or _slug(got.get("name") or need, 30)
    taken = set(capabilities.tools_config().get("apps") or {}) | set(existing()) | {d["tool_id"] for d in rows if d["status"] not in ("rejected", "removed")}
    if not update_of and tool_id in taken:
        tool_id = _slug(f"{tool_id}_{len(rows) + 1}", 30)
    spec = {"kind": "code", "update_of": update_of, "name": str(got.get("name") or tool_id)[:60], "purpose": str(got.get("purpose") or need)[:400],
            "need": need, "details": details, "code": got["code"], "inspect": info, "requested_by": who,
            "base_url": ", ".join(info["hosts"]) or "-", "operations": [{"id": m["name"], "summary": m["doc"],
                                                                         "kind": "change" if m["change"] else "read"} for m in info["methods"]]}
    try:   # libraries it needs that the engine does not have (air-gapped: they must be brought)
        need_libs = _engine("POST", "/studio-engine/check-imports", {"code": got["code"]}, timeout=30)
    except httpx.HTTPError:
        need_libs = {"missing": [], "steps": ""}
    spec["missing"], spec["bring"] = need_libs["missing"], need_libs["steps"]
    row = store.create_tool_draft(owner, tool_id, spec)
    test = try_code(spec, tool_id, owner=owner, user=who) if not spec["missing"] else {
        "passed": False, "results": [{"id": "-", "summary": "Libraries", "ok": False, "detail": need_libs["steps"]}]}
    store.update_tool_draft_spec(row["id"], {**spec, "test": test})
    risky = [r["text"] for r in info["risks"]]
    return {"outcome": "drafted", "request_id": row["id"], "tool_id": tool_id, "name": spec["name"], "level": info["level"],
            "risks": risky, "methods": info["methods"], "secrets": info["secrets"], "test": test,
            "missing": spec["missing"], "bring": spec["bring"],
            "text": (f"Wrote '{spec['name']}' ({len(info['methods'])} operation(s); risk: {info['level']}"
                     + (f" - {'; '.join(dict.fromkeys(risky))}" if risky else "") + "). "
                     + (spec["bring"] + " " if spec["missing"] else "")
                     + ("Enter " + ", ".join(info["secrets"]) + " on the Systems page, then try it. " if info["secrets"] else "")
                     + "An administrator reads the code and approves it on the Systems page.")}


def contract(spec: dict, tool_id: str) -> dict:
    """The approved code tool as a contract: capabilities (reads; changes behind approval) + its manifest."""
    info = spec["inspect"]
    reads = [m["name"] for m in info["methods"] if not m["change"]]
    changes = [m["name"] for m in info["methods"] if m["change"]]
    caps = []
    if reads:
        caps.append({"id": f"{tool_id}_read", "label": f"Use {spec['name']}", "side_effect": "read",
                     "description": f"{spec['purpose']}: " + "; ".join(m["doc"] for m in info["methods"] if not m["change"])[:600],
                     "tool": {"component": "ext:studio:CodeToolComponent@official", "params": {"tool_id": tool_id, "allowed_operations": ",".join(reads)}},
                     "requires": f"code.{tool_id}"})
    if changes:
        caps.append({"id": f"{tool_id}_change", "label": f"{spec['name']}: changes (with approval)", "side_effect": "write",
                     "approval": "required",
                     "description": "; ".join(m["doc"] for m in info["methods"] if m["change"])[:600],
                     "tool": {"component": "ext:studio:CodeToolComponent@official", "params": {"tool_id": tool_id, "allowed_operations": ",".join(changes)}},
                     "requires": f"code.{tool_id}"})
    manifest = {"purpose": spec["purpose"], "risk_level": info["level"], "hosts": info["hosts"], "changes": changes,
                "methods": {m["name"]: {"args": m["args"], "required": m["required"], "doc": m["doc"]} for m in info["methods"]},
                "secret_envs": {n: secret_env(tool_id, n) for n in info.get("secrets") or []}, "timeout_s": 60}
    return {"capabilities": caps, "tools": {"code": {tool_id: manifest}}}


def brief(tool_id: str, allowed: str = "") -> str:
    """One line for the agent: the tool's operations with their arguments."""
    m = existing().get(tool_id) or {}
    ok = {x.strip() for x in allowed.split(",") if x.strip()}
    ops = [f"{n}({', '.join(v.get('args') or [])}): {v.get('doc', '')}" for n, v in (m.get("methods") or {}).items() if not ok or n in ok]
    return f"tool '{tool_id}' operations (call with operation=<name>, arguments={{...}}): " + " | ".join(ops)


class InstallIn(BaseModel):
    packages: str = Field("", max_length=1000)       # empty: everything brought into data/toolkit/wheels


@router.get("/toolkit", summary="Libraries tools written by AI can use: bundled, brought (installed) and waiting to install")
async def toolkit(request: Request):
    from agent_studio.tools import _me

    await _me(request)
    return await run_in_threadpool(_engine, "GET", "/studio-engine/python", None, 30)


@router.post("/toolkit/install", summary="Install libraries brought as files into data/toolkit/wheels (no internet used)",
             dependencies=[roles.need("admin")])
async def toolkit_install(body: InstallIn, request: Request):
    from agent_studio.tools import _me

    me = await _me(request)
    out = await run_in_threadpool(_engine, "POST", "/studio-engine/toolkit/install", {"packages": body.packages}, 660)
    await activity.note(me["username"], "installed libraries for tools" if out.get("ok") else "tried to install libraries",
                        body.packages or "all brought files", out.get("output", "")[-200:])
    return out


@router.post("/tools/code/draft", summary="Need a tool nobody has? Agent Studio writes it (Python), tries it and asks an administrator",
             dependencies=[roles.need("builder")])
async def draft_endpoint(body: DraftIn, request: Request):
    from agent_studio.tools import _me

    me = await _me(request)
    out = await run_in_threadpool(draft, body.need, body.details, me["id"], me["username"], body.update_of)
    if out["outcome"] == "drafted":
        await activity.note(me["username"], "had a tool written by AI", out["tool_id"], f"risk {out['level']}: {body.need[:150]}")
    return out


@router.post("/tools/code/{request_id}/try", summary="Run one operation of a written tool in the engine (before approval)",
             dependencies=[roles.need("builder")])
async def try_endpoint(request_id: str, body: TryIn, request: Request):
    from agent_studio.tools import _me

    me = await _me(request)
    row = await run_in_threadpool(store.get_tool_draft, request_id)
    if not row or row["spec"].get("kind") != "code":
        raise HTTPException(404, "Not found")
    if row["status"] != "draft" and body.method in set(row["spec"]["inspect"]["methods"] and
                                                       [m["name"] for m in row["spec"]["inspect"]["methods"] if m["change"]]):
        raise HTTPException(409, "After approval, changes run only inside an agent, with a person's approval.")
    result = await run_in_threadpool(try_code, row["spec"], row["tool_id"], body.method, body.args, me["id"], me["username"])
    if row["status"] == "draft":
        await run_in_threadpool(store.update_tool_draft_spec, request_id, {**row["spec"], "test": result})
    return result


@router.post("/tools/code/{tool_id}/secret", status_code=204, summary="Save a value a written tool needs (kept encrypted)",
             dependencies=[roles.need("builder")])
async def secret_endpoint(tool_id: str, body: SecretIn, request: Request):
    from agent_studio.tools import _me

    me = await _me(request)
    rows = await run_in_threadpool(store.list_tool_drafts, None)
    spec = next((d["spec"] for d in rows if d["tool_id"] == tool_id and d["spec"].get("kind") == "code"), None)
    if not spec or body.name not in (spec["inspect"].get("secrets") or []):
        raise HTTPException(404, "This tool does not ask for that value")
    await run_in_threadpool(vault.put, secret_env(tool_id, body.name), body.value)
    await activity.note(me["username"], "saved a value for a written tool", tool_id, body.name)


if __name__ == "__main__":
    spec = {"name": "Mail", "purpose": "Read mail", "inspect": codetool.inspect_code(
        "class Tool:\n    SECRETS=['PW']\n    CHANGES=['move']\n    def unread(self, n: int = 5):\n        '''List unread.'''\n"
        "        return []\n    def move(self, uid: str):\n        '''Move one.'''\n        return uid\n")}
    c = contract(spec, "mail")
    assert [x["id"] for x in c["capabilities"]] == ["mail_read", "mail_change"]
    assert c["capabilities"][1]["side_effect"] == "write" and c["tools"]["code"]["mail"]["changes"] == ["move"]
    assert c["tools"]["code"]["mail"]["secret_envs"] == {"PW": "STUDIO_CODE_MAIL_PW"}
    print("codetools ok")
