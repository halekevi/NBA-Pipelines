#requires -Version 5.1
<#
.SYNOPSIS
  Unscheduled or scheduled full daily: git pull main, run_daily.ps1 (today's pipeline + publish), prop snapshot.

.NOTES
  Scheduled 5:00 AM fetch + line snapshot + live payout CDP. Grader/A1 stay at 3AM
  when overnight stamps exist. 1AM already fetched overnight; this recaptures the
  pre-lock board (lines + payout_patch / rate cards) before 8AM.
  Refresh cadence after this: 8 / 9:45 / 10:30 / 1 / 4:30.
#>
param()

$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Daily 5AM" } catch { }
$Root = Split-Path $PSScriptRoot -Parent
$Daily = Join-Path $Root "scripts\run_daily.ps1"
$Snapshot = Join-Path $Root "scripts\log_prop_snapshot.ps1"

if (-not (Test-Path $Daily)) {
    Write-Error "Missing daily script: $Daily"
    exit 1
}
if (-not (Test-Path $Snapshot)) {
    Write-Error "Missing prop snapshot script: $Snapshot"
    exit 1
}

Set-Location $Root

function Get-MainWorktreeRoot {
    param([string]$RepoRoot = $Root)
    $porcelain = git -C $RepoRoot worktree list --porcelain 2>$null
    if (-not $porcelain) { return $null }
    $wt = $null
    foreach ($line in $porcelain) {
        if ($line -match '^worktree (.+)$') { $wt = $Matches[1].Trim() }
        elseif ($line -match '^branch refs/heads/main$' -and $wt) { return $wt }
        elseif ($line -eq "") { $wt = $null }
    }
    return $null
}

# Railway tracks origin/main. Prefer running daily on the main worktree when this
# checkout is a feature branch (main may already be locked in PropORACLE_main_cp).
$branch = (git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
$mainWt = Get-MainWorktreeRoot
if ($branch -ne "main") {
    if ($mainWt -and (Test-Path -LiteralPath (Join-Path $mainWt "scripts\run_daily.ps1"))) {
        Write-Host "[5AM DAILY] On '$branch' - running daily inside main worktree: $mainWt" -ForegroundColor Yellow
        $Root = $mainWt
        $Daily = Join-Path $Root "scripts\run_daily.ps1"
        $Snapshot = Join-Path $Root "scripts\log_prop_snapshot.ps1"
        Set-Location $Root
    }
    else {
        Write-Host "[5AM DAILY] On '$branch' - switching to main for Railway freshness..." -ForegroundColor Yellow
        git checkout main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[5AM DAILY] FAILED: cannot checkout main (locked by another worktree or WIP). Abort." -ForegroundColor Red
            exit 1
        }
    }
}

# Always capture wrapper output (Task Scheduler has no console + history often disabled).
$LogsDir = Join-Path $Root "logs"
if (-not (Test-Path -LiteralPath $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}
$WrapperLog = Join-Path $LogsDir ("task_5am_{0:yyyy-MM-dd_HHmmss}.log" -f (Get-Date))
try { Start-Transcript -Path $WrapperLog -Append | Out-Null } catch { }

Write-Host "[5AM DAILY] Pulling latest repository (main)..." -ForegroundColor Cyan
# Permanent fix: generated publish JSON (tickets_latest / tickets_winrate_latest /
# pipeline_status / sport_breakdown / slate_sport_*) used to leave orphaned
# unmerged index entries and abort every early run with exit 128 before STEP A/C.
# Ensure-CleanPull clears those; only real source-code conflicts abort (exit 2).
$EnsurePull = Join-Path $PSScriptRoot "Ensure-CleanPull.ps1"
if (-not (Test-Path -LiteralPath $EnsurePull)) {
    $EnsurePull = Join-Path $Root "scripts\Ensure-CleanPull.ps1"
}
& pwsh -NoProfile -File $EnsurePull -RepoRoot $Root -Label "[5AM DAILY]" -StashMessage ("proporacle-5am-pre-pull-{0:yyyyMMdd_HHmmss}" -f (Get-Date))
$pullPrepExit = $LASTEXITCODE
if ($pullPrepExit -eq 2) {
    # One retry after publish-only repair (handles leftover winrate/slate stages).
    Write-Host "[5AM DAILY] Source conflict reported — retrying publish-artifact repair..." -ForegroundColor Yellow
    & pwsh -NoProfile -File $EnsurePull -RepoRoot $Root -Label "[5AM DAILY]" -SkipPull
    $pullPrepExit = $LASTEXITCODE
}
if ($pullPrepExit -eq 2) {
    Write-Host "[5AM DAILY] FAILED: source-code conflicts block pull (resolve manually)." -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit 128
}
if ($pullPrepExit -ne 0) {
    Write-Host "[5AM DAILY] Pull prep warned (exit $pullPrepExit); continuing with local tree." -ForegroundColor Yellow
}

# Overnight 1AM owns grader + A1. Fall back only if those outputs never landed.
$Today = (Get-Date).ToString("yyyy-MM-dd")
$Yesterday = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
$gradedProbe = @(
    (Join-Path $Root "outputs\$Yesterday\graded_mlb_$Yesterday.xlsx"),
    (Join-Path $Root "outputs\$Yesterday\graded_soccer_$Yesterday.xlsx"),
    (Join-Path $Root "outputs\$Yesterday\graded_wnba_$Yesterday.xlsx")
)
$missingOvernight = @($gradedProbe | Where-Object { -not (Test-Path -LiteralPath $_) })
$a1Stamp = Join-Path $Root "data\cache\historical_actuals_ok_$Today.flag"
$dailyArgs = @()
if ($missingOvernight.Count -eq 0) {
    $dailyArgs += "-SkipGrader"
}
else {
    Write-Host "[5AM DAILY] Overnight grade incomplete — grader fallback ON" -ForegroundColor Yellow
    foreach ($m in $missingOvernight) {
        Write-Host "  missing -> $m" -ForegroundColor DarkYellow
    }
}
if (Test-Path -LiteralPath $a1Stamp) {
    $dailyArgs += "-SkipHistoricalActuals"
    Write-Host "[5AM DAILY] A1 stamp present — SkipHistoricalActuals" -ForegroundColor DarkGray
}
else {
    Write-Host "[5AM DAILY] No A1 stamp — historical actuals will run in daily" -ForegroundColor Yellow
}
Write-Host ("[5AM DAILY] Running run_daily.ps1 {0}" -f ($dailyArgs -join " ")) -ForegroundColor Cyan
$env:PROPORACLE_BET_WINDOW = "5AM"
$loggedHelper = Join-Path $PSScriptRoot "Invoke-LoggedPwsh.ps1"
if (-not (Test-Path -LiteralPath $loggedHelper)) { $loggedHelper = Join-Path $Root "scripts\Invoke-LoggedPwsh.ps1" }
$childLog = Join-Path $LogsDir ("run_daily_child_5am_{0:yyyy-MM-dd_HHmmss}.log" -f (Get-Date))
if (Test-Path -LiteralPath $loggedHelper) {
    . $loggedHelper
    $dailyExit = Invoke-LoggedPwsh -File $Daily -ArgumentList $dailyArgs -LogPath $childLog -WorkingDirectory $Root
} else {
    Write-Host "[5AM DAILY] WARN: Invoke-LoggedPwsh.ps1 missing — child output may not be logged" -ForegroundColor Yellow
    & pwsh -NoProfile -File $Daily @dailyArgs
    $dailyExit = $LASTEXITCODE
}

Write-Host "[5AM DAILY] Logging fetched prop snapshot..." -ForegroundColor Cyan
& pwsh -NoProfile -File $Snapshot -Label "5AM DAILY POST" -CompareToState -WriteState
if ($LASTEXITCODE -ne 0) {
    Write-Host "[5AM DAILY] Snapshot logging failed" -ForegroundColor Yellow
}

$Health = Join-Path $Root "scripts\Write-DailyRunHealth.ps1"
$healthExit = 0
if (Test-Path -LiteralPath $Health) {
    Write-Host "[5AM DAILY] Writing health stamp (fails task if board date != today)..." -ForegroundColor Cyan
    & pwsh -NoProfile -File $Health -RepoRoot $Root -Label "5AM" -RequireTickets
    $healthExit = $LASTEXITCODE
}
else {
    Write-Host "[5AM DAILY] WARN: Write-DailyRunHealth.ps1 missing" -ForegroundColor Yellow
}

if ($dailyExit -ne 0) {
    Write-Host "[5AM DAILY] run_daily failed (exit $dailyExit)" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit $dailyExit
}
if ($healthExit -ne 0) {
    Write-Host "[5AM DAILY] HEALTH CHECK FAILED (exit $healthExit) — Task Scheduler will show non-zero LastTaskResult" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit $healthExit
}

$AssertFresh = Join-Path $Root "scripts\Assert-ActiveSportsFresh.ps1"
if (Test-Path -LiteralPath $AssertFresh) {
    Write-Host "[5AM DAILY] Asserting active sports FRESH..." -ForegroundColor Cyan
    & pwsh -NoProfile -File $AssertFresh -RepoRoot $Root -Today $Today -JsonOut (Join-Path $Root "logs\LAST_ACTIVE_SPORTS_FRESH.json")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[5AM DAILY] ACTIVE SPORTS FRESHNESS GATE FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
        try { Stop-Transcript | Out-Null } catch { }
        exit $LASTEXITCODE
    }
}

Write-Host "[5AM DAILY] Complete" -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch { }
exit 0
