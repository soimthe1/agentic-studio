"""Answer guardrail (no stack needed): secrets and personal identifiers are masked before people see or receive them."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_studio.guard import redact  # noqa: E402


def test_secrets_and_ids_are_masked_and_normal_text_kept():
    assert redact("the password is Hunter2!") == "the password is [hidden password]"
    assert redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123") == "Authorization: Bearer [hidden token]"
    assert redact("card 4111-1111-1111-1111") == "card [hidden card number]"
    assert redact("4 failed jobs on SQL01, CPU 93%") == "4 failed jobs on SQL01, CPU 93%"


def test_engine_copy_is_identical():
    a = (ROOT / "backend" / "agent_studio" / "guard.py").read_text(encoding="utf-8")
    b = (ROOT / "tools" / "studio_tools" / "studio_tools" / "core" / "redact.py").read_text(encoding="utf-8")
    assert a == b, "tools/studio_tools/studio_tools/core/redact.py must be an exact copy of backend/agent_studio/guard.py"
