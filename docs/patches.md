# Engine customisations (patch inventory)

Agent Studio uses the unmodified Langflow 1.13.2 release as its engine. Nothing in Langflow's source is forked. Every
difference from a stock install is listed here, so an engine upgrade knows exactly what to re-check.

## 1. Build-time: branding of the engine UI (only admins ever see it)

`docker/langflow/Dockerfile` builds the engine UI from the v1.13.2 source tarball (checksum pinned) after
`branding/apply-branding.mjs` has run on it. The script changes:

- logo, favicon, manifest, fonts (self-hosted), CSP meta tag
- the word "Langflow" in every locale and in a fixed list of UI files (with minimum replacement counts, so an
  upgrade that moves text fails the build instead of silently showing the old name)
- three "seams": the login form is replaced by a redirect to Agent Studio sign-in (`?local=1` keeps break-glass login),
  the GitHub/Discord counters and community links are removed (no outbound calls)

## 2. Runtime: the `studio-engine` plugin (`engine/studio_engine/plugin.py`, entry point `langflow.plugins`)

Plugins can only add routes; they cannot replace engine routes.

| Addition | Why |
|---|---|
| `POST /studio-engine/session` | Agent Studio signs people in with AD, then asks the engine (shared secret) for a normal engine session for that person |
| `POST /studio-engine/compile`, `/decompile` | Agent Studio agent definitions <-> engine flows, built with the engine's own `lfx.graph.flow_builder` against the live component registry |
| compile: values that Agent Studio sets are made visible (`show: true`) | the engine ignores values of hidden fields at run time (`param_handler` skips `show=False`), e.g. a language model's `ollama_base_url` |
| `GET /`, `GET /studio-auth/login` | browsers that land on the engine go to Agent Studio |
| `GET /{path}` (registered last) - console gate | every engine page opens only for `engine.console_admins` and the break-glass superuser; others go to Agent Studio. Serves the branded UI from `langflow.frontend_path`. Engine API routes are registered earlier and are unaffected |
| model connection retries | patches `ollama` client constructors to use an httpx transport with `retries=7` (connection failures only; a request the server already received is never repeated). Measured ~25% connect timeouts to the shared Ollama host |

## 3. Runtime: the entrypoint (`engine/studio_engine/entrypoint.py`)

- exports `LANGFLOW_*` settings from `config.yaml` `langflow:` and the database URL from `database:`
- exports model endpoints (`OLLAMA_BASE_URL`, `VLLM_API_BASE`, `OLLAMA_HOST`) from the `ai:` profiles
- disables the startup banner's PyPI update check (`fetch_latest_version`), which has no setting (air-gap)
- `langflow.models_dev_refresh: false` in config stops the live models.dev catalog fetch (air-gap)

## 4. Engine behaviour Agent Studio works around (no patch, but the director depends on it)

| Behaviour in 1.13.2 | What Agent Studio does |
|---|---|
| Flows with a human approval step only pause/resume through `/api/v2/workflows` (background jobs) | `backend/agent_studio/engine.py` runs such agents as jobs and resumes them with the person's decision |
| On resume the engine re-runs an Agent that feeds a HumanInput directly (its output is not checkpoint-safe) and schedules the next step too early | the director puts a plain-text step (`CombineText`) between the agent's proposal and the approval |
| Background jobs lose per-user variables, so models fall back to `localhost` | every agent thinks through one explicit model step that carries the server address |
| `/api/v1/all` hides blocked components; some components are listed twice (lowercase alias); an extension component is also checked under its short class name (`NotifyComponent` -> core `Notify`) | `agent_studio.seed` counts live-blocked keys as installed, never blocks aliases of allowed keys, and leaves those short names open |
| The engine closes idle keep-alive connections after ~5 s | the adapter retries a GET once on a transport error |

## Upgrade checklist

1. Change the pinned version + checksum in `docker/langflow/Dockerfile` and `docker/langflow/requirements.lock`.
2. Build: the branding script fails loudly if any replacement target moved.
3. Run `.\scripts\dev.ps1 test` (bundle, contract, console gate, policy, approvals, designer suites).
4. Re-check each row of section 4: when the engine fixes a behaviour, remove the workaround.
