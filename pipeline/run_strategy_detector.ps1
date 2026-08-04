# run_strategy_detector.ps1 -- entry point invocado por Windows Task Scheduler.
#
# Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Laboratorio de Estrategias
# Type:         Implementation (orquestador generico -- llama a
#               run_live_strategies.py, que corre TODAS las estrategias LIVE
#               activas, no una sola. Emite via ATLAS Notify -- atlas_engine/notify/)
# Status:       Produccion (estrategia activa actual: L1; E-LAB-001 REFUTADA
#               2026-08-04, ver strategies_registry.json, no corre mas)
# Dependencies: atlas_engine\data\run_live_strategies.py, atlas_engine\notify\,
#               signal_platform_capture.db (solo lectura)
#
# Publica (git commit+push) SOLO live_alerts.json y live_alerts_history.jsonl
# -- registro COMPARTIDO de todo el laboratorio (cualquier estrategia activa),
# escrito por atlas_engine/notify/engine.py. Mismo patron de barreras que
# run_live_feed.ps1 (verificar pre-staged, git add nombrando archivos,
# verificar staged == esperado, revert si falla algo).
#
# CADENCIA: cada 1 minuto (minimo real que acepta Windows Task Scheduler --
# se probo 30s, lo rechazo con error de rango). Task Scheduler: ATLAS_Lab_StrategyDetector.
#
# Agregar una estrategia nueva = escribir su modulo en atlas_engine/data/ +
# una linea en ACTIVE_STRATEGIES de run_live_strategies.py -- NUNCA hace
# falta tocar este .ps1 ni crear una tarea de Task Scheduler nueva.

$ErrorActionPreference = "Continue"
$root = "C:\SoccerAnalyticsExtractor"
$mockupRoot = "C:\SoccerAnalyticsExtractor\atlas_lab_mockup"
$pipeline = "$mockupRoot\pipeline"
$python = "C:\SoccerAnalyticsExtractor\.venv\Scripts\python.exe"
$detectorScript = "$root\atlas_engine\data\run_live_strategies.py"
$logDir = "$pipeline\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("run_strategy_detector_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$filesToPublish = @("live_alerts.json", "live_alerts_history.jsonl")

Start-Transcript -Path $logFile -Force | Out-Null

function Abort($msg) {
    Write-Output "ABORTA: $msg"
    Set-Location $mockupRoot
    git reset -- $filesToPublish 2>$null
    git checkout -- live_alerts.json 2>$null
    Stop-Transcript | Out-Null
    exit 1
}

Set-Location $root
Write-Output ("=== Inicio run_strategy_detector.ps1 " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " ===")

& $python $detectorScript
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { Abort "strategy_lab_detector.py salio con codigo $exitCode" }

Set-Location $mockupRoot
if (-not (Test-Path "live_alerts.json")) {
    Write-Output "sin alertas activas todavia -- nada que publicar en este ciclo"
    Write-Output "=== Fin run_strategy_detector.ps1 (sin alertas) ==="
    Stop-Transcript | Out-Null
    exit 0
}

Write-Output "-- validacion de JSON --"
& $python -c "import json; json.load(open('live_alerts.json', encoding='utf-8'))"
if ($LASTEXITCODE -ne 0) { Abort "live_alerts.json invalido -- no se publica" }

Write-Output "-- verificacion previa: nada debe estar ya en el index --"
$preStaged = @(git diff --cached --name-only)
if ($preStaged.Count -gt 0) {
    Abort ("hay archivo(s) ya en el index antes de iniciar esta tarea ({0}) -- no se toca nada, revisar manualmente" -f ($preStaged -join ", "))
}

Write-Output "-- git add (SOLO live_alerts.json y live_alerts_history.jsonl) --"
git add $filesToPublish
if ($LASTEXITCODE -ne 0) { Abort "git add fallo" }

$staged = @(git diff --cached --name-only)
$unexpected = $staged | Where-Object { $filesToPublish -notcontains $_ }
if ($unexpected.Count -gt 0) {
    Abort ("staging inesperado -- se encontro archivo(s) fuera de lo esperado: {0}" -f ($unexpected -join ", "))
}

if ($staged.Count -eq 0) {
    Write-Output "sin cambios reales respecto al ultimo commit -- nada que publicar"
    Write-Output "=== Fin run_strategy_detector.ps1 (sin cambios) ==="
    Stop-Transcript | Out-Null
    exit 0
}

Write-Output "-- git commit + push --"
$commitMsg = "ATLAS Notify: refresco automatico de alertas ({0})" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
git commit -m $commitMsg -- $filesToPublish
if ($LASTEXITCODE -ne 0) { Abort "git commit fallo" }

git push origin main
if ($LASTEXITCODE -ne 0) { Abort "git push fallo (revisar credenciales/red) -- el commit local SI se hizo, reintentar push a mano" }

Write-Output "=== Fin run_strategy_detector.ps1 (publicado OK) ==="
Stop-Transcript | Out-Null
exit 0
