# run_settlement_cycle.ps1 -- entry point invocado por Windows Task Scheduler.
#
# Building:     ATLAS_LAB_MOCKUP (Edificio 5, mockup publico GitHub Pages)
# Type:         Implementation (ciclo de settlement intraday, Tipster ATLAS)
# Status:       Produccion
#
# Corre UNICAMENTE 13_settle_tipster.py (liquidacion de Rankings/Picks ATLAS
# contra soccer_analytics.db -- logica SIN CAMBIOS, ver
# atlas_lab_mockup/tipster/settlement.py) con mayor frecuencia que la
# corrida diaria (cada 30-60 min en vez de una vez al dia), para que un pick
# que termina de jugarse pase de PENDIENTE a GANADO/PERDIDO/ANULADO en el
# siguiente ciclo disponible, no al dia siguiente. NUNCA regenera picks,
# rankings, cuotas (OddsPapi) ni invoca motores de atlas_pocket -- eso sigue
# siendo EXCLUSIVO de run_daily.ps1 (06:30). 13_settle_tipster.py tampoco
# depende de pipeline\_work\ (settlement consulta soccer_analytics.db
# directo), asi que esta tarea es segura de correr en paralelo con
# run_daily.ps1 sin ningun archivo compartido -- SALVO cuando efectivamente
# hay algo que publicar (ver mas abajo).
#
# Solo re-hornea y publica index.html cuando 13_settle_tipster.py cambio
# algo REAL (detectado con git status ANTES de tocar nada) -- si no liquido
# nada nuevo, no se toca index.html, no hay commit, no hay push (mismo
# criterio "sin cambios reales" ya usado en run_daily.ps1/run_live_feed.ps1).
# El re-horneado (03/04/05) SI depende de pipeline\_work\ (mismos archivos
# que escribe run_daily.ps1) -- por eso el intervalo/horario de esta tarea
# se eligio para no coincidir con la ventana 06:30 de la corrida diaria (ver
# registro de la tarea en Task Scheduler).
#
# Mismas protecciones que run_live_feed.ps1 (unico otro ciclo frecuente de
# este proyecto): GIT_TERMINAL_PROMPT=0 / GCM_INTERACTIVE=Never (incidente
# real 2026-08-07: git push colgado indefinidamente bajo Task Scheduler por
# un dialogo grafico de autenticacion invisible), verificacion previa de que
# no haya nada ya en el index de git, git add con pathspec EXPLICITO (nunca
# -A, nunca toca archivos fuera de la lista declarada), abort-and-revert si
# cualquier paso falla.
#
# Registrado via Task Scheduler (ATLAS_Lab_Mockup_SettlementCycle), corrida
# cada 45 min, MultipleInstancesPolicy=IgnoreNew, StartWhenAvailable=True.

$ErrorActionPreference = "Continue"
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "Never"
$root = "C:\SoccerAnalyticsExtractor\atlas_lab_mockup"
$pipeline = "$root\pipeline"
$python = "C:\SoccerAnalyticsExtractor\.venv\Scripts\python.exe"
$logDir = "$pipeline\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("run_settlement_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $logFile -Force | Out-Null

# Unico universo de archivos que esta tarea tiene permitido tocar/publicar
# -- nunca "git add -A", nunca index.html sin pasar primero por estos.
$tipsterFiles = @("tipster_rankings_history.jsonl", "tipster_picks_history.jsonl", "tipster_picks_estado.json")

function Abort($msg) {
    Write-Output "ABORTA: $msg"
    Set-Location $root
    git checkout -- $tipsterFiles 2>$null
    git checkout -- index.html 2>$null
    Stop-Transcript | Out-Null
    exit 1
}

Set-Location $root
Write-Output ("=== Inicio run_settlement_cycle.ps1 " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " ===")

Write-Output "-- verificacion previa: nada debe estar ya en el index --"
$preStaged = @(git diff --cached --name-only)
if ($preStaged.Count -gt 0) {
    Abort ("hay archivo(s) ya en el index antes de iniciar esta tarea ({0}) -- no se toca nada, revisar manualmente" -f ($preStaged -join ", "))
}

Write-Output "-- 13_settle_tipster.py --"
& $python "$pipeline\13_settle_tipster.py"
if ($LASTEXITCODE -ne 0) { Abort "13_settle_tipster.py salio con codigo $LASTEXITCODE" }

Write-Output "-- verificar si hubo liquidacion real (antes de tocar index.html) --"
$tipsterChanged = @(git status --porcelain -- $tipsterFiles) | Where-Object { $_ }
if (-not $tipsterChanged) {
    Write-Output "sin liquidaciones nuevas -- nada que publicar"
    Write-Output "=== Fin run_settlement_cycle.ps1 (sin cambios) ==="
    Stop-Transcript | Out-Null
    exit 0
}
Write-Output ("cambios reales detectados: {0}" -f (($tipsterChanged | Out-String).Trim()))

Write-Output "-- re-hornear index.html (03/04/05 -- NO se recalculan motores/OddsPapi/rankings) --"
& $python "$pipeline\03_export_lean_js.py"
if ($LASTEXITCODE -ne 0) { Abort "03_export_lean_js.py salio con codigo $LASTEXITCODE" }
& $python "$pipeline\04_resplice_index_html.py"
if ($LASTEXITCODE -ne 0) { Abort "04_resplice_index_html.py salio con codigo $LASTEXITCODE" }
& $python "$pipeline\05_extract_script.py"
if ($LASTEXITCODE -ne 0) { Abort "05_extract_script.py salio con codigo $LASTEXITCODE" }

Write-Output "-- node --check (validacion de sintaxis) --"
& node --check "$pipeline\_work\extracted.js"
if ($LASTEXITCODE -ne 0) { Abort "node --check fallo -- JS invalido, no se publica" }

Write-Output "-- git add (SOLO los archivos de settlement + index.html) --"
git add $tipsterFiles index.html
if ($LASTEXITCODE -ne 0) { Abort "git add fallo" }

$staged = @(git diff --cached --name-only) | Sort-Object
$expected = @($tipsterFiles + @("index.html")) | Sort-Object
$unexpected = @($staged | Where-Object { $expected -notcontains $_ })
if ($unexpected.Count -gt 0) {
    Abort ("staging inesperado -- se encontraron archivos fuera de lo esperado: {0}" -f ($unexpected -join ", "))
}

Write-Output "-- git commit + push --"
$commitMsg = "Liquidacion automatica Tipster ATLAS ({0})" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
git commit -m $commitMsg -- $tipsterFiles index.html
if ($LASTEXITCODE -ne 0) { Abort "git commit fallo" }

git push origin main
if ($LASTEXITCODE -ne 0) { Abort "git push fallo (revisar credenciales/red) -- el commit local SI se hizo, reintentar push a mano" }

Write-Output "=== Fin run_settlement_cycle.ps1 (publicado OK) ==="
Stop-Transcript | Out-Null
exit 0
