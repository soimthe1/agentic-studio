"""Readiness watchkeeper: just before Build and Test, is everything this agent will need reachable and set up?

Uses the engine's own view (where agents run): its model servers and every configured connection (reachable?
secrets set?). Blocks on what would certainly fail (a connection without its secret, internet use where it is
switched off); warns on what may only be temporary (a server not answering right now).
"""

from __future__ import annotations

from agent_studio import capabilities


def check(prefs: dict, engine_status: dict) -> list[dict]:
    findings: list[dict] = []
    conns = {c["name"]: c for c in engine_status.get("connections") or []}
    caps = capabilities.by_id()
    model_rows = [c for c in conns.values() if c.get("kind") == "model"]
    from agent_studio.director import model_for

    want = "Ollama" if model_for(prefs.get("brain") or "fast")["provider"] == "Ollama" else "vLLM"
    model = next((c for c in model_rows if c["name"] == want), None)
    if model and model.get("ok") is False:
        findings.append({"level": "warn", "text": f"The AI model server ({want}) is not answering right now ({model.get('detail')}). "
                                                  "The agent can be built; its test run will fail until the server is back."})
    elif model:
        findings.append({"level": "ok", "text": f"AI model server ({want}) answers ({model.get('ms')} ms)."})
    for cid in prefs.get("capabilities") or []:
        cap = caps.get(cid)
        if not cap:
            continue
        if cid == "web_read" and not engine_status.get("web_enabled"):
            findings.append({"level": "block", "text": "Reading websites is switched off in this deployment (no internet access)."})
            continue
        app = ((cap.get("tool") or {}).get("params") or {}).get("app")
        name = app or (prefs.get("channel") if cid == "notify" else None)
        conn = conns.get(name) if name else None
        if not conn:
            continue
        from agent_studio import vault

        missing = [e for e in conn.get("missing_secrets") or [] if not vault.has(e)]   # Tools-page sign-ins count
        if missing:
            findings.append({"level": "block", "text": f"'{cap['label']}' cannot sign in: an administrator has to set "
                                                       f"{', '.join(missing)} on the engine (or enter its sign-in on the Tools page)."})
        elif conn.get("ok") is False:
            findings.append({"level": "warn", "text": f"'{cap['label']}' is not reachable right now ({conn.get('detail')})."})
        else:
            findings.append({"level": "ok", "text": f"'{cap['label']}' reachable" + (" (test system)" if conn.get("test_system") else "") + "."})
    return findings
