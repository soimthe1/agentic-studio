"""Engine container entrypoint: export LANGFLOW_* from config.yaml (+ DB URL from database:), then exec `langflow run`."""

import os
import sys
from urllib.parse import quote

from studio_engine import config


def model_endpoints(ai: dict) -> dict[str, str]:
    """Map the Project Standard AI profiles to the engine's provider variables (env fallback,
    lfx/base/models/unified_models/credentials.py). One endpoint per provider."""
    out: dict[str, str] = {}
    targets = {"ollama": ("OLLAMA_BASE_URL", None), "openai": ("VLLM_API_BASE", "VLLM_API_KEY")}
    default = ai.get("default", {})
    # default and reasoning first: they are what agents use; a backup profile on another address is skipped.
    for name, prof in sorted(ai.items(), key=lambda kv: (kv[0] not in ("default", "reasoning"), kv[0] != "default")):
        provider = prof.get("provider", default.get("provider"))
        if provider not in targets or prof.get("enabled") is False:
            continue
        base_key, key_key = targets[provider]
        url = prof.get("base_url", default.get("base_url") if provider == default.get("provider") else None)
        if not url:
            continue
        if out.get(base_key, url) != url:
            if name in ("default", "reasoning"):
                raise SystemExit(f"ai.{name}: the engine supports one {provider} endpoint; {out[base_key]} vs {url}")
            print(f"ai.{name}: skipped for the engine ({provider} already uses {out[base_key]})", file=sys.stderr)
            continue
        out[base_key] = url
        if provider == "ollama":
            # The Ollama client's own default. Engine paths that lose the user's variables (e.g. resuming a
            # suspended human-approval run in Langflow 1.13.2) would otherwise fall back to localhost:11434.
            out["OLLAMA_HOST"] = url
        if key_key and prof.get("api_key_env"):
            key = os.environ.get(prof["api_key_env"]) or _saved_key(prof["api_key_env"])
            if key:
                out[key_key] = key
    return out


def _contracts_dir() -> str | None:
    try:
        from studio_tools.core.config import load_config

        return load_config().get("contracts_dir")
    except Exception:  # noqa: BLE001 - no tools config: no saved settings
        return None


def _saved_key(name: str) -> str | None:
    """API key saved on the studio's Settings page (encrypted next to the contracts)."""
    from studio_tools.core import vault

    return vault.read(_contracts_dir(), name)


def ai_profiles(cfg: dict) -> dict:
    """config ai:, with the model servers saved on the studio's Settings page on top (same rule as the app)."""
    import json
    from pathlib import Path

    ai = dict(cfg.get("ai", {}))
    folder = _contracts_dir()
    f = Path(folder) / ".setup" / "ai.json" if folder else None
    if f and f.is_file():
        try:
            ai.update(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            pass
    return ai


def main() -> None:
    cfg = config.load()
    env = config.langflow_env(cfg)
    clash = sorted(k for k in env if k in os.environ)
    if clash:  # one place per key: YAML owns these
        raise SystemExit(f"set in both config.yaml and the environment: {clash}")
    os.environ.update(env)
    db = cfg["database"]
    password = quote(os.environ[db["password_env"]], safe="")
    os.environ["LANGFLOW_DATABASE_URL"] = (
        f"postgresql://{db['user']}:{password}@{db['host']}:{db['port']}/{db['name']}")
    os.environ.update(model_endpoints(ai_profiles(cfg)))
    os.environ.setdefault("DO_NOT_TRACK", "true")
    sys.argv = ["langflow", "run", "--host", env["LANGFLOW_HOST"], "--port", env["LANGFLOW_PORT"], *sys.argv[1:]]
    import langflow.__main__ as cli

    cli.fetch_latest_version = lambda *a, **k: None  # air-gap: the startup banner's PyPI update check has no switch
    cli.main()


if __name__ == "__main__":
    main()
