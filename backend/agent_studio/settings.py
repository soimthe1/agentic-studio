"""Settings, per the Project Standard: config/config.yaml (+ config.prod.yaml when APP_ENV=prod) for
everything non-secret, environment variables for secrets. In development the repo-root .env is loaded
here (never overriding variables already set), so dev.ps1, VS Code, the debugger and tests behave alike."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SECRET_SUFFIXES = ("password", "secret", "secret_key", "api_key", "token")


def _load_dotenv() -> None:
    env = REPO / ".env"
    if os.environ.get("APP_ENV") == "prod" or not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _keys(d: dict, prefix: str = "") -> set[str]:
    out = set()
    for k, v in d.items():
        out.add(prefix + k)
        if isinstance(v, dict):
            out |= _keys(v, prefix + k + ".")
    return out


def _reject_secrets(d: dict, prefix: str = "") -> None:
    for k, v in d.items():
        if isinstance(v, dict):
            _reject_secrets(v, prefix + k + ".")
        elif k.endswith(SECRET_SUFFIXES):
            raise SystemExit(f"config key {prefix}{k} looks like a secret; secrets belong in .env (refer to them with *_env)")


@lru_cache(maxsize=1)
def load() -> dict:
    _load_dotenv()
    root = Path(os.environ.get("CONFIG_DIR") or REPO / "config")

    def read(name: str) -> dict:
        """config/<name>, then config/local/<name> on top (this organisation's values; never committed)."""
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
    _reject_secrets(cfg)
    return _with_setup(cfg)


def setup_file(cfg: dict) -> Path:
    """Model servers chosen on Settings (setup.py). Next to the approved contracts, so the engine reads it too."""
    return path(cfg["app"]["contracts_dir"]) / ".setup" / "ai.json"


def _with_setup(cfg: dict) -> dict:
    import json

    f = setup_file(cfg)
    if not f.is_file():
        return cfg
    try:
        saved = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return cfg
    return {**cfg, "ai": {**cfg["ai"], **saved}}   # whole profiles: a saved profile replaces the file's one


def secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing secret {name} (set it in .env / .env.prod)")
    return value


def path(value: str) -> Path:
    """Config paths may be relative to the repo (dev) or absolute (container)."""
    p = Path(value)
    return p if p.is_absolute() else REPO / p
