"""Local accounts: sign-in without a directory (config ldap.enabled: false, the default for a new install).

The first visit to the sign-in page creates the administrator; the administrator then adds people on Settings.
Passwords are stored as scrypt hashes (standard library). With ldap.enabled: true this module is unused.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import roles, settings, store
from agent_studio.api import PREFIX
from agent_studio.engine import Engine

MIN_PASSWORD = 10
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{1,59}")
ROLES = ("user", "builder", "admin")


def local() -> bool:
    """True when people sign in with accounts kept here (no directory)."""
    return not settings.load()["ldap"].get("enabled")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), digest)


def problem(username: str, password: str) -> str:
    """Why a new account cannot be made ('' = fine)."""
    if not NAME.fullmatch(username):
        return "Use 2-60 characters for the username: lower-case letters, digits, dot, dash or underscore."
    if len(password) < MIN_PASSWORD:
        return f"Use a password of at least {MIN_PASSWORD} characters."
    return ""


def identity(username: str, password: str) -> dict | None:
    """The local equivalent of auth.authenticate: None on any failure."""
    row = store.account((username or "").strip().lower())
    if not row or not password or not verify(password, row["pw_hash"]):
        return None
    return {"sub": f"local:{row['username']}", "username": row["username"], "name": row["name"] or row["username"],
            "email": None, "role": row["role"]}


# ---------------------------------------------------------------- administrator: people who may sign in
router = APIRouter(prefix=PREFIX, tags=["Agent Studio"])


class AccountIn(BaseModel):
    username: str = Field(min_length=2, max_length=60)
    name: str = Field("", max_length=120)
    password: str = Field(min_length=1, max_length=200)
    role: str = Field("user", pattern="^(user|builder|admin)$")


class AccountPatch(BaseModel):
    role: str | None = Field(None, pattern="^(user|builder|admin)$")
    password: str | None = Field(None, max_length=200)


def _need_local():
    if not local():
        raise HTTPException(409, "People sign in with the directory (ldap.enabled: true); manage access there.")


@router.get("/accounts", summary="People who may sign in (local accounts)", dependencies=[roles.need("admin")])
async def list_accounts():
    _need_local()
    return await run_in_threadpool(store.accounts)


@router.post("/accounts", status_code=201, summary="Add a person (local accounts)", dependencies=[roles.need("admin")])
async def add(body: AccountIn):
    _need_local()
    username = body.username.strip().lower()
    why = problem(username, body.password)
    if why:
        raise HTTPException(422, why)
    if not await run_in_threadpool(store.add_account, username, body.name.strip(), hash_password(body.password), body.role):
        raise HTTPException(409, f"{username} already exists.")
    await run_in_threadpool(store.set_person, username, body.role)
    return {"username": username, "role": body.role}


async def _admins_left(without: str) -> int:
    rows = await run_in_threadpool(store.accounts)
    return sum(1 for r in rows if r["role"] == "admin" and r["username"] != without)


@router.patch("/accounts/{username}", summary="Change a person's role or set a new password", dependencies=[roles.need("admin")])
async def change(username: str, body: AccountPatch):
    _need_local()
    row = await run_in_threadpool(store.account, username)
    if not row:
        raise HTTPException(404, "No such account")
    if body.role and body.role != "admin" and row["role"] == "admin" and not await _admins_left(row["username"]):
        raise HTTPException(409, "Keep at least one administrator.")
    if body.password is not None and len(body.password) < MIN_PASSWORD:
        raise HTTPException(422, f"Use a password of at least {MIN_PASSWORD} characters.")
    await run_in_threadpool(store.change_account, row["username"], body.role,
                            hash_password(body.password) if body.password else None)
    if body.role:
        await run_in_threadpool(store.set_person, row["username"], body.role)
    return {"username": row["username"], "role": body.role or row["role"]}


@router.delete("/accounts/{username}", status_code=204, summary="Remove a person", dependencies=[roles.need("admin")])
async def remove(username: str, request: Request):
    _need_local()
    async with Engine(request) as e:
        me = (await e.me())["username"]
    row = await run_in_threadpool(store.account, username)
    if not row:
        raise HTTPException(404, "No such account")
    if row["username"] == me.lower():
        raise HTTPException(409, "You cannot remove your own account.")
    if row["role"] == "admin" and not await _admins_left(row["username"]):
        raise HTTPException(409, "Keep at least one administrator.")
    # ponytail: an open session stays valid until it expires (langflow.refresh_token_expire_seconds, 8 h); new
    # sign-ins are refused at once. Deactivate the engine user too if immediate cut-off is ever needed.
    await run_in_threadpool(store.drop_account, row["username"])
    await run_in_threadpool(store.drop_person, row["username"])


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


@router.post("/accounts/me/password", status_code=204, summary="Change my own password (local accounts)")
async def my_password(body: PasswordIn, request: Request):
    _need_local()
    async with Engine(request) as e:
        me = (await e.me())["username"]
    if not await run_in_threadpool(identity, me, body.current):
        raise HTTPException(403, "The current password is not correct.")
    if len(body.new) < MIN_PASSWORD:
        raise HTTPException(422, f"Use a password of at least {MIN_PASSWORD} characters.")
    await run_in_threadpool(store.change_account, me, None, hash_password(body.new))


if __name__ == "__main__":
    h = hash_password("correct horse battery")
    assert verify("correct horse battery", h) and not verify("wrong", h) and not verify("x", "garbage")
    assert problem("ab", "x" * 10) == "" and problem("A B", "x" * 10) and problem("ok", "short")
    print("accounts ok")
