"""notify: SMTP email / internal chat webhook to a registered channel. Never retried."""

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, MultilineInput, Output
from lfx.schema.data import Data

from studio_tools.components.common import acting_user, flags, flow_policy_inputs, to_data
from studio_tools.core import envelope
from studio_tools.core import notify as N
from studio_tools.core.catalog import NOTIFY as SPEC
from studio_tools.core.config import get_connection
from studio_tools.core.util import check_agent_scope, scope_one


class NotifyComponent(Component):
    display_name = "Agent Studio Notify"
    description = SPEC.description
    icon = "bell"
    name = "StudioNotify"
    tool_spec = SPEC

    inputs = [
        MessageTextInput(name="channel", display_name="Channel", tool_mode=True, required=True,
                         info="Registered channel name (tools.yaml, section notify)."),
        MessageTextInput(name="subject", display_name="Subject", tool_mode=True, required=True),
        MultilineInput(name="body", display_name="Body", tool_mode=True, required=True),
        DropdownInput(name="severity", display_name="Severity", options=list(N.SEVERITIES), value="info",
                      tool_mode=True),
        *flow_policy_inputs(scope_name="allowed_channels", scope_info="Channels this agent may use.", writes=True),
    ]
    outputs = [Output(display_name="Result", name="result", method="notify")]

    def notify(self) -> Data:
        name = (self.channel or "").strip()
        name = scope_one(name, self.allowed_channels)
        approved, dry_run = flags(self)

        def work():
            check_agent_scope(name, self.allowed_channels, "channel")
            ch = get_connection("notify", name)
            return N.send(ch, subject=self.subject, body=self.body, severity=self.severity,
                          approved=approved, dry_run=dry_run)

        return to_data(self, envelope.run(work, source={"tool": SPEC.name, "channel": name,
                                                        "as_user": acting_user(self)}))
