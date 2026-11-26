"""Diagnostic: proves the Agent Studio bundle is loaded and executable under the hardened settings.

Used by tests/security and the upgrade check on every Langflow release. Pure function, no I/O.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.message import Message

from studio_tools import __name__ as _pkg
from studio_tools.core.catalog import BUNDLE_CHECK as SPEC

VERSION = "0.3.0"


class BundleCheckComponent(Component):
    display_name = "Agent Studio Bundle Check"
    description = "Returns the Agent Studio tools bundle version. Use to verify the bundle is installed and runnable."
    icon = "badge-check"
    name = "StudioBundleCheck"
    tool_spec = SPEC

    inputs = [MessageTextInput(name="input_value", display_name="Input", value="ping", tool_mode=True)]
    outputs = [Output(display_name="Result", name="result", method="check")]

    def check(self) -> Message:
        return Message(text=f"{_pkg} {VERSION} ok: {self.input_value}")
