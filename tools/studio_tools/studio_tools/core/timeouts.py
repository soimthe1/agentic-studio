"""Wall-clock timeout for blocking calls that have no reliable timeout of their own."""

from __future__ import annotations

import threading
from typing import Any, Callable

from .errors import ToolTimeout


def run_with_timeout(fn: Callable[[], Any], timeout_s: float, what: str = "call") -> Any:
    """Run fn in a daemon thread; raise ToolTimeout if it does not finish in time.

    The worker is abandoned, not killed (Python cannot kill threads). Server-side timeouts (statement_timeout,
    max_execution_time, HTTP timeouts) are what actually stop the work; this guarantees the agent gets a clean
    error instead of hanging.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True, name="studio-tools-call")
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise ToolTimeout(f"{what} timed out after {timeout_s:.0f}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")
