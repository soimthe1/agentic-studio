"""Smart contract API: create agents from plain language + choices (Agent Studio API v1, /designs).

Flow (mirrors Mashahed's create): describe -> Agent Studio answers with what it understood + ONE choices card
(defaults preselected) -> optional answers / more messages -> Create -> the director builds the agent and
the engine compiles it -> the person tests it. Every design is a saved draft (resumable), private to its owner.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import api, capabilities, designer, director, skills, store
from agent_studio.watch import buildcheck, duplicate, intake, readiness
from agent_studio import roles
from agent_studio.engine import Engine

log = logging.getLogger("agent_studio.designs")
FILE_CAPS = {"save_data", "bundle_files", "document"}

router = APIRouter(prefix="/api/studio/v1", tags=["Agent Designer"])

PREF_FIELDS = {"name", "trigger", "cron", "schedule_text", "timezone", "capabilities", "acts", "notify", "channel",
               "detail", "brain", "sub_agents", "skills", "remember", "effort"}


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class AnswersIn(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class PrefsIn(BaseModel):
    prefs: dict = Field(default_factory=dict)


def _public(design: dict) -> dict:
    st = design["state"]
    return {"id": design["id"], "title": design["title"], "status": design["status"], "agent_id": design["agent_id"],
            "turns": st.get("turns", []), "plan": st.get("plan"), "prefs": st.get("prefs"),
            "left_out": st.get("left_out", []), "error": st.get("error"), "proof": st.get("proof"),
            "watch": st.get("watch", {}),
            "skills_applied": skills.names((st.get("prefs") or {}).get("skills") or []),
            "agent_state": (store.life(design["agent_id"]) or {}).get("state", "built") if design.get("agent_id") else None,
            "updated_at": design["updated_at"]}


async def _whoami_and_agents(request: Request) -> tuple[dict, list[dict]]:
    async with Engine(request) as e:
        return await e.me(), await e.list_agents()


def _merge_prefs(plan: dict, touched: dict) -> dict:
    prefs = director.default_prefs(plan)
    prefs["skills"] = list(plan.get("skills") or [])
    prefs.update({k: v for k, v in touched.items() if k in PREF_FIELDS})
    return prefs


def _assistant_text(plan: dict) -> str:
    if plan.get("refuse"):
        return plan["refuse"]
    caps = capabilities.by_id()
    lines = [plan.get("understood") or ""]
    for cid in plan.get("capabilities") or []:
        cap = caps.get(cid) or {}
        if cap.get("status") == "needs_setup":
            lines.append(f"Not available here yet: {cap.get('label', cid)}. "
                         + (cap.get("needs_setup_text") or "An administrator has to set it up first."))
    return "\n\n".join(x for x in lines if x)


def _my_built(owner: str, except_id: str | None) -> list[dict]:
    """The person's built agents with their agreed choices (for the Duplicate watchkeeper)."""
    out = []
    for row in store.list_designs(owner, limit=200):
        if row["status"] != "created" or row["id"] == except_id or not row.get("agent_id"):
            continue
        full = store.get_design(owner, row["id"]) or {}
        st = full.get("state") or {}
        if st.get("prefs"):
            out.append({"design_id": row["id"], "agent_id": row["agent_id"], "name": row["title"], "prefs": st["prefs"],
                        "targets": (st.get("watch") or {}).get("facts", {}).get("targets", [])})
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z؀-ۿ]", "", (text or "").lower())


def named_systems_only(caps: list[str], said: str) -> list[str]:
    """When the person names the system(s) to use ("from Ops Portal ..."), the agent reads only those systems: the model
    sometimes adds another connected system that sounds related. Names are matched loosely (case, spaces, dashes and
    an organisation prefix such as "ACME " ignored). Nothing is removed when no system is named."""
    cat = capabilities.catalog()
    app_names = {a["id"]: a["name"] for a in cat["apps"]}
    by_id = {c["id"]: c for c in cat["capabilities"]}
    text = _norm(said)

    def keys(cap_id: str) -> set[str]:
        req = str((by_id.get(cap_id) or {}).get("requires") or "")
        if not req.startswith("apps."):
            return set()
        app = req[5:]
        out = set()
        for k in (app, app_names.get(app, "")):
            # also without a two-letter organisation prefix: "xy_sales" is named as "sales"
            out |= {_norm(k), _norm(re.sub(r"^[a-z0-9]{2}_", "", k.lower()))}
        return {k for k in out if len(k) >= 4}

    system = {c: keys(c) for c in caps if keys(c)}
    named = {c for c, ks in system.items() if any(k in text for k in ks)}
    if not named:
        return caps
    return [c for c in caps if c not in system or c in named]


def named_agents(said: str, agents: list[dict], picked: list[str], self_id: str | None = None) -> list[str]:
    """"Use my Low Resource Servers Report agent and ..." - an agent the person names becomes a helper of the new
    one (it is asked like a tool and the new agent builds its answer from what it returns). Matched by name, loosely."""
    text = _norm(said)
    out = list(picked)
    for a in agents:
        key = _norm(a.get("name") or "")
        if len(key) >= 6 and key in text and a["id"] not in out and a["id"] != self_id:
            out.append(a["id"])
    return out


WATCH_WORDS = re.compile(r"(?i)\b(keep (watching|an eye|monitoring|checking)|as soon as|whenever(?!\s+(?:i|we|you|they|needed|necessary|required)\b)|the moment|watch (for|out))\b"
                         r"|فور|كلما|راقب باستمرار|أول ما")


def watch_if_asked(plan: dict, said: str) -> dict:
    """"Keep watching ... tell me as soon as ..." means an agent that keeps looking and reports what is new, not one
    that waits to be asked (the model sometimes picks chat or a daily schedule for it)."""
    if not WATCH_WORDS.search(said or "") or plan.get("trigger") in ("watch", "alert"):
        return plan
    return {**plan, "trigger": "watch"}


REPORT_WORDS = re.compile(r"(?i)\breports?\b|تقرير")


def report_is_delivered(plan: dict, said: str) -> dict:
    """"I need a report" means a report the person gets, not only an answer in the run history: when nothing would
    deliver it (no message, no file), the agent writes it as a document in the person's files."""
    caps = list(plan.get("capabilities") or [])
    if not REPORT_WORDS.search(said or "") or {"notify", "document", "save_data"} & set(caps):
        return plan
    if "document" in capabilities.by_id() and capabilities.by_id()["document"].get("status") != "needs_setup":
        caps.append("document")
    return {**plan, "capabilities": caps, "detail": "report"}


async def _think(design_state: dict, agents: list[dict], owner: str | None = None, design_id: str | None = None) -> dict:
    """Understand, then the watchkeepers: Intake keeps the person's exact details, Duplicate compares with their agents.
    On model failure the draft is kept and the error recorded (principle 5)."""
    try:
        plan = await run_in_threadpool(designer.understand, design_state["turns"], agents, design_state.get("plan"))
    except designer.DesignerError as exc:
        log.warning("designer unavailable: %s", exc)
        design_state["error"] = "The AI could not be reached or answered unclearly. Your draft is saved; try again in a moment."
        return design_state
    design_state["error"] = None
    said = "\n".join(t["text"] for t in design_state["turns"] if t["role"] == "user")
    found = intake.facts(said, [c["id"] for c in capabilities.notify_channels()])
    watch = {"facts": found, "intake": []}
    if not plan.get("refuse") and (plan.get("goals") or plan.get("capabilities")):
        plan, kept, watch["intake"] = intake.check(plan, director.default_prefs(plan), found, said)
        plan["capabilities"] = kept["capabilities"]
        if kept.get("channel") and not design_state.get("touched", {}).get("channel"):
            design_state.setdefault("touched", {})["channel"] = kept["channel"]
    if not plan.get("refuse"):
        plan["capabilities"] = named_systems_only(list(plan.get("capabilities") or []), said)
        plan = report_is_delivered(plan, said)
        plan = watch_if_asked(plan, said)
        plan["sub_agents"] = named_agents(said, agents, list(plan.get("sub_agents") or []), design_state.get("agent_id"))
    design_state["plan"] = plan
    design_state["prefs"] = _merge_prefs(plan, design_state.get("touched", {}))
    if not plan.get("refuse"):
        # the person never has to know about skills: matching approved know-how is applied for them, with the tools
        # it needs (only tools that exist and work here). Kept in the plan so later card edits keep it.
        picked = await run_in_threadpool(skills.suggest, said)
        known = capabilities.by_id()
        plan["skills"] = [x["id"] for x in picked]
        plan["capabilities"] = list(plan.get("capabilities") or []) + [
            t for x in picked for t in x["tools"]
            if t in known and known[t].get("status") != "needs_setup" and t not in (plan.get("capabilities") or [])]
        # know-how about a system the person did not name does not apply (e.g. SQL know-how for an Ops Portal report)
        plan["capabilities"] = named_systems_only(plan["capabilities"], said)
        plan["skills"] = [x["id"] for x in picked
                          if not x["tools"] or any(t in plan["capabilities"] for t in x["tools"])]
        design_state["prefs"] = _merge_prefs(plan, design_state.get("touched", {}))
    if owner and design_state["prefs"].get("capabilities"):
        others = await run_in_threadpool(_my_built, owner, design_id)
        watch["duplicate"] = duplicate.compare(duplicate.fingerprint(design_state["prefs"], found["targets"]), others)
    design_state["watch"] = {**design_state.get("watch", {}), **watch}
    design_state["turns"].append({"role": "assistant", "text": _assistant_text(plan)})
    return design_state


@router.get("/capabilities", summary="What agents can use (plain language), with availability")
async def get_capabilities(request: Request):
    me, agents = await _whoami_and_agents(request)
    cat = capabilities.catalog()
    return {**cat, "channels": capabilities.notify_channels(),
            "agents": [{"id": a["id"], "name": a["name"], "description": a["description"]} for a in agents]}


@router.get("/designs", summary="My agent drafts")
async def list_designs(request: Request):
    me, _ = await _whoami_and_agents(request)
    return await run_in_threadpool(store.list_designs, me["id"])


@router.post("/designs", status_code=201, summary="Start: describe the agent in your own words", dependencies=[roles.need("builder")])
async def start_design(body: MessageIn, request: Request):
    me, agents = await _whoami_and_agents(request)
    state = {"turns": [{"role": "user", "text": body.text}], "touched": {}}
    design = await run_in_threadpool(store.create_design, me["id"], body.text[:80], state)
    state = await _think(state, agents, me["id"], design["id"])
    title = (state.get("plan") or {}).get("name") or body.text[:80]
    design = await run_in_threadpool(lambda: store.save_design(me["id"], design["id"], state=state, title=title))
    return _public(design)


@router.get("/designs/{design_id}", summary="One draft")
async def get_design(design_id: str, request: Request):
    me, _ = await _whoami_and_agents(request)
    design = await run_in_threadpool(store.get_design, me["id"], design_id)
    if not design:
        raise HTTPException(404, "Not found")
    return _public(design)


@router.post("/designs/{design_id}/messages", summary="Say more / correct the plan", dependencies=[roles.need("builder")])
async def add_message(design_id: str, body: MessageIn, request: Request):
    me, agents = await _whoami_and_agents(request)
    design = await run_in_threadpool(store.get_design, me["id"], design_id)
    if not design:
        raise HTTPException(404, "Not found")
    state = design["state"]
    state["turns"].append({"role": "user", "text": body.text})
    state = await _think(state, agents, me["id"], design_id)
    return _public(await run_in_threadpool(lambda: store.save_design(me["id"], design_id, state=state)))


@router.post("/designs/{design_id}/turns/{index}", summary="Edit an earlier message: everything after it is redone", dependencies=[roles.need("builder")])
async def edit_turn(design_id: str, index: int, body: MessageIn, request: Request):
    """Like editing a message in a chat: later messages, answers, choices and the test result no longer apply.
    An agent that was already built keeps working unchanged until the person builds the new version."""
    me, agents = await _whoami_and_agents(request)
    design = await run_in_threadpool(store.get_design, me["id"], design_id)
    if not design:
        raise HTTPException(404, "Not found")
    state = design["state"]
    turns = state.get("turns", [])
    if not (0 <= index < len(turns)) or turns[index]["role"] != "user":
        raise HTTPException(422, "Only your own messages can be edited")
    state["turns"] = turns[:index] + [{"role": "user", "text": body.text}]
    state["touched"], state["proof"], state["left_out"], state["watch"] = {}, None, [], {}
    state = await _think(state, agents, me["id"], design_id)
    saved = await run_in_threadpool(lambda: store.save_design(me["id"], design_id, state=state, status="draft"))
    return _public(saved)


@router.post("/designs/{design_id}/answers", summary="Answer Agent Studio's questions (choices)", dependencies=[roles.need("builder")])
async def answer(design_id: str, body: AnswersIn, request: Request):
    me, agents = await _whoami_and_agents(request)
    design = await run_in_threadpool(store.get_design, me["id"], design_id)
    if not design:
        raise HTTPException(404, "Not found")
    state = design["state"]
    questions = {q["id"]: q for q in (state.get("plan") or {}).get("questions", [])}
    lines = []
    for qid, value in body.answers.items():
        q = questions.get(qid)
        if q and value in q["options"]:
            lines.append(f"{q['text']} -> {value}")
    if not lines:
        raise HTTPException(422, "No valid answers")
    state["turns"].append({"role": "user", "text": "\n".join(lines)})
    state = await _think(state, agents, me["id"], design_id)
    return _public(await run_in_threadpool(lambda: store.save_design(me["id"], design_id, state=state)))


@router.patch("/designs/{design_id}/prefs", summary="Change choices on the card", dependencies=[roles.need("builder")])
async def set_prefs(design_id: str, body: PrefsIn, request: Request):
    me, _ = await _whoami_and_agents(request)
    design = await run_in_threadpool(store.get_design, me["id"], design_id)
    if not design:
        raise HTTPException(404, "Not found")
    state = design["state"]
    bad = set(body.prefs) - PREF_FIELDS
    if bad:
        raise HTTPException(422, f"Unknown choices: {sorted(bad)}")
    if "skills" in body.prefs:          # only approved skills; a chosen skill brings the tools it needs
        have = await run_in_threadpool(skills.approved)
        chosen = [s for s in body.prefs["skills"] or [] if s in have]
        body.prefs["skills"] = chosen
        caps = list(body.prefs.get("capabilities") or (state.get("prefs") or {}).get("capabilities") or [])
        known, before = capabilities.by_id(), len(caps)
        for sid in chosen:
            caps += [t for t in have[sid]["spec"].get("tools") or [] if t in known and t not in caps]
        if len(caps) > before or "capabilities" in body.prefs:
            body.prefs["capabilities"] = caps
    state.setdefault("touched", {}).update(body.prefs)
    state["prefs"] = _merge_prefs(state.get("plan") or {}, state["touched"])
    return _public(await run_in_threadpool(lambda: store.save_design(me["id"], design_id, state=state)))


@router.post("/designs/{design_id}/create", summary="Create the agent from this draft", dependencies=[roles.need("builder")])
async def create_agent(design_id: str, request: Request, allow_duplicate: bool = False):
    me, agents = await _whoami_and_agents(request)
    design = await run_in_threadpool(store.get_design, me["id"], design_id)
    if not design:
        raise HTTPException(404, "Not found")
    state = design["state"]
    plan, prefs = state.get("plan"), state.get("prefs")
    if not plan or not prefs:
        raise HTTPException(409, "The designer has not understood this request yet")
    if plan.get("refuse"):
        raise HTTPException(422, plan["refuse"])
    watch = state.setdefault("watch", {})
    if not allow_duplicate and not design["agent_id"]:
        same = [f for f in duplicate.compare(duplicate.fingerprint(prefs, watch.get("facts", {}).get("targets")),
                                             await run_in_threadpool(_my_built, me["id"], design_id)) if f["kind"] == "duplicate"]
        if same:
            raise HTTPException(409, {"watchkeeper": "duplicate", "text": same[0]["text"], "agent_id": same[0]["agent_id"]})
    async with Engine(request) as e:
        try:
            status = await e.status()
        except HTTPException:
            status = {}
    watch["readiness"] = readiness.check(prefs, status) if status else [{"level": "warn", "text": "Could not ask the engine what it can reach."}]
    blocks = [f["text"] for f in watch["readiness"] if f["level"] == "block"]
    if blocks:
        await run_in_threadpool(lambda: store.save_design(me["id"], design_id, state=state))
        raise HTTPException(409, {"watchkeeper": "readiness", "text": " ".join(blocks)})
    if design.get("agent_id"):   # corrections people made on this agent's answers become part of its instructions
        fixes = await run_in_threadpool(store.corrections, design["agent_id"])
        prefs = {**prefs, "corrections": [f["correction"] for f in fixes][-20:]}
    try:
        known = {c["name"]: c for c in (status or {}).get("connections") or [] if c.get("kind") == "apps"}
        built = director.build(plan, prefs, {a["id"]: a["name"] for a in agents}, known)
    except director.DirectorError as exc:
        raise HTTPException(422, str(exc)) from exc
    watch["build"] = buildcheck.check(built["definition"], prefs, built["left_out"])
    blocks = [f["text"] for f in watch["build"] if f["level"] == "block"]
    if blocks:
        await run_in_threadpool(lambda: store.save_design(me["id"], design_id, state=state))
        raise HTTPException(422, {"watchkeeper": "build", "text": " ".join(blocks)})
    async with Engine(request) as e:
        if design["agent_id"]:                       # re-create = update the same agent (edit through the same draft)
            agent = await e.save_definition(design["agent_id"], built["definition"])
            await e.update_agent(design["agent_id"], name=prefs["name"], description=director.describe(plan, prefs))
        else:
            agent = await e.create_agent(prefs["name"], director.describe(plan, prefs))
            try:
                agent = await e.save_definition(agent["id"], built["definition"])
            except HTTPException:
                await e.delete_agent(agent["id"])      # never leave a half-built agent behind
                raise
    state["left_out"] = built["left_out"]
    life = await run_in_threadpool(store.life, agent["id"])
    if not life or life["state"] in ("live", "paused"):
        # new or changed: runs on request only until it is published on purpose; its triggers stay disarmed
        await run_in_threadpool(store.set_life, agent["id"], me["id"], "built")
        async with Engine(request) as e:
            try:
                await e.set_triggers(agent["id"], False)
                await e.set_mcp(agent["id"], False)      # not offered to other tools until published again
            except HTTPException:
                pass
    saved = await run_in_threadpool(lambda: store.save_design(me["id"], design_id, state=state, status="created",
                                                              agent_id=agent["id"], title=prefs["name"]))
    if prefs.get("corrections"):
        await run_in_threadpool(store.mark_corrections_applied, agent["id"])
    from agent_studio import activity
    await activity.note(me["username"], "created an agent" if not design.get("agent_id") else "changed an agent", prefs["name"])
    return {"design": _public(saved), "agent": agent}


@router.get("/designs/{design_id}/preview", summary="Exactly what will be built, in plain words (before Create)")
async def preview(design_id: str, request: Request):
    me, agents = await _whoami_and_agents(request)
    design = await run_in_threadpool(store.get_design, me["id"], design_id)
    if not design:
        raise HTTPException(404, "Not found")
    plan, prefs = design["state"].get("plan"), design["state"].get("prefs")
    if not plan or not prefs:
        raise HTTPException(409, "The designer has not understood this request yet")
    try:
        built = director.build(plan, prefs, {a["id"]: a["name"] for a in agents})
    except director.DirectorError as exc:
        raise HTTPException(422, str(exc)) from exc
    return director.summary(plan, prefs, built)


def _plain_tools(names) -> list[str]:
    """Engine tool names (app_query_tool_sql_health, save_data, ...) -> what people call them, once each."""
    caps = capabilities.by_id()
    out = []
    for n in names:
        cid = next((c for c in caps if c in (n or "")), None)
        label = caps[cid]["label"] if cid else (n or "").replace("_", " ")
        if label not in out:
            out.append(label)
    return out


@router.post("/designs/{design_id}/prove", summary="Run the agent once and check it against the goal", dependencies=[roles.need("builder")])
async def prove(design_id: str, request: Request):
    me, _ = await _whoami_and_agents(request)
    design = await run_in_threadpool(store.get_design, me["id"], design_id)
    if not design or not design["agent_id"]:
        raise HTTPException(404, "Create the agent first")
    state = design["state"]
    plan, prefs = state["plan"], state["prefs"]
    said = next((t["text"] for t in state.get("turns") or [] if t.get("role") == "user"), "")
    message = director.first_test(plan, prefs, said)
    reply, error, session_id, approval, tools = "", None, None, None, []
    files_before = set(api.list_files(me["id"]))
    async with Engine(request) as e:
        try:
            out = await e.run_agent(design["agent_id"], message)
            reply, session_id, approval = out["reply"], out["session_id"], out.get("approval")
            if out["status"] == "failed":
                error = reply
            if session_id:
                tools = [t for m in await e.messages(session_id=session_id) for t in m["tools"]]
        except HTTPException as exc:
            from agent_studio.engine import _plain_error
            error = _plain_error(str(exc.detail))
    new_files = sorted(set(api.list_files(me["id"])) - files_before)
    if approval:  # the test stops at the approval step: judge the proposal; the person decides in Approvals
        reply = f"[Waiting for approval] Proposed: {reply}"
    delivery = None
    if prefs.get("notify", "never") != "never" and "notify" in (prefs.get("capabilities") or []):
        chan = prefs.get("channel") or next((c["id"] for c in capabilities.notify_channels()), "the channel")
        delivery = (f"The app posts the agent's answer to '{chan}' " +
                    ("when the answer's last line is 'STATUS: PROBLEM'." if prefs["notify"] == "problems" else "after every run."))
    check = await run_in_threadpool(designer.check_result, plan, message, reply, error, tools, delivery)
    # Facts beat the judge: what the run really did (tool calls, files) overrides a model's claim.
    facts = []
    uses_tools = any(c != "date" and c != "calculate" for c in prefs["capabilities"]) or prefs.get("sub_agents")
    if not error and uses_tools and not tools and not approval:
        facts.append("The agent answered without using any of its tools, so its answer is not based on real data.")
    if not error and not approval and set(prefs["capabilities"]) & FILE_CAPS and not new_files:
        facts.append("No file was created, although the goal needs one.")
    if facts and check["verdict"] in ("met", "partly", "unknown"):
        check = {**check, "verdict": "not_met", "missing": facts + check["missing"],
                 "fixes": ["Try again", "Use the thorough brain", *check["fixes"]][:4]}
    state["proof"] = {"message": message, "reply": reply, "session_id": session_id, "approval": approval,
                      "tools_used": _plain_tools(t["name"] for t in tools), "files": new_files, **check}
    await run_in_threadpool(lambda: store.save_design(me["id"], design_id, state=state))
    return state["proof"]


@router.delete("/designs/{design_id}", status_code=204, summary="Discard a draft", dependencies=[roles.need("builder")])
async def delete_design(design_id: str, request: Request):
    me, _ = await _whoami_and_agents(request)
    if not await run_in_threadpool(store.delete_design, me["id"], design_id):
        raise HTTPException(404, "Not found")


@router.get("/agents/{agent_id}/definition", summary="An agent's steps and connections (Agent Studio format)")
async def get_definition(agent_id: str, request: Request):
    async with Engine(request) as e:
        return await e.get_definition(agent_id)


@router.put("/agents/{agent_id}/definition", summary="Replace an agent's steps and connections", dependencies=[roles.need("builder")])
async def put_definition(agent_id: str, body: dict, request: Request):
    allowed = {k for g in _catalog_policy()["groups"] for k in g["components"]}
    unknown = sorted({s.get("component") for s in body.get("steps", [])} - allowed)
    if unknown:
        raise HTTPException(422, f"Not approved components: {unknown}")
    async with Engine(request) as e:
        return await e.save_definition(agent_id, body)


@router.post("/agents/{agent_id}/duplicate", status_code=201, summary="Make a copy of an agent as a new draft (change the words, then create)", dependencies=[roles.need("builder")])
async def duplicate_agent(agent_id: str, request: Request):
    me, _ = await _whoami_and_agents(request)

    def copy() -> dict:
        src = next((store.get_design(me["id"], r["id"]) for r in store.list_designs(me["id"], limit=200) if r.get("agent_id") == agent_id), None)
        if not src:
            raise HTTPException(404, "This agent was not made from a description, so there is nothing to copy")
        st = {k: v for k, v in (src["state"] or {}).items() if k not in ("proof", "left_out", "error")}
        if st.get("prefs"):
            st["prefs"] = {**st["prefs"], "name": f"{st['prefs'].get('name') or src['title']} (copy)"}
        st.setdefault("touched", {})["name"] = st.get("prefs", {}).get("name")
        return store.create_design(me["id"], f"{src['title']} (copy)", st)

    return _public(await run_in_threadpool(copy))


@router.get("/templates", summary="Ready-made descriptions by team: pick one, change the words, create")
async def templates(request: Request):
    await _whoami_and_agents(request)
    teams = await run_in_threadpool(lambda: capabilities._load("templates.yaml").get("teams") or [])
    # agents colleagues shared (and that work: they are live) are templates too, in their owners' own words
    shared = []
    for row in await run_in_threadpool(store.shared_agents):
        said = ((await run_in_threadpool(store.design_of_agent, row["agent_id"])).get("plan") or {}).get("understood")
        if said:
            shared.append({"en": said, "ar": said})
    if shared:
        teams = [*teams, {"id": "shared", "name": {"en": "From colleagues", "ar": "من الزملاء"}, "templates": shared[:12]}]
    return teams


@router.get("/palette", summary="Approved building blocks with their Agent Studio names (for the Steps view)")
async def palette():
    out = {}
    for g in _catalog_policy()["groups"]:
        for key, spec in g["components"].items():
            out[key] = {"label": spec.get("label", key), "group": g["id"], "group_label": g["label"]}
    caps = [{"id": c["id"], "label": c["label"], "component": c["tool"]["component"], "app": c["tool"].get("params", {}).get("app")}
            for c in capabilities.catalog()["capabilities"]]
    return {"components": out, "capabilities": caps}


@router.get("/models", summary="Models the agents can think with")
async def models(request: Request):
    async with Engine(request) as e:
        return {"fast": director.model_for("fast"), "thorough": director.model_for("thorough"),
                "available": await e.model_options()}


def _catalog_policy() -> dict:
    import yaml

    from agent_studio.capabilities import _config_dir

    return yaml.safe_load((_config_dir() / "policy" / "catalog.yaml").read_text(encoding="utf-8"))
