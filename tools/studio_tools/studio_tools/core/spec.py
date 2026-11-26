"""Declared contract of every Agent Studio tool (feeds the tool catalog and the Tool Advisor)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str  # LLM-facing
    side_effects: str  # "none" | "read" | "write"
    timeout_s: float  # default; a connection may lower/raise it in tools.yaml
    retry: str  # human-readable policy; writes never auto-retry
    connection: str  # tools.yaml section the tool draws its named connection from ("" = none)
    approval_required: bool
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def approval_gate(*, approved: bool, dry_run: bool, write_allowed: bool, what: str) -> str | None:
    """Return None when a write may execute, else the reason it must not.

    The gate lives inside each write tool so that removing an approval node from a flow cannot bypass it.
    ``approved`` and ``dry_run`` are deliberately NOT tool_mode inputs: the LLM cannot set them, only the flow
    (a human-approval step or the flow builder) can.
    """
    if not write_allowed:
        return f"{what}: the connection is not configured to allow writes (allow_write/allow_post is false)"
    if dry_run:
        return f"{what}: dry run (dry_run is true); nothing was executed"
    if not approved:
        return f"{what}: not approved; a human approval (approved=true) is required before execution"
    return None
