"""Skills: reusable know-how for agents. Tools are an agent's hands (call a system); a skill is how to do a job well.

A skill is a short card: name, when to use it, steps, the shape of the answer, the tools it needs, an example.
1. draft    The person describes the know-how in their own words; the model writes the card from those words only
            (never invents systems, figures or rules) and may only name tools that exist. Nothing is saved yet.
2. request  The person edits and submits the card: a draft until an administrator approves it.
3. approve  An administrator approves: a new version. Earlier versions stay in history.
4. use      The Designer suggests matching approved skills while an agent is described; a chosen skill's text goes into
            the agent's instructions and its tools into the agent's abilities. Agents pick up a new version when rebuilt.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import ai_providers as ai
from agent_studio import capabilities, roles, settings, store
from agent_studio.engine import Engine

router = APIRouter(prefix="/api/studio/v1", tags=["Skills"])

CARD = """You turn a person's description of HOW a job should be done into a skill card for AI agents.
Return only JSON: {{"name": "<at most 6 words>", "when_to_use": "<one sentence>", "steps": ["<3 to 8 short imperative steps>"],
"output_format": "<how the answer must look>", "tools": ["<ids from AVAILABLE TOOLS that the steps need>"],
"example": "<one short example of a good answer, or empty>"}}
Rules: use only what the person said or what follows directly from it. Never invent systems, servers, figures, names,
thresholds or company rules. Use only tool ids listed in AVAILABLE TOOLS ([] if none fits). Write in {lang}.
AVAILABLE TOOLS: {tools}"""

WORD = re.compile(r"\w{4,}")
STOP = {"with", "that", "this", "from", "your", "what", "when", "have", "will", "they", "them", "then", "each", "every",
        "about", "into", "only", "agent", "agents", "should", "answer", "make", "give", "tell", "using", "there"}


class SkillText(BaseModel):
    text: str = Field(min_length=10, max_length=4000)


class SkillCard(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    when_to_use: str = Field("", max_length=300)
    steps: list[str] = Field(min_length=1, max_length=12)
    output_format: str = Field("", max_length=600)
    tools: list[str] = Field(default_factory=list, max_length=10)
    example: str = Field("", max_length=1500)
    update_of: str = Field("", max_length=40)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "skill"


def _tool_ids() -> dict[str, str]:
    return {c["id"]: c.get("label", c["id"]) for c in capabilities.catalog()["capabilities"]}


def draft_card(text: str) -> dict:
    tools = _tool_ids()
    lang = "Arabic" if re.search(r"[؀-ۿ]", text) else "English"
    msgs = [{"role": "system", "content": CARD.format(lang=lang, tools=json.dumps(tools, ensure_ascii=False))},
            {"role": "user", "content": text}]
    ai.configure(settings.load()["ai"], base_dir=settings.REPO)
    try:
        data = json.loads(ai.chat(msgs, profile=settings.load()["app"]["designer_profile"], json_mode=True))
    except (ai.AIError, ValueError, TypeError) as exc:
        raise HTTPException(503, "Agent Studio's AI could not be reached or answered unclearly. Try again in a moment.") from exc
    steps = [str(s).strip()[:300] for s in (data.get("steps") or []) if str(s).strip()][:12]
    return {"name": str(data.get("name") or "")[:60].strip() or text[:40], "when_to_use": str(data.get("when_to_use") or "")[:300],
            "steps": steps or [text[:300]], "output_format": str(data.get("output_format") or "")[:600],
            "tools": [t for t in data.get("tools") or [] if t in tools][:10],   # only tools that exist
            "example": str(data.get("example") or "")[:1500]}


def approved() -> dict[str, dict]:
    """skill_id -> newest approved version {id, skill_id, version, spec, ...}."""
    out: dict[str, dict] = {}
    for row in store.list_skills():          # oldest first: later approvals overwrite earlier ones
        if row["status"] == "approved":
            n = out.get(row["skill_id"], {}).get("version", 0) + 1
            out[row["skill_id"]] = {**row, "version": n}
    return out


def text_for(skill_ids: list[str]) -> str:
    """The instruction block an agent gets for its skills."""
    have = approved()
    blocks = []
    for sid in skill_ids:
        s = (have.get(sid) or {}).get("spec")
        if not s:
            continue
        lines = [f"Skill '{s['name']}'" + (f" (use when {s['when_to_use'].rstrip('.')})" if s.get("when_to_use") else "") + ":"]
        lines += [f"{i}. {step}" for i, step in enumerate(s["steps"], 1)]
        if s.get("output_format"):
            lines.append("Answer format: " + s["output_format"])
        if s.get("example"):
            lines.append("Example of a good answer: " + s["example"])
        blocks.append("\n".join(lines))
    return ("Follow these skills:\n\n" + "\n\n".join(blocks)) if blocks else ""


def names(skill_ids: list[str]) -> list[str]:
    if not skill_ids:
        return []
    have = approved()
    return [have[s]["spec"]["name"] for s in skill_ids if s in have]


def _words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP}


def _stem(w: str) -> str:
    """'servers' -> 'server', 'healthy' -> 'health', 'reports' -> 'report' (good enough for matching, no model)."""
    w = w[:-1] if len(w) > 4 and w.endswith("s") else w
    return w[:-1] if len(w) > 5 and w.endswith("y") else w


def _keys(text: str) -> set[str]:
    return {_stem(w) for w in _words(text)}


def suggest(said: str, chosen: list[str] | None = None) -> list[dict]:
    """Approved skills that clearly fit what the person described (no model): at most 3. A skill fits when at least
    2 of its key words (from its name and 'use when') are in the request and they are at least 30% of them - so a
    file job that only mentions 'SQL Server' does not pick up a reporting skill."""
    mine = _keys(said)
    scored = []
    for sid, row in approved().items():
        if sid in (chosen or []):
            continue
        s = row["spec"]
        keys = _keys(" ".join([s["name"], s.get("when_to_use", "")]))
        hit = len(mine & keys)
        if keys and hit >= 2 and hit / len(keys) >= 0.3:
            scored.append((hit / len(keys), {"id": sid, "name": s["name"], "when_to_use": s.get("when_to_use", ""), "tools": s.get("tools", [])}))
    return [x for _, x in sorted(scored, key=lambda p: -p[0])[:3]]


def _used_by(owner: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in store.list_designs(owner, limit=200):
        if row.get("agent_id"):
            prefs = ((store.get_design(owner, row["id"]) or {}).get("state") or {}).get("prefs") or {}
            for sid in prefs.get("skills") or []:
                out.setdefault(sid, []).append({"id": row["agent_id"], "name": row["title"]})
    return out


async def _me(request: Request) -> dict:
    async with Engine(request) as e:
        return await e.me()


@router.post("/skills/draft", summary="Write a skill card from the person's own words (nothing is saved)", dependencies=[roles.need("builder")])
async def draft(body: SkillText, request: Request):
    await _me(request)
    return await run_in_threadpool(draft_card, body.text)


@router.get("/skills", summary="Approved skills (newest version each), skill requests, and who uses them")
async def list_skills(request: Request):
    me = await _me(request)
    have = await run_in_threadpool(approved)
    rows = await run_in_threadpool(store.list_skills)
    used = await run_in_threadpool(_used_by, me["id"])
    admin = roles.resolve(me, await run_in_threadpool(store.person_role, me["username"])) == "admin"
    return {"skills": [{"id": sid, "version": r["version"], **r["spec"], "approved_by": r["decided_by"],
                        "used_by": used.get(sid, [])} for sid, r in sorted(have.items())],
            "requests": [r for r in reversed(rows) if r["status"] != "approved" and (admin or r["owner"] == me["id"])][:100],
            "can_approve": admin}


@router.post("/skills", status_code=201, summary="Ask for a new skill or a new version (a draft until an administrator approves)", dependencies=[roles.need("builder")])
async def request_skill(body: SkillCard, request: Request):
    me = await _me(request)
    rows = await run_in_threadpool(store.list_skills)
    if body.update_of:
        sid = body.update_of
        if not any(r["skill_id"] == sid and r["status"] == "approved" for r in rows):
            raise HTTPException(404, "There is no approved skill with that name to update")
    else:
        sid = _slug(body.name)
        if any(r["skill_id"] == sid and r["status"] != "rejected" for r in rows):
            raise HTTPException(409, f"A skill called '{sid}' already exists or is requested; reuse it, or request a new version of it")
    if any(r["skill_id"] == sid and r["status"] == "draft" for r in rows):
        raise HTTPException(409, "A change to this skill is already waiting for approval")
    tools = await run_in_threadpool(_tool_ids)
    unknown = [t for t in body.tools if t not in tools]
    if unknown:
        raise HTTPException(422, f"Unknown tools: {unknown}")
    return await run_in_threadpool(store.create_skill, me["id"], sid, {**body.model_dump(), "requested_by": me["username"]})


@router.post("/skills/requests/{row_id}/{decision}", summary="Approve or reject a skill request (administrators)", dependencies=[roles.need("admin")])
async def decide(row_id: str, decision: str, request: Request):
    me = await _me(request)
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "Not found")
    row = await run_in_threadpool(store.get_skill, row_id)
    if not row or row["status"] != "draft":
        raise HTTPException(404, "This request is not waiting")
    from agent_studio import activity
    await activity.note(me["username"], "approved know-how" if decision == "approve" else "rejected know-how", row["skill_id"])
    return await run_in_threadpool(store.set_skill_status, row_id, "approved" if decision == "approve" else "rejected", me["username"])


if __name__ == "__main__":   # self-check of the parts that need no database or model
    assert _slug("Incident report (org format)") == "incident_report_org_format"
    assert _words("Check the critical findings every morning") == {"check", "critical", "findings", "morning"}
    assert _keys("healthy SQL Servers reports") == {"health", "server", "report"}
    print("ok")
