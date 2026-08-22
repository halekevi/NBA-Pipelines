#requires -Version 5.1
<#
  Mid-day line-move refresh (scheduled 9 AM, 10:30 AM, 1 PM ET).
  - log_prop_snapshot PRE/POST captures added/removed props vs prior state
  - run_nba_late_fetch -NoOverwrite appends step1 CSV rows and backs up prior
    combined slate / ticket_eval before rerun so line movement is visible
  - After rebuild: incremental payout UPDATE only (slips missing live_cdp);
    MAIN full scrape stays on 5AM STEP D-payout
  First full multi-sport fetch of the day is PropOracle - Daily 5AM (run_daily_5am.ps1).
#>
param(
    [string]$RunLabel = "9AM"
)

$ErrorActionPreference = "Continue"
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

    # Slim Standard-line archive + website timing card (keeps history without relying on bak xlsx).
    $LineSnap = Join-Path $Root "scripts\snapshot_pp_standard_lines.py"
    $LinePublish = Join-Path $Root "scripts\publish_line_move_timing.py"
    if ((Test-Path -LiteralPath $LineSnap) -and $refreshExit -eq 0) {
        $snapDate = (Get-Date).ToString("yyyy-MM-dd")
        try {
            $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
            $etNow = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz)
            if ($etNow.Hour -ge 20) {
                $snapDate = $etNow.Date.AddDays(1).ToString("yyyy-MM-dd")
            } else {
                $snapDate = $etNow.ToString("yyyy-MM-dd")
            }
        } catch { }
        Write-Host "[REFRESH $RunLabel] Snapshot Standard lines ($snapDate / $RunLabel)..." -ForegroundColor DarkGray
        & py -3.14 -X utf8 $LineSnap --date $snapDate --label $RunLabel
        if (Test-Path -LiteralPath $LinePublish) {
            & py -3.14 -X utf8 $LinePublish
        }
    }

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
        $todayEt = (Get-Date).ToString("yyyy-MM-dd")
        try {
            $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
            $todayEt = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz).ToString("yyyy-MM-dd")
        } catch { }
        $assertScript = Join-Path $Root "scripts\assert_live_board_sync.py"
        $pushScript = Join-Path $Root "scripts\push_live_to_main.ps1"
        if ((Test-Path -LiteralPath $assertScript) -and (Test-Path -LiteralPath $pushScript)) {
            Write-Host "[REFRESH $RunLabel] Publishing live tickets/slate if dates match ($todayEt)..." -ForegroundColor Cyan
            & py -3.14 -X utf8 $assertScript --today $todayEt --templates-dir (Join-Path $Root "ui_runner\templates")
            if ($LASTEXITCODE -eq 0) {
                & pwsh -NoProfile -File $pushScript -CommitMessage "chore: $RunLabel live tickets/slate $todayEt [auto]"
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "[REFRESH $RunLabel] WARN: push_live_to_main exit $LASTEXITCODE (Railway may stay on prior board)" -ForegroundColor Yellow
                    $scriptExit = $LASTEXITCODE
                }
            } else {
                Write-Host "[REFRESH $RunLabel] SKIP push — tickets_latest lags slate_latest. Combined --write-web must finish first." -ForegroundColor Yellow
            }
        }
        $assertFresh = Join-Path $Root "scripts\Assert-ActiveSportsFresh.ps1"
        if (Test-Path -LiteralPath $assertFresh) {
            $freshJson = Join-Path $Root "logs\LAST_ACTIVE_SPORTS_FRESH.json"
            Write-Host "[REFRESH $RunLabel] Asserting active sports FRESH..." -ForegroundColor Cyan
            & pwsh -NoProfile -File $assertFresh -RepoRoot $Root -Today $todayEt -JsonOut $freshJson
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[REFRESH $RunLabel] ACTIVE SPORTS FRESHNESS GATE FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
                $scriptExit = $LASTEXITCODE
            }
        }
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
