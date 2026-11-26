"""Agent Studio app: sign-in, the Agent Studio API and (in production) the built web app, in one FastAPI process.

Dev:   .\\scripts\\dev.ps1 start   (uvicorn agent_studio.app:app --reload; the web app runs on Vite)
Prod:  container `agent-studio` (docker-compose.prod.yaml), serving frontend/dist from app.frontend_dir.
"""

from __future__ import annotations

import logging
import mimetypes

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from agent_studio import accounts, activity, api, auth, brand, codetools, designs, mcp, health, lifecycle, quality, settings, setup, sharing, skills, tools

# Windows hosts can map .js to text/plain in the registry; browsers then refuse the web app's modules.
for _type, _ext in (("text/javascript", ".js"), ("text/javascript", ".mjs"), ("text/css", ".css"),
                    ("image/svg+xml", ".svg"), ("font/woff2", ".woff2")):
    mimetypes.add_type(_type, _ext)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

cfg = settings.load()
app = FastAPI(title="Agent Studio", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth.router)
app.include_router(api.router)
app.include_router(accounts.router)
app.include_router(setup.router)
app.include_router(designs.router)
app.include_router(codetools.router)   # before tools: its /tools/code/... paths are more specific
app.include_router(tools.router)
app.include_router(skills.router)
app.include_router(activity.router)
app.include_router(brand.router)
app.include_router(mcp.router)
app.include_router(health.router)
app.include_router(sharing.router)     # before lifecycle: its /agents/{id}/{action} would catch /share and /tests
app.include_router(quality.router)
app.include_router(lifecycle.router)


@app.middleware("http")
async def _framing(request, call_next):
    """Only this app itself and the configured chat apps (app.embed_origins, e.g. the chat app) may show it in a frame."""
    response = await call_next(request)
    origins = " ".join(str(o).rstrip("/") for o in cfg["app"].get("embed_origins") or [])
    response.headers["Content-Security-Policy"] = f"frame-ancestors 'self' {origins}".strip()
    return response


@app.on_event("startup")
async def _watch_failures():
    import asyncio

    setup.load_keys()   # API keys saved on Settings -> AI models

    from agent_studio.watch import failures

    asyncio.get_event_loop().create_task(failures.loop())   # app.failure_check_minutes; 0 = off


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


FRONTEND = settings.path(cfg["app"]["frontend_dir"])


@app.get("/{path:path}", include_in_schema=False)
async def web_app(path: str):
    """Built web app (production). Unknown paths fall back to index.html for client-side routing."""
    index = FRONTEND / "index.html"
    if not index.is_file():
        return JSONResponse({"detail": "web app not built; in development open the Vite dev server"}, status_code=404)
    target = (FRONTEND / path).resolve()
    if path and target.is_file() and FRONTEND.resolve() in target.parents:
        return FileResponse(target)
    return FileResponse(index, headers={"Cache-Control": "no-store"})
