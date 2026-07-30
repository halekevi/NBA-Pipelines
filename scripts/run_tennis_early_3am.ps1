#requires -Version 5.1
<#
.SYNOPSIS
  3:00 AM ET light tennis fetch only (pre-tip data for ~4:00–5:30 AM matches).

.DESCRIPTION
  - Pulls latest main (Railway tracks origin/main).
  - Runs run_pipeline.ps1 -TennisOnly -SkipCombined -SkipPush for Eastern today.
  - Does NOT rebuild/publish tickets_latest — that used to stomp the overnight board
    before Daily 5AM owned the full multi-sport publish.
  - First full multi-sport daily is at 5:00 AM (run_daily_5am.ps1).
  - Overnight graders: midnight + 1AM only (no 7PM–11PM).

  Register via scripts\Register_Daily_Task.ps1 (task: PropOracle - Tennis Early 3AM).
#>
param()

$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Tennis Early 3AM" } catch { }
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
        Write-Host "[3AM TENNIS] On '$branch' - running inside main worktree: $mainWt" -ForegroundColor Yellow
        $Root = $mainWt
        $Pipeline = Join-Path $Root "run_pipeline.ps1"
        $Snapshot = Join-Path $Root "scripts\log_prop_snapshot.ps1"
        Set-Location $Root
    }
    else {
        Write-Host "[3AM TENNIS] On '$branch' - switching to main for Railway freshness..." -ForegroundColor Yellow
        git checkout main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[3AM TENNIS] FAILED: cannot checkout main. Abort." -ForegroundColor Red
            exit 1
        }
    }
}

$LogsDir = Join-Path $Root "logs"
if (-not (Test-Path -LiteralPath $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}
$WrapperLog = Join-Path $LogsDir ("task_3am_{0:yyyy-MM-dd_HHmmss}.log" -f (Get-Date))
try { Start-Transcript -Path $WrapperLog -Append | Out-Null } catch { }

Write-Host "[3AM TENNIS] Pulling latest repository (main)..." -ForegroundColor Cyan
# Same permanent fix as 5AM/8AM: never abort the run for generated publish JSON.
$EnsurePull = Join-Path $PSScriptRoot "Ensure-CleanPull.ps1"
if (-not (Test-Path -LiteralPath $EnsurePull)) {
    $EnsurePull = Join-Path $Root "scripts\Ensure-CleanPull.ps1"
}
& pwsh -NoProfile -File $EnsurePull -RepoRoot $Root -Label "[3AM TENNIS]" -StashMessage ("proporacle-3am-pre-pull-{0:yyyyMMdd_HHmmss}" -f (Get-Date))
$pullPrepExit = $LASTEXITCODE
if ($pullPrepExit -eq 2) {
    Write-Host "[3AM TENNIS] FAILED: source-code conflicts block pull (resolve manually)." -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit 128
}
if ($pullPrepExit -ne 0) {
    Write-Host "[3AM TENNIS] Pull prep warned (exit $pullPrepExit); continuing with local tree." -ForegroundColor Yellow
}

$Today = Get-PropOracleEasternTodayYmd
Write-Host "[3AM TENNIS] Tennis fetch only Date=$Today TennisDate=$Today (SkipCombined/SkipPush — 5AM publishes board)" -ForegroundColor Cyan

if (Test-Path $Snapshot) {
    & pwsh -NoProfile -File $Snapshot -Label "3AM TENNIS PRE" -WriteState
}

# Fetch + build tennis step8 for early tips, but do not rewrite tickets_latest / git push.
& pwsh -NoProfile -File $Pipeline -Date $Today -TennisDate $Today -TennisOnly -SkipCombined -SkipPush -SkipDailyGrader
$pipeExit = $LASTEXITCODE

if (Test-Path $Snapshot) {
    & pwsh -NoProfile -File $Snapshot -Label "3AM TENNIS POST" -CompareToState -WriteState
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[3AM TENNIS] Snapshot logging failed" -ForegroundColor Yellow
    }
}

if ($pipeExit -ne 0) {
    Write-Host "[3AM TENNIS] run_pipeline -TennisOnly failed (exit $pipeExit)" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit $pipeExit
}

Write-Host "[3AM TENNIS] Complete (tennis data only; board publish deferred to 5AM)" -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch { }
exit 0
