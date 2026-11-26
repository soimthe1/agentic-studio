"""A system can describe itself in an AGENT-STUDIO.md: prose for people, the contract as YAML front-matter or a ```yaml
block. Agent Studio reads only the yaml; everything else in the file is ignored (no model involved)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from agent_studio.tools import _from_contract_yaml, _md_contract  # noqa: E402

OPS = "operations:\n  - id: fleet\n    path: /fleet/{host}\n    summary: Fleet status\n  - {id: restart, method: POST, path: /restart}\n"


def test_front_matter():
    doc = _md_contract("---\nname: Ops Portal\n" + OPS + "---\n# Ops Portal\nPeople read this part.\n")
    ops = _from_contract_yaml(doc)
    assert [o["kind"] for o in ops] == ["read", "change"] and ops[0]["path_params"] == ["host"]


def test_fenced_block_first_with_operations_wins():
    text = "# Sys\nSome prose.\n```yaml\nnot: a contract\n```\nMore.\r\n```yaml\r\n" + OPS.replace("\n", "\r\n") + "```\n"
    assert [o["id"] for o in _from_contract_yaml(_md_contract(text))] == ["fleet", "restart"]


def test_no_contract():
    assert _md_contract("# Just docs\n```yaml\n: bad: [\n```\n") is None
    assert _md_contract("plain text") is None
