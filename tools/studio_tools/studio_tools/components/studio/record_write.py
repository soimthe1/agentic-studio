"""record_write: one record into an allowlisted SQL table or a registered app record type, with approval."""

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, MultilineInput, NestedDictInput, Output
from lfx.schema.data import Data

from studio_tools.components.common import acting_user, flags, flow_policy_inputs, to_data
from studio_tools.core import envelope
from studio_tools.core.catalog import RECORD_WRITE as SPEC
from studio_tools.core.records import write_record
from studio_tools.core.util import check_agent_scope, parse_json, scope_one


class RecordWriteComponent(Component):
    display_name = "Agent Studio Record Write"
    description = SPEC.description
    icon = "file-pen-line"
    name = "StudioRecordWrite"
    tool_spec = SPEC

    inputs = [
        MessageTextInput(name="system", display_name="System", tool_mode=True, required=True,
                         info="Registered record system: an SQL connection or an app name from tools.yaml."),
        MessageTextInput(name="record_type", display_name="Record type", tool_mode=True, required=True,
                         info="Allowlisted table (e.g. ops.incident_notes) or the app's record type."),
        NestedDictInput(name="fields", display_name="Fields", tool_mode=True, required=True, value={},
                        info='JSON object of field -> value, e.g. {"server": "WEB01", "note": "..."}.'),
        MessageTextInput(name="reason", display_name="Reason", tool_mode=True, value="",
                         info="Why this record is written (kept in the plan / trace)."),
        *flow_policy_inputs(scope_name="allowed_systems", scope_info="Record systems this agent may write.",
                            writes=True),
    ]
    outputs = [Output(display_name="Result", name="result", method="record_write")]

    def record_write(self) -> Data:
        system, rtype = (self.system or "").strip(), (self.record_type or "").strip()
        system = scope_one(system, self.allowed_systems)
        approved, dry_run = flags(self)
        user = acting_user(self)

        def work():
            check_agent_scope(system, self.allowed_systems, "system")
            return write_record(system, rtype, parse_json(self.fields, "fields", default={}), approved=approved,
                                dry_run=dry_run, reason=self.reason or "", as_user=user)

        return to_data(self, envelope.run(work, source={"tool": SPEC.name, "system": system, "record_type": rtype,
                                                        "as_user": user}))
