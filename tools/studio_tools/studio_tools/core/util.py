"""Small helpers shared by the components (kept free of lfx so they are unit-testable on their own)."""

from __future__ import annotations

import json
from typing import Any

from .errors import NotAllowed, ToolError


def parse_json(text: Any, what: str, *, default: Any = None, expect: type | tuple = dict) -> Any:
    """Accept a dict/list as-is (tool calls may pass structured values) or parse a JSON string."""
    if text is None or (isinstance(text, str) and not text.strip()):
        return default
    if isinstance(text, (dict, list)):
        value = text
    else:
        try:
            value = json.loads(str(text))
        except json.JSONDecodeError as exc:
            raise ToolError(f"{what} must be valid JSON: {exc.msg} at position {exc.pos}") from None
    if not isinstance(value, expect):
        names = expect.__name__ if isinstance(expect, type) else "/".join(t.__name__ for t in expect)
        raise ToolError(f"{what} must be a JSON {names.replace('dict', 'object').replace('list', 'array')}")
    return value


def scope_one(name: str, allowed_csv: str | None) -> str:
    """When the flow allows exactly one app/channel/connection, that one is used: the model cannot redirect the tool."""
    allowed = [s.strip() for s in (allowed_csv or "").split(",") if s.strip()]
    return allowed[0] if len(allowed) == 1 else name


def check_agent_scope(name: str, allowed_csv: str | None, kind: str = "connection") -> str:
    """Optional per-agent narrowing set by the flow builder (never by the LLM): the global tools.yaml
    allowlist says what exists, this says which of those this particular agent may use.
    Returns the name to use (see scope_one)."""
    name = scope_one(name, allowed_csv)
    allowed = {s.strip() for s in (allowed_csv or "").split(",") if s.strip()}
    if allowed and name not in allowed:
        raise NotAllowed(f"{kind} '{name}' is not enabled for this agent (enabled: {', '.join(sorted(allowed))})")
    return name


def as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")
