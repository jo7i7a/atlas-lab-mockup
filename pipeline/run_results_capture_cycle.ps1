# run_results_capture_cycle.ps1 -- entry point invocado por Windows Task Scheduler.
#
# Building:     ATLAS_LAB_MOCKUP (Edificio 5, mockup publico GitHub Pages)
# Type:         Implementation (captura intradia de resultados, Tipster ATLAS)
# Status:       Produccion
#
# Corre UNICAMENTE 14_sync_results_intraday.py, que invoca extractor_master.py
# (BASELINE CONGELADO, sin modificar) --sync-only para la lista acotada de
# ligas de ATLAS LAB. Su unica responsabilidad es dejar soccer_analytics.db
# con resultados mas frescos -- NO liquida picks, NO toca
# tipster_*_history.jsonl/tipster_picks_estado.json, NO re-hornea ni publica
# index.html, NO hace ningun git add/commit/push. Esa responsabilidad sigue
# siendo EXCLUSIVA de run_settlement_cycle.ps1 (settlement.py, sin cambios).
#
# Secuencia deseada:
#   captura de resultados (esta tarea, cada ~40 min)
#     -> soccer_analytics.db actualizada
#       -> run_settlement_cycle.ps1 (cada 45 min) encuentra el resultado
#         -> liquida, depura Picks activos, publica solo si hubo cambio real
#
# Registrado via Task Scheduler (ATLAS_Lab_Mockup_ResultsCaptureIntraday),
# corrida cada 40 min, MultipleInstancesPolicy=IgnoreNew,
# StartWhenAvailable=True -- mismo patron de proteccion que
# run_settlement_cycle.ps1/run_live_feed.ps1, sin la parte de git (esta
# tarea no tiene ninguna).

$ErrorActionPreference = "Continue"
$repoRoot = "C:\SoccerAnalyticsExtractor"
$pipeline = "$repoRoot\atlas_lab_mockup\pipeline"
$python = "$repoRoot\.venv\Scripts\python.exe"
$logDir = "$pipeline\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("run_results_capture_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $logFile -Force | Out-Null

Write-Output ("=== Inicio run_results_capture_cycle.ps1 " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " ===")

& $python "$pipeline\14_sync_results_intraday.py"
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Output "FALLO: 14_sync_results_intraday.py salio con codigo $exitCode (ninguna liga se sincronizo correctamente)"
    Write-Output "=== Fin run_results_capture_cycle.ps1 (con errores) ==="
    Stop-Transcript | Out-Null
    exit 1
}

Write-Output "=== Fin run_results_capture_cycle.ps1 (OK) ==="
Stop-Transcript | Out-Null
exit 0
