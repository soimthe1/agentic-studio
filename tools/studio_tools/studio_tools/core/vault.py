"""Sign-ins entered on Agent Studio's Tools page (a system's user id + password), kept encrypted next to the approved
contracts: <contracts_dir>/.vault/<NAME>. The key comes from STUDIO_ENGINE_SECRET, which the app and the engine
share. Only read here; the app writes. A value set in the environment still wins (administrators may prefer it)."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path


def _fernet():
    from cryptography.fernet import Fernet

    secret = os.environ.get("STUDIO_ENGINE_SECRET") or ""
    if not secret:
        return None
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"studio-vault:" + secret.encode()).digest()))


def read(folder: str | Path | None, name: str) -> str | None:
    if not folder or not re.fullmatch(r"[A-Z0-9_]{1,120}", name or ""):
        return None
    path = Path(folder) / ".vault" / name
    f = _fernet()
    if f is None or not path.is_file():
        return None
    try:
        return f.decrypt(path.read_bytes()).decode()
    except Exception:  # wrong key (secret rotated) or damaged: treated as "no saved sign-in"
        return None
