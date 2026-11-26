"""Sign-ins people enter on the Tools page (a system's user id + password). Encrypted with a key derived from
STUDIO_ENGINE_SECRET and kept next to the approved contracts (<contracts_dir>/.vault/<NAME>), where the engine's
tools read them (studio_tools.core.vault). Never returned by any endpoint, never logged, never in a contract file."""

from __future__ import annotations

import base64
import hashlib
import os
import re

from fastapi import HTTPException

from agent_studio import capabilities


def _fernet():
    from cryptography.fernet import Fernet

    secret = os.environ.get("STUDIO_ENGINE_SECRET") or ""
    if not secret:
        raise HTTPException(503, "Saving sign-ins needs STUDIO_ENGINE_SECRET to be set for the app and the engine")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"studio-vault:" + secret.encode()).digest()))


def _path(name: str):
    if not re.fullmatch(r"[A-Z0-9_]{1,120}", name):
        raise ValueError("bad vault name")
    return capabilities.contracts_dir() / ".vault" / name


def env_name(tool_id: str) -> str:
    return f"STUDIO_TOOL_{re.sub(r'[^A-Z0-9]', '_', tool_id.upper())}_SECRET"


def put(name: str, value: str) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_fernet().encrypt(value.encode()))
    tmp.replace(path)


def get(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    path = _path(name)
    if not path.is_file():
        return None
    try:
        return _fernet().decrypt(path.read_bytes()).decode()
    except Exception:
        return None


def has(name: str) -> bool:
    return bool(os.environ.get(name)) or _path(name).is_file()


def drop(name: str) -> None:
    _path(name).unlink(missing_ok=True)
