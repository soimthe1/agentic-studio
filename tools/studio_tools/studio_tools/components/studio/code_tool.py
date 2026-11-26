"""code_tool: run an operation of a tool written by AI and approved by an administrator (Agent Studio Systems page).

The approved code lives at <contracts_dir>/code/<tool_id>.py and its manifest in the contract (tools: code: <tool_id>).
Methods marked as changes (declared, or found risky: shell commands, file writes, deleting, sending data) run only
when the flow's human approval step set approved=true and dry_run=false; otherwise the call is reported as planned.
"""

import sys
from pathlib import Path

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, NestedDictInput, Output, StrInput
from lfx.schema.data import Data

from studio_tools.components.common import acting_user, flags, flow_policy_inputs, to_data
from studio_tools.core import codetool, envelope, files, vault
from studio_tools.core.catalog import CODE_TOOL as SPEC
from studio_tools.core.config import get_connection, load_config
from studio_tools.core.errors import ConfigError, NotAllowed, UpstreamError
from studio_tools.core.util import parse_json


class CodeToolComponent(Component):
    display_name = "Agent Studio Tool (written by AI)"
    description = SPEC.description
    tool_spec = SPEC
    icon = "code"
    name = "StudioCodeTool"

    inputs = [
        StrInput(name="tool_id", display_name="Tool", advanced=True, value="",
                 info="The approved tool (set by Agent Studio, never by the model)."),
        MessageTextInput(name="operation", display_name="Operation", tool_mode=True, required=True,
                         info="Name of the tool's operation to run."),
        NestedDictInput(name="arguments", display_name="Arguments", tool_mode=True, value={},
                        info="JSON object with the operation's arguments."),
        MessageTextInput(name="reason", display_name="Reason", tool_mode=True, value="",
                         info="Why this operation is needed (shown to the approver for changes)."),
        StrInput(name="allowed_operations", display_name="Operations allowed here", advanced=True, value="",
                 info="Comma-separated operations this step may run (set by Agent Studio)."),
        *flow_policy_inputs(scope_name="allowed_tools", scope_info="Tools this agent may run.", writes=True),
    ]
    outputs = [Output(display_name="Result", name="result", method="code_tool")]

    def code_tool(self) -> Data:
        tool_id, op = (self.tool_id or "").strip(), (self.operation or "").strip()
        approved, dry_run = flags(self)

        def work():
            manifest = get_connection("code", tool_id)
            allowed = {x.strip() for x in (self.allowed_operations or "").split(",") if x.strip()}
            if allowed and op not in allowed:
                raise NotAllowed(f"operation '{op}' is not enabled for this agent (enabled: {', '.join(sorted(allowed))})")
            folder = load_config().get("contracts_dir")
            path = Path(folder or "") / "code" / f"{tool_id}.py"
            if not path.is_file():
                raise ConfigError(f"the approved code of tool '{tool_id}' is missing ({path})")
            code = path.read_text(encoding="utf-8")
            args = parse_json(self.arguments, "arguments", default={})
            if op in set(manifest.get("changes") or []) and (not approved or dry_run):
                return {"status": "planned" if dry_run else "pending_approval", "operation": op, "arguments": args,
                        "reason": self.reason or "", "note": "This operation changes something; it runs after a person approves it."}
            secrets = {n: vault.read(folder, env) for n, env in (manifest.get("secret_envs") or {}).items()}
            missing = [n for n, v in secrets.items() if not v]
            if missing:
                raise ConfigError(f"no saved value for {', '.join(missing)}: enter it for tool '{tool_id}' on the Systems page")
            try:
                own = str(files.user_dir(self.user_id))     # the agent owner's files folder
            except Exception:  # noqa: BLE001 - a run without an owner simply has no files folder
                own = ""
            out = codetool.run(code, op, args, secrets, timeout=float(manifest.get("timeout_s") or 60), python=sys.executable,
                               user=acting_user(self) or "", files_dir=own)
            if not out.get("ok"):
                raise UpstreamError(out.get("error") or "the tool failed")   # its message reaches the agent
            return {"status": "done", "operation": op, "result": out.get("result"), "truncated": bool(out.get("truncated"))}

        return to_data(self, envelope.run(work, source={"tool": "code_tool", "tool_id": tool_id, "operation": op,
                                                        "acting_user": acting_user(self)}))
