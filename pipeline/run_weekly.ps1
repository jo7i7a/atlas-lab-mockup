# run_weekly.ps1 -- entry point invocado por Windows Task Scheduler.
#
# Building:     ATLAS_LAB_MOCKUP (Edificio 5, mockup publico GitHub Pages)
# Type:         Implementation (orquestador semanal)
# Status:       Produccion
# Dependencies: soccer_analytics.db (matches/match_stats/seasons reales)
#
# Recalcula TEAM_RADIOGRAPHY y TEAM_LEADERBOARDS (rankings de temporada 2026,
# BTTS/Over2.5/Corners+9.5/Remates/Tarjetas, TOTAL y Local/Visita) desde cero
# contra la base real y los resplice en index.html. Publica (git commit+push)
# SOLO si la validacion de sintaxis (node --check) pasa. Si algo falla,
# revierte index.html al ultimo commit bueno y no publica nada -- mismo
# patron ya validado en run_daily.ps1 (partidos), separado en su propia
# tarea porque el ranking cambia con frecuencia semanal, no diaria.
#
# Registrado via Task Scheduler, corrida semanal, StartWhenAvailable=True.

$ErrorActionPreference = "Continue"
$root = "C:\SoccerAnalyticsExtractor\atlas_lab_mockup"
$pipeline = "$root\pipeline"
$python = "C:\SoccerAnalyticsExtractor\.venv\Scripts\python.exe"
$logDir = "$pipeline\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("run_weekly_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $logFile -Force | Out-Null

function Abort($msg) {
    Write-Output "ABORTA: $msg"
    Set-Location $root
    git checkout -- index.html
    Stop-Transcript | Out-Null
    exit 1
}

Set-Location $root
Write-Output ("=== Inicio run_weekly.ps1 " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " ===")

$steps = @(
    "06_compute_team_leaderboards.py",
    "07_resplice_team_data.py",
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
    Write-Output "=== Fin run_weekly.ps1 (sin cambios) ==="
    Stop-Transcript | Out-Null
    exit 0
}

git add index.html
$commitMsg = "Refresh semanal de rankings: TEAM_RADIOGRAPHY/TEAM_LEADERBOARDS ({0})" -f (Get-Date -Format "yyyy-MM-dd")
git commit -m $commitMsg
if ($LASTEXITCODE -ne 0) { Abort "git commit fallo" }

git push origin main
if ($LASTEXITCODE -ne 0) { Abort "git push fallo (revisar credenciales/red) -- el commit local SI se hizo, reintentar push a mano" }

Write-Output "=== Fin run_weekly.ps1 (publicado OK) ==="
Stop-Transcript | Out-Null
exit 0
