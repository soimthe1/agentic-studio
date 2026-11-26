"""Critical compatibility test: with custom components and code interpreters disabled, our own
extension bundle (studio-tools) must still load AND run. If this fails, "extensions, not modifications" breaks."""

from conftest import edge, node

KEY = "ext:studio:BundleCheckComponent@official"


def test_hardening_is_on(admin):
    cfg = admin.get("/api/v1/config").json()
    # The server must report custom components as not allowed (beta flag, see security.py:119).
    flags = {k: v for k, v in cfg.items() if "custom" in k.lower()}
    assert flags, f"config exposes no custom-component flag: {sorted(cfg)}"
    assert not any(v is True for k, v in flags.items() if "allow" in k.lower()), flags


def test_bundle_component_registered(catalog):
    assert KEY in catalog


def test_bundle_component_runs(admin, admin_key, catalog):
    nodes = [node(catalog, "ChatInput", "ChatInput-a1"), node(catalog, KEY, "StudioBundleCheck-b2"),
             node(catalog, "ChatOutput", "ChatOutput-c3")]
    edges = [edge("ChatInput-a1", "message", ["Message"], "StudioBundleCheck-b2", "input_value", ["Message"]),
             edge("StudioBundleCheck-b2", "result", ["Message"], "ChatOutput-c3", "input_value", ["Data", "DataFrame", "Message"])]
    flow = admin.post("/api/v1/flows/", json={"name": "test-bundle-check", "data": {"nodes": nodes, "edges": edges}})
    assert flow.status_code in (200, 201), flow.text
    fid = flow.json()["id"]
    try:
        r = admin.post(f"/api/v1/run/{fid}", json={"input_value": "hello", "input_type": "chat", "output_type": "chat"},
                       headers={"x-api-key": admin_key})
        assert r.status_code == 200, r.text
        assert "studio_tools 0.3.0 ok: hello" in r.text
    finally:
        admin.delete(f"/api/v1/flows/{fid}")
