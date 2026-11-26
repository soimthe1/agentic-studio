"""Quality: what an agent noted for its next runs (long-term memory, learn.py) and its test questions (an evaluation
set: question + what a good answer must contain, run again after every change to catch an agent getting worse).

A test run uses the same goal judge as the first test run (designer.check_result), with the expected answer as the
goal. Test runs are Agent Studio runs ("run-test-…"), so the goal watch never judges or retries them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agent_studio import activity, designer, learn, roles, store
from agent_studio.engine import Engine

router = APIRouter(prefix="/api/studio/v1", tags=["Quality"])
MAX_CASES = 10


class CaseIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    expect: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- notes (long-term memory)
@router.get("/agents/{agent_id}/notes", summary="What the agent noted in earlier runs for its next runs")
async def notes(agent_id: str, request: Request):
    async with Engine(request) as e:
        await e.get_agent(agent_id)
    return await run_in_threadpool(store.notes, agent_id)


@router.delete("/agents/{agent_id}/notes/{note_id}", status_code=204, summary="Remove a wrong note (the agent forgets it at once)",
               dependencies=[roles.need("builder")])
async def forget_note(agent_id: str, note_id: int, request: Request):
    async with Engine(request) as e:
        await e.get_agent(agent_id)
        await run_in_threadpool(store.delete_note, agent_id, note_id)
        await learn.apply_notes(e, agent_id)
        await activity.note_as(e, "removed a note an agent made", agent_id)


# ---------------------------------------------------------------- test questions (evaluation set)
@router.get("/agents/{agent_id}/tests", summary="The agent's test questions with their last result")
async def tests(agent_id: str, request: Request):
    async with Engine(request) as e:
        await e.get_agent(agent_id)
    return await run_in_threadpool(store.eval_cases, agent_id)


@router.post("/agents/{agent_id}/tests", status_code=201, summary="Add a test question and what a good answer must contain",
             dependencies=[roles.need("builder")])
async def add_test(agent_id: str, body: CaseIn, request: Request):
    async with Engine(request) as e:
        await e.get_agent(agent_id)
    if len(await run_in_threadpool(store.eval_cases, agent_id)) >= MAX_CASES:
        from fastapi import HTTPException
        raise HTTPException(409, f"An agent keeps at most {MAX_CASES} test questions. Remove one first.")
    return {"id": await run_in_threadpool(store.add_eval_case, agent_id, body.question.strip(), body.expect.strip())}


@router.delete("/agents/{agent_id}/tests/{case_id}", status_code=204, summary="Remove a test question", dependencies=[roles.need("builder")])
async def remove_test(agent_id: str, case_id: int, request: Request):
    async with Engine(request) as e:
        await e.get_agent(agent_id)
    await run_in_threadpool(store.delete_eval_case, agent_id, case_id)


def judge(question: str, expect: str, reply: str, tools: list[dict]) -> dict:
    """Same judge as an agent's first test run, with the expected answer as its goal."""
    check = designer.check_result({"understood": expect, "goals": [expect]}, question, reply, None, tools)
    return {"passed": check["verdict"] == "met", "verdict": check["verdict"], "missing": check["missing"][:3]}


@router.post("/agents/{agent_id}/tests/run", summary="Run every test question now and judge each answer", dependencies=[roles.need("builder")])
async def run_tests(agent_id: str, request: Request):
    from agent_studio.watch.goals import _run_of

    results = []
    async with Engine(request) as e:
        await e.get_agent(agent_id)
        for case in await run_in_threadpool(store.eval_cases, agent_id):
            out = await e.run_agent(agent_id, case["question"], f"run-test-{uuid.uuid4()}")
            if out["status"] == "done":
                _, reply, tools = await _run_of(e, out["session_id"])
                res = await run_in_threadpool(judge, case["question"], case["expect"], reply or out["reply"], tools)
            else:
                res = {"passed": False, "verdict": out["status"], "missing": [out["reply"][:200]]}
            res = {**res, "at": datetime.now(timezone.utc).isoformat(), "session_id": out.get("session_id")}
            await run_in_threadpool(store.set_eval_result, case["id"], res)
            results.append({**case, "last": res})
        passed = sum(1 for r in results if r["last"]["passed"])
        await activity.note_as(e, "ran an agent's test questions", agent_id, f"{passed} of {len(results)} passed")
    return {"passed": passed, "total": len(results), "cases": results}
