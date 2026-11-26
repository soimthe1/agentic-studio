# Under the hood

A guided tour of the techniques and decisions behind Agent Studio: **what** each one is, **where** it lives, **why**
it was chosen, and the **alternative** that was considered. Read it from time to time; it changes with the code.

---

## Architecture

**Thin app over an unmodified agent engine.**
- *Where:* `backend/agent_studio/engine.py` is the only module that talks to the engine (Langflow, `docker-compose.yaml` service `engine`).
- *Why:* the engine already runs flows, tool calls, memory, schedules, approvals and MCP. The app adds what people see and what keeps agents safe, without forking the engine, so engine upgrades stay cheap.
- *Alternative:* writing our own agent runtime (full control, but months of work and every engine feature rebuilt), or forking the engine (fast start, painful upgrades).

**Engine extension instead of engine patches.**
- *Where:* `engine/studio_engine/plugin.py` (session, compile/decompile, status, code-test endpoints), `tools/studio_tools/` (the approved tool components as an extension bundle).
- *Why:* the engine loads plugins and component bundles by entry point, so we add behaviour without touching its source. The canvas front end is only re-branded at image build (`branding/apply-branding.mjs`, `docs/patches.md`).
- *Alternative:* patching engine files in the image (simpler at first, breaks on every upgrade).

**An agent is a definition, compiled by the engine.**
- *Where:* `director.py` builds a plain definition (steps + connections); the engine's own builder compiles it (`/studio-engine/compile`).
- *Why:* the designer never writes engine JSON by hand, and the engine validates what it will run.
- *Alternative:* generating engine flow JSON directly (couples the app to the engine's internal format).

## Making agents from plain words

**Designer = model proposes, rules decide.**
- *Where:* `designer.py` (the model reads the request and returns a plan as JSON), `designs.py` (the conversation, choices card), `director.py` (turns the plan into an agent).
- *Why:* models are good at understanding words and bad at guaranteeing safety. Everything that matters (which tools, approval, schedule, notifications) is checked or set by code, with the person's exact words kept as evidence.
- *Alternative:* letting the model write the whole agent (fewer lines, unpredictable results).

**Watchkeepers before and after building.**
- *Where:* `watch/intake.py`, `duplicate.py`, `readiness.py`, `buildcheck.py`.
- *Why:* cheap, deterministic checks catch the common mistakes (duplicate agent, missing sign-in, unapproved component, write tool outside approval) before anything runs.
- *Alternative:* a second model reviewing the first (slower, can also be wrong).

## Tools

**Tools from a system's own description, not hand-written connectors.**
- *Where:* `tools.py` (learn OpenAPI / contract files, draft, live test, approve), `studio_tools/core/apps.py` (one generic connector).
- *Why:* most in-house systems already publish an API description; one generic connector driven by YAML covers them, so new systems need settings, not code. Options cover odd shapes: `instances` (one deployment per target), `resolve` (look up an id by name), `defaults`, `extra_headers`.
- *Alternative:* a connector per product (more control, endless maintenance).

**AI picks operations; reuse before create.**
- *Where:* `tools.py` `pick()`, `auto_draft()`, `endpoint()`, `_known_routes()`.
- *Why:* people shouldn't have to know which endpoints a goal needs. Endpoints are compared as normalised addresses (host aliases folded), so the same operation is never connected twice.
- *Alternative:* word matching only (kept as the shortlist; too weak alone).

**Tools written by AI (Python), safety by people not by blocking.**
- *Where:* `codetool.py` (risk report + isolated runner; exact copy in `studio_tools/core/`), `codetools.py` (write, try, approve), `components/studio/code_tool.py` (runs approved tools in agents).
- *Why:* some jobs have no API description (mail, file shares, PowerShell). Nothing the code may do is blocked; instead every risky thing is named in plain words, an administrator approves the code, and every change or risky operation asks a person on each call. Tools run in their own process with a time limit.
- *Alternative:* a sandbox with an allowlist of modules (safer by default, but blocks exactly the tools people need).

**Air-gapped tool kit.**
- *Where:* `docker/langflow/requirements.in` (bundled libraries), `data/toolkit/` (wheels brought by people, installed with `pip --no-index`).
- *Why:* no internet on target servers; the common libraries ship in the image, anything else is brought as files with exact instructions.
- *Alternative:* an internal package mirror (better at scale, more infrastructure).

## Running and self-healing

**One watch loop for everything that runs by itself.**
- *Where:* `watch/failures.py` (loop), `goals.py`, `models.py`.
- *Why:* scheduled runs happen inside the engine; the app looks at each live agent as its owner every few minutes. One loop handles failure alerts, retries with the failure reason, parking agents that keep failing, making up missed schedules, goal checks and model switch-over.
- *Alternative:* hooks inside the engine (immediate, but couples us to engine internals).

**Model switch-over with hysteresis.**
- *Where:* `watch/models.py`, `ai_providers.py` (`fallback`).
- *Why:* two looks in a row before moving agents, so one dropped connection never flips them. Agents' model step is rewritten to the backup and back.
- *Alternative:* a load balancer in front of the model servers (transparent, but needs compatible models and more infrastructure).

**Agents check their own work.**
- *Where:* `director.work_loop()` (plan → act → check → one more try inside every run), `goals.py` (judge + retry with what was missing), `learn.py` (corrections, notes between runs).
- *Why:* local models make slips; a short self-check and a targeted retry fix most of them without a person.
- *Alternative:* larger models only (costly, not available offline).

## Data and security

**App tables in the existing PostgreSQL, engine data in the same server.**
- *Where:* `store.py` (schema from config), engine `database:` settings.
- *Why:* uses infrastructure that already exists and is backed up; no extra database to run.
- *Alternative:* SQLite (simplest, but no shared access and harder backups).

**Encrypted vault for sign-ins.**
- *Where:* `vault.py` (writes), `studio_tools/core/vault.py` (reads), key derived from the shared engine secret.
- *Why:* passwords typed on the Systems page never land in files or config.
- *Alternative:* an external secret manager (better for large estates, another service to run).

**Answer guardrail.**
- *Where:* `guard.py` (exact copy in `studio_tools/core/redact.py`), applied in `engine.py` and the notify tool.
- *Why:* secrets and personal identifiers are masked before people see or receive them.
- *Alternative:* a classifier model (catches more, slower and less predictable).

**Two sign-in modes, roles, engine console closed.**
- *Where:* `auth.py` (directory bind), `accounts.py` (local accounts), `roles.py`, engine plugin console gate.
- *Why:* `ldap.enabled: true` uses the directory (roles from groups); `false` keeps scrypt-hashed accounts in the app's tables, so a new install works with no directory (the first visit creates the administrator). Either way the app then asks the engine to open a normal session for the person. The raw engine UI is only for named administrators.
- *Alternative:* the engine's own login or an OIDC provider (Keycloak); more moving parts for the same result.

## Configuration and branding

**Neutral code, local organisation values, one brand file.**
- *Where:* `branding/brand.example` vs `branding/brand.local` (`brand.py`, `brand.ts`, canvas build), `config/*.yaml` vs `config/local/`, `scripts/release_check.py`.
- *Why:* one codebase serves the public release and in-house deployments; renaming the product or moving to another organisation is configuration, and the release check proves nothing private ships.
- *Alternative:* separate public and private branches (constant merge pain).

**Model servers set in the browser.**
- *Where:* `setup.py` (Settings -> AI models), `settings.py` (`_with_setup`), engine `entrypoint.ai_profiles` and `/studio-engine/models`.
- *Why:* saved profiles go to `<contracts_dir>/.setup/ai.json` (the folder both containers share) and win over `ai:` in config; keys go to the vault. The engine is told at once and refreshes every person's model address, so no restart.
- *Alternative:* edit `config.yaml` and restart (still works; the saved file wins when present).

**Quick start compose.**
- *Where:* `docker-compose.quickstart.yaml`, `config/config.quickstart.yaml` (merged last via `STUDIO_CONFIG_OVERLAY`).
- *Why:* one command on any OS, with its own PostgreSQL and secrets generated on first start into a volume (no shared default keys).
- *Alternative:* a `.env` file people must fill in (one more step, and defaults tend to stay unchanged).

## User interface

**Fit the screen, plain words first.**
- *Where:* `frontend/src/styles.css` (`page-fit`, `list-card`), every page.
- *Why:* no page scroll bars; long lists scroll inside their card. Technical terms appear only as small labels next to plain words.
- *Alternative:* conventional scrolling pages (simpler CSS, harder to scan on operations screens).
