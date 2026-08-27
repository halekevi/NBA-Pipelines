#requires -Version 5.1
<#
  Line-move refresh (8 AM primary lock, 9:00, 9:45, 10:30, 1 PM, 4:30 PM).
  - log_prop_snapshot PRE/POST captures added/removed props vs prior state
  - run_nba_late_fetch -NoOverwrite appends step1 CSV rows and backs up prior
    combined slate / ticket_eval before rerun so line movement is visible
  - After rebuild: Force CDP payout scrape, rebuild Goblin-70 + patch mixer legs
    from this fetch, then Publish-LiveSite.ps1 so Railway / GitHub raw tickets
    match the new lines (not the 1AM board).
  First full multi-sport fetch of the day is PropOracle - Daily 1AM (run_daily_1am.ps1).
  Refresh cadence: 8 / 9 / 9:45 / 10:30 / 1 / 4:30.
#>
param(
    [string]$RunLabel = "945AM"
)

$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Refresh $RunLabel" } catch { }
$Root = Split-Path $PSScriptRoot -Parent
$LateFetch = Join-Path $Root "scripts\run_nba_late_fetch.ps1"
$Snapshot = Join-Path $Root "scripts\log_prop_snapshot.ps1"
$LockDir = Join-Path $Root "data\cache"
$LockFile = Join-Path $LockDir "refresh.lock"
# Soft TTL: dead/hung holders must not block the rest of the day's cadence.
# Previously a 4h TTL + exit 0 on skip made 10:30 look "successful" while 9AM was hung.
$LockTTLMinutes = 90

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

function Test-TodaySlateNeedsCatchup {
    $today = (Get-Date).ToString("yyyy-MM-dd")
    try {
        $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
        $etNow = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz)
        if ($etNow.Hour -ge 20) {
            $today = $etNow.Date.AddDays(1).ToString("yyyy-MM-dd")
        }
        else {
            $today = $etNow.ToString("yyyy-MM-dd")
        }
    } catch { }
    $combined = Join-Path $Root "outputs\$today\combined_slate_tickets_$today.xlsx"
    if (-not (Test-Path -LiteralPath $combined)) { return $true }
    $statusPath = Join-Path $Root "outputs\$today\pipeline_slate_status.json"
    if (-not (Test-Path -LiteralPath $statusPath)) { return $true }
    try {
        $ss = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
        $complete = 0
        $active = @("mlb", "soccer", "tennis")
        $wnbaResume = "2026-07-28"
        if ($env:WNBA_RESUME_DATE) { $wnbaResume = $env:WNBA_RESUME_DATE.Trim() }
        $wnbaPause = "2026-07-19"
        if ($env:WNBA_PAUSE_START) { $wnbaPause = $env:WNBA_PAUSE_START.Trim() }
        if (-not (($today -ge $wnbaPause) -and ($today -lt $wnbaResume))) {
            $active = @("mlb", "wnba", "soccer", "tennis")
        }
        foreach ($sk in $active) {
            $st = if ($ss.sports) { "$($ss.sports.$sk)" } else { "" }
            if ($st -eq "complete" -or $st -eq "off_season") { $complete++ }
        }
        # Any in-season sport still empty/pending (incl. no_slate) means 8AM should keep going.
        return ($complete -lt $active.Count)
    } catch {
        return $true
    }
}

if (Test-Path -LiteralPath $LockFile) {
    $lockAge = (Get-Date) - (Get-Item -LiteralPath $LockFile).LastWriteTime
    $lockContent = (Get-Content -LiteralPath $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $lockContent) { $lockContent = "<unknown owner>" }
    $lockPid = $null
    if ("$lockContent" -match 'PID\s+(\d+)') { $lockPid = [int]$Matches[1] }
    $lockPidAlive = $false
    if ($lockPid) {
        $lockPidAlive = $null -ne (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)
    }

    $staleByAge = ($lockAge.TotalMinutes -ge $LockTTLMinutes)
    $staleByDeadPid = ($lockPid -and -not $lockPidAlive)
    # Never steal a live owner — 8AM often runs past 90 min. TTL only applies when PID is dead/unknown.
    if ($lockPidAlive) {
        $needsCatchup = Test-TodaySlateNeedsCatchup
        Write-Host "[REFRESH $RunLabel] SKIP — another refresh is running ($lockContent)" -ForegroundColor Yellow
        Write-Host "[REFRESH $RunLabel] Lock age: $([int]$lockAge.TotalMinutes) min (TTL: $LockTTLMinutes min, live PID kept)" -ForegroundColor Yellow
        if ($needsCatchup) {
            # Non-zero so Task Scheduler LastResult is not a false success when the day is still empty.
            Write-Host "[REFRESH $RunLabel] Today's slate still incomplete — exit 2 (not a soft success)" -ForegroundColor Yellow
            exit 2
        }
        exit 0
    }
    elseif ($staleByAge -or $staleByDeadPid) {
        $why = if ($staleByDeadPid) { "owner PID $lockPid not running" } else { "$([int]$lockAge.TotalMinutes) min old (TTL $LockTTLMinutes)" }
        Write-Host "[REFRESH $RunLabel] Stale lock detected ($why) — clearing" -ForegroundColor Yellow
        Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
    }
    else {
        Write-Host "[REFRESH $RunLabel] Orphan lock without live PID — clearing" -ForegroundColor Yellow
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
        $todayEt = (Get-Date).ToString("yyyy-MM-dd")
        try {
            $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
            $todayEt = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz).ToString("yyyy-MM-dd")
        } catch { }
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
        # Pipeline push happens before CDP payout scrape. Always publish after
        # late_fetch so Railway / GitHub raw tickets match this refresh.
        $publish = Join-Path $Root "scripts\Publish-LiveSite.ps1"
        if (-not (Test-Path -LiteralPath $publish)) {
            $hit = Get-ChildItem -LiteralPath (Join-Path $Root "scripts") -Filter "Publish*Live*.ps1" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { $publish = $hit.FullName }
        }
        if (Test-Path -LiteralPath $publish) {
            Write-Host "[REFRESH $RunLabel] Publishing live site JSON to origin/main..." -ForegroundColor Cyan
            & pwsh -NoProfile -File $publish -RepoRoot $Root -CommitMessage "chore: live tickets/slate $todayEt $RunLabel"
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[REFRESH $RunLabel] LIVE SITE PUBLISH FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
                if ($scriptExit -eq 0) { $scriptExit = $LASTEXITCODE }
            }
        }
        else {
            Write-Host "[REFRESH $RunLabel] WARN: Publish-LiveSite.ps1 missing — site may stay on prior board" -ForegroundColor Yellow
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
