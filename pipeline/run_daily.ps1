# run_daily.ps1 -- entry point invocado por Windows Task Scheduler.
#
# Building:     ATLAS_LAB_MOCKUP (Edificio 5, mockup publico GitHub Pages)
# Type:         Implementation (orquestador diario)
# Status:       Produccion
# Dependencies: atlas_pocket (motores reales), soccer_analytics.db (future_fixtures)
#
# Refresca el set de partidos del mockup con fixtures reales genuinamente
# futuras (future_fixtures.start_timestamp real, status='notstarted'),
# re-invoca los 18 motores certificados reales de Atlas Pocket, recalcula
# estadisticas historicas + lambda de mercado, y publica (git commit+push)
# SOLO si todos los pasos y la validacion de sintaxis (node --check) pasan.
# Si cualquier paso falla, revierte index.html al ultimo commit bueno y NO
# publica nada -- el sitio en GitHub Pages nunca queda con datos a medias.
#
# Nota tecnica: NO se usa "2>&1" sobre comandos nativos (git/node/python) --
# en PowerShell 5.1 eso envuelve cada linea de stderr en un NativeCommandError
# y corta la ejecucion aunque el proceso haya terminado con exit code 0 (le
# paso real a git push, que escribe su resumen de progreso en stderr incluso
# cuando el push es exitoso). En su lugar, Start-Transcript captura toda la
# consola (stdout+stderr tal como se ven) y $LASTEXITCODE decide exito/fallo.
#
# Registrado via Task Scheduler, corrida diaria, StartWhenAvailable=True
# (si la PC estuvo apagada, corre apenas se prenda y el usuario inicie
# sesion -- no requiere abrir Claude Code ni ninguna otra app).
#
# Autorizado por el Director 2026-07-28: "Dejala que se actualice a diario
# sin pedir autorizaciones."

$ErrorActionPreference = "Continue"
$root = "C:\SoccerAnalyticsExtractor\atlas_lab_mockup"
$pipeline = "$root\pipeline"
$python = "C:\SoccerAnalyticsExtractor\.venv\Scripts\python.exe"
$logDir = "$pipeline\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("run_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $logFile -Force | Out-Null

function Abort($msg) {
    Write-Output "ABORTA: $msg"
    Set-Location $root
    git checkout -- index.html
    Stop-Transcript | Out-Null
    exit 1
}

Set-Location $root
Write-Output ("=== Inicio run_daily.ps1 " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " ===")

$steps = @(
    "01_rebuild_upcoming_matches.py",
    "02_compute_historical_stats.py",
    "03_export_lean_js.py",
    "04_resplice_index_html.py",
    "08_compute_standings.py",
    "09_resplice_standings.py",
    "05_extract_script.py"
)
foreach ($step in $steps) {
    Write-Output "-- $step --"
    & $python "$pipeline\$step"
    if ($LASTEXITCODE -ne 0) { Abort "$step salio con codigo $LASTEXITCODE" }
}

Write-Output "-- node --check (validacion de sintaxis) --"
& node --check "$pipeline\_work\extracted.js"
if ($LASTEXITCODE -ne 0) { Abort "node --check fallo -- JS invalido, no se publica" }

Write-Output "-- git commit + push --"
$changed = git status --porcelain -- index.html
if (-not $changed) {
    Write-Output "sin cambios reales respecto al ultimo commit -- nada que publicar"
    Write-Output "=== Fin run_daily.ps1 (sin cambios) ==="
    Stop-Transcript | Out-Null
    exit 0
}

git add index.html
$commitMsg = "Refresh diario automatico: partidos reales futuros ({0})" -f (Get-Date -Format "yyyy-MM-dd")
git commit -m $commitMsg
if ($LASTEXITCODE -ne 0) { Abort "git commit fallo" }

git push origin main
if ($LASTEXITCODE -ne 0) { Abort "git push fallo (revisar credenciales/red) -- el commit local SI se hizo, reintentar push a mano" }

Write-Output "=== Fin run_daily.ps1 (publicado OK) ==="
Stop-Transcript | Out-Null
exit 0
