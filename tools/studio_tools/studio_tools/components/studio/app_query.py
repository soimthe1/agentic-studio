"""app_query: generic read connector to registered internal apps (SQL Monitor, IIS Monitor, generic)."""

from lfx.custom.custom_component.component import Component
from lfx.io import IntInput, MessageTextInput, NestedDictInput, Output
from lfx.schema.data import Data

from studio_tools.components.common import acting_user, flow_policy_inputs, to_data
from studio_tools.core import apps, envelope
from studio_tools.core.catalog import APP_QUERY as SPEC
from studio_tools.core.config import get_connection
from studio_tools.core.util import check_agent_scope, parse_json, scope_one


class AppQueryComponent(Component):
    display_name = "Agent Studio App Query"
    description = SPEC.description
    icon = "activity"
    name = "StudioAppQuery"
    tool_spec = SPEC

    inputs = [
        MessageTextInput(name="app", display_name="App", tool_mode=True, required=True,
                         info="Registered app name from tools.yaml (section apps), e.g. sqlmon or iis."),
        MessageTextInput(name="operation", display_name="Operation", tool_mode=True, required=True,
                         info="Operation of that app, e.g. health_summary, findings, fleet_health, incidents, "
                              "node_detail, slow_requests."),
        MessageTextInput(name="target", display_name="Target", tool_mode=True, value="",
                         info="Server / SQL instance / IIS node hostname the operation is about (if any)."),
        NestedDictInput(name="filters", display_name="Filters", tool_mode=True, value={},
                        info='Optional JSON object, e.g. {"severity": "critical"} or {"query_hash": "0x1A"}.'),
        IntInput(name="limit", display_name="Limit", tool_mode=True, value=50, info="Max list items (<= 200)."),
        *flow_policy_inputs(scope_name="allowed_apps", scope_info="Apps this agent may query."),
    ]
    outputs = [Output(display_name="Result", name="result", method="app_query")]

    def app_query(self) -> Data:
        name, op, target = (self.app or "").strip(), (self.operation or "").strip(), (self.target or "").strip()
        name = scope_one(name, self.allowed_apps)
        user = acting_user(self)

        def work():
            check_agent_scope(name, self.allowed_apps, "app")
            app = get_connection("apps", name)
            return apps.query(app, op, target=target or None, filters=parse_json(self.filters, "filters", default={}),
                              limit=self.limit, as_user=user)

        return to_data(self, envelope.run(work, source={"tool": SPEC.name, **apps.source(name, op, target or None, user)}))
