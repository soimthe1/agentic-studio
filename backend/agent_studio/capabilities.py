"""Capability registry: config/capabilities.yaml (what agents can do, existing apps) + config/tools.yaml
(which systems are actually set up). Read fresh on each call so edits apply without a restart."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_studio import settings


def _config_dir() -> Path:
    import os

    return Path(os.environ.get("CONFIG_DIR") or settings.REPO / "config")


def _load(name: str) -> dict:
    """config/local/<name> (this organisation's own file, never committed) wins over the committed example."""
    local = _config_dir() / "local" / name
    path = local if local.is_file() else _config_dir() / name
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _lookup(tools: dict, dotted: str):
    node = tools
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def status(cap: dict, tools: dict) -> tuple[str, bool]:
    """('ready' | 'needs_setup', is_test_system) for one capability."""
    req = cap.get("requires")
    if not req:
        return "ready", False
    target = _lookup(tools, req)
    if not target:
        return "needs_setup", False
    mock = isinstance(target, dict) and bool(target.get("mock"))
    return "ready", mock


def contracts_dir() -> Path:
    """Approved system contracts written by Agent Studio (Tools page) - shared with the engine's tools."""
    return settings.path(settings.load()["app"]["contracts_dir"])


def _contracts() -> list[dict]:
    """App capability contracts (spec 02 section 5): config/capabilities.d/*.yaml (hand-written, an app's
    agent-studio.yaml) and <contracts_dir>/*.yaml (learned and approved in Agent Studio). Each may add `capabilities:`,
    `apps:` and `tools:` (connector settings, same shape as tools.yaml). The Designer needs no change."""
    out = []
    for folder in (_config_dir() / "capabilities.d", contracts_dir()):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                out.append(data)
    return out


def tools_config() -> dict:
    """tools.yaml plus the connector settings of approved contracts (built-in names always win)."""
    tools = _load("tools.yaml")
    for contract in _contracts():
        for section, entries in (contract.get("tools") or {}).items():
            if isinstance(entries, dict):
                tools.setdefault(section, {})
                for name, value in entries.items():
                    tools[section].setdefault(name, value)
    return tools


def catalog() -> dict:
    caps = _load("capabilities.yaml")
    tools = tools_config()
    own = _load("apps.yaml").get("apps")   # config/local/apps.yaml: the organisation's own applications
    entries, apps = list(caps.get("capabilities", [])), list(own if own is not None else caps.get("apps", []))
    known = {c["id"] for c in entries} | {a["id"] for a in apps}
    for contract in _contracts():                       # contracts never override built-in ids
        entries += [c for c in contract.get("capabilities", []) if isinstance(c, dict) and c.get("id") not in known]
        apps += [a for a in contract.get("apps", []) if isinstance(a, dict) and a.get("id") not in known]
    out = []
    for cap in entries:
        st, mock = status(cap, tools)
        out.append({**cap, "status": st, "test_system": mock})
    return {"capabilities": out, "apps": apps}


def by_id() -> dict[str, dict]:
    return {c["id"]: c for c in catalog()["capabilities"]}


def notify_channels() -> list[dict]:
    """Pre-configured notification channels (names only; addresses stay in tools.yaml)."""
    return [{"id": k, "type": v.get("type"), "needs_approval": bool(v.get("requires_approval", True))}
            for k, v in (_load("tools.yaml").get("notify") or {}).items()]


def app_brief(app: str, known: dict | None = None) -> str:
    """One line telling an agent exactly how to call an app: its read operations, actions (+ fields), targets.
    known = the engine's own list for this connector (built-in monitors define theirs in code)."""
    a = (tools_config().get("apps") or {}).get(app) or {}
    actions = a.get("actions") if isinstance(a.get("actions"), dict) else {}
    acts = "; ".join(n + (f" (fields: {', '.join(v.get('body') or [])})" if v.get("body") else "") for n, v in actions.items())         or ", ".join((known or {}).get("actions") or [])
    reads = list(a["operations"]) if isinstance(a.get("operations"), dict) else list((known or {}).get("reads") or [])
    parts = [f"app '{app}' (call the tool with app='{app}')"]
    if reads:
        parts.append("operation is one of: " + ", ".join(reads))
    if acts:
        parts.append("actions: " + acts)
    if a.get("allowed_targets"):
        parts.append("targets: " + ", ".join(a["allowed_targets"]))
    return "; ".join(parts)
