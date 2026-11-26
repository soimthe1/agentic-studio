"""Apply the version-controlled Agent Studio policy to a running Langflow (rule 6). Idempotent.

    python -m agent_studio.seed [--check]        (dev.ps1 seed)

Reads config/policy/catalog.yaml and writes it through Langflow's own admin API as one atomic
policy-bundle revision (PUT /api/v1/policy-bundle, compare-and-swap on the revision):

  * components: an ALLOWLIST in the file. Langflow 1.13.2 catalog policy is block-only
    (models/catalog_policy/model.py: ALLOW is reserved), so every installed component that is
    not allowed is written as blocked. New components appearing after an upgrade are therefore
    blocked on the next seed, not silently allowed.
  * templates: every starter template is blocked unless listed.
  * model providers: only the listed provider ids are approved.

--check prints the difference and exits 1 if the live policy differs (for tests / deploy checks).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
import yaml

from agent_studio import settings



def login(client: httpx.Client) -> None:
    r = client.post("/api/v1/login", data={"username": os.environ["LANGFLOW_SUPERUSER"],
                                            "password": os.environ["LANGFLOW_SUPERUSER_PASSWORD"]})
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def installed_components(client: httpx.Client) -> dict[str, str]:
    """{component key: category} for everything the server can build."""
    r = client.get("/api/v1/all")
    r.raise_for_status()
    return {name: category for category, comps in r.json().items() for name in comps}


def installed_templates(client: httpx.Client) -> set[str]:
    r = client.get("/api/v1/starter-projects/")
    if r.status_code == 404:
        return set()
    r.raise_for_status()
    data = r.json()
    items = data if isinstance(data, list) else data.get("items", [])
    return {str(t.get("key") or t.get("name")) for t in items if isinstance(t, dict)}


def desired(policy: dict, components: dict[str, str], templates: set[str]) -> dict:
    allow = {key for group in policy["groups"] for key in group["components"]}
    allow_categories: set[str] = set()
    known = {k.lower() for k in components}
    missing = {a for a in allow if a.lower() not in known}  # an allowed key may be visible only by its alias
    if missing:
        raise SystemExit(f"catalog.yaml allows components this server does not have: {sorted(missing)}")
    lower = {a.lower() for a in allow}
    # Langflow 1.13.2 also checks an extension component under its short class name ("ext:studio:NotifyComponent@x"
    # -> "Notify"): blocking a core component with that name hides the approved tool, so that name stays open.
    lower |= {k.split(":")[-1].split("@")[0].removesuffix("Component").lower() for k in allow if k.startswith("ext:")}
    # The engine lists some components twice (canonical key + lowercase alias); blocking an alias blocks the
    # component itself, so aliases of allowed keys are allowed too.
    allowed = {k for k, cat in components.items() if k in allow or k.lower() in lower or cat in allow_categories}
    return {
        "approved_provider_ids": sorted(policy["model_providers"]["approve"]),
        "blocked_component_keys": sorted(set(components) - allowed),
        "blocked_template_keys": sorted(templates - set(policy.get("templates", {}).get("allow", []))),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report drift, change nothing")
    ap.add_argument("--policy", default=str(Path(os.environ.get("CONFIG_DIR") or settings.REPO / "config") / "policy" / "catalog.yaml"))
    args = ap.parse_args()
    policy = yaml.safe_load(Path(args.policy).read_text(encoding="utf-8"))

    with httpx.Client(base_url=settings.load()["engine"]["url"], timeout=60, trust_env=False) as client:
        login(client)
        live = client.get("/api/v1/policy-bundle").raise_for_status().json()
        # The engine's component list hides blocked components: count those as installed, or a re-seed would
        # forget (unblock) them.
        components = {**{k: "" for k in live.get("blocked_component_keys") or []}, **installed_components(client)}
        templates = installed_templates(client) | set(live.get("blocked_template_keys") or [])
        want = desired(policy, components, templates)
        drift = {k: v for k, v in want.items() if sorted(live.get(k, [])) != v}
        if not drift:
            print(f"policy up to date (revision {live['revision']}, "
                  f"{len(want['blocked_component_keys'])} components blocked)")
            return 0
        for k, v in drift.items():
            print(f"{k}: live {len(live.get(k, []))} -> wanted {len(v)}")
        if args.check:
            return 1
        body = {**{k: live.get(k, []) for k in ("blocked_model_keys", "approved_integration_provider_ids",
                                                 "blocked_integration_action_keys")},
                **want, "expected_revision": live["revision"], "reason": "agent_studio.seed from config/policy"}
        r = client.put("/api/v1/policy-bundle", json=body)
        if r.status_code >= 400:
            print(r.text, file=sys.stderr)
            r.raise_for_status()
        print(f"policy applied: revision {r.json()['revision']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
