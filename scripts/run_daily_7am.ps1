#requires -Version 5.1
param()

$ErrorActionPreference = "Continue"
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
        Write-Host "[7AM DAILY] On '$branch' — running daily inside main worktree: $mainWt" -ForegroundColor Yellow
        $Root = $mainWt
        $Daily = Join-Path $Root "scripts\run_daily.ps1"
        $Snapshot = Join-Path $Root "scripts\log_prop_snapshot.ps1"
        Set-Location $Root
    }
    else {
        Write-Host "[7AM DAILY] On '$branch' — switching to main for Railway freshness..." -ForegroundColor Yellow
        git checkout main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[7AM DAILY] FAILED: cannot checkout main (locked by another worktree or WIP). Abort." -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host "[7AM DAILY] Pulling latest repository (main)..." -ForegroundColor Cyan
git pull --ff-only origin main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Write-Host "[7AM DAILY] git pull failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "[7AM DAILY] Running run_daily.ps1 (-SkipGrader)..." -ForegroundColor Cyan
& pwsh -NoProfile -File $Daily -SkipGrader
$dailyExit = $LASTEXITCODE

Write-Host "[7AM DAILY] Logging fetched prop snapshot..." -ForegroundColor Cyan
& pwsh -NoProfile -File $Snapshot -Label "7AM DAILY POST" -CompareToState -WriteState
if ($LASTEXITCODE -ne 0) {
    Write-Host "[7AM DAILY] Snapshot logging failed" -ForegroundColor Yellow
}

if ($dailyExit -ne 0) {
    Write-Host "[7AM DAILY] run_daily failed (exit $dailyExit)" -ForegroundColor Red
    exit $dailyExit
}

Write-Host "[7AM DAILY] Complete" -ForegroundColor Green
exit 0
