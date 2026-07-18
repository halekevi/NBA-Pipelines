#requires -Version 5.1
<#
  Line-move refresh (scheduled 8 AM update, 9 AM, 11 AM, 1 PM).
  - log_prop_snapshot PRE/POST captures added/removed props vs prior state
  - run_nba_late_fetch -NoOverwrite appends step1 CSV rows and backs up prior
    combined slate / ticket_eval before rerun so line movement is visible
  - After rebuild: incremental payout UPDATE only (slips missing live_cdp);
    MAIN full scrape is PropOracle - Payout CDP @ 11:00 (after 10:30 line-move refresh)
  First full multi-sport fetch of the day is PropOracle - Daily 5AM (run_daily_5am.ps1).
  Refresh cadence: 8 / 9 / 10:30 / 1.
#>
param(
    [string]$RunLabel = "9AM"
)

$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Refresh $RunLabel" } catch { }
$Root = Split-Path $PSScriptRoot -Parent
$LateFetch = Join-Path $Root "scripts\run_nba_late_fetch.ps1"
$Snapshot = Join-Path $Root "scripts\log_prop_snapshot.ps1"
$LockDir = Join-Path $Root "data\cache"
$LockFile = Join-Path $LockDir "refresh.lock"
$LockTTLHours = 4

if (-not (Test-Path $LateFetch)) {
    Write-Error "Missing late fetch script: $LateFetch"
    exit 1
}
if (-not (Test-Path $Snapshot)) {
    Write-Error "Missing prop snapshot script: $Snapshot"
    exit 1
}

if (-not (Test-Path -LiteralPath $LockDir)) {
    New-Item -ItemType Directory -Path $LockDir -Force | Out-Null
}

if (Test-Path -LiteralPath $LockFile) {
    $lockAge = (Get-Date) - (Get-Item -LiteralPath $LockFile).LastWriteTime
    if ($lockAge.TotalHours -lt $LockTTLHours) {
        $lockContent = (Get-Content -LiteralPath $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if (-not $lockContent) { $lockContent = "<unknown owner>" }
        Write-Host "[REFRESH $RunLabel] SKIP — another refresh is running ($lockContent)" -ForegroundColor Yellow
        Write-Host "[REFRESH $RunLabel] Lock age: $([int]$lockAge.TotalMinutes) min (TTL: $($LockTTLHours * 60) min)" -ForegroundColor Yellow
        exit 0
    }
    else {
        Write-Host "[REFRESH $RunLabel] Stale lock detected ($([int]$lockAge.TotalHours)h old) — clearing" -ForegroundColor Yellow
        Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
    }
}

$lockContent = "$RunLabel | PID $PID | $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Set-Content -LiteralPath $LockFile -Value $lockContent
Write-Host "[REFRESH $RunLabel] Lock acquired: $lockContent" -ForegroundColor DarkGray

$scriptExit = 0
try {
    Set-Location $Root
    Write-Host "[REFRESH $RunLabel] Starting $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan

    & pwsh -NoProfile -File $Snapshot -Label "$RunLabel PRE" -WriteState
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[REFRESH $RunLabel] PRE snapshot logging failed (continuing)" -ForegroundColor Yellow
    }

    & pwsh -NoProfile -File $LateFetch -NoOverwrite -RunLabel $RunLabel
    $refreshExit = $LASTEXITCODE

    & pwsh -NoProfile -File $Snapshot -Label "$RunLabel POST" -CompareToState -WriteState
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[REFRESH $RunLabel] POST snapshot logging failed" -ForegroundColor Yellow
    }

    if ($refreshExit -ne 0) {
        Write-Host "[REFRESH $RunLabel] Refresh failed (exit $refreshExit)" -ForegroundColor Red
        $scriptExit = $refreshExit
    }
    else {
        Write-Host "[REFRESH $RunLabel] Complete" -ForegroundColor Green
    }
}
finally {
    if (Test-Path -LiteralPath $LockFile) {
        $currentLock = (Get-Content -LiteralPath $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ("$currentLock" -like "*PID $PID*") {
            Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
            Write-Host "[REFRESH $RunLabel] Lock released" -ForegroundColor DarkGray
        }
    }
}

exit $scriptExit
