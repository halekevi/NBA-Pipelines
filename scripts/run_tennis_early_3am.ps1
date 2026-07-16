#requires -Version 5.1
<#
.SYNOPSIS
  3:00 AM ET light tennis fetch + ticket rebuild (pre-tip for ~4:00–5:30 AM matches).

.DESCRIPTION
  - Pulls latest main (Railway tracks origin/main).
  - Runs run_pipeline.ps1 -TennisOnly for Eastern today (same-day tennis_date).
  - Combined slate / web tickets refresh after tennis; pipeline push publishes JSON.
  - First full multi-sport daily is at 5:00 AM (run_daily_5am.ps1).
  - 7:00 AM is a line-move update refresh (run_daily_7am.ps1 → run_refresh_with_log).

  Register via scripts\Register_Daily_Task.ps1 (task: PropOracle - Tennis Early 3AM).
#>
param()

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$Pipeline = Join-Path $Root "run_pipeline.ps1"
$Snapshot = Join-Path $Root "scripts\log_prop_snapshot.ps1"

if (-not (Test-Path $Pipeline)) {
    Write-Error "Missing pipeline script: $Pipeline"
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

function Get-PropOracleEasternTodayYmd {
    try {
        return [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(
            (Get-Date), 'Eastern Standard Time'
        ).ToString('yyyy-MM-dd')
    } catch {
        return (Get-Date).ToString('yyyy-MM-dd')
    }
}

# Prefer main worktree when this checkout is a feature branch.
$branch = (git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
$mainWt = Get-MainWorktreeRoot
if ($branch -ne "main") {
    if ($mainWt -and (Test-Path -LiteralPath (Join-Path $mainWt "run_pipeline.ps1"))) {
        Write-Host "[3AM TENNIS] On '$branch' — running inside main worktree: $mainWt" -ForegroundColor Yellow
        $Root = $mainWt
        $Pipeline = Join-Path $Root "run_pipeline.ps1"
        $Snapshot = Join-Path $Root "scripts\log_prop_snapshot.ps1"
        Set-Location $Root
    }
    else {
        Write-Host "[3AM TENNIS] On '$branch' — switching to main for Railway freshness..." -ForegroundColor Yellow
        git checkout main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[3AM TENNIS] FAILED: cannot checkout main. Abort." -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host "[3AM TENNIS] Pulling latest repository (main)..." -ForegroundColor Cyan
git pull --ff-only origin main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Write-Host "[3AM TENNIS] git pull failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

$Today = Get-PropOracleEasternTodayYmd
Write-Host "[3AM TENNIS] Light TennisOnly for Date=$Today TennisDate=$Today (same-day board)" -ForegroundColor Cyan

if (Test-Path $Snapshot) {
    & pwsh -NoProfile -File $Snapshot -Label "3AM TENNIS PRE" -WriteState
}

& pwsh -NoProfile -File $Pipeline -Date $Today -TennisDate $Today -TennisOnly -SkipDailyGrader
$pipeExit = $LASTEXITCODE

if (Test-Path $Snapshot) {
    & pwsh -NoProfile -File $Snapshot -Label "3AM TENNIS POST" -CompareToState -WriteState
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[3AM TENNIS] Snapshot logging failed" -ForegroundColor Yellow
    }
}

if ($pipeExit -ne 0) {
    Write-Host "[3AM TENNIS] run_pipeline -TennisOnly failed (exit $pipeExit)" -ForegroundColor Red
    exit $pipeExit
}

Write-Host "[3AM TENNIS] Complete" -ForegroundColor Green
exit 0
