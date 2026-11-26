"""Settings -> AI models: point the studio at your model server from the browser, no file editing.

Saved profiles go to <contracts_dir>/.setup/ai.json (settings.load merges them over config ai:), API keys to the
vault. The engine is told at once (/studio-engine/models) and reads the same file when it starts.
"""

from __future__ import annotations

import json
import os

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import ai_providers, roles, settings, vault
from agent_studio.api import PREFIX

PLACEHOLDERS = ("your-model-name", "__SET_ME__")
PROFILES = ("default", "reasoning")
router = APIRouter(prefix=PREFIX, tags=["Agent Studio"])


def key_name(profile: str) -> str:
    return f"STUDIO_AI_KEY_{profile.upper()}"


def load_keys() -> None:
    """API keys saved on Settings -> the environment, where ai_providers reads them (api_key_env)."""
    for p in PROFILES:
        name = key_name(p)
        if not os.environ.get(name):
            try:
                value = vault.get(name)
            except Exception:    # no STUDIO_ENGINE_SECRET: nothing can have been saved
                value = None
            if value:
                os.environ[name] = value


def needs_setup() -> bool:
    d = settings.load()["ai"].get("default") or {}
    return any(p in str(d.get(k, "")) for p in PLACEHOLDERS for k in ("model", "base_url")) or not d.get("model")


class ProfileIn(BaseModel):
    provider: str = Field(pattern="^(openai|ollama)$")
    base_url: str = Field(min_length=8, max_length=300, pattern="^https?://")
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(None, max_length=500)   # None = keep the saved one; "" = remove it


class ModelsIn(BaseModel):
    default: ProfileIn
    reasoning: ProfileIn | None = None   # None = same as default


def _profile(p: ProfileIn, name: str, old: dict) -> dict:
    out = {"provider": p.provider, "base_url": p.base_url.rstrip("/"), "model": p.model.strip(), "suppress_thinking": True}
    if old.get("fallback"):
        out["fallback"] = old["fallback"]
    has_key = bool(p.api_key) or (p.api_key is None and bool(vault.get(key_name(name))))
    if p.provider == "openai" and has_key:
        out["api_key_env"] = key_name(name)
    return out


def _check(ai: dict, name: str) -> dict:
    ai_providers.configure(ai, base_dir=settings.REPO)
    try:
        return ai_providers.check(name)
    finally:
        ai_providers.configure(settings.load()["ai"], base_dir=settings.REPO)


@router.get("/setup/models", summary="The model servers agents use (administrator)", dependencies=[roles.need("admin")])
async def current():
    ai = settings.load()["ai"]
    view = {}
    for name in PROFILES:
        p = ai.get(name) or {}
        view[name] = {"provider": p.get("provider", ai["default"].get("provider")), "base_url": p.get("base_url", ""),
                      "model": p.get("model", ""), "has_key": bool(p.get("api_key_env") and os.environ.get(p["api_key_env"]))}
    return {**view, "needs_setup": needs_setup(), "saved_here": settings.setup_file(settings.load()).is_file()}


@router.post("/setup/models/test", summary="Try one model server: reachable, and is the model there?",
             dependencies=[roles.need("admin")])
async def test(body: ProfileIn):
    if body.api_key:
        os.environ["STUDIO_AI_KEY_TRY"] = body.api_key
    elif body.api_key is None:
        os.environ["STUDIO_AI_KEY_TRY"] = vault.get(key_name("default")) or ""
    trial = {"provider": body.provider, "base_url": body.base_url.rstrip("/"), "model": body.model.strip()}
    if body.provider == "openai" and os.environ.get("STUDIO_AI_KEY_TRY"):
        trial["api_key_env"] = "STUDIO_AI_KEY_TRY"
    try:
        out = await run_in_threadpool(_check, {"default": trial}, "default")
    finally:
        os.environ.pop("STUDIO_AI_KEY_TRY", None)
    if not out.get("ok") and out.get("models") and not out.get("model_available"):
        out["error"] = f"The server answers, but has no model named {trial['model']}. Pick one from its list."
    return out


def _one_endpoint_each(profiles: dict) -> str:
    """The engine has one address per provider kind: two different addresses of the same kind cannot both work."""
    seen: dict[str, str] = {}
    for p in profiles.values():
        if seen.setdefault(p["provider"], p["base_url"]) != p["base_url"]:
            return (f"Both models use {p['provider']} servers at different addresses. The engine supports one address "
                    "per kind: use the same server for both, or one Ollama and one OpenAI-compatible server.")
    return ""


@router.put("/setup/models", summary="Save the model servers (tested first) and tell the engine",
            dependencies=[roles.need("admin")])
async def save(body: ModelsIn):
    cfg = settings.load()
    old = cfg["ai"]
    chosen = {"default": body.default, "reasoning": body.reasoning or body.default}
    for name, p in chosen.items():
        if p.api_key:
            vault.put(key_name(name), p.api_key)
            os.environ[key_name(name)] = p.api_key
        elif p.api_key == "":
            vault.drop(key_name(name))
            os.environ.pop(key_name(name), None)
    profiles = {name: _profile(p, name, old.get(name) or {}) for name, p in chosen.items()}
    clash = _one_endpoint_each(profiles)
    if clash:
        raise HTTPException(422, clash)
    trial = {**old, **profiles}
    for name in profiles:
        out = await run_in_threadpool(_check, trial, name)
        if not out.get("ok"):
            raise HTTPException(422, f"The {'thorough' if name == 'reasoning' else 'everyday'} model did not answer: "
                                     f"{out.get('error') or 'the model is not on that server'}. Nothing was saved.")
    f = settings.setup_file(cfg)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    settings.load.cache_clear()
    engine = await tell_engine()
    return {**(await current()), "engine": engine}


async def tell_engine() -> str:
    """The engine re-reads the saved models and refreshes every person's model addresses. '' = done."""
    from agent_studio import engine

    cfg = engine._cfg()
    try:
        async with httpx.AsyncClient(base_url=cfg["url"], timeout=30, trust_env=False) as c:
            r = await c.post("/studio-engine/models", headers={"X-Studio-Engine-Secret": settings.secret(cfg["secret_env"])})
        return "" if r.status_code == 200 else f"engine said {r.status_code}: restart it to use the new models"
    except httpx.HTTPError:
        return "engine not reachable: it uses the new models when it next starts"


if __name__ == "__main__":
    a = {"provider": "openai", "base_url": "http://a:8000/v1"}
    assert not _one_endpoint_each({"default": a, "reasoning": dict(a)})
    assert _one_endpoint_each({"default": a, "reasoning": {**a, "base_url": "http://b:8000/v1"}})
    assert not _one_endpoint_each({"default": a, "reasoning": {"provider": "ollama", "base_url": "http://b:11434"}})
    print("setup ok")
