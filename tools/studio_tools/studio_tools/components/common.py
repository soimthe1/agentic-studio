"""Inputs and helpers shared by the Agent Studio components.

Lives OUTSIDE components/studio on purpose: the lfx loader imports every .py file in a bundle folder and
registers each Component subclass it declares; helpers here must not become catalog entries.
"""

from __future__ import annotations

from typing import Any

from lfx.io import BoolInput, StrInput
from lfx.schema.data import Data

from studio_tools.core.util import as_bool


def flow_policy_inputs(*, scope_name: str, scope_info: str, writes: bool = False) -> list:
    """Inputs set by the flow builder / approval step, never exposed to the LLM (no tool_mode)."""
    inputs = [
        StrInput(name=scope_name, display_name="Enabled for this agent", advanced=True, value="",
                 info=f"{scope_info} Comma-separated; empty = everything registered in tools.yaml."),
        StrInput(name="acting_user", display_name="Acting user", advanced=True, value="",
                 info="Requesting user's login, to be set by the Agent Studio backend (never by the LLM). Used where "
                      "the target supports on-behalf-of; recorded in the result's source."),
    ]
    if writes:
        inputs += [
            BoolInput(name="approved", display_name="Approved", value=False, advanced=False,
                      info="Set true only from a human approval step. The tool refuses to execute without it."),
            BoolInput(name="dry_run", display_name="Dry run", value=True, advanced=False,
                      info="Default true: plan and report only. Set false in the flow to allow real execution."),
        ]
    return inputs


def acting_user(component: Any) -> str | None:
    return (getattr(component, "acting_user", "") or "").strip() or None


def flags(component: Any) -> tuple[bool, bool]:
    return as_bool(getattr(component, "approved", False)), as_bool(getattr(component, "dry_run", True))


def to_data(component: Any, envelope: dict[str, Any]) -> Data:
    status = "ok" if envelope.get("ok") else f"error: {envelope.get('error', {}).get('message')}"
    data = envelope.get("data")
    if isinstance(data, dict) and data.get("status"):
        status = f"{data['status']}"
    component.status = status
    return Data(data=envelope)
