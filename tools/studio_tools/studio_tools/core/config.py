"""Named-connection registry: $CONFIG_DIR/tools.yaml (CONFIG_DIR defaults to /app/config).

The YAML is the allowlist: a tool can only reach a connection, channel, table, path or host that an
administrator wrote here. Secrets are never in the YAML; each connection names the environment variable that
holds its password or token (``password_env`` / ``token_env`` / ``*_env``), resolved at call time.
See tools.example.yaml for the full schema.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

SECTIONS = ("sql", "apps", "knowledge", "notify", "documents", "files", "web", "code")


def config_path() -> Path:
    explicit = os.environ.get("STUDIO_TOOLS_CONFIG")
    if explicit:
        return Path(explicit)
    root = Path(os.environ.get("CONFIG_DIR", "/app/config"))
    local = root / "local" / "tools.yaml"            # this organisation's own file (never committed) wins
    return local if local.is_file() else root / "tools.yaml"


_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read tools.yaml, cached by mtime so an admin edit is picked up without an engine restart."""
    p = Path(path) if path else config_path()
    try:
        mtime = p.stat().st_mtime
    except FileNotFoundError:
        raise ConfigError(f"tools config not found at {p} (set CONFIG_DIR or STUDIO_TOOLS_CONFIG)") from None
    hit = _cache.get(str(p))
    if hit and hit[0] == mtime:
        return _with_contracts(hit[1])  # contracts are re-read every call: approving a system needs no restart
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"tools config {p} is not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"tools config {p} must be a mapping")
    unknown = set(data) - set(SECTIONS) - {"version", "contracts_dir"}
    if unknown:
        raise ConfigError(f"tools config has unknown sections: {sorted(unknown)}")
    _check_no_inline_secrets(data)
    _cache[str(p)] = (mtime, data)
    return _with_contracts(data)


def _with_contracts(data: dict[str, Any]) -> dict[str, Any]:
    """Add connectors of approved system contracts (<contracts_dir>/*.yaml, `tools:` part). tools.yaml names win;
    contracts can only add, never change, what an administrator wrote here. Re-read when the folder changes."""
    folder = Path(data["contracts_dir"]) if data.get("contracts_dir") else None
    if not folder or not folder.is_dir():
        return data
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in data.items()}
    for path in sorted(folder.glob("*.yaml")):
        try:
            extra = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("tools") or {}
        except yaml.YAMLError:
            continue
        _check_no_inline_secrets(extra)
        for section, entries in extra.items():
            if section in ("apps", "notify", "code") and isinstance(entries, dict):   # code: tools written by AI, approved
                merged.setdefault(section, {})
                for name, value in entries.items():
                    merged[section].setdefault(name, value)
    return merged


_SECRET_KEYS = {"password", "token", "secret", "api_key", "apikey", "key"}


def _check_no_inline_secrets(node: Any, where: str = "") -> None:
    """Refuse a config that carries a secret value inline instead of naming an env var."""
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).lower() in _SECRET_KEYS and v not in (None, ""):
                raise ConfigError(f"inline secret '{where}{k}' in tools config; use '{k}_env' naming an env var")
            _check_no_inline_secrets(v, f"{where}{k}.")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_no_inline_secrets(v, f"{where}{i}.")


def get_connection(section: str, name: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the named connection from a section or fail: unknown names are rejected (allowlist)."""
    cfg = load_config() if cfg is None else cfg
    entries = cfg.get(section) or {}
    name = (name or "").strip()
    if name not in entries:
        known = ", ".join(sorted(entries)) or "none configured"
        raise ConfigError(f"'{name}' is not an approved {section} connection (known: {known})")
    conn = dict(entries[name] or {})
    conn["_name"] = name
    return conn


def list_connections(section: str, cfg: dict[str, Any] | None = None) -> list[str]:
    try:
        cfg = load_config() if cfg is None else cfg
    except ConfigError:
        return []
    return sorted((cfg.get(section) or {}).keys())


def secret(conn: dict[str, Any], key: str, required: bool = True) -> str | None:
    """Resolve ``<key>_env`` from the environment. The value is never logged or returned to the LLM."""
    env_name = conn.get(f"{key}_env")
    if not env_name:
        if required:
            raise ConfigError(f"connection '{conn.get('_name')}' has no {key}_env configured")
        return None
    value = os.environ.get(str(env_name))
    if not value:   # entered on the Tools page: kept encrypted next to the approved contracts
        from . import vault
        try:
            folder = load_config().get("contracts_dir")
        except ConfigError:
            folder = None
        value = vault.read(folder, str(env_name))
    if not value:
        raise ConfigError(f"no saved sign-in for '{conn.get('_name')}': enter its user id and password on the Tools page "
                          f"(or set {env_name})")
    return value
