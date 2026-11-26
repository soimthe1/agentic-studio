# agent-studio (Agent Studio) developer commands. Run from anywhere: .\scripts\dev.ps1 <command>
#
#   setup    create .venv (Python 3.12: backend + test tools), install frontend packages, create .env from .env.example
#   start    start the engine container (Langflow), then API (uvicorn :8095, auto-reload) +
#            UI (Vite :5195) in this window and open the browser. Ctrl+C stops API + UI (on a fresh copy runs setup first)
#   stop     stop the dev servers and the engine container
#   status   show the engine container and what is listening on the dev ports
#   logs     follow the engine logs; `start` prints the API in its window, the UI goes to logs\ui.log
#   test     tests against the running stack (pytest), frontend type check
#   seed     apply the version-controlled catalog policy (config\policy\catalog.yaml) to the engine
#   docs     synchronize the generated sections of docs\REFERENCE.md with the repository (scripts\docs.py)
#   build    validate, test, docs, build the Docker images (app + engine; also refreshes the dev engine image) and
#            the offline deployment bundle in dist\agent-studio-<yyyyMMdd-HHmm>\
#   publish  push the public version to GitHub: docs, release check, commit (-Message), push. Your brand and
#            organisation values (branding/brand.local, config/local, docs/local, .env) never leave this PC; the
#            pre-push hook refuses any push that would carry them.
#   deploy   run the newest successful bundle (or -Bundle <folder>) locally in production shape: Compose project
#            agent-studio-localdeploy, .env.local-deploy, ports 18095 / 17860 (docker-compose.local-deploy.yaml)

param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "start", "stop", "status", "logs", "test", "seed", "docs", "build", "deploy", "publish", "help")]
    [string]$Command = "help",
    [string]$Message,  # publish: commit message
    [string]$Bundle   # deploy: bundle folder (default: newest dist\agent-studio-* with a deployment-manifest.json)
)

# Continue, not Stop: Windows PowerShell 5.1 turns any stderr line from a native tool
# (npm/pip warnings) into a terminating error under Stop. Every native call checks $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Frontend = Join-Path $Root "frontend"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Project = "agent-studio"
$EngineImage = "$Project-engine:dev"
$Ports = [ordered]@{ api = 8095; ui = 5195 }
$EnginePort = 7860
$PidFile = Join-Path $Root ".dev-pids"
# 127.0.0.1, not localhost: on some workstations localhost resolves to ::1 and Docker's IPv6 forward stalls.
$Host4 = "127.0.0.1"

function Say($text, $color = "Cyan") { Write-Host $text -ForegroundColor $color }

function Stop-Tree($id) {
    # /T also ends child processes (uvicorn worker, node).
    & taskkill /PID $id /T /F 2>$null | Out-Null
    # uvicorn --reload on Windows serves from a spawned worker; if the reloader already exited, find it by parent id.
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ParentProcessId -eq $id -or $_.CommandLine -like "*parent_pid=$id*" } |
        ForEach-Object { & taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null }
}

function Stop-DevServers {
    if (Test-Path $PidFile) {
        foreach ($id in Get-Content $PidFile) { Stop-Tree $id }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
    foreach ($port in $Ports.Values) {
        $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($id in $owners) { Stop-Tree $id }
    }
    # Wait until the ports are really free, so a following start does not hit "address in use".
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        $busy = $Ports.Values | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue }
        if (-not $busy) { return }
        Start-Sleep -Milliseconds 300
    }
    Say ("Port(s) still in use after stopping: {0}. Check with: Get-NetTCPConnection -LocalPort <port>" -f ($busy -join ", ")) Yellow
}

function Wait-Http($url, $seconds = 90) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3 | Out-Null; return $true } catch { Start-Sleep -Milliseconds 500 }
    }
    return $false
}

function Assert-Setup {
    if (-not (Test-Path $Py)) { throw ".venv missing - run: .\scripts\dev.ps1 setup" }
    if (-not (Test-Path (Join-Path $Frontend "node_modules"))) { throw "frontend\node_modules missing - run: .\scripts\dev.ps1 setup" }
    if (-not (Test-Path (Join-Path $Root ".env"))) { throw ".env missing - run: .\scripts\dev.ps1 setup" }
}

Push-Location $Root
try {
    switch ($Command) {
        "setup" {
            if (-not (Test-Path $Py)) {
                Say "Creating .venv (Python 3.12)..."
                & uv venv -q -p 3.12 (Join-Path $Root ".venv")
                if ($LASTEXITCODE) { throw "Could not create the venv - is uv installed (and can it find Python 3.12)?" }
            }
            Say "Installing backend and test packages..."
            & uv pip install -q -p $Py -r (Join-Path $Root "requirements-dev.txt")
            if ($LASTEXITCODE) { throw "pip install failed." }
            & $Py -m playwright install chromium
            Say "Installing frontend packages..."
            Push-Location $Frontend; try { & npm ci --no-audit --no-fund } finally { Pop-Location }
            if ($LASTEXITCODE) { throw "npm ci failed." }
            $envFile = Join-Path $Root ".env"
            if (-not (Test-Path $envFile)) {
                Copy-Item (Join-Path $Root ".env.example") $envFile
                Say "Created .env from .env.example (secrets only) - fill it in. Settings are in config\config.yaml." Yellow
            }
            & git -C $Root config core.hooksPath .githooks   # pre-push: refuse anything private
            Say "Setup complete. Next: .\scripts\dev.ps1 start" Green
        }

        "start" {
            if (-not (Test-Path $Py) -or -not (Test-Path (Join-Path $Frontend "node_modules"))) {
                Say "First run: setting up (Python venv, backend and frontend packages)..." Yellow
                & $PSCommandPath setup
                if (-not $?) { throw "Setup failed - see the output above." }
            }
            Assert-Setup
            # Engine: a container. start never builds images; build does.
            if (-not (& docker image ls -q $EngineImage)) { throw "No engine image yet ($EngineImage) - build it once: docker compose build engine   (dev.ps1 build refreshes it later)" }
            Say "Starting the engine container..."
            & docker compose -f (Join-Path $Root "docker-compose.yaml") up -d --no-build engine
            if ($LASTEXITCODE) { throw "Engine did not start - is Docker Desktop running?" }
            Say "Stopping any previous dev servers..."
            Stop-DevServers
            $api = Start-Process -FilePath $Py -WorkingDirectory $Root -NoNewWindow -PassThru `
                -ArgumentList "-m", "uvicorn", "agent_studio.app:app", "--host", $Host4, "--port", $Ports.api, "--reload", "--reload-dir", "backend"
            # The UI runs in its own hidden console: uvicorn --reload restarts its worker on Windows by
            # sending Ctrl+C to the whole console, which would otherwise also stop Vite on every code change.
            $logDir = Join-Path $Root "logs"
            New-Item -ItemType Directory -Force $logDir | Out-Null
            $uiLog = Join-Path $logDir "ui.log"
            $ui = Start-Process -FilePath "cmd.exe" -WorkingDirectory $Frontend -WindowStyle Hidden -PassThru `
                -ArgumentList "/c", "npx vite --port $($Ports.ui) --strictPort > `"$uiLog`" 2>&1"
            Say "UI (Vite) output: $uiLog" Gray
            Set-Content $PidFile @($api.Id, $ui.Id)
            try {
                if (-not (Wait-Http "http://$($Host4):$EnginePort/health" 300)) { throw "Engine did not become healthy - see: .\scripts\dev.ps1 logs" }
                if (-not (Wait-Http "http://$($Host4):$($Ports.api)/health")) { throw "API did not answer on port $($Ports.api) within 90s - see the output above." }
                if (-not (Wait-Http "http://$($Host4):$($Ports.ui)")) { throw "UI did not answer on port $($Ports.ui) within 90s - see $uiLog." }
                Say "Ready: http://$($Host4):$($Ports.ui)   (API :$($Ports.api), engine :$EnginePort). Ctrl+C stops API + UI." Green
                Start-Process "http://$($Host4):$($Ports.ui)"
                while (-not $api.HasExited -and -not $ui.HasExited) { Start-Sleep -Seconds 1 }
                Say ("A dev server exited (API exited={0} code={1}; UI exited={2} code={3}) - stopping the other." -f $api.HasExited, $(if ($api.HasExited) { $api.ExitCode }), $ui.HasExited, $(if ($ui.HasExited) { $ui.ExitCode })) Yellow
            }
            finally { Stop-DevServers }
        }

        "stop" {
            Stop-DevServers
            & docker compose -f (Join-Path $Root "docker-compose.yaml") stop engine
            Say "Dev servers and engine stopped." Green
        }

        "status" {
            & docker compose -f (Join-Path $Root "docker-compose.yaml") ps engine
            foreach ($p in $Ports.GetEnumerator()) {
                $on = Get-NetTCPConnection -LocalPort $p.Value -State Listen -ErrorAction SilentlyContinue
                Say ("{0,-4} :{1}  {2}" -f $p.Key, $p.Value, $(if ($on) { "listening" } else { "-" }))
            }
        }

        "logs" {
            Say "Following the engine container. The API logs in the start window; the UI in logs\ui.log." Yellow
            & docker compose -f (Join-Path $Root "docker-compose.yaml") logs -f engine
        }

        "test" {
            Assert-Setup
            if (-not (Wait-Http "http://$($Host4):$($Ports.api)/health" 3)) { throw "Tests need the running stack - run .\scripts\dev.ps1 start in another window." }
            & $Py -m pytest (Join-Path $Root "tests") -q
            if ($LASTEXITCODE) { throw "Tests failed." }
            Push-Location $Frontend; try { & npm run typecheck } finally { Pop-Location }
            if ($LASTEXITCODE) { throw "Frontend type check failed." }
            Say "All tests passed." Green
        }

        "seed" {
            Assert-Setup
            & $Py -m agent_studio.seed
            if ($LASTEXITCODE) { throw "Seed failed." }
        }

        "docs" {
            if (-not (Test-Path $Py)) { throw ".venv missing - run: .\scripts\dev.ps1 setup" }
            & $Py (Join-Path $Root "scripts\docs.py")
            if ($LASTEXITCODE) { throw "docs failed - see the message above." }
        }

        "publish" {
            if (-not (Test-Path $Py)) { throw ".venv missing - run: .\scripts\dev.ps1 setup" }
            & git -C $Root config core.hooksPath .githooks
            & $Py (Join-Path $Root "scripts\docs.py")
            if ($LASTEXITCODE) { throw "docs failed - see the message above." }
            & $Py (Join-Path $Root "scripts\release_check.py")
            if ($LASTEXITCODE) { throw "Not published: organisation details found (listed above). Fix them and run publish again." }
            $changes = & git -C $Root status --porcelain
            if ($changes) {
                if (-not $Message) { throw "There are changes to commit: give a message, e.g. .\scripts\dev.ps1 publish -Message `"Add X`"" }
                Say "Changes to publish:"; $changes | ForEach-Object { Write-Host "  $_" }
                & git -C $Root add -A
                & git -C $Root commit -q -m $Message
                if ($LASTEXITCODE) { throw "commit failed." }
            }
            & git -C $Root push
            if ($LASTEXITCODE) { throw "push failed - see the message above." }
            Say "Published: $(& git -C $Root remote get-url origin)" Green
            Say "Screenshots in docs\images are not checked automatically: retake them with the public brand (docs\REFERENCE.md, section Make it yours)." Yellow
        }

        "build" {
            Assert-Setup
            $ts = Get-Date -Format "yyyyMMdd-HHmm"
            $bundle = Join-Path $Root "dist\$Project-$ts"
            # 1. validate
            foreach ($f in "docker-compose.prod.yaml", "FIRST_DEPLOYMENT.md", "README.md", ".env.example", ".env.prod.example",
                           "config\config.yaml", "config\config.prod.yaml", "docker\app\Dockerfile", "docker\langflow\Dockerfile") {
                if (-not (Test-Path $f)) { throw "Missing required file: $f" }
            }
            & $Py -c "import os; os.environ['APP_ENV']='prod'; from agent_studio import settings; settings.load()"   # mirrored keys, no secrets in YAML
            if ($LASTEXITCODE) { throw "Config check failed." }
            $names = { param($f) (Get-Content $f | Where-Object { $_ -match '^\s*#?\s*([A-Z][A-Z0-9_]+)=' } | ForEach-Object { $Matches[1] }) | Sort-Object -Unique }
            if (Compare-Object (& $names ".env.example") (& $names ".env.prod.example")) { throw ".env.example and .env.prod.example name different variables." }
            & docker compose -f docker-compose.prod.yaml --env-file .env.prod.example config --quiet
            if ($LASTEXITCODE) { throw "docker-compose.prod.yaml does not validate." }
            Push-Location $Frontend; try { & npm run build } finally { Pop-Location }
            if ($LASTEXITCODE) { throw "Web app build failed." }
            & $PSCommandPath test
            if (-not $?) { throw "Tests failed - no images built." }
            # 2. generated reference sections
            & $PSCommandPath docs
            if (-not $?) { throw "docs failed - no images built." }
            # 3. images (application-owned only; PostgreSQL / AD / model servers are external)
            $images = @("$Project-app:$ts", "$Project-engine:$ts")
            Say "Building the engine image (the builder canvas step takes ~20 min when branding changed)..."
            & docker build -f docker\langflow\Dockerfile -t $images[1] -t $EngineImage .
            if ($LASTEXITCODE) { throw "Engine image build failed - is Docker Desktop running?" }
            Say "Building the app image..."
            & docker build -f docker\app\Dockerfile -t $images[0] .
            if ($LASTEXITCODE) { throw "App image build failed." }
            # 4-6. bundle
            New-Item -ItemType Directory -Force (Join-Path $bundle "config") | Out-Null
            $tar = Join-Path $bundle "$Project-$ts.tar"
            & docker save -o $tar @images
            if ($LASTEXITCODE) { throw "docker save failed." }
            $hash = (Get-FileHash $tar -Algorithm SHA256).Hash.ToLower()
            "$hash  $Project-$ts.tar" | Set-Content -NoNewline -Encoding ascii (Join-Path $bundle "$Project-$ts.sha256")
            (Get-Content docker-compose.prod.yaml -Raw).Replace("__TAG__", $ts) | Set-Content -NoNewline -Encoding utf8 (Join-Path $bundle "docker-compose.prod.yaml")
            Copy-Item config\config.yaml, config\config.prod.yaml, config\capabilities.yaml (Join-Path $bundle "config")
            # tools.yaml is site-specific (dev points at test doubles): the target writes its own from this example.
            Copy-Item tools\studio_tools\tools.example.yaml (Join-Path $bundle "config\tools.example.yaml")
            if (Test-Path config\policy) { Copy-Item config\policy (Join-Path $bundle "config") -Recurse }
            Copy-Item .env.prod.example, FIRST_DEPLOYMENT.md, README.md, docs\REFERENCE.md $bundle
            # 7. verify image references, then the manifest last (its presence marks a successful build)
            $compose = Get-Content (Join-Path $bundle "docker-compose.prod.yaml") -Raw
            foreach ($img in $images) { if (-not $compose.Contains($img.Split(":")[0] + ':${STUDIO_TAG:-' + $ts + '}')) { throw "Bundled compose does not reference $img." } }
            $rev = (& git rev-parse --short HEAD 2>$null); if (-not $rev) { $rev = $null }; $global:LASTEXITCODE = 0   # no git here is fine
            [ordered]@{
                project = $Project; build = $ts; git_revision = $rev; images = $images
                tar = @{ file = "$Project-$ts.tar"; sha256 = $hash }
                required_files = @("docker-compose.prod.yaml", ".env.prod (from .env.prod.example)", "config/config.yaml", "config/config.prod.yaml",
                                   "config/capabilities.yaml", "config/policy/catalog.yaml", "config/tools.yaml (from config/tools.example.yaml)")
                external_dependencies = @("PostgreSQL (config database:)", "Active Directory, optional (config ldap:)", "Ollama / vLLM (config ai:)",
                                          "monitored apps (config/tools.yaml)")
            } | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $bundle "deployment-manifest.json")
            Say "Bundle: $bundle" Green
        }

        "deploy" {
            # Local production-mode rehearsal of a built bundle (Project Standard, local deploy contract).
            $dir = if ($Bundle) { (Resolve-Path $Bundle -ErrorAction SilentlyContinue).Path } else {
                Get-ChildItem (Join-Path $Root "dist") -Directory -Filter "$Project-*" -ErrorAction SilentlyContinue |
                    Where-Object { Test-Path (Join-Path $_.FullName "deployment-manifest.json") } |
                    Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName }
            if (-not $dir) { throw "No successful bundle (folder with deployment-manifest.json) - run: .\scripts\dev.ps1 build" }
            $manifestFile = Join-Path $dir "deployment-manifest.json"
            if (-not (Test-Path $manifestFile)) { throw "$dir has no deployment-manifest.json (incomplete build)." }
            $m = Get-Content $manifestFile -Raw | ConvertFrom-Json
            if ($m.project -ne $Project -or -not $m.images -or -not $m.tar.file) { throw "$manifestFile is not a $Project bundle manifest." }
            $tar = Join-Path $dir $m.tar.file
            $composeFile = Join-Path $dir "docker-compose.prod.yaml"
            foreach ($f in $tar, $composeFile, (Join-Path $dir "config\config.yaml")) { if (-not (Test-Path $f)) { throw "Bundle is missing $f" } }
            & docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
            if ($LASTEXITCODE) { throw "Docker is not running - start Docker Desktop." }
            Say "Verifying checksum of $($m.tar.file)..."
            if ((Get-FileHash $tar -Algorithm SHA256).Hash.ToLower() -ne $m.tar.sha256) { throw "Checksum mismatch: $tar is corrupt or not the one this manifest describes." }
            Say "Loading images..."
            & docker load -i $tar
            if ($LASTEXITCODE) { throw "docker load failed." }
            foreach ($img in $m.images) {
                & docker image inspect $img 2>$null | Out-Null
                if ($LASTEXITCODE) { throw "Image $img (from the manifest) was not loaded from the TAR." }
            }
            $envLocal = Join-Path $Root ".env.local-deploy"
            if (-not (Test-Path $envLocal)) {
                Copy-Item (Join-Path $Root ".env.prod.example") $envLocal
                throw "Created .env.local-deploy from .env.prod.example - fill in local test values (never real production secrets), then run deploy again."
            }
            if (Select-String -Path $envLocal -Pattern '^[A-Z][A-Z0-9_]*=<' -Quiet) { throw ".env.local-deploy still has <placeholder> values - fill them in." }
            $override = Join-Path $Root "docker-compose.local-deploy.yaml"
            $files = @("-f", $composeFile); if (Test-Path $override) { $files += @("-f", $override) }
            $dc = @("compose", "-p", "$Project-localdeploy") + $files + @("--env-file", $envLocal)
            $env:STUDIO_REPO = $Root
            Say "Starting $Project-localdeploy from $dir ..."
            & docker @dc up -d
            if ($LASTEXITCODE) { throw "docker compose up failed - logs: docker compose -p $Project-localdeploy logs" }
            $appUrl = "http://$($Host4):18095"; $engineUrl = "http://$($Host4):17860"
            $healthy = (Wait-Http "$engineUrl/health" 300) -and (Wait-Http "$appUrl/health" 90)
            & docker @dc ps
            if (-not $healthy) { throw "Local deploy is NOT healthy (containers kept for inspection). Logs: docker compose -p $Project-localdeploy logs" }
            Say "Applying the catalog policy (idempotent)..."
            & docker @dc exec -T agent-studio python -m agent_studio.seed --policy /app/config/policy/catalog.yaml
            if ($LASTEXITCODE) { throw "Seed failed in the local deploy - logs: docker compose -p $Project-localdeploy logs agent-studio" }
            Say "Local deploy healthy ($(Split-Path $dir -Leaf)): $appUrl   (engine $engineUrl/health)" Green
            Say "Logs: docker compose -p $Project-localdeploy logs -f     Stop: docker compose -p $Project-localdeploy down" Gray
        }

        default {
            Get-Content $PSCommandPath | Select-Object -Skip 1 -First 14 | ForEach-Object { $_ -replace "^# ?", "" }
        }
    }
}
finally { Pop-Location }
