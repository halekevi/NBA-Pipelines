# ============================================================
#  Register_Daily_Task.ps1
#  PropOracle automation scheduler:
#   - 1:00 AM  overnight grader (yesterday; late results) — single overnight slot
#   - 3:00 AM  light tennis fetch only (NO ticket/web publish — 5AM owns the board)
#   - 5:00 AM  first full daily (grade yesterday + multi-sport fetch + web; NO live CDP)
#   - 8:00 AM  line-move refresh
#   - 9:00 AM  line-move refresh
#   - 10:30 AM line-move refresh (PP often moves lines hard ~10:30–11)
#   - 11:00 AM live PrizePicks CDP MAIN floors (after 10:30 board settles)
#   - 1:00 PM  line-move refresh
#   Each refresh also runs only-missing CDP for new/changed slips.
#
# Each task opens ONE visible PowerShell console (direct pwsh.exe action).
# Do NOT wrap with cmd.exe "start /wait" — that leaves an empty cmd.exe window
# plus a second titled window. Requires "Run only when user is logged on".
#
# Run elevated from the repo you want tasks to use (e.g. H:\...\PropORACLE\scripts).
# Re-running replaces tasks so paths stay in sync after moving the clone off OneDrive.
# ============================================================

$PipelineRoot = Split-Path -Parent $PSScriptRoot
# Prefer pwsh (UTF-8 / PS7). Windows PowerShell 5.1 mis-parses UTF-8 em-dashes in wrappers.
$PowerShellExe = $null
foreach ($cand in @(
    (Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "$env:ProgramFiles\PowerShell\7\pwsh.exe",
    (Get-Command powershell.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
)) {
    if ($cand -and (Test-Path -LiteralPath $cand)) { $PowerShellExe = $cand; break }
}
if (-not $PowerShellExe) {
    Write-Error "No pwsh.exe/powershell.exe found"
    exit 1
}
Write-Host "Registering tasks with: $PowerShellExe" -ForegroundColor Cyan
Write-Host "Windows: one visible console (pwsh.exe directly; no cmd start wrapper)" -ForegroundColor Cyan

$Script3 = Join-Path $PipelineRoot "scripts\run_tennis_early_3am.ps1"
$Script5 = Join-Path $PipelineRoot "scripts\run_daily_5am.ps1"
$ScriptEvening = Join-Path $PipelineRoot "scripts\run_grader_evening.ps1"
$Script8 = Join-Path $PipelineRoot "scripts\run_daily_8am.ps1"
$ScriptPayout = Join-Path $PipelineRoot "scripts\run_payout_cdp.ps1"
$ScriptRefresh = Join-Path $PipelineRoot "scripts\run_refresh_with_log.ps1"

foreach ($s in @($Script3, $Script5, $ScriptEvening, $Script8, $ScriptPayout, $ScriptRefresh)) {
    if (-not (Test-Path $s)) {
        Write-Error "Required script missing: $s"
        exit 1
    }
}

# Legacy tasks to remove (superseded schedule).
$LegacyTasksToRemove = @(
    "PropORACLE Daily Pipeline",
    "PropOracle - Daily 4AM",
    "PropOracle - Grader 5AM",
    "PropOracle - Daily 7AM",
    "PropOracle - Refresh 11AM",
    # Early / extra overnight graders removed — keep only 1AM (+ grade inside Daily 5AM)
    "PropOracle - Grader 7PM",
    "PropOracle - Grader 8PM",
    "PropOracle - Grader 9PM",
    "PropOracle - Grader 10PM",
    "PropOracle - Grader 11PM",
    "PropOracle - Grader 12AM"
)
foreach ($legacy in $LegacyTasksToRemove) {
    $existing = Get-ScheduledTask -TaskName $legacy -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $legacy -Confirm:$false
        Write-Host "Removed legacy task: $legacy" -ForegroundColor Yellow
    }
}

function Register-PropTask {
    param(
        [string]$TaskName,
        [string]$Description,
        [string]$ScriptPath,
        [string]$At,
        [string]$ExtraArgs = ""
    )

    # One console only: Task Scheduler runs pwsh.exe with Interactive logon.
    # (cmd.exe + "start /wait" used to leave an empty cmd window + a second titled window.)
    $extra = $ExtraArgs.Trim()
    $psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    if ($extra) { $psArgs = "$psArgs $extra" }

    $action = New-ScheduledTaskAction `
        -Execute $PowerShellExe `
        -Argument $psArgs `
        -WorkingDirectory $PipelineRoot

    $trigger = New-ScheduledTaskTrigger -Daily -At $At
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
        -RestartCount 2 `
        -RestartInterval (New-TimeSpan -Minutes 15) `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew

    # Interactive = show UI when user is logged on (required for visible window).
    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Limited

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $Description `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Host "  Registered: $TaskName @ $At (visible window)" -ForegroundColor DarkGray
}

Register-PropTask `
    -TaskName "PropOracle - Tennis Early 3AM" `
    -Description "Light tennis fetch only (SkipCombined/SkipPush). 5AM owns multi-sport board publish. Opens visible PowerShell." `
    -ScriptPath $Script3 `
    -At "03:00"

Register-PropTask `
    -TaskName "PropOracle - Daily 5AM" `
    -Description "First full daily: multi-sport fetch, combined slate/web publish. Skips grader+A1 when overnight done; skips live CDP (mid-day/11AM). Opens visible PowerShell." `
    -ScriptPath $Script5 `
    -At "05:00"

# Single overnight grader + A1 historical actuals. Daily 5AM skips those when outputs/stamp exist.
$EveningGraderTasks = @(
    @{ Name = "PropOracle - Grader 1AM"; At = "01:00" }
)
foreach ($eg in $EveningGraderTasks) {
    Register-PropTask `
        -TaskName $eg.Name `
        -Description "Overnight: historical actuals (A1) + grader for yesterday. Opens visible PowerShell." `
        -ScriptPath $ScriptEvening `
        -At $eg.At
}

Register-PropTask `
    -TaskName "PropOracle - Daily 8AM" `
    -Description "Line-move update refresh (8/9/10:30/1 cadence). Opens visible PowerShell." `
    -ScriptPath $Script8 `
    -At "08:00"

Register-PropTask `
    -TaskName "PropOracle - Refresh 9AM" `
    -Description "Line-move refresh (8/9/10:30/1 cadence). Opens visible PowerShell." `
    -ScriptPath $ScriptRefresh `
    -At "09:00" `
    -ExtraArgs "-RunLabel 9AM"

Register-PropTask `
    -TaskName "PropOracle - Refresh 1030AM" `
    -Description "Line-move refresh at PP morning move window (~10:30–11). Opens visible PowerShell." `
    -ScriptPath $ScriptRefresh `
    -At "10:30" `
    -ExtraArgs "-RunLabel 1030AM"

Register-PropTask `
    -TaskName "PropOracle - Payout CDP" `
    -Description "Catchup CDP MAIN/STRONG floors (primary scrapes ride with 8/9/10:30/1 refreshes). Opens visible PowerShell." `
    -ScriptPath $ScriptPayout `
    -At "11:00"

$ScriptPayoutUpdate = Join-Path $PipelineRoot "scripts\run_payout_cdp_update.ps1"
if (-not (Test-Path $ScriptPayoutUpdate)) {
    Write-Error "Required script missing: $ScriptPayoutUpdate"
    exit 1
}
Register-PropTask `
    -TaskName "PropOracle - Payout CDP Update" `
    -Description "Afternoon catchup FillMissing CDP if a refresh left pending_live. Opens visible PowerShell." `
    -ScriptPath $ScriptPayoutUpdate `
    -At "15:00"

Register-PropTask `
    -TaskName "PropOracle - Refresh 1PM" `
    -Description "Afternoon line-move refresh (8/9/10:30/1 cadence). Opens visible PowerShell." `
    -ScriptPath $ScriptRefresh `
    -At "13:00" `
    -ExtraArgs "-RunLabel 1PM"

Write-Host ""
Write-Host "Scheduler tasks registered (visible PowerShell windows)." -ForegroundColor Green
Write-Host "  - PropOracle - Tennis Early 3AM (fetch only; no board publish)"
Write-Host "  - PropOracle - Daily 5AM (initial full run + FillMissing CDP)"
foreach ($eg in $EveningGraderTasks) {
    Write-Host "  - $($eg.Name)"
}
Write-Host "  - PropOracle - Daily 8AM (refresh + Force CDP)"
Write-Host "  - PropOracle - Refresh 9AM (refresh + Force CDP)"
Write-Host "  - PropOracle - Refresh 1030AM (refresh + Force CDP)"
Write-Host "  - PropOracle - Payout CDP (11:00 catchup)"
Write-Host "  - PropOracle - Payout CDP Update (15:00 catchup)"
Write-Host "  - PropOracle - Refresh 1PM (refresh + Force CDP)"
Write-Host ""
Write-Host "Removed extra graders: 7PM–12AM (keep 1AM + Daily 5AM grade only)" -ForegroundColor Yellow
Write-Host ""
Write-Host "Quick checks:"
Write-Host "  Get-ScheduledTask | Where-Object TaskName -like 'PropOracle -*' | Select-Object TaskName, State"
Write-Host "  Get-ScheduledTaskInfo -TaskName 'PropOracle - Daily 5AM' | Select LastRunTime, LastTaskResult, NextRunTime"
Write-Host "  Get-ScheduledTaskInfo -TaskName 'PropOracle - Grader 1AM' | Select LastRunTime, LastTaskResult, NextRunTime"
Write-Host "  Get-ScheduledTaskInfo -TaskName 'PropOracle - Payout CDP' | Select LastRunTime, LastTaskResult, NextRunTime"
Write-Host ""
Write-Host "Manual catchup (visible window):  pwsh -File scripts\Launch_Daily_5AM_Visible.ps1" -ForegroundColor Cyan
Write-Host "Manual payout CDP:              pwsh -File scripts\run_payout_cdp.ps1" -ForegroundColor Cyan
Write-Host "Manual payout update:           pwsh -File scripts\run_payout_cdp_update.ps1" -ForegroundColor Cyan
