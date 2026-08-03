#requires -Version 5.1
<#
.SYNOPSIS
  Scheduled 8:00 AM line-move update: git pull main, then mid-day-style refresh.

.NOTES
  First full multi-sport fetch is PropOracle - Daily 5AM (run_daily_5am.ps1).
  This task mirrors 9AM / 11AM / 1PM via run_refresh_with_log.ps1 → run_nba_late_fetch.ps1.
  Scheduled at 8:00 (was 7:00) so the 5AM full daily usually finishes first.
  Registered by scripts\Register_Daily_Task.ps1 as "PropOracle - Daily 8AM".
#>
param()

$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Daily 8AM" } catch { }
$Root = Split-Path $PSScriptRoot -Parent
$Refresh = Join-Path $Root "scripts\run_refresh_with_log.ps1"

if (-not (Test-Path $Refresh)) {
    Write-Error "Missing refresh script: $Refresh"
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

# Railway tracks origin/main. Prefer running refresh on the main worktree when this
# checkout is a feature branch (main may already be locked in PropORACLE_main_cp).
$branch = (git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
$mainWt = Get-MainWorktreeRoot
if ($branch -ne "main") {
    if ($mainWt -and (Test-Path -LiteralPath (Join-Path $mainWt "scripts\run_refresh_with_log.ps1"))) {
        Write-Host "[8AM UPDATE] On '$branch' - running refresh inside main worktree: $mainWt" -ForegroundColor Yellow
        $Root = $mainWt
        $Refresh = Join-Path $Root "scripts\run_refresh_with_log.ps1"
        Set-Location $Root
    }
    else {
        Write-Host "[8AM UPDATE] On '$branch' - switching to main for Railway freshness..." -ForegroundColor Yellow
        git checkout main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[8AM UPDATE] FAILED: cannot checkout main (locked by another worktree or WIP). Abort." -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host "[8AM UPDATE] Pulling latest repository (main)..." -ForegroundColor Cyan
# Same permanent fix as 5AM/8AM: never abort the run for generated publish JSON.
$EnsurePull = Join-Path $PSScriptRoot "Ensure-CleanPull.ps1"
if (-not (Test-Path -LiteralPath $EnsurePull)) {
    $EnsurePull = Join-Path $Root "scripts\Ensure-CleanPull.ps1"
}
& pwsh -NoProfile -File $EnsurePull -RepoRoot $Root -Label "[8AM UPDATE]" -StashMessage ("proporacle-8am-pre-pull-{0:yyyyMMdd_HHmmss}" -f (Get-Date))
$pullPrepExit = $LASTEXITCODE
if ($pullPrepExit -eq 2) {
    Write-Host "[8AM UPDATE] FAILED: source-code conflicts block pull (resolve manually)." -ForegroundColor Red
    exit 128
}
if ($pullPrepExit -ne 0) {
    Write-Host "[8AM UPDATE] Pull prep warned (exit $pullPrepExit); continuing with local tree." -ForegroundColor Yellow
}

Write-Host "[8AM UPDATE] Running line-move refresh (RunLabel 8AM)..." -ForegroundColor Cyan
& pwsh -NoProfile -File $Refresh -RunLabel "8AM"
$refreshExit = $LASTEXITCODE

if ($refreshExit -ne 0) {
    Write-Host "[8AM UPDATE] Refresh failed (exit $refreshExit)" -ForegroundColor Red
    exit $refreshExit
}

Write-Host "[8AM UPDATE] Complete" -ForegroundColor Green
exit 0
