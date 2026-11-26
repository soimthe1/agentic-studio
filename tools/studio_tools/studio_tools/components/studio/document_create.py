"""document_create: DOCX / XLSX from a registered template + data, written to the configured output folder."""

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, MultilineInput, NestedDictInput, Output
from lfx.schema.data import Data

from studio_tools.components.common import acting_user, to_data
from studio_tools.core import envelope, files
from studio_tools.core.catalog import DOCUMENT_CREATE as SPEC
from studio_tools.core.config import load_config
from studio_tools.core.documents import FORMATS, generate
from studio_tools.core.util import parse_json


class DocumentCreateComponent(Component):
    display_name = "Agent Studio Document Create"
    description = SPEC.description
    icon = "file-text"
    name = "StudioDocumentCreate"
    tool_spec = SPEC

    inputs = [
        DropdownInput(name="format", display_name="Format", options=list(FORMATS), value="docx", tool_mode=True),
        NestedDictInput(name="data", display_name="Data", tool_mode=True, required=True, value={},
                        info='JSON object, e.g. {"title": "Weekly report", "period": "W45", "rows": [{...}, ...]}.'),
        MessageTextInput(name="template", display_name="Template", tool_mode=True, value="",
                         info="Leave empty: a plain document is made. Only set it to a template name an administrator gave you; never guess one."),
        MessageTextInput(name="filename", display_name="File name", tool_mode=True, value="report",
                         info="Base name; a timestamp and the extension are added."),
        MessageTextInput(name="acting_user", display_name="Acting user", advanced=True, value="",
                         info="Set by the Agent Studio backend; recorded in the result's source."),
    ]
    outputs = [Output(display_name="Result", name="result", method="document_create")]

    def document_create(self) -> Data:
        def work():
            cfg = dict(load_config().get("documents") or {})
            cfg["output_dir"] = str(files.user_dir(self.user_id))  # documents land in the owner's files
            return generate(cfg, fmt=self.format, data=parse_json(self.data, "data", default={}),
                            template=(self.template or "").strip() or None, filename=self.filename)

        return to_data(self, envelope.run(work, source={"tool": SPEC.name, "as_user": acting_user(self)}))
