"""Smart contract, step 2: the Agent Studio director turns a plan + the person's choices into an agent definition.

Deterministic: fixed rules and proven patterns, no model call (like Mashahed's director). The definition uses
engine component keys from the approved catalog only and is compiled by the engine extension.

Rules
- Only capabilities whose status is "ready" become tools; others are listed as needs-setup and left out.
- Read-only agents never receive tools that change systems.
- Any tool that changes systems runs only after a human approval step; the approval flag is set by the flow
  (the director), never by the model. Pre-approved notification channels may post without the step.
- Scheduled and alert agents start from a trigger, turn the event into a task sentence, and end in a text result.
- Other agents the person owns can be used as sub-agents (agent as a tool).
"""

from __future__ import annotations

import copy
import os
import re

from agent_studio import capabilities, settings

AGENT = "Agent"
CHAT_IN, CHAT_OUT = "ChatInput", "ChatOutput"
SCHEDULE, WEBHOOK, PARSER, APPROVAL = "ScheduleTrigger", "InboundWebhookTrigger", "ParserComponent", "HumanInput"
SUB_AGENT = "RunFlow"
NOTIFY_KEY = "ext:studio:NotifyComponent@official"

BASE = ("You are an AI agent working for our organization. Use only the tools you are given, never invent "
        "data, and say clearly when a system could not be reached. When a check shows a problem, fetch its details "
        "(findings, incidents, node detail) before reporting; never guess what a problem is. When you are started, "
        "do the task now: the trigger has already decided it is time, so never skip work because of today's date. "
        "When you save, write or bundle files, say each file's name in your answer. Never say you did something "
        "unless a tool result in this run confirms it. Before you state a total, add up the items you list: the "
        "total must equal both the tool results and your own list. If a tool says its sign-in failed or no sign-in "
        "is saved, say so plainly: the saved sign-in for that system needs updating on the Tools page. In lists and "
        "files, give each item once (merge repeated entries for the same thing), and never leave an item out because "
        "it has no name: show it by its id or address instead.")
DETAIL = {"short": "Answer briefly: the outcome first, then at most three key points.",
          "detailed": "Answer in full: outcome, findings per system, and recommended next steps.",
          "report": "Write a structured report with a summary, findings per system, and recommended actions.",
          "table": "Answer with one table (Markdown), one row per item with the same columns for every row, then one "
                   "line of summary under it.",
          "data": 'Answer with ONE JSON object and no other text (except a final STATUS line if you are told to end with '
                  'one): {"status": "ok" or "problem", "summary": "one line", "items": [one object per item, every '
                  'object with the same fields]}. Other systems read this answer, so keep exactly this shape.'}
EFFORT = {"quick": 2, "normal": 4, "deep": 8}   # tool calls allowed in one run (limits per run)
STATUS_PROBLEM = "STATUS: PROBLEM"
PROBLEM = ("What counts as a problem: any state other than healthy/ok/running (degraded, warning, critical, down, "
           "failed, not synchronizing), any open incident, unacknowledged alert or open finding of warning or worse. "
           "Check every item the tools return before you decide; never call something healthy that a tool reported "
           "otherwise.")
NOTIFY = {"problems": PROBLEM + f" End your answer with one final line: '{STATUS_PROBLEM}' if you found any problem, otherwise 'STATUS: OK'. "
                      "People are notified automatically from that line; you do not send notifications yourself and never say "
                      "that you cannot.",
          "always": "Your answer is sent to people automatically when you finish; make it a clear, self-contained update. "
                    "You do not send messages yourself and never say that you cannot.",
          "never": ""}
ROUTER = "ConditionalRouter"
PROVIDERS = {"ollama": "Ollama", "openai": "vLLM"}


class DirectorError(ValueError):
    """The choices cannot produce a valid agent (shown to the person with the reason)."""



def _brand_name() -> str:
    from agent_studio.brand import brand

    return brand()["name"]

def profile_for(brain: str) -> str:
    """fast -> ai.default, thorough -> ai.reasoning (falls back to default)."""
    return "reasoning" if brain == "thorough" and settings.load()["ai"].get("reasoning") else "default"


def model_of(profile: str) -> dict:
    """The engine's model choice for one ai profile: {provider (engine name), name, base_url}."""
    ai = settings.load()["ai"]
    prof = ai.get(profile) or ai["default"]
    provider = prof.get("provider", ai["default"].get("provider"))
    return {"provider": PROVIDERS.get(provider, provider), "name": prof.get("model", ai["default"].get("model")),
            "base_url": prof.get("base_url", ai["default"].get("base_url"))}


def model_for(brain: str) -> dict:
    return model_of(profile_for(brain))


def brain_params(model: dict) -> dict:
    """Model step settings for one model. Ollama needs its address on the step; vLLM reads VLLM_API_BASE."""
    params = {"model": {"provider": model["provider"], "name": model["name"]}, "temperature": 0.1}
    if model["provider"] == "Ollama":
        params["ollama_base_url"] = model["base_url"]
    return params


MODEL_STEP = "LanguageModelComponent"


def work_loop(plan: dict) -> str:
    """Plan -> act -> check -> one more try, inside every run (the agent checks its own work before it answers)."""
    goals = [g.strip() for g in plan.get("goals") or [] if g.strip()] or [plan.get("understood") or ""]
    goals = [g for g in goals if g]
    text = ("How you work: first decide which tool calls cover your goals; make them; then, before you answer, check "
            "every goal against the tool results. If a goal is not covered or a tool failed, make one more attempt "
            "another way (other arguments or another tool). Then answer, and name any goal you could not finish and why.")
    return text + ("\nYour goals:\n- " + "\n- ".join(goals) if goals else "")


def instructions(plan: dict, prefs: dict, tool_names: list[str], briefs: list[str] | None = None) -> str:
    lang = "Answer in Arabic." if plan.get("language") == "ar" else "Answer in English."
    parts = [BASE, plan.get("instructions", "").strip(), DETAIL.get(prefs["detail"], ""), NOTIFY.get(prefs["notify"], "")]
    if prefs["acts"] == "with_approval":
        parts.append("You do not change any system yourself: propose the exact action (which system, which target, "
                     "what to do and why) and wait for a person to approve it.")
    if prefs.get("corrections"):
        parts.append("People who use you corrected earlier answers. Always follow these corrections:\n- "
                     + "\n- ".join(prefs["corrections"]))
    if prefs.get("skills"):
        from agent_studio import skills   # skills are stored know-how; their text becomes part of the instructions
        parts.append(skills.text_for(prefs["skills"]))
    if tool_names:
        parts.append("Your tools: " + ", ".join(tool_names) + ".")
        parts.append(work_loop(plan))
    if briefs:
        parts.append("What exists (use only these names): " + " | ".join(briefs))
    if prefs.get("sub_agents"):
        parts.append("Other agents work for you as tools. To ask one, call its tool with exactly this argument: "
                     'flow_tweak_data = {"input~input_value": "<the question for that agent>"} - pass the full '
                     "question (or the part that agent handles). Build your answer only from what those agents return. "
                     "Handoff: when the whole request belongs to one of those agents, pass it the full request with "
                     "everything the person said that matters, and give its answer as it is, saying which agent answered.")
    caps = set(prefs["capabilities"])
    if caps & {"save_data", "bundle_files", "document"}:
        steps = ["first collect the data with your other tools"]
        if "save_data" in caps:
            steps.append("call the save-data tool with the collected records as rows (several tables if the data has "
                         "different kinds of records)")
        if "document" in caps:
            steps.append("call the document tool with the findings")
        if "bundle_files" in caps:
            steps.append("call the bundle tool with the file names the previous tools returned")
        parts.append("This task produces files. In this run: " + "; then ".join(steps) + ". You are not finished until "
                     "those tools have returned file names; report exactly those names.")
    if prefs["acts"] == "with_approval" and briefs:
        parts.append("Propose only an action listed under 'actions' above, with its target and fields.")
    parts.append(lang)
    return "\n\n".join(p for p in parts if p)


def build(plan: dict, prefs: dict, my_agents: dict[str, str] | None = None, known: dict | None = None) -> dict:
    """Return {"definition": {...}, "left_out": [...]} for engine compile."""
    caps = capabilities.by_id()
    channels = {c["id"]: c for c in capabilities.notify_channels()}
    my_agents = my_agents or {}
    steps, conns, left_out = [], [], []

    def step(sid, component, params=None, x=0, y=0):
        steps.append({"id": sid, "component": component, "params": params or {}, "position": {"x": x, "y": y}})
        return sid

    def link(src, out, dst, inp):
        conns.append({"from": src, "output": out, "to": dst, "input": inp})

    read_tools, write_tools, names = [], [], []
    read_briefs, write_briefs = [], []   # what really exists on each app, so plans name real operations and actions
    notify_params = None
    for i, cid in enumerate(prefs["capabilities"]):
        cap = caps.get(cid)
        if not cap:
            continue
        if cap["status"] != "ready":
            left_out.append({"capability": cid, "label": cap["label"], "reason": "needs setup"})
            continue
        writes = cap.get("side_effect") == "write"
        if writes and prefs["acts"] == "read_only" and cid != "notify":
            left_out.append({"capability": cid, "label": cap["label"], "reason": "agent is read-only"})
            continue
        params = copy.deepcopy(cap["tool"].get("params") or {})
        if cap.get("mcp", {}).get("key_env") and isinstance(params.get("mcp_server"), dict):
            # an MCP server's access key: from its environment variable at build time, never from a file
            key = os.environ.get(cap["mcp"]["key_env"], "")
            if key:
                params["mcp_server"].setdefault("config", {})["headers"] = {cap["mcp"].get("key_header") or "x-api-key": key}
        template_fields = set(params)
        if "app" in template_fields:                      # pin the tool to its one app (allowlist inside the tool too)
            params["allowed_apps"] = params["app"]
        if cid == "notify":
            chan = prefs.get("channel") or next(iter(channels), None)
            if not chan or chan not in channels:
                left_out.append({"capability": cid, "label": cap["label"], "reason": "no notification channel set up"})
                continue
            if prefs["notify"] == "never":
                left_out.append({"capability": cid, "label": cap["label"], "reason": "you chose never to notify"})
                continue
            if channels[chan]["needs_approval"]:
                left_out.append({"capability": cid, "label": cap["label"], "reason": "this channel needs an approval per message; choose a pre-approved channel"})
                continue
            # Rule: a promised notification must not depend on the model choosing to call a tool. The agent judges
            # (status line); the flow sends. Pre-approved channel -> approved by configuration, not by the model.
            notify_params = {"channel": chan, "allowed_channels": chan, "approved": True, "dry_run": False,
                             "subject": f"{_brand_name()} - {prefs['name']}", "severity": "warning" if prefs["notify"] == "problems" else "info"}
            continue
        sid = step(f"tool-{cid}", cap["tool"]["component"], params, x=-420, y=260 + 150 * i)
        names.append(cap["label"].lower())
        if "app" in template_fields:
            (write_briefs if writes else read_briefs).append(capabilities.app_brief(params["app"], (known or {}).get(params["app"])))
        if "tool_id" in template_fields:                  # a tool written by AI: its operations and arguments
            from agent_studio import codetools
            (write_briefs if writes else read_briefs).append(codetools.brief(params["tool_id"], params.get("allowed_operations", "")))
        (write_tools if writes and cid != "notify" else read_tools).append(sid)

    for j, agent_id in enumerate(prefs.get("sub_agents") or []):
        if agent_id not in my_agents:
            left_out.append({"capability": f"agent:{agent_id}", "label": "sub-agent", "reason": "not found"})
            continue
        sid = step(f"sub-{j + 1}", SUB_AGENT, {"flow_id_selected": agent_id, "flow_name_selected": my_agents[agent_id]},
                   x=-420, y=260 + 150 * (len(read_tools) + j + 1))
        names.append(f"the '{my_agents[agent_id]}' agent")
        read_tools.append(sid)

    model = model_for(prefs["brain"])
    system = instructions(plan, prefs, names, read_briefs + write_briefs)
    # Rule: agents think through ONE explicit model step carrying the model AND its server address, so every run
    # mode (including resuming an approved run, where the engine drops per-user settings) reaches the configured
    # server.
    brain = step("brain", MODEL_STEP, brain_params(model), x=-700, y=-260)

    # ---- entry
    if prefs["trigger"] == "chat":
        entry, entry_out = step("input", CHAT_IN, {}, x=-800, y=0), "message"
        result_component = CHAT_OUT
    else:
        task = plan.get("instructions") or plan.get("understood") or "Run your task now."
        if prefs["trigger"] == "schedule":
            cron = prefs.get("cron") or plan.get("cron")
            if not cron:
                raise DirectorError("A scheduled agent needs a schedule.")
            trig = step("trigger", SCHEDULE, {"cron_expression": cron, "timezone": prefs.get("timezone") or "Asia/Dubai"}, x=-1100, y=0)
            pattern = f"Scheduled run: it is time to run now (the schedule decided that; do not check the date). Task: {task}"
        elif prefs["trigger"] == "watch":
            # keeps an eye on a system: looks again every few minutes, all looks share one conversation (the
            # engine's share_session), so the agent sees what it found last time and reports only what changed
            cron = prefs.get("cron") or plan.get("cron") or WATCH_CRON
            trig = step("trigger", SCHEDULE, {"cron_expression": cron, "timezone": prefs.get("timezone") or "Asia/Dubai",
                                              "share_session": True}, x=-1100, y=0)
            pattern = WATCH_ROUND + f" Task: {task}"
        else:
            trig = step("trigger", WEBHOOK, {}, x=-1100, y=0)
            pattern = f"An alert arrived: {{text}}\nTask: {task}"
        entry = step("task", PARSER, {"mode": "Stringify" if prefs["trigger"] == "alert" else "Parser", "pattern": pattern}, x=-800, y=0)
        link(trig, "trigger_event", entry, "input_data")
        entry_out = "parsed_text"
        result_component = CHAT_OUT  # a recorded output: every run (scheduled or alert) is kept with its tool trace

    # ---- main agent (read tools; write tools only after approval)
    agent_params: dict = {"system_prompt": system}
    if prefs["trigger"] == "watch":
        agent_params["n_messages"] = WATCH_MEMORY   # its last few looks only: enough to compare, small for the model
    # Limits per run (the person's choice, default normal). A 32k-token model fills up after ~6
    # tool results, so even "deep" stops in time and answers with what it has.
    uses = EFFORT.get(prefs.get("effort") or "normal", 4)
    agent_params["max_iterations"] = uses + 2
    agent_params["system_prompt"] = system + (f"\n\nYou may use your tools at most {uses} times in this run: start with "
                                              "summaries, ask only for what you need, never fetch the same thing "
                                              "twice, then answer with what you have.")
    agent = step("agent", AGENT, agent_params, x=-400, y=0)
    link(brain, "model_output", agent, "model")
    link(entry, entry_out, agent, "input_value")
    for t in read_tools:
        link(t, "tool", agent, "tools")

    if write_tools:
        # The proposal passes through a plain-text step: a resumed run then restores it from the checkpoint instead
        # of re-running the agent (Langflow 1.13.2 re-runs an Agent that feeds a HumanInput directly).
        proposal = step("proposal", "CombineText", {"delimiter": "", "text2": ""}, x=-150, y=0)
        link(agent, "response", proposal, "text1")
        approval = step("approval", APPROVAL, {"decisions": ["Approve", "Reject"]}, x=0, y=0)
        link(proposal, "combined_text", approval, "prompt")
        executor = step("executor", AGENT, {"system_prompt": (
            "A person approved the action below. Carry out exactly that action with your tools, once, then report "
            "the result. If the approved text does not name a clear action, do nothing and say why.\n\nAvailable: "
            + " | ".join(write_briefs))}, x=400, y=-120)
        link(brain, "model_output", executor, "model")
        link(approval, "branch_approve", executor, "input_value")
        for t in write_tools:
            for st in steps:
                if st["id"] == t:
                    st["params"].update({"approved": True, "dry_run": False})  # reached only through the human approval step
            link(t, "tool", executor, "tools")
        done = step("result", result_component, {}, x=800, y=-120)
        link(executor, "response", done, "input_value")
        rejected = step("rejected", CHAT_OUT, {}, x=400, y=160)
        link(approval, "branch_reject", rejected, "input_value")
    else:
        done = step("result", result_component, {}, x=0, y=0)
        link(agent, "response", done, "input_value")

    if notify_params:
        source = "executor" if write_tools else "agent"
        notify = step("notify", NOTIFY_KEY, notify_params, x=400, y=320)
        if prefs["notify"] == "problems":
            router = step("problem", ROUTER, {"match_text": STATUS_PROBLEM, "operator": "contains", "case_sensitive": False}, x=0, y=320)
            link(source, "response", router, "input_text")
            link(router, "true_result", notify, "body")
        else:
            link(source, "response", notify, "body")

    if not any(s["id"].startswith(("tool-", "sub-")) for s in steps) and prefs["capabilities"]:
        # Nothing usable: still a valid agent (answers from the model), but tell the person.
        pass
    return {"definition": {"steps": steps, "connections": conns}, "left_out": left_out, "model": model}


_TRIGGER_WORDS = {"chat": "When someone chats with it", "alert": "When an alert arrives",
                  "watch": "It keeps watching and acts on what is new or changed"}
WATCH_CRON = "*/15 * * * *"
WATCH_MEMORY = 6
WATCH_ROUND = ("Watch round: look again now (the schedule decided it is time). Your earlier rounds are in this "
               "conversation. Report only what is NEW or CHANGED since your last round: new problems, problems that got "
               "worse, and problems that are now fixed. If nothing changed, answer in one line: 'No change since the last "
               "look.' and end with 'STATUS: OK'. End with 'STATUS: PROBLEM' only when something new needs attention.")


def summary(plan: dict, prefs: dict, built: dict) -> dict:
    """Plain-language description generated FROM the built definition (what you read is what gets built)."""
    caps = capabilities.by_id()
    steps = {s["id"]: s for s in built["definition"]["steps"]}
    tools = [caps[c]["label"] for c in prefs["capabilities"]
             if c in caps and f"tool-{c}" in steps]
    subs = [s["params"].get("flow_name_selected") for s in steps.values() if s["component"] == SUB_AGENT]
    if prefs["trigger"] == "watch":
        when = f"Keeps watching: looks again {prefs.get('schedule_text') or 'every 15 minutes'} and acts only on what is new or changed"
    elif prefs["trigger"] == "schedule":
        when = f"On a schedule: {prefs.get('schedule_text') or prefs.get('cron')} ({steps['trigger']['params']['cron_expression']}, {steps['trigger']['params']['timezone']})"
    else:
        when = _TRIGGER_WORDS[prefs["trigger"]]
    does = [when, "It works out what to do from your instructions"]
    if tools:
        does.append("It can use: " + ", ".join(tools))
    if subs:
        does.append("It can ask these agents: " + ", ".join(subs))
    if "approval" in steps:
        does.append("Before it changes anything, a person must approve the exact action")
    if "notify" in steps:
        chan = steps["notify"]["params"].get("channel")
        does.append(f"It notifies {chan} " + ("only when something is wrong" if prefs["notify"] == "problems" else "every time"))
    will_not = []
    if "approval" not in steps:
        will_not.append("It will not change any system")
    will_not += [f"It will not use '{x['label']}' ({x['reason']})" for x in built["left_out"]]
    model = built["model"]
    return {"name": prefs["name"], "does": does, "will_not": will_not, "thinks_with": f"{model['name']} ({model['provider']})",
            "answer_style": prefs["detail"]}


def describe(plan: dict, prefs: dict) -> str:
    """One plain line for lists: what the agent does (its goals), not how the request was phrased."""
    goals = [g.strip().rstrip(".") for g in plan.get("goals") or [] if g.strip()]
    text = "; ".join(goals) or plan.get("understood", "")
    text = re.sub(r"^(the user wants|you want|user wants)( an agent)?( that)?( to)?\s*", "", text, flags=re.I).strip()
    return (text[:1].upper() + text[1:])[:300]


def first_test(plan: dict, prefs: dict, said: str = "") -> str:
    """The message used for the automatic first run that proves the agent. A chat agent is tried with the person's
    own first request when it asks for something concrete (exact names, files, servers survive); otherwise with
    its goals."""
    if prefs["trigger"] == "chat":
        describes_agent = re.search(r"(?i)\b(create|build|make|design|set up)\b.{0,40}\b(agent|bot|assistant)\b|أنشئ|اصنع|ابن"
                                    r"|\b(i want|i need|i'd like) to (ask|chat|talk)\b|\banswer (my )?questions\b", said)
        concrete = re.search(r"\b[\w-]+\.(pdf|docx?|xlsx?|csv|txt|json|zip)\b|\b[A-Z]{2,}[\w-]*\d+\b", said)
        if said.strip() and concrete and not describes_agent:
            return said.strip()[:2000]                      # a real task with real names: exactly the person's words
        samples = [str(q) for q in plan.get("sample_questions") or [] if str(q).strip()]
        if samples:
            return samples[0]                               # a description of a service: one of its own sample questions
        goals = plan.get("goals") or [plan.get("understood") or "help me"]
        return "Please do this now: " + "; ".join(goals)
    return "Test run requested by the owner: do the whole task once now, exactly as on a scheduled run."


def default_prefs(plan: dict) -> dict:
    """The preferences card, preselected from the plan (the person can change any of it)."""
    return {"name": plan.get("name") or "New agent", "trigger": plan.get("trigger", "chat"), "cron": plan.get("cron"),
            "schedule_text": plan.get("schedule_text"), "timezone": "Asia/Dubai",
            "capabilities": list(plan.get("capabilities") or []), "acts": plan.get("acts", "read_only"),
            "notify": plan.get("notify", "never"), "channel": None, "detail": plan.get("detail", "short"),
            "brain": "fast", "effort": "normal", "sub_agents": list(plan.get("sub_agents") or [])}
