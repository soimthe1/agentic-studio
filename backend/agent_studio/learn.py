"""'Not right? Tell it how' takes effect at once: a correction is written into the agent's instructions right away
(the steps stay as they are, a live agent stays live and keeps its schedule), and a new version records it."""

from __future__ import annotations

import re

from fastapi.concurrency import run_in_threadpool

from agent_studio import store

HEAD = "People who use you corrected earlier answers. Always follow these corrections:"
BLOCK = re.compile(re.escape(HEAD) + r"\n(?:- [^\n]*(?:\n|$))+")


def with_corrections(prompt: str, fixes: list[str]) -> str:
    block = HEAD + "\n- " + "\n- ".join(fixes)
    if BLOCK.search(prompt or ""):
        return BLOCK.sub(lambda _m: block + "\n", prompt, count=1).rstrip()
    return (prompt or "").rstrip() + "\n\n" + block


async def apply_now(e, agent_id: str) -> bool:
    """Put every correction made on this agent into its instructions now. True when the agent was changed."""
    fixes = [f["correction"] for f in await run_in_threadpool(store.corrections, agent_id)][-20:]
    if not fixes:
        return False
    definition = await e.get_definition(agent_id)
    changed = False
    for st in definition.get("steps") or []:
        prompt = (st.get("params") or {}).get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            st["params"]["system_prompt"] = with_corrections(prompt, fixes)
            changed = True
    if not changed:
        return False
    await e.save_definition(agent_id, definition)
    life = await run_in_threadpool(store.life, agent_id)
    if life and life["state"] == "live":
        n = (await e.snapshot(agent_id, "Correction applied: " + fixes[-1][:200]))["version_number"]   # recorded
        await run_in_threadpool(store.set_life, agent_id, life["owner"], "live", n, life.get("owner_name"))
    await run_in_threadpool(store.mark_corrections_applied, agent_id)
    return True



# ---------------------------------------------------------------- notes an agent keeps between runs (long-term memory)
NOTES_HEAD = "Notes you made in earlier runs (facts about the systems you look after; use them, but trust today's tool results first):"
NOTES_BLOCK = re.compile(r"\n*" + re.escape(NOTES_HEAD) + r"\n(?:- [^\n]*(?:\n|$))+")
NOTES_ASK = ("You keep short notes for an AI agent between its runs. From this run, write at most 3 durable facts worth "
             "knowing next time (a recurring pattern, a known exception, which item is normal for this system). No "
             "one-off numbers, no dates, nothing already in the notes. Answer JSON: {\"notes\": [\"...\"]} ([] if none).")


def with_notes(prompt: str, notes: list[str]) -> str:
    prompt = NOTES_BLOCK.sub("", prompt or "").rstrip()
    return prompt + ("\n\n" + NOTES_HEAD + "\n- " + "\n- ".join(notes) if notes else "")


def extract_notes(reply: str, have: list[str]) -> list[str]:
    import json

    from agent_studio import ai_providers

    from agent_studio import settings
    ai_providers.configure(settings.load()["ai"], base_dir=settings.REPO)
    raw = ai_providers.chat([{"role": "system", "content": NOTES_ASK},
                             {"role": "user", "content": json.dumps({"notes_so_far": have, "agent_answer": reply[:6000]},
                                                                    ensure_ascii=False)}], json_mode=True)
    try:
        return [str(n).strip()[:300] for n in (json.loads(raw).get("notes") or []) if str(n).strip()][:3]
    except (ValueError, AttributeError):
        return []


async def remember_run(e, agent_id: str, reply: str) -> bool:
    """After a self-started run that met its goal: keep what is worth knowing next time, in the agent's instructions."""
    have = [n["note"] for n in await run_in_threadpool(store.notes, agent_id)]
    new = await run_in_threadpool(extract_notes, reply, have)
    if not new:
        return False
    await run_in_threadpool(store.add_notes, agent_id, new)
    return await apply_notes(e, agent_id)


async def apply_notes(e, agent_id: str) -> bool:
    notes = [n["note"] for n in await run_in_threadpool(store.notes, agent_id)]
    definition = await e.get_definition(agent_id)
    changed = False
    for st in definition.get("steps") or []:
        prompt = (st.get("params") or {}).get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            st["params"]["system_prompt"] = with_notes(prompt, notes)
            changed = True
    if changed:
        await e.save_definition(agent_id, definition)
    return changed


if __name__ == "__main__":
    p = with_corrections("You are an agent.", ["Give totals"])
    assert p.endswith("- Give totals") and HEAD in p
    p2 = with_corrections(p + "\n\nYou may use your tools at most 4 times.", ["Give totals", "List by id"])
    assert p2.count(HEAD) == 1 and "- List by id" in p2 and p2.endswith("at most 4 times.")
    n = with_notes("You are an agent.", ["SQL02 is always slow on Mondays"])
    assert n.endswith("- SQL02 is always slow on Mondays") and NOTES_HEAD in n
    assert with_notes(n, ["x"]).count(NOTES_HEAD) == 1 and with_notes(n, []) == "You are an agent."
    print("learn ok")
