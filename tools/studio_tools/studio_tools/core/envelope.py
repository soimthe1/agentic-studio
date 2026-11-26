"""Uniform result envelope (the tool catalog): {ok, data | error{code, message}, source, fetched_at}.

Errors are returned, not raised, so a flow keeps running and an agent sees a clean, secret-free message.
Unexpected exceptions are reduced to their type name (no stack traces or connection strings to the LLM).
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Callable

from .errors import ConfigError, NotAllowed, ToolError, ToolTimeout, UpstreamError

log = logging.getLogger("studio_tools")

_CODES = [(ToolTimeout, "timeout"), (NotAllowed, "not_allowed"), (ConfigError, "config"),
          (UpstreamError, "upstream")]


def code_for(exc: BaseException) -> str:
    for cls, code in _CODES:
        if isinstance(exc, cls):
            return code
    if type(exc).__name__ == "Unavailable":
        return "unavailable"
    return "error"


def run(fn: Callable[[], Any], *, source: dict[str, Any]) -> dict[str, Any]:
    fetched_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    try:
        data = fn()
    except ToolError as exc:
        return {"ok": False, "error": {"code": code_for(exc), "message": str(exc)}, "source": source,
                "fetched_at": fetched_at}
    except Exception as exc:  # noqa: BLE001 - last line of defence; details go to the server log only
        log.exception("studio_tools: unexpected error in %s", source.get("tool"))
        return {"ok": False, "error": {"code": "internal", "message": f"internal error ({type(exc).__name__})"},
                "source": source, "fetched_at": fetched_at}
    return {"ok": True, "data": data, "source": source, "fetched_at": fetched_at}
