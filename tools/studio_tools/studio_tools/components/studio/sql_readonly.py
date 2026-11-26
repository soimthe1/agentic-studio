"""sql_readonly: one read-only SELECT on a named connection (replaces the blocked native SQL Database component)."""

from lfx.custom.custom_component.component import Component
from lfx.io import IntInput, MessageTextInput, MultilineInput, NestedDictInput, Output
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame

from studio_tools.components.common import acting_user, flow_policy_inputs, to_data
from studio_tools.core import envelope
from studio_tools.core.catalog import SQL_READONLY as SPEC
from studio_tools.core.config import get_connection
from studio_tools.core.sqlexec import run_select
from studio_tools.core.util import check_agent_scope, parse_json, scope_one


class SqlReadonlyComponent(Component):
    display_name = "Agent Studio SQL Read-only"
    description = SPEC.description
    icon = "database"
    name = "StudioSqlReadonly"
    tool_spec = SPEC

    inputs = [
        MessageTextInput(name="connection", display_name="Connection", tool_mode=True, required=True,
                         info="Name of an approved SQL connection (tools.yaml, section sql)."),
        MultilineInput(name="sql", display_name="SQL", tool_mode=True, required=True,
                       info="One SELECT or WITH ... SELECT statement. Use :name placeholders for values."),
        NestedDictInput(name="params", display_name="Parameters", tool_mode=True, value={},
                        info='JSON object with a value for every :name placeholder, e.g. {"since": "2026-11-01"}.'),
        IntInput(name="max_rows", display_name="Max rows", tool_mode=True, value=200,
                 info="Row cap; the connection's max_rows is the upper bound."),
        *flow_policy_inputs(scope_name="allowed_connections",
                            scope_info="SQL connections this agent may use."),
    ]
    outputs = [
        Output(display_name="Result", name="result", method="sql_readonly"),
        Output(display_name="Table", name="table", method="as_table", tool_mode=False),
    ]

    def _run(self) -> dict:
        name = (self.connection or "").strip()
        name = scope_one(name, self.allowed_connections)

        def work():
            check_agent_scope(name, self.allowed_connections)
            conn = get_connection("sql", name)
            params = parse_json(self.params, "params", default={})
            return run_select(conn, self.sql, params, max_rows=self.max_rows)

        return envelope.run(work, source={"tool": SPEC.name, "connection": name, "as_user": acting_user(self)})

    def sql_readonly(self) -> Data:
        return to_data(self, self._run())

    def as_table(self) -> DataFrame:
        env = self._run()
        if not env["ok"]:
            raise ValueError(env["error"]["message"])
        self.status = f"{env['data']['row_count']} rows" + (" (truncated)" if env["data"]["truncated"] else "")
        return DataFrame(env["data"]["rows"])
