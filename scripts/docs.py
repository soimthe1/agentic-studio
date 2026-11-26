"""Synchronize the generated sections of docs/REFERENCE.md with the repository (dev.ps1 docs). Idempotent.

Rewrites only the text between <!-- docs:begin X --> and <!-- docs:end X -->; everything else is human-written.
Reads dev.ps1, config/*.yaml, the env templates, the Compose files and the Dockerfiles. Writes names, never values
of secrets. Fails (exit 1) naming the item when the repository and these rules disagree.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "docs" / "REFERENCE.md"
PROJECT = "agent-studio"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def yml(rel: str) -> dict:
    return yaml.safe_load(read(rel)) or {}


def fail(msg: str):
    raise SystemExit(f"docs: {msg}")


def dev_commands() -> list[tuple[str, str]]:
    """The command list in dev.ps1's header comment (`#   name   text`, continuation lines indented)."""
    rows: list[list[str]] = []
    for line in read("scripts/dev.ps1").splitlines():
        if not line.startswith("#"):
            break
        m = re.match(r"^#   ([a-z][a-z-]*)\s{2,}(.+)$", line)
        if m:
            rows.append([m.group(1), m.group(2).strip()])
        elif rows and re.match(r"^#\s{6,}\S", line):
            rows[-1][1] += " " + line[1:].strip()
    declared = re.search(r'ValidateSet\(([^)]*)\)', read("scripts/dev.ps1")).group(1)
    valid = set(re.findall(r'"([a-z-]+)"', declared)) - {"help"}
    if {c for c, _ in rows} != valid:
        fail(f"dev.ps1 header lists {sorted(c for c, _ in rows)} but ValidateSet has {sorted(valid)}")
    return [(c, d) for c, d in rows]


def env_names(rel: str) -> list[str]:
    return sorted(set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", read(rel), re.M)))


def health(dockerfile: str) -> tuple[int, str]:
    m = re.search(r"urlopen\('http://127\.0\.0\.1:(\d+)(/[^']*)'\)", read(dockerfile))
    if not m:
        fail(f"no HEALTHCHECK URL in {dockerfile}")
    return int(m.group(1)), m.group(2)


def dev_ports() -> dict[str, int]:
    m = re.search(r"\$Ports = \[ordered\]@\{ api = (\d+); ui = (\d+) \}", read("scripts/dev.ps1"))
    e = re.search(r"\$EnginePort = (\d+)", read("scripts/dev.ps1"))
    if not (m and e):
        fail("dev.ps1 port variables ($Ports, $EnginePort) not found")
    return {"api": int(m.group(1)), "ui": int(m.group(2)), "engine": int(e.group(1))}


def published(ports: list[str]) -> str:
    return ", ".join(p.rsplit(":", 1)[0].split(":")[-1] for p in ports)


# ---------------------------------------------------------------- sections
def commands() -> str:
    rows = [f"| `{c}` | {d} |" for c, d in dev_commands()]
    return "`.\\scripts\\dev.ps1 <command>` (no argument prints help).\n\n| Command | Does |\n|---|---|\n" + "\n".join(rows)


def configuration() -> str:
    cfg, prod = yml("config/config.yaml"), yml("config/config.prod.yaml")
    out = ["Non-secret settings: `config/config.yaml`; production values: `config/config.prod.yaml` (same keys, merged over",
           "`config.yaml` when `APP_ENV=prod`). Keys still marked `__SET_ME__` in `config.prod.yaml` must be filled at deployment.",
           "", "| Section | Keys | `__SET_ME__` in config.prod.yaml |", "|---|---|---|"]
    for key, val in cfg.items():
        keys = ", ".join(f"`{k}`" for k in val) if isinstance(val, dict) else f"`{val}`"
        todo = sorted(set(re.findall(r"([\w.]+)=__SET_ME__", _flat(prod.get(key), key))))
        out.append(f"| `{key}` | {keys} | {', '.join(f'`{t}`' for t in todo) or '-'} |")
    tools = yml("config/tools.yaml")
    caps = yml("config/capabilities.yaml")
    out += ["", "Other files in `config/` (read fresh, no restart needed):", "",
            f"- `tools.yaml` - the tools' allowlist (sections: {', '.join(f'`{k}`' for k in tools if k != 'version')}). "
            f"Internet access for agents: `web.enabled` (currently `{str(tools.get('web', {}).get('enabled')).lower()}`). "
            "Schema and examples: `tools/studio_tools/tools.example.yaml`.",
            f"- `capabilities.yaml` - {len(caps.get('capabilities', []))} capabilities and {len(caps.get('apps', []))} existing apps the Agent Designer knows.",
            "- `policy/catalog.yaml` - approved engine components, templates and model providers (applied by `dev.ps1 seed`).",
            "- `config.local-deploy.yaml` - local endpoints for `dev.ps1 deploy` only (never bundled).",
            "", "Secrets (`.env` in development, `.env.prod` in production; same names, templates `.env.example` / `.env.prod.example`): "
            + ", ".join(f"`{n}`" for n in env_names(".env.example")) + "."]
    if env_names(".env.example") != env_names(".env.prod.example"):
        fail(".env.example and .env.prod.example name different variables")
    return "\n".join(out)


def _flat(node, prefix: str) -> str:
    if isinstance(node, dict):
        return " ".join(_flat(v, f"{prefix}.{k}") for k, v in node.items())
    if isinstance(node, list):
        return " ".join(_flat(v, prefix) for v in node)
    return f"{prefix}={'__SET_ME__' if '__SET_ME__' in str(node) else ''}"


def services() -> str:
    prod, dev = yml("docker-compose.prod.yaml"), yml("docker-compose.yaml")
    cfg = yml("config/config.yaml")
    dockerfile = {"agent-studio": "docker/app/Dockerfile", "engine": "docker/langflow/Dockerfile"}
    out = ["Application containers (`docker-compose.prod.yaml`, both built and bundled by `build`):", "",
           "| Service | Image | Host port | Health | Built from |", "|---|---|---|---|---|"]
    for name, svc in prod["services"].items():
        if name not in dockerfile:
            fail(f"docker-compose.prod.yaml service {name!r} has no known Dockerfile")
        port, path = health(dockerfile[name])
        out.append(f"| `{name}` | `{svc['image'].split(':')[0]}:<timestamp>` | {published(svc.get('ports', []))} "
                   f"| `GET http://<host>:{port}{path}` | `{dockerfile[name]}` |")
    out += ["", "Development (`docker-compose.yaml`) runs only " + ", ".join(f"`{s}`" for s in dev["services"])
            + " as a container; the app runs natively (`dev.ps1 start`).", "",
            "External services (not bundled, never started by this project):", "",
            "| Dependency | Setting | Used for |", "|---|---|---|",
            f"| PostgreSQL | `database:` / `app.database:` (db `{cfg['database']['name']}`, role `{cfg['database']['user']}`, "
            f"app schema `{cfg['app']['database']['schema']}`) | engine data (agents, runs, users) and the app's drafts |",
            f"| Active Directory / LDAP (optional) | `ldap.enabled`, `ldap.server_uri` | directory sign-in; off = local accounts |"]
    for name, p in cfg["ai"].items():
        state = " (disabled)" if p.get("enabled") is False else ""
        out.append(f"| {p['provider']} model server{state} | `ai.{name}` (`{p.get('model', '-')}`) | "
                   + ("models for agents (engine) and the Agent Designer (`app.designer_profile`) |" if p["provider"] != "comfyui" else "media generation |"))
    out.append("| Monitored / organizational apps | `config/tools.yaml` `apps:`, `notify:`, `sql:` | what agents read and act on |")
    return "\n".join(out)


def local_run() -> str:
    p = dev_ports()
    return f"""Windows PC with Python 3.12 (`uv`), Node.js, Docker Desktop, and the existing PostgreSQL reachable as set in `config/config.yaml`.

```powershell
.\\scripts\\dev.ps1 setup      # .venv, frontend packages, .env from .env.example (then fill in .env)
docker compose build engine  # first time only: the engine image (~20 min); dev.ps1 build refreshes it
.\\scripts\\dev.ps1 start      # engine container, then API + web app; opens the browser
.\\scripts\\dev.ps1 seed       # apply config/policy/catalog.yaml to the engine
.\\scripts\\dev.ps1 test       # needs the running stack
```

| Part | URL |
|---|---|
| Web app (Vite) | http://127.0.0.1:{p['ui']} |
| Agent Studio API | http://127.0.0.1:{p['api']}/api/studio/v1 (OpenAPI: `/api/studio/v1/openapi.json`), health `/health` |
| Engine | http://127.0.0.1:{p['engine']}/health (console only for `engine.console_admins`) |"""


def build() -> str:
    images = ", ".join(f"`{s['image'].split(':')[0]}:<yyyyMMdd-HHmm>`" for s in yml("docker-compose.prod.yaml")["services"].values())
    return f"""`.\\scripts\\dev.ps1 build` checks the required files, the config (mirrored keys, no secrets in YAML), the env template
names and the production Compose file, builds the web app, runs `test` (needs the running dev stack), runs `docs`, builds {images}
and writes the bundle `dist\\{PROJECT}-<yyyyMMdd-HHmm>\\`: the image TAR and its `.sha256`, `docker-compose.prod.yaml` (release tag
filled in), `config/` (`config.yaml`, `config.prod.yaml`, `capabilities.yaml`, `policy/`, `tools.example.yaml`), `.env.prod.example`,
`FIRST_DEPLOYMENT.md`, `README.md`, `REFERENCE.md`, and `deployment-manifest.json` last (its presence marks a successful build)."""


def local_deploy() -> str:
    over = yaml.safe_load(read("docker-compose.local-deploy.yaml").replace("!override", ""))["services"]  # Compose-only tag
    ports = {n: published(s["ports"]) for n, s in over.items()}
    return f"""`.\\scripts\\dev.ps1 deploy [-Bundle dist\\{PROJECT}-<yyyyMMdd-HHmm>]` takes the newest bundle with a manifest, verifies the
checksum, loads the images, checks the tags against the manifest and runs the bundle's `docker-compose.prod.yaml` plus
`docker-compose.local-deploy.yaml` as Compose project `{PROJECT}-localdeploy` with `--env-file .env.local-deploy`. It then
waits for health, applies the catalog policy and prints the state. The dev stack keeps running.

- Ports: app http://127.0.0.1:{ports['agent-studio']}, engine http://127.0.0.1:{ports['engine']}/health.
- Secrets: `.env.local-deploy` (created from `.env.prod.example` on the first run; fill in local test values).
- Settings: the repo's `config/` with `config/config.local-deploy.yaml` in place of `config.prod.yaml`.
- Data: `data\\localdeploy\\` (kept across bundles); database `studio_localdeploy` on the dev PostgreSQL (create once:
  `CREATE DATABASE studio_localdeploy OWNER agent_studio;`).
- Stop: `docker compose -p {PROJECT}-localdeploy down` (keeps data). Logs: `docker compose -p {PROJECT}-localdeploy logs -f`."""


def airgapped() -> str:
    return f"""Copy the whole `dist\\{PROJECT}-<yyyyMMdd-HHmm>\\` folder to the target and follow `FIRST_DEPLOYMENT.md`. The TAR holds
every application image; nothing is pulled from a registry. Not in the bundle: PostgreSQL, Active Directory, the model
servers (Ollama / vLLM and their models) and the monitored apps - they are existing services the target must reach.
Agents get no internet access unless `config/tools.yaml` sets `web.enabled: true` (keep `false` on air-gapped sites)."""


SECTIONS = {"commands": commands, "configuration": configuration, "services": services, "local-run": local_run,
            "build": build, "local-deploy": local_deploy, "air-gapped-deployment": airgapped}


def main() -> int:
    text = README.read_text(encoding="utf-8")
    for name, fn in SECTIONS.items():
        begin, end = f"<!-- docs:begin {name} -->", f"<!-- docs:end {name} -->"
        if text.count(begin) != 1 or text.count(end) != 1:
            fail(f"docs/REFERENCE.md needs exactly one {begin} ... {end} pair")
        pre, rest = text.split(begin, 1)
        _, post = rest.split(end, 1)
        text = f"{pre}{begin}\n{fn().strip()}\n{end}{post}"
    if text != README.read_text(encoding="utf-8"):
        README.write_text(text, encoding="utf-8", newline="\n")
        print("docs/REFERENCE.md updated")
    else:
        print("docs/REFERENCE.md already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
