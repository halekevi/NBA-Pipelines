# ============================================================
#  Register_Daily_Task.ps1
#  PropOracle automation scheduler:
#   - 3:00 AM  light tennis fetch + ticket rebuild (same-day early board)
#   - 5:00 AM  first full daily (grade yesterday + multi-sport fetch + web)
#   - 7:00 PM-1:00 AM  grader every hour (yesterday; games finishing)
#   - 8:00 AM  line-move update refresh (same path as mid-day refreshes; was 7AM)
#   - 9:00 AM  refresh + add/remove diff log
#   - 11:00 AM refresh + add/remove diff log
#   - 1:00 PM  refresh + add/remove diff log
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
$ScriptRefresh = Join-Path $PipelineRoot "scripts\run_refresh_with_log.ps1"

foreach ($s in @($Script3, $Script5, $ScriptEvening, $Script8, $ScriptRefresh)) {
    if (-not (Test-Path $s)) {
        Write-Error "Required script missing: $s"
        exit 1
    }
}

# Legacy tasks to remove (superseded by Daily 5AM / 8AM update).
$LegacyTasksToRemove = @(
    "PropORACLE Daily Pipeline",
    "PropOracle - Refresh 1030AM",
    "PropOracle - Daily 4AM",
    "PropOracle - Grader 5AM",
    "PropOracle - Daily 7AM"
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
    -Description "Light tennis fetch + ticket rebuild for same-day early-AM board (pre ~4:00 ET tips). Opens visible PowerShell." `
    -ScriptPath $Script3 `
    -At "03:00"

Register-PropTask `
    -TaskName "PropOracle - Daily 5AM" `
    -Description "First full daily: grade yesterday, multi-sport fetch, combined slate/web publish. Opens visible PowerShell." `
    -ScriptPath $Script5 `
    -At "05:00"

# Evening: hourly 7:00 PM - 1:00 AM local time (yesterday slate; pick up late results)
$EveningGraderTasks = @(
    @{ Name = "PropOracle - Grader 7PM";  At = "19:00" },
    @{ Name = "PropOracle - Grader 8PM";  At = "20:00" },
    @{ Name = "PropOracle - Grader 9PM";  At = "21:00" },
    @{ Name = "PropOracle - Grader 10PM"; At = "22:00" },
    @{ Name = "PropOracle - Grader 11PM"; At = "23:00" },
    @{ Name = "PropOracle - Grader 12AM"; At = "00:00" },
    @{ Name = "PropOracle - Grader 1AM";  At = "01:00" }
)
foreach ($eg in $EveningGraderTasks) {
    Register-PropTask `
        -TaskName $eg.Name `
        -Description "Hourly evening grader: pull latest, run grader for yesterday. Opens visible PowerShell." `
        -ScriptPath $ScriptEvening `
        -At $eg.At
}

Register-PropTask `
    -TaskName "PropOracle - Daily 8AM" `
    -Description "Line-move update refresh after 5AM full daily (same path as mid-day refreshes; 8:00 so 5AM usually finishes first). Opens visible PowerShell." `
    -ScriptPath $Script8 `
    -At "08:00"

Register-PropTask `
    -TaskName "PropOracle - Refresh 9AM" `
    -Description "Refresh props, update outputs, and log added/removed props. Opens visible PowerShell." `
    -ScriptPath $ScriptRefresh `
    -At "09:00" `
    -ExtraArgs "-RunLabel 9AM"

Register-PropTask `
    -TaskName "PropOracle - Refresh 11AM" `
    -Description "Mid-morning line-move refresh: re-fetch + rebuild tickets. Opens visible PowerShell." `
    -ScriptPath $ScriptRefresh `
    -At "11:00" `
    -ExtraArgs "-RunLabel 11AM"

Register-PropTask `
    -TaskName "PropOracle - Refresh 1PM" `
    -Description "Refresh props, update outputs, and log added/removed props. Opens visible PowerShell." `
    -ScriptPath $ScriptRefresh `
    -At "13:00" `
    -ExtraArgs "-RunLabel 1PM"

Write-Host ""
Write-Host "Scheduler tasks registered (visible PowerShell windows)." -ForegroundColor Green
Write-Host "  - PropOracle - Tennis Early 3AM"
Write-Host "  - PropOracle - Daily 5AM"
foreach ($eg in $EveningGraderTasks) {
    Write-Host "  - $($eg.Name)"
}
Write-Host "  - PropOracle - Daily 8AM (update refresh)"
Write-Host "  - PropOracle - Refresh 9AM"
Write-Host "  - PropOracle - Refresh 11AM"
Write-Host "  - PropOracle - Refresh 1PM"
Write-Host ""
Write-Host "Quick checks:"
Write-Host "  Get-ScheduledTask | Where-Object TaskName -like 'PropOracle -*' | Select-Object TaskName, State"
Write-Host "  Get-ScheduledTaskInfo -TaskName 'PropOracle - Daily 5AM' | Select LastRunTime, LastTaskResult, NextRunTime"
Write-Host "  Get-ScheduledTaskInfo -TaskName 'PropOracle - Daily 8AM' | Select LastRunTime, LastTaskResult, NextRunTime"
Write-Host ""
Write-Host "Manual catchup (visible window):  pwsh -File scripts\Launch_Daily_5AM_Visible.ps1" -ForegroundColor Cyan
