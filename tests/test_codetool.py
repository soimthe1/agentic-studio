"""Tools written by AI (no stack needed): nothing is blocked, risks are named in plain words, changes and risky
operations ask a person on every call, tools run in their own process with a time limit."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_studio import codetool, codetools  # noqa: E402

POWERSHELL_TOOL = '''
import subprocess
class Tool:
    HOSTS = ["srv01:5985"]
    SECRETS = ["ADMIN_PW"]
    CHANGES = ["restart_service"]
    def services(self, host: str) -> str:
        """List services on a Windows server."""
        return "ok"
    def run_ps(self, script: str) -> str:
        """Run a PowerShell script."""
        return subprocess.run(["powershell", "-Command", script], capture_output=True, text=True).stdout
    def restart_service(self, name: str) -> str:
        """Restart one service."""
        return name
'''


def test_nothing_is_blocked_but_every_risk_is_named():
    info = codetool.inspect_code(POWERSHELL_TOOL)
    assert info["ok"], "PowerShell / subprocess tools are allowed (the approver decides)"
    assert info["level"] == "high" and any(r["text"] == "runs PowerShell commands" for r in info["risks"])
    by = {m["name"]: m for m in info["methods"]}
    assert not by["services"]["change"]
    assert by["run_ps"]["change"], "a risky operation asks a person on every call"
    assert by["restart_service"]["change"], "a declared change asks a person on every call"


def test_contract_puts_changes_behind_approval():
    spec = {"name": "Win", "purpose": "Windows servers", "inspect": codetool.inspect_code(POWERSHELL_TOOL)}
    c = codetools.contract(spec, "win")
    caps = {x["id"]: x for x in c["capabilities"]}
    assert caps["win_read"]["side_effect"] == "read" and caps["win_change"]["side_effect"] == "write"
    assert set(c["tools"]["code"]["win"]["changes"]) == {"run_ps", "restart_service"}
    assert c["tools"]["code"]["win"]["secret_envs"] == {"ADMIN_PW": "STUDIO_CODE_WIN_ADMIN_PW"}


def test_runs_isolated_with_time_limit():
    code = "import time\nclass Tool:\n    def n(self, x: int = 2):\n        '''Echo.'''\n        return x * 2\n    def hang(self):\n        '''Hang.'''\n        time.sleep(9)\n"
    assert codetool.run(code, "n", {"x": 4}) == {"ok": True, "result": 8}
    assert "stopped" in codetool.run(code, "hang", timeout=1)["error"]


def test_engine_copy_is_identical():
    a = (ROOT / "backend" / "agent_studio" / "codetool.py").read_text(encoding="utf-8")
    b = (ROOT / "tools" / "studio_tools" / "studio_tools" / "core" / "codetool.py").read_text(encoding="utf-8")
    assert a == b, "tools/studio_tools/studio_tools/core/codetool.py must be an exact copy of backend/agent_studio/codetool.py"
