"""app_action: approval-gated, dry-run-by-default, never-retried action on a registered app."""

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, NestedDictInput, Output
from lfx.schema.data import Data

from studio_tools.components.common import acting_user, flags, flow_policy_inputs, to_data
from studio_tools.core import apps, envelope
from studio_tools.core.catalog import APP_ACTION as SPEC
from studio_tools.core.config import get_connection
from studio_tools.core.util import check_agent_scope, parse_json, scope_one


class AppActionComponent(Component):
    display_name = "Agent Studio App Action"
    description = SPEC.description
    icon = "shield-alert"
    name = "StudioAppAction"
    tool_spec = SPEC

    inputs = [
        MessageTextInput(name="app", display_name="App", tool_mode=True, required=True,
                         info="Registered app name (tools.yaml, section apps)."),
        MessageTextInput(name="action", display_name="Action", tool_mode=True, required=True,
                         info="Registered action of that app, e.g. acknowledge_finding."),
        MessageTextInput(name="target", display_name="Target", tool_mode=True, value="",
                         info="The one server / instance the action is about, if the action needs one."),
        NestedDictInput(name="params", display_name="Parameters", tool_mode=True, value={},
                        info='JSON object of the action parameters, e.g. {"finding_id": 42}.'),
        MessageTextInput(name="reason", display_name="Reason", tool_mode=True, required=True,
                         info="Why this action is needed (shown to the approver and kept in the trace)."),
        *flow_policy_inputs(scope_name="allowed_apps", scope_info="Apps this agent may act on.", writes=True),
    ]
    outputs = [Output(display_name="Result", name="result", method="app_action")]

    def app_action(self) -> Data:
        name, act, target = (self.app or "").strip(), (self.action or "").strip(), (self.target or "").strip()
        name = scope_one(name, self.allowed_apps)
        approved, dry_run = flags(self)
        user = acting_user(self)
        mock = False

        def work():
            nonlocal mock
            check_agent_scope(name, self.allowed_apps, "app")
            app = get_connection("apps", name)
            mock = bool(app.get("mock"))
            return apps.action(app, act, target=target or None, params=parse_json(self.params, "params", default={}),
                               reason=self.reason or "", approved=approved, dry_run=dry_run, as_user=user)

        env = envelope.run(work, source={"tool": SPEC.name, **apps.source(name, act, target or None, user)})
        if mock:
            env["source"]["mock"] = True
        return to_data(self, env)
