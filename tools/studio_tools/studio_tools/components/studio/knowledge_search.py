"""knowledge_search: the knowledge platform search / cited answer AS THE REQUESTING USER (unavailable for now)."""

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, IntInput, MessageTextInput, Output
from lfx.schema.data import Data

from studio_tools.components.common import acting_user, flow_policy_inputs, to_data
from studio_tools.core import envelope
from studio_tools.core.catalog import KNOWLEDGE_SEARCH as SPEC
from studio_tools.core.config import load_config
from studio_tools.core.knowledge import knowledge_query


class KnowledgeSearchComponent(Component):
    display_name = "Agent Studio Knowledge Search"
    description = SPEC.description
    icon = "book-open"
    name = "StudioKnowledgeSearch"
    tool_spec = SPEC

    inputs = [
        MessageTextInput(name="query", display_name="Query", tool_mode=True, required=True,
                         info="The question or search terms."),
        DropdownInput(name="mode", display_name="Mode", options=["answer", "search"], value="answer", tool_mode=True,
                      info="answer = cited answer; search = matching passages."),
        IntInput(name="top_k", display_name="Top K", value=5, tool_mode=True, info="Passages to use (<= 10)."),
        *flow_policy_inputs(scope_name="allowed_scopes", scope_info="Reserved (not used in v1)."),
    ]
    outputs = [Output(display_name="Result", name="result", method="knowledge_search")]

    def knowledge_search(self) -> Data:
        user = acting_user(self)

        def work():
            cfg = load_config().get("knowledge")
            return knowledge_query(cfg, mode=self.mode, query=self.query, as_user=user, top_k=self.top_k)

        return to_data(self, envelope.run(work, source={"tool": SPEC.name, "app": "knowledge", "as_user": user}))
