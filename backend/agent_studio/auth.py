"""Agent Studio sign-in: local accounts (ldap.enabled: false) or an Active Directory bind, then an engine session.

Same approach and config shape as a sibling app iip_auth/ldap_auth.py: the user
binds with their own UPN; their memberOf groups map to roles through ``ldap.group_map``
('' = nobody, ``everybody`` = any account, else an AD group CN/DN). After the bind succeeds the
engine opens a normal session for the user (engine.open_session), so the builder canvas and every
engine call carry the user's own identity.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from ldap3 import SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from agent_studio import engine, settings

log = logging.getLogger("agent_studio.auth")
STATIC = Path(__file__).parent / "static"
EVERYBODY = "everybody"

# Per-IP sign-in attempts per minute (in-memory: one app process).
_ATTEMPTS: dict[str, list[float]] = {}
MAX_PER_MINUTE = 10



def _name() -> str:
    from agent_studio.brand import brand

    return brand()["name"]


def wanted_groups(value) -> list[str]:
    """A group_map entry: '' (nobody), 'everybody', one group, a comma list, or a YAML list of groups (CN or DN)."""
    items = value if isinstance(value, list) else str(value or "").split(",") if "cn=" not in str(value or "").lower() else [value]
    return [str(x).strip().lower() for x in items if str(x).strip()]


def _cn(dn: str) -> str:
    first = dn.split(",", 1)[0].strip()
    return (first[3:] if first.lower().startswith("cn=") else first).strip().lower()


def role_for(group_map: dict, groups: list[str], username: str = "") -> str | None:
    """First role (admin > builder > user) whose group_map entry matches; None = no access. An entry is an AD group
    (CN or DN), 'everybody', or 'user:<account>' for one named person."""
    cns = {_cn(g) for g in groups}
    me = (username or "").strip().lower()
    for role in ("admin", "builder", "user"):
        for wanted in wanted_groups(group_map.get(role)):
            if wanted == EVERYBODY or _cn(wanted) in cns or (me and wanted == f"user:{me}"):
                return role
    return None


def authenticate(ldap: dict, username: str, password: str) -> dict | None:
    """Bind as the user and read their own entry. None on any failure (never says which)."""
    name = (username or "").strip().split("\\")[-1].split("@")[0]
    if not name or not password:  # an empty password is an anonymous bind that "succeeds"
        return None
    suffix = ".".join(p.split("=", 1)[1] for p in ldap["user_search_base"].split(",") if p.strip().lower().startswith("dc="))
    try:
        conn = Connection(Server(ldap["server_uri"], use_ssl=ldap["use_tls"]), user=f"{name}@{suffix}",
                          password=password, auto_bind=True)
    except LDAPException:
        log.info("sign-in rejected")
        return None
    try:
        conn.search(ldap["user_search_base"], f"(&(objectClass=user)(sAMAccountName={escape_filter_chars(name)}))",
                    SUBTREE, attributes=["objectGUID", "sAMAccountName", "displayName", "mail", "memberOf"])
        if not conn.entries:
            return None
        e = conn.entries[0]
        return {"sub": str(e.objectGUID.value), "username": str(e.sAMAccountName.value).lower(),
                "name": str(e.displayName.value) if "displayName" in e else name,
                "email": str(e.mail.value) if "mail" in e and e.mail.value else None,
                "groups": [str(g) for g in (e.memberOf.values if "memberOf" in e else [])]}
    finally:
        conn.unbind()


def _rate_limited(request: Request) -> bool:
    import time

    ip = request.client.host if request.client else "?"
    now = time.monotonic()
    recent = [t for t in _ATTEMPTS.get(ip, []) if now - t < 60]
    recent.append(now)
    _ATTEMPTS[ip] = recent
    return len(recent) > MAX_PER_MINUTE


def _page(error: str = "", username: str = "", status: int = 200, first: bool = False) -> HTMLResponse:
    """The sign-in page; first=True: the one-time form that creates the administrator (local accounts)."""
    from agent_studio.accounts import MIN_PASSWORD, local
    from agent_studio.brand import brand as _brand

    brand = _brand()
    if first:
        words = {"{{TITLE}}": "Create the administrator", "{{ACTION}}": "/auth/setup", "{{BUTTON}}": "Create and sign in",
                 "{{HINT}}": f"First start: choose the administrator's username and a password of at least {MIN_PASSWORD} "
                             "characters. The administrator then adds everyone else on Settings.",
                 "{{FOOT}}": "Shown once, until the first account exists."}
    elif local():
        words = {"{{TITLE}}": "Sign in", "{{ACTION}}": "/auth/login", "{{BUTTON}}": "Sign in",
                 "{{HINT}}": f"Use the account your {brand['name']} administrator gave you.",
                 "{{FOOT}}": "No account yet? Ask your administrator."}
    else:
        words = {"{{TITLE}}": "Sign in", "{{ACTION}}": "/auth/login", "{{BUTTON}}": "Sign in",
                 "{{HINT}}": "Use your network account, the same username and password you use to sign in to Windows.",
                 "{{FOOT}}": f"Access is granted by your {brand['name']} group membership."}
    page = (STATIC / "login.html").read_text(encoding="utf-8")
    for key, value in (("{{BRAND}}", brand["name"]), ("{{BRAND_AR}}", brand["name_ar"]),
                       ("{{TAGLINE}}", brand["tagline"]), ("{{USERNAME}}", username), ("{{ERROR}}", error), *words.items()):
        page = page.replace(key, html.escape(value))
    page = page.replace("{{ERROR_HIDDEN}}", "" if error else "hidden").replace("{{INVALID}}", "true" if error else "false")
    page = page.replace("{{CONFIRM_HIDDEN}}", "" if first else "hidden")
    return HTMLResponse(page, status_code=status, headers={"Cache-Control": "no-store"})


async def _first_run() -> bool:
    """Local accounts and none made yet: the sign-in page creates the administrator."""
    from agent_studio import accounts, store

    return accounts.local() and not await run_in_threadpool(store.accounts)


router = APIRouter(prefix="/auth", include_in_schema=False)


@router.get("/login")
async def login_page():
    return _page(first=await _first_run())


@router.get("/login.js")
async def login_js():
    return Response((STATIC / "login.js").read_text(encoding="utf-8"), media_type="text/javascript")


_ASSETS = {"logo.svg": "image/svg+xml", "favicon.png": "image/png", "inter.woff2": "font/woff2",
           "plex-arabic-700.woff2": "font/woff2"}


@router.get("/assets/{name}")
async def asset(name: str):
    if name not in _ASSETS:
        raise HTTPException(404)
    return Response((STATIC / name).read_bytes(), media_type=_ASSETS[name],
                    headers={"Cache-Control": "public, max-age=86400"})


@router.post("/login")
async def login(request: Request, username: str = Form(""), password: str = Form("")):
    if _rate_limited(request):
        return _page("Too many attempts. Wait a minute and try again.", username, 429)
    from agent_studio import accounts

    if accounts.local():
        identity = await run_in_threadpool(accounts.identity, username, password)
        role = identity and identity.pop("role")
    else:
        ldap = settings.load()["ldap"]
        if not ldap.get("server_uri") or not ldap.get("user_search_base"):
            return _page("Directory sign-in is on, but ldap.server_uri / user_search_base are empty in the settings.",
                         username, 503)
        identity = await run_in_threadpool(authenticate, ldap, username, password)
        role = identity and role_for(ldap["group_map"], identity["groups"], identity.get("username", ""))
    if not identity:
        return _page("Username or password is incorrect.", username, 401)
    if not role:
        return _page(f"Your account is not in a {_name()} access group. Ask your administrator.", username, 403)
    return await _signed_in(identity, role, username)


@router.post("/setup")
async def first_admin(request: Request, username: str = Form(""), password: str = Form(""), confirm: str = Form("")):
    """First start with local accounts: create the administrator, then sign in as them."""
    from agent_studio import accounts, store

    if _rate_limited(request):
        return _page("Too many attempts. Wait a minute and try again.", username, 429, first=True)
    if not await _first_run():
        return RedirectResponse("/auth/login", status_code=303)
    username = username.strip().lower()
    why = accounts.problem(username, password) or ("" if password == confirm else "The two passwords differ.")
    if why:
        return _page(why, username, 422, first=True)
    if not await run_in_threadpool(store.add_account, username, "", accounts.hash_password(password), "admin", True):
        return RedirectResponse("/auth/login", status_code=303)   # someone else was faster
    identity = await run_in_threadpool(accounts.identity, username, password)
    identity.pop("role")
    return await _signed_in(identity, "admin", username)


async def _signed_in(identity: dict, role: str, username: str):
    from agent_studio import store

    await run_in_threadpool(store.set_person, identity["username"], role)   # roles.py checks it on every call
    from agent_studio import activity
    await activity.note(identity["username"], "signed in", role)
    try:
        cookies = await engine.open_session(identity)
    except HTTPException as exc:
        if exc.status_code == 403:
            return _page(f"Your {_name()} account is disabled. Ask your administrator.", username, 403)
        log.error("engine refused to open a session: %s", exc.detail)
        return _page(f"{_name()} is not available right now. Try again in a minute.", username, 503)
    response = RedirectResponse("/", status_code=303)
    for c in cookies:
        response.set_cookie(c["name"], c["value"], max_age=c["max_age"], path="/", httponly=c["httponly"],
                            samesite=c["samesite"], secure=c["secure"])
    return response


@router.get("/logout")
async def logout(request: Request):
    await engine.close_session(request)
    response = RedirectResponse("/auth/login", status_code=303)
    for name in engine.SESSION_COOKIES:
        response.delete_cookie(name, path="/")
    return response
