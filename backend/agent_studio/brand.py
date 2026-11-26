"""The product's name and look come from ONE brand.json, never from code (single source of truth).

branding/brand.local/brand.json (the organisation's own, git-ignored) wins over branding/brand.example/brand.json
(the neutral public brand). Fields: name, name_ar, tagline, tagline_ar, logo, favicon, theme (files in that folder).
The web app, the API, messages and the engine canvas (at image build) all read it. Public (the sign-in page needs it).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from agent_studio import settings

router = APIRouter(prefix="/api/studio/v1", tags=["Brand"])
NEUTRAL = {"name": "Agentic Studio", "name_ar": "", "tagline": "AI agents in plain words", "tagline_ar": "",
           "logo": "", "favicon": "", "theme": ""}


def folder() -> Path:
    root = Path(os.environ.get("BRAND_ROOT") or settings.REPO / "branding")
    local = root / "brand.local"
    return local if (local / "brand.json").is_file() else root / "brand.example"


@lru_cache(maxsize=1)
def brand() -> dict:
    try:
        data = json.loads((folder() / "brand.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**NEUTRAL, **{k: str(v) for k, v in data.items() if v not in (None, "")}}


def title() -> str:
    """'Name - الاسم' for browser tabs and messages."""
    b = brand()
    return f"{b['name']} - {b['name_ar']}" if b.get("name_ar") else b["name"]


def _file(key: str) -> Path | None:
    name = brand().get(key) or ""
    p = folder() / name
    return p if name and p.is_file() and p.resolve().parent == folder().resolve() else None


@router.get("/brand", summary="Product name, Arabic name and tagline (from brand.json)")
async def get_brand():
    b = brand()
    return {k: b[k] for k in ("name", "name_ar", "tagline", "tagline_ar")} | {
        "title": title(), "custom_logo": _file("logo") is not None, "favicon": _file("favicon") is not None,
        "theme": _file("theme") is not None}


@router.get("/brand/{what}", summary="The brand's logo, favicon or theme file")
async def get_file(what: str):
    if what not in ("logo", "favicon", "theme"):
        raise HTTPException(404, "Not found")
    p = _file(what)
    if not p:
        raise HTTPException(404, "This brand has no such file")
    return FileResponse(p, headers={"Cache-Control": "max-age=300"})
