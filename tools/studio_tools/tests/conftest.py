"""studio-tools unit tests: no live systems (sqlite, httpx.MockTransport, fake SMTP)."""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio_tools.core import config as C  # noqa: E402
from studio_tools.core import http as H  # noqa: E402


@pytest.fixture
def write_cfg(tmp_path, monkeypatch):
    """Write a tools.yaml and point STUDIO_TOOLS_CONFIG at it; returns the loaded dict."""
    def _write(data: dict) -> dict:
        p = tmp_path / "tools.yaml"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        monkeypatch.setenv("STUDIO_TOOLS_CONFIG", str(p))
        C._cache.clear()
        return C.load_config()
    yield _write
    C._cache.clear()


@pytest.fixture
def mock_http(monkeypatch):
    """Install an httpx.MockTransport; returns (set_handler, calls)."""
    import httpx

    calls: list = []
    state = {"handler": lambda req: httpx.Response(200, json={})}

    def handler(request):
        calls.append(request)
        return state["handler"](request)

    monkeypatch.setattr(H, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setattr(H.time, "sleep", lambda s: None)

    def set_handler(fn):
        state["handler"] = fn

    return set_handler, calls
