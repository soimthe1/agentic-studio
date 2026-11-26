"""Project-standard config loader: config/config.yaml, then config.prod.yaml over it when APP_ENV=prod."""

import os
from pathlib import Path

import yaml

SECRET_SUFFIXES = ("password", "secret", "secret_key", "api_key", "token")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(config_dir: str | None = None) -> dict:
    root = Path(config_dir or os.environ.get("CONFIG_DIR", "/app/config"))

    def read(name: str) -> dict:
        """config/<name>, then config/local/<name> on top (the organisation's own values; never committed)."""
        base = yaml.safe_load((root / name).read_text(encoding="utf-8")) or {}
        local = root / "local" / name
        return _merge(base, yaml.safe_load(local.read_text(encoding="utf-8")) or {}) if local.is_file() else base

    cfg = read("config.yaml")
    if os.environ.get("APP_ENV") == "prod":
        prod = read("config.prod.yaml")
        unknown = _keys(prod) - _keys(cfg)
        if unknown:
            raise SystemExit(f"config.prod.yaml has keys config.yaml lacks: {sorted(unknown)}")
        cfg = _merge(cfg, prod)
    overlay = os.environ.get("STUDIO_CONFIG_OVERLAY")   # one extra file merged last (docker-compose.quickstart.yaml)
    if overlay:
        cfg = _merge(cfg, yaml.safe_load(Path(overlay).read_text(encoding="utf-8")) or {})
    return cfg


def _keys(d: dict, prefix: str = "") -> set[str]:
    out = set()
    for k, v in d.items():
        out.add(prefix + k)
        if isinstance(v, dict):
            out |= _keys(v, prefix + k + ".")
    return out


def langflow_env(cfg: dict) -> dict[str, str]:
    """Map the `langflow:` section to LANGFLOW_* variables. Secrets never come from YAML."""
    env = {}
    for key, value in cfg["langflow"].items():
        if key.endswith(SECRET_SUFFIXES):
            raise SystemExit(f"config.yaml langflow.{key} looks like a secret; secrets belong in .env")
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif isinstance(value, list):
            value = ",".join(str(v) for v in value)
        env[f"LANGFLOW_{key.upper()}"] = str(value)
    return env
