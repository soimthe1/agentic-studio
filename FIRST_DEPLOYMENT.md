# First deployment

One-time setup of Agentic Studio on a new server, from the offline bundle. Upgrades: see the header of
`docker-compose.prod.yaml`.

Words used below: an **image** is a packaged program (here two: the studio app and the agent engine); a
**container** is a running copy of an image; **Docker Compose** starts the containers described in
`docker-compose.prod.yaml`. The bundle folder contains no real secrets.

## 0. Before you start

Values to collect. Each `<PLACEHOLDER>` below means: replace it, including the angle brackets.

| Placeholder | Meaning | Where to get it |
|---|---|---|
| `<TIMESTAMP>` | Bundle build time, e.g. `20261124-1430` | The bundle folder name `agent-studio-<TIMESTAMP>` (step 1) |
| `<TARGET_HOST>` | DNS name of the target server | Infrastructure team |
| `<APP_URL>` | Address people open, e.g. `https://<TARGET_HOST>` behind your reverse proxy | Infrastructure team |
| `<DEPLOY_DIR>` | Folder on the target, e.g. `/opt/agent-studio` | Your choice |
| `<DB_HOST>` | Existing PostgreSQL server (port 5432) | Database team |
| `<DB_ADMIN>` | A PostgreSQL login allowed to create roles and databases | Database team |
| `<MODEL_HOST>` | Model server(s): vLLM / OpenAI-compatible (port 8000) and/or Ollama (port 11434) | AI platform team |
| `<LDAP_URI>` | Only for directory sign-in: directory server, e.g. `ldaps://dc.example.org:636`, and its user search base | Directory team |
| `<CONSOLE_ADMINS>` | Directory usernames of the technical admins allowed to open the engine console | Project owner |
| `<INTERNET>` | `false` on an air-gapped site; `true` only where agents may read public websites | Security officer |

Secrets you will create in step 4 (never written in this file): the PostgreSQL password, the break-glass
administrator password and two random keys.

Access needed: `sudo` on the target; `<DB_ADMIN>` on PostgreSQL; network rules (step 2).
Time needed: about 1 hour, plus about 30 minutes for the build.

## 1. Build

**Where:** build PC (Windows), PowerShell, in the repository folder; Docker Desktop running; the development stack
running (`.\scripts\dev.ps1 start` in another window), because `build` runs the tests.

Brand it first if you want your own name and logo: copy `branding/brand.example/` to `branding/brand.local/` and edit
`brand.json` (name, Arabic name, tagline, logo, favicon, theme). The engine's canvas takes the brand at build.

```powershell
.\scripts\dev.ps1 build
```

Success: the last line is `Bundle: ...\dist\agent-studio-<TIMESTAMP>`. That folder contains
`agent-studio-<TIMESTAMP>.tar`, `.sha256`, `deployment-manifest.json`, `docker-compose.prod.yaml`,
`.env.prod.example`, `config\`, `README.md`, `REFERENCE.md` and this file. If it stops earlier, the message names the failing step
(missing file, config check, tests, image build); fix that and run it again.

Copy the whole bundle folder to the target as `<DEPLOY_DIR>` (USB / approved transfer). Copy your
`branding/brand.local/` folder too if you made one.

## 2. Prerequisites

**Where:** target server, bash.

- Linux x86-64 with Docker Engine 24+ and Docker Compose v2.24+. See *Sizing* below for CPU, memory and disk.
- Inbound: **8095** (the studio, everyone; usually through your reverse proxy) and **7860** (engine, only the console
  admins and monitoring).
- Outbound: `<DB_HOST>:5432`, the directory (LDAPS 636), the model server(s), and the systems agents will use.

```bash
docker version --format '{{.Server.Version}}'
docker compose version
for hp in <DB_HOST>:5432 <MODEL_HOST>:8000; do
  timeout 3 bash -c "</dev/tcp/${hp%:*}/${hp#*:}" && echo "OK $hp" || echo "FAIL $hp"
done
```

Success: two version lines and `OK` for every address. `FAIL` means a firewall or a wrong name: fix it first.

## 3. External setup

**Where:** any machine with `psql`, connected to `<DB_HOST>` as `<DB_ADMIN>`.

The engine and the app share one database (config `database:` and `app.database:`); the app creates its own schema on
first use, the engine creates its tables on first start.

```bash
psql "host=<DB_HOST> port=5432 dbname=postgres user=<DB_ADMIN>"
```

```sql
CREATE ROLE agent_studio LOGIN;
\password agent_studio
CREATE DATABASE agent_studio OWNER agent_studio ENCODING 'UTF8' TEMPLATE template0;
\q
```

`\password` asks for the new password twice; keep it for `STUDIO_DB_PASSWORD` (step 4). Make sure `pg_hba.conf` on
`<DB_HOST>` allows this role from the target server.

Directory (only with `ldap.enabled: true`): nothing to create in it. People sign in with their own account. Decide which directory groups map to the
roles `user`, `builder` and `admin` (`ldap.group_map`, step 4.2).

## 4. Configuration

**Where:** target server, bash, in `<DEPLOY_DIR>`.

### 4.1 Secrets (`.env.prod`)

```bash
cd <DEPLOY_DIR>
cp .env.prod.example .env.prod
chmod 600 .env.prod
openssl rand -base64 36    # run twice: one value each for the two keys below
nano .env.prod
```

| Variable | Fill with |
|---|---|
| `LANGFLOW_SUPERUSER` | Name of the local break-glass administrator |
| `LANGFLOW_SUPERUSER_PASSWORD` | A long random password (store it in your password safe) |
| `LANGFLOW_SECRET_KEY` | A random value from `openssl rand` (never change it later: it encrypts stored credentials) |
| `STUDIO_DB_PASSWORD` | The password set with `\password agent_studio` in step 3 |
| `STUDIO_ENGINE_SECRET` | A random value from `openssl rand` (also the key of saved sign-ins: keep it) |

Passwords for systems are typed later on the **Systems** page and kept encrypted; they do not go in this file.

Success: `grep -c '=<' .env.prod` prints `0`.

### 4.2 Settings (`config/local/config.prod.yaml`)

Your values go in `config/local/` (merged over the committed placeholders by the app **and** the engine), so a later
bundle never overwrites them.

```bash
mkdir -p config/local
grep -n '__SET_ME__' config/config.prod.yaml      # the keys you must set
nano config/local/config.prod.yaml
```

Set at least:

| Key | Value |
|---|---|
| `app.public_url`, `engine.app_url` | `<APP_URL>` |
| `app.database.host`, `database.host` | `<DB_HOST>` |
| `engine.public_url` | `https://<TARGET_HOST>:7860` |
| `engine.console_admins` | `[<CONSOLE_ADMINS>]` |
| `ai.default`, `ai.reasoning` | your model server(s) and model names; `fallback:` names a backup profile |
| `ldap.enabled` | `false`: local accounts (the first visit creates the administrator, who adds people on Settings); `true`: directory sign-in |
| `ldap.server_uri`, `ldap.user_search_base`, `ldap.group_map` | directory sign-in only: your directory and the groups for each role |
| `langflow.cors_origins` | `[<APP_URL>]` |

Both containers serve plain HTTP: terminate TLS at your reverse proxy and forward to port 8095.

Success: every `__SET_ME__` key has a value in `config/local/config.prod.yaml`.

### 4.3 Tools allowlist (`config/tools.yaml`)

The tools may reach only what this file (and systems approved on the Systems page) names:

- `files.root: /data/files` and `documents.output_dir: /data/files` (documents go to people's files).
- `contracts_dir: /data/contracts` (systems and tools approved in the studio).
- `notify:` your pre-approved alert channel (webhook or SMTP), if any.
- Internet access: `web.enabled: <INTERNET>`. Keep `false` on air-gapped sites.

Your own applications (what the designer recommends reusing) go in `config/local/apps.yaml` (same shape as `apps:`
in `config/capabilities.yaml`).

### 4.4 Data folders

Both containers run as user id 1000 and write here. Back up `data/` with the database.

```bash
mkdir -p data/files data/contracts data/engine data/toolkit/wheels
sudo chown -R 1000:1000 data
```

`data/files/<owner id>/` holds each person's files; `data/contracts/` holds approved systems and tools written by AI;
`data/toolkit/` holds libraries you bring for those tools (see `docs/REFERENCE.md`, *Offline libraries*); `data/engine/` is
the engine's cache.

## 5. First start

**Where:** target server, bash, in `<DEPLOY_DIR>`.

```bash
sha256sum -c agent-studio-<TIMESTAMP>.sha256
docker load -i agent-studio-<TIMESTAMP>.tar
docker compose -f docker-compose.prod.yaml --env-file .env.prod up -d
```

Success: `agent-studio-<TIMESTAMP>.tar: OK`, then the two `Loaded image:` lines, then both containers `Started`. The
engine needs up to 3 minutes on the first start (it creates its tables); the app starts after the engine is healthy.

Then apply the approved component catalog (blocks every engine component not in `config/policy/catalog.yaml`;
safe to repeat):

```bash
docker compose -f docker-compose.prod.yaml exec -T agent-studio python -m agent_studio.seed --policy /app/config/policy/catalog.yaml
```

Success: `policy applied: revision ...` or `policy up to date ...`.

## 6. Verify

```bash
docker compose -f docker-compose.prod.yaml ps
curl -s http://localhost:8095/health
curl -s http://localhost:7860/health
```

Success: both services `Up (healthy)`; `{"status":"ok"}` from the app.

Open `<APP_URL>` in a browser: the sign-in page shows your brand. Sign in with a directory account (or, with local
accounts, create the administrator on the first visit): the dashboard opens. Then **Settings → AI models** shows the
model servers in use; changes made there take effect at once. **System health** lists the models, systems, channels, the app and the engine; everything should be green.
A name in `engine.console_admins` additionally sees an "Engine console" link.

## Sizing

The studio app is light; the work happens in the engine (agent runs) and, above all, on the model servers.

| Scale | Studio host | Notes |
|---|---|---|
| Pilot, up to a few hundred people | 4 CPU, 8 GB RAM, 20 GB disk | defaults |
| Department, a few thousand people | 8 CPU, 16 GB RAM | raise `langflow.workers` (engine processes) to 4; PostgreSQL on its own server |
| Organisation, tens of thousands of people | 16+ CPU, 32+ GB RAM, or several engine hosts | engine workers to match CPUs; a load balancer in front of the engine replicas; PostgreSQL sized for the run history |

- **Model servers set the real limit:** every agent step is a model call. Plan model capacity from the number of
  runs per hour, not from the number of people. Configure a `fallback` model profile so agents keep working when one
  server is down.
- **Keep one studio app process** (`uvicorn` without extra workers): it also runs the watchkeepers (failure checks,
  goal checks, model switch-over), which must run once. Scale the engine, not the app; one app process serves many
  thousands of people because every request is a thin call to the engine and the database.
- Put the reverse proxy's timeouts above the longest agent run (default up to 15 minutes for a thorough model).

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `sha256sum` says `FAILED` | TAR damaged in transfer | Copy the bundle again |
| Engine never healthy; log shows a database error | `database.host`, `pg_hba.conf` or `STUDIO_DB_PASSWORD` wrong | `docker compose -f docker-compose.prod.yaml logs engine`; fix, then run the start command again |
| A log says `missing secret ...` | `.env.prod` missing or incomplete | Do step 4.1, then run the start command again |
| A log says `config.prod.yaml has keys config.yaml lacks` | A key was misspelled | Correct the named key |
| `Permission denied` under `/data/...` or `/home/langflow/.cache` | Data folders not owned by uid 1000 | Step 4.4 |
| Sign-in says the name or password is incorrect for a valid account | LDAPS (636) blocked, or wrong `ldap:` values | Test port 636 as in step 2; check `ldap.server_uri` |
| Sign-in says the studio is not available right now | App cannot reach the engine, or `STUDIO_ENGINE_SECRET` differs | Both services read the same `.env.prod`; check `docker compose ... logs agent-studio` |
| Agents say web reading "needs setup" | `web.enabled: false` | Intended on air-gapped sites; otherwise step 4.3 |
| A capability shows "needs setup" | Its system is not connected | Connect it on the Systems page (or add it to `config/tools.yaml`); no restart needed |
| Saved sign-ins stop working after changing `STUDIO_ENGINE_SECRET` | The secret is also their encryption key | Re-enter them on the Systems page |
