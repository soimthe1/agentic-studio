"""Sign-ins typed on the Tools page: kept encrypted where the engine's tools read them, never in plain text, and a
refused or missing sign-in becomes one plain sentence (no model or external system needed)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "studio_tools"))


def test_saved_sign_in_is_encrypted_and_readable_by_the_tools(tmp_path, monkeypatch):
    from agent_studio import capabilities, vault
    from studio_tools.core import vault as tool_vault

    monkeypatch.setenv("STUDIO_ENGINE_SECRET", "test-secret")
    monkeypatch.setattr(capabilities, "contracts_dir", lambda: tmp_path)
    name = vault.env_name("ops-portal")
    assert name == "STUDIO_TOOL_OPS_PORTAL_SECRET"
    vault.put(name, "p@ss word")
    assert b"p@ss" not in (tmp_path / ".vault" / name).read_bytes()
    assert vault.get(name) == "p@ss word" and tool_vault.read(tmp_path, name) == "p@ss word"
    monkeypatch.setenv("STUDIO_ENGINE_SECRET", "rotated")
    assert tool_vault.read(tmp_path, name) is None          # wrong key: treated as "no saved sign-in"
    vault.drop(name)
    assert not vault.has(name)


def test_sign_in_to_a_system_that_is_not_there_says_so():
    from agent_studio.tools import sign_in

    client, note = sign_in("http://127.0.0.1:9", "/api/v1/auth/login", "someone", "x")
    assert client is None and "did not answer" in note
