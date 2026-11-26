"""Files an agent produces for its owner: data sets (SQLite / CSV / Excel / JSON), bundles (zip / 7z), web reads."""

from lfx.custom.custom_component.component import Component
from lfx.io import BoolInput, DropdownInput, MessageTextInput, NestedDictInput, Output
from lfx.schema.data import Data

from studio_tools.components.common import to_data
from studio_tools.core import envelope, files, web
from studio_tools.core.catalog import FILES_BUNDLE, SAVE_DATA, WEB_READ


class SaveDataComponent(Component):
    display_name = "Agent Studio Save Data"
    description = SAVE_DATA.description
    icon = "database"
    name = "StudioSaveData"
    tool_spec = SAVE_DATA

    inputs = [
        DropdownInput(name="format", display_name="Format", options=list(files.DATA_FORMATS), value="sqlite", tool_mode=True),
        NestedDictInput(name="data", display_name="Data", tool_mode=True, required=True, value={},
                        info='{"rows": [{...}, ...]} for one table, or {"tables": {"name": [{...}], ...}}.'),
        MessageTextInput(name="filename", display_name="File name", tool_mode=True, value="data",
                         info="Base name; the date and the extension are added."),
    ]
    outputs = [Output(display_name="Result", name="result", method="save_data")]

    def save_data(self) -> Data:
        return to_data(self, envelope.run(lambda: files.save_dataset(self.user_id, self.data, self.format, self.filename),
                                          source={"tool": SAVE_DATA.name}))


class FilesBundleComponent(Component):
    display_name = "Agent Studio Bundle Files"
    description = FILES_BUNDLE.description
    icon = "archive"
    name = "StudioBundleFiles"
    tool_spec = FILES_BUNDLE

    inputs = [
        MessageTextInput(name="files", display_name="Files", tool_mode=True, required=True,
                         info="Names of your files to put in the bundle, separated by commas."),
        DropdownInput(name="format", display_name="Format", options=list(files.ARCHIVE_FORMATS), value="zip", tool_mode=True),
        MessageTextInput(name="filename", display_name="File name", tool_mode=True, value="bundle"),
    ]
    outputs = [Output(display_name="Result", name="result", method="bundle_files")]

    def bundle_files(self) -> Data:
        names = [n.strip() for n in str(self.files or "").split(",")]
        return to_data(self, envelope.run(lambda: files.archive(self.user_id, names, self.format, self.filename),
                                          source={"tool": FILES_BUNDLE.name}))


class WebReadComponent(Component):
    display_name = "Agent Studio Read Web"
    description = WEB_READ.description
    icon = "globe"
    name = "StudioWebRead"
    tool_spec = WEB_READ

    inputs = [
        MessageTextInput(name="url", display_name="Address", tool_mode=True, required=True),
        DropdownInput(name="mode", display_name="Read as", options=list(web.MODES), value="text", tool_mode=True,
                      info="text: readable page text; links: the page's links; feed: RSS/Atom items or sitemap URLs; "
                           "json: an API answer; raw: just save the file."),
        BoolInput(name="save", display_name="Save a copy", tool_mode=True, value=False,
                  info="Also keep the downloaded file in your files."),
    ]
    outputs = [Output(display_name="Result", name="result", method="read_web")]

    def read_web(self) -> Data:
        def work():
            out, raw = web.fetch(self.url, self.mode)
            if self.save or self.mode == "raw":
                from urllib.parse import urlparse

                p = urlparse(out["url"])
                ext = (p.path.rsplit(".", 1)[-1] if "." in p.path.rsplit("/", 1)[-1] else "html")[:8]
                path = files.new_path(self.user_id, p.hostname, ext)
                path.write_bytes(raw)
                out["saved_as"] = path.name
            return out

        return to_data(self, envelope.run(work, source={"tool": WEB_READ.name, "url": self.url}))
