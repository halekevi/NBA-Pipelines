#requires -Version 5.1
<#
.SYNOPSIS
  Scheduled 5:00 AM full daily: git pull main, run_daily.ps1 (grade yesterday + today's pipeline), prop snapshot.

.NOTES
  First big multi-sport run of the day. Publishes fresh slate_latest / tickets for the home page.
  Live PrizePicks CDP payout is NOT in this job — see PropOracle - Payout CDP (run_payout_cdp.ps1 @ 11:00 after 10:30 refresh).
  Refresh cadence: 8 / 9 / 10:30 / 1 (PP line moves often hit ~10:30–11).
  3:00 AM remains light TennisOnly.
  Registered by scripts\Register_Daily_Task.ps1 as "PropOracle - Daily 5AM".
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
# Dirty main worktree is common; stash so ff-only pull can proceed (STEP E does the same).
# Never leave the tree in an unmerged state: abort if already conflicted, and only
# stash-pop AFTER a successful pull. Stash-pop conflicts keep the stash and exit.
$unmergedBefore = @(git ls-files -u 2>$null)
if ($unmergedBefore.Count -gt 0) {
    Write-Host "[5AM DAILY] FAILED: unmerged paths block pull (resolve or reset first)." -ForegroundColor Red
    $unmergedBefore | Select-Object -First 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    try { Stop-Transcript | Out-Null } catch { }
    exit 128
}
$stashOut = git stash push -u -m "proporacle-5am-pre-pull-$(Get-Date -Format 'yyyyMMdd_HHmmss')" 2>&1
$stashOut | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
$didStash = ("$stashOut" -notmatch 'No local changes to save')
git pull --ff-only origin main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
$pullExit = $LASTEXITCODE
if ($pullExit -ne 0) {
    Write-Host "[5AM DAILY] git pull failed (exit $pullExit); leaving pre-pull stash (if any) intact." -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit $pullExit
}
if ($didStash) {
    git stash pop 2>&1 | ForEach-Object { Write-Host "    stash pop: $_" -ForegroundColor DarkGray }
    $popExit = $LASTEXITCODE
    $unmergedAfter = @(git ls-files -u 2>$null)
    if ($popExit -ne 0 -or $unmergedAfter.Count -gt 0) {
        Write-Host "[5AM DAILY] FAILED: stash pop left conflicts; aborting before daily (stash kept)." -ForegroundColor Red
        $unmergedAfter | Select-Object -First 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        try { Stop-Transcript | Out-Null } catch { }
        exit 128
    }
}

Write-Host "[5AM DAILY] Running full run_daily.ps1 (includes grader)..." -ForegroundColor Cyan
& pwsh -NoProfile -File $Daily
$dailyExit = $LASTEXITCODE

Write-Host "[5AM DAILY] Logging fetched prop snapshot..." -ForegroundColor Cyan
& pwsh -NoProfile -File $Snapshot -Label "5AM DAILY POST" -CompareToState -WriteState
if ($LASTEXITCODE -ne 0) {
    Write-Host "[5AM DAILY] Snapshot logging failed" -ForegroundColor Yellow
}

if ($dailyExit -ne 0) {
    Write-Host "[5AM DAILY] run_daily failed (exit $dailyExit)" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit $dailyExit
}

Write-Host "[5AM DAILY] Complete" -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch { }
exit 0
