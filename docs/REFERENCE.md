# Agentic Studio reference

The operator manual: how it is built, configured, run, tested and deployed. What it does and why:
[README](../README.md). Why each design decision was made: [UNDER_THE_HOOD.md](../UNDER_THE_HOOD.md). First setup on
a new server: [FIRST_DEPLOYMENT.md](../FIRST_DEPLOYMENT.md).

Sections marked *generated* are rewritten from the repository by `.\scripts\dev.ps1 docs` (`scripts/docs.py`).

## Architecture

- **Thin app over an unmodified engine.** The engine runs flows, tool calls, memory, schedules, approvals and MCP; the
  studio adds what people see and what keeps agents safe. `backend/agent_studio/engine.py` is the only module that
  knows the engine's API (`tests/test_api_contract.py` checks it). Every engine call carries the signed-in person's
  own session: no shared service account.
- **Extension, not fork.** `engine/studio_engine` (plugin: sessions, compile, status, code tests) and
  `tools/studio_tools` (the approved tools) are installed into the stock engine image; the engine's canvas is only
  re-branded at build (`branding/apply-branding.mjs`, [`patches.md`](patches.md)).

## Make it yours

One codebase serves the public release and each organisation's own deployment. Nothing organisation-specific is in
the code.

| What | Where | Committed? |
|---|---|---|
| Product name, Arabic name, tagline, logo, favicon, theme | `branding/brand.example/brand.json` (public) · `branding/brand.local/brand.json` (yours, wins) | example only |
| Hosts, directory, groups, model servers, database, contract file names | `config/config.yaml` (placeholders) · `config/local/config.yaml` (yours, merged over it, app **and** engine) | placeholders only |
| Your organisation's applications | `config/local/apps.yaml` | no |
| Your documents | `docs/local/` | no |
| Words that must never be published | `config/local/release-words.txt` | no |

Before publishing anything: `python scripts/release_check.py` must print **Ready**. Its generic patterns live in the
script; your own forbidden words stay in your local file, so the check itself carries no organisation detail.
`.\scripts\dev.ps1 publish -Message "..."` runs the docs, the release check, commits and pushes; the pre-push hook
(`.githooks/pre-push`) refuses any push carrying a private path.

## Sign-in

Local accounts by default (`ldap.enabled: false`): the first visit creates the administrator, who adds people on
**Settings → People**. For directory sign-in (Active Directory / LDAP) set `ldap.enabled: true`, `server_uri`,
`user_search_base` and the groups for each role in `ldap.group_map`.

## Offline libraries

The engine image bundles the common libraries for AI-written tools: PDF (pypdf, pdfplumber, reportlab), Word,
PowerPoint, Excel, Outlook `.msg`, HTML/XML, images and charts, Exchange (EWS), IMAP, calendars, PowerShell over
WinRM, SSH, SMB file shares, NTLM web APIs, DNS, SNMP, Oracle, MySQL, SQL Server, PostgreSQL, pandas. When a tool
needs something else, the studio names the package and the exact steps: `pip download` on any PC with internet, copy
the files into `data/toolkit/wheels`, press **Install** on the Systems page. Nothing is ever downloaded on the server.

## External dependencies (not bundled)

PostgreSQL (one database for the engine and the app's schema; the quick start brings its own), optionally a
directory (LDAP/AD), the model servers (vLLM / Ollama), and the systems agents talk to. In development
`config/tools.yaml` points at a declared test double (`tests/mocks/apps.py`, port 9190) and every result from it says
so.

## Commands

<!-- docs:begin commands -->
`.\scripts\dev.ps1 <command>` (no argument prints help).

| Command | Does |
|---|---|
| `setup` | create .venv (Python 3.12: backend + test tools), install frontend packages, create .env from .env.example |
| `start` | start the engine container (Langflow), then API (uvicorn :8095, auto-reload) + UI (Vite :5195) in this window and open the browser. Ctrl+C stops API + UI (on a fresh copy runs setup first) |
| `stop` | stop the dev servers and the engine container |
| `status` | show the engine container and what is listening on the dev ports |
| `logs` | follow the engine logs; `start` prints the API in its window, the UI goes to logs\ui.log |
| `test` | tests against the running stack (pytest), frontend type check |
| `seed` | apply the version-controlled catalog policy (config\policy\catalog.yaml) to the engine |
| `docs` | synchronize the generated sections of docs\REFERENCE.md with the repository (scripts\docs.py) |
| `build` | validate, test, docs, build the Docker images (app + engine; also refreshes the dev engine image) and the offline deployment bundle in dist\agent-studio-<yyyyMMdd-HHmm>\ |
| `publish` | push the public version to GitHub: docs, release check, commit (-Message), push. Your brand and organisation values (branding/brand.local, config/local, docs/local, .env) never leave this PC; the pre-push hook refuses any push that would carry them. |
| `deploy` | run the newest successful bundle (or -Bundle <folder>) locally in production shape: Compose project agent-studio-localdeploy, .env.local-deploy, ports 18095 / 17860 (docker-compose.local-deploy.yaml) |
<!-- docs:end commands -->

## Configuration

<!-- docs:begin configuration -->
Non-secret settings: `config/config.yaml`; production values: `config/config.prod.yaml` (same keys, merged over
`config.yaml` when `APP_ENV=prod`). Keys still marked `__SET_ME__` in `config.prod.yaml` must be filled at deployment.

| Section | Keys | `__SET_ME__` in config.prod.yaml |
|---|---|---|
| `app` | `contract_files`, `public_url`, `port`, `frontend_dir`, `files_dir`, `contracts_dir`, `discover`, `failure_check_minutes`, `embed_origins`, `database`, `designer_profile` | `app.database.host`, `app.public_url` |
| `engine` | `url`, `public_url`, `app_url`, `secret_env`, `console_admins` | `engine.app_url`, `engine.public_url` |
| `ai` | `default`, `reasoning`, `ollama`, `media` | `ai.default.base_url`, `ai.media.base_url`, `ai.reasoning.base_url` |
| `database` | `host`, `port`, `name`, `user`, `password_env` | `database.host` |
| `langflow` | `deployment_profile`, `host`, `port`, `workers`, `log_level`, `log_file`, `frontend_path`, `do_not_track`, `models_dev_refresh`, `store`, `store_url`, `download_webhook_url`, `like_webhook_url`, `variables_to_get_from_environment`, `agentic_experience`, `create_starter_projects`, `update_starter_projects`, `hide_starter_projects`, `auto_login`, `enable_signup`, `new_user_is_active`, `external_auth_provider`, `refresh_token_expire_seconds`, `allow_custom_components`, `allow_components_paths_override`, `custom_component_admin_only`, `block_code_interpreter_components`, `restrict_local_file_access`, `tweaks_policy`, `mcp_servers_locked`, `mcp_server_docker_hardening`, `mcp_server_interpreter_hardening`, `mcp_server_allowed_packages`, `mcp_server_env_allowlist`, `skip_mcp_auto_init`, `add_projects_to_mcp_servers`, `mcp_composer_enabled`, `mcp_sse_enabled`, `connector_ssrf_allow_loopback`, `disable_track_apikey_usage`, `cors_origins` | `langflow.cors_origins` |
| `ldap` | `enabled`, `server_uri`, `use_tls`, `user_search_base`, `group_map` | - |

Other files in `config/` (read fresh, no restart needed):

- `tools.yaml` - the tools' allowlist (sections: `apps`, `knowledge`, `notify`, `contracts_dir`, `files`, `web`, `documents`). Internet access for agents: `web.enabled` (currently `false`). Schema and examples: `tools/studio_tools/tools.example.yaml`.
- `capabilities.yaml` - 13 capabilities and 2 existing apps the Agent Designer knows.
- `policy/catalog.yaml` - approved engine components, templates and model providers (applied by `dev.ps1 seed`).
- `config.local-deploy.yaml` - local endpoints for `dev.ps1 deploy` only (never bundled).

Secrets (`.env` in development, `.env.prod` in production; same names, templates `.env.example` / `.env.prod.example`): `LANGFLOW_SECRET_KEY`, `LANGFLOW_SUPERUSER`, `LANGFLOW_SUPERUSER_PASSWORD`, `STUDIO_DB_PASSWORD`, `STUDIO_ENGINE_SECRET`, `STUDIO_TOOL_IIS_PASSWORD`.
<!-- docs:end configuration -->

## Services

<!-- docs:begin services -->
Application containers (`docker-compose.prod.yaml`, both built and bundled by `build`):

| Service | Image | Host port | Health | Built from |
|---|---|---|---|---|
| `agent-studio` | `agent-studio-app:<timestamp>` | 8095 | `GET http://<host>:8095/health` | `docker/app/Dockerfile` |
| `engine` | `agent-studio-engine:<timestamp>` | 7860 | `GET http://<host>:7860/health` | `docker/langflow/Dockerfile` |

Development (`docker-compose.yaml`) runs only `engine` as a container; the app runs natively (`dev.ps1 start`).

External services (not bundled, never started by this project):

| Dependency | Setting | Used for |
|---|---|---|
| PostgreSQL | `database:` / `app.database:` (db `agent_studio`, role `agent_studio`, app schema `agent_studio`) | engine data (agents, runs, users) and the app's drafts |
| Active Directory / LDAP (optional) | `ldap.enabled`, `ldap.server_uri` | directory sign-in; off = local accounts |
| openai model server | `ai.default` (`your-model-name`) | models for agents (engine) and the Agent Designer (`app.designer_profile`) |
| openai model server | `ai.reasoning` (`your-model-name`) | models for agents (engine) and the Agent Designer (`app.designer_profile`) |
| ollama model server | `ai.ollama` (`qwen3:30b-a3b-instruct-2507-q8_0`) | models for agents (engine) and the Agent Designer (`app.designer_profile`) |
| comfyui model server (disabled) | `ai.media` (`-`) | media generation |
| Monitored / organizational apps | `config/tools.yaml` `apps:`, `notify:`, `sql:` | what agents read and act on |
<!-- docs:end services -->

## Run locally

<!-- docs:begin local-run -->
Windows PC with Python 3.12 (`uv`), Node.js, Docker Desktop, and the existing PostgreSQL reachable as set in `config/config.yaml`.

```powershell
.\scripts\dev.ps1 setup      # .venv, frontend packages, .env from .env.example (then fill in .env)
docker compose build engine  # first time only: the engine image (~20 min); dev.ps1 build refreshes it
.\scripts\dev.ps1 start      # engine container, then API + web app; opens the browser
.\scripts\dev.ps1 seed       # apply config/policy/catalog.yaml to the engine
.\scripts\dev.ps1 test       # needs the running stack
```

| Part | URL |
|---|---|
| Web app (Vite) | http://127.0.0.1:5195 |
| Agent Studio API | http://127.0.0.1:8095/api/studio/v1 (OpenAPI: `/api/studio/v1/openapi.json`), health `/health` |
| Engine | http://127.0.0.1:7860/health (console only for `engine.console_admins`) |
<!-- docs:end local-run -->

## Build

<!-- docs:begin build -->
`.\scripts\dev.ps1 build` checks the required files, the config (mirrored keys, no secrets in YAML), the env template
names and the production Compose file, builds the web app, runs `test` (needs the running dev stack), runs `docs`, builds `agent-studio-app:<yyyyMMdd-HHmm>`, `agent-studio-engine:<yyyyMMdd-HHmm>`
and writes the bundle `dist\agent-studio-<yyyyMMdd-HHmm>\`: the image TAR and its `.sha256`, `docker-compose.prod.yaml` (release tag
filled in), `config/` (`config.yaml`, `config.prod.yaml`, `capabilities.yaml`, `policy/`, `tools.example.yaml`), `.env.prod.example`,
`FIRST_DEPLOYMENT.md`, `README.md`, `REFERENCE.md`, and `deployment-manifest.json` last (its presence marks a successful build).
<!-- docs:end build -->

## Local deploy

<!-- docs:begin local-deploy -->
`.\scripts\dev.ps1 deploy [-Bundle dist\agent-studio-<yyyyMMdd-HHmm>]` takes the newest bundle with a manifest, verifies the
checksum, loads the images, checks the tags against the manifest and runs the bundle's `docker-compose.prod.yaml` plus
`docker-compose.local-deploy.yaml` as Compose project `agent-studio-localdeploy` with `--env-file .env.local-deploy`. It then
waits for health, applies the catalog policy and prints the state. The dev stack keeps running.

- Ports: app http://127.0.0.1:18095, engine http://127.0.0.1:17860/health.
- Secrets: `.env.local-deploy` (created from `.env.prod.example` on the first run; fill in local test values).
- Settings: the repo's `config/` with `config/config.local-deploy.yaml` in place of `config.prod.yaml`.
- Data: `data\localdeploy\` (kept across bundles); database `studio_localdeploy` on the dev PostgreSQL (create once:
  `CREATE DATABASE studio_localdeploy OWNER agent_studio;`).
- Stop: `docker compose -p agent-studio-localdeploy down` (keeps data). Logs: `docker compose -p agent-studio-localdeploy logs -f`.
<!-- docs:end local-deploy -->

## Air-gapped deployment

<!-- docs:begin air-gapped-deployment -->
Copy the whole `dist\agent-studio-<yyyyMMdd-HHmm>\` folder to the target and follow `FIRST_DEPLOYMENT.md`. The TAR holds
every application image; nothing is pulled from a registry. Not in the bundle: PostgreSQL, Active Directory, the model
servers (Ollama / vLLM and their models) and the monitored apps - they are existing services the target must reach.
Agents get no internet access unless `config/tools.yaml` sets `web.enabled: true` (keep `false` on air-gapped sites).
<!-- docs:end air-gapped-deployment -->

## API

The web app uses only the studio API (OpenAPI: `/api/studio/v1/openapi.json`). The main groups:

| Group | Endpoints (prefix `/api/studio/v1`) |
|---|---|
| Agents | `GET/POST /agents`, `POST /agents/{id}/run` (+ `/run/stream`), `/publish`, `/pause`, `/resume`, `/retire`, `/versions`, `/share`, `/feedback`, `/memory` |
| Designer | `POST /designs`, `/designs/{id}/messages`, `/answers`, `/prefs`, `/create`, `/prove`, `GET /templates`, `/capabilities` |
| Tools | `GET /tools/discover`, `POST /tools/learn`, `/tools/auto`, `/tools/requests`, `/tools/code/draft`, `/tools/code/{id}/try`, `DELETE /tools/{id}`, `GET /toolkit` |
| Skills | `GET/POST /skills`, `POST /skills/draft`, `/skills/requests/{id}/approve` (or `/reject`) |
| Quality | `/agents/{id}/tests` (+ `/run`), `/agents/{id}/notes` |
| Sharing | `GET /shared`, `POST /shared/{id}/run` |
| Oversight | `/executions`, `/usage`, `/dashboard`, `/system`, `/activity` (+ `.csv`), `/approvals` |
| MCP | `/agents/{id}/mcp/connect`, `/mcp/keys`, `/mcp/servers` |
| Files | `GET/POST /files`, `GET/DELETE /files/{name}` |
| Setup | `/accounts`, `/setup/models` (+ `/test`) |

## Project layout

```text
backend/agent_studio/     FastAPI app: API, designer, director, watchkeepers, tools, guardrail, vault, roles
  watch/                  intake, duplicate, readiness, build check, runtime, failures, goals, model failover
frontend/src/             React web app (pages, components, i18n en/ar, styles)
engine/studio_engine/     engine plugin (sessions, compile, status, code tests, toolkit)
tools/studio_tools/       approved tool components for the engine (+ their own tests)
branding/                 brand.example (public) · brand.local (yours) · canvas branding
config/                   settings (placeholders) · capabilities · templates · tools · policy · local/ (yours)
docker/                   app and engine images
scripts/                  dev.ps1 (setup · start · test · build · deploy · publish) · docs.py · release_check.py
tests/                    API, designer, end-to-end and browser tests · mocks/ test doubles
docs/images/              the README screenshots
examples/policy-qa/       the showcase: sample PDF, the tool the studio wrote, how to recreate it
```

## Tests

`.\scripts\dev.ps1 test` runs the suite against the running stack (about 30 minutes; the model servers must answer):
API contract, designer rules and end-to-end designs, approvals, sharing, tools learning and drafting, AI-written
tools, guardrail, vault, roles, policy, branding (no engine name visible, no outside requests), MCP, watchkeepers.
`STUDIO_CLICKTHROUGH=1` adds the full browser journey (describe → build → prove → publish → scheduled run).
The tools package has its own tests (`tools/studio_tools/tests`), run where its libraries are installed.
