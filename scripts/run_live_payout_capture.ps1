#requires -Version 7.2
# ============================================================
#  Live PrizePicks payout capture (post-ticket step)
#
#  Two-tier model:
#    MAIN (PropOracle - Payout CDP @ 10:00): scrape all MAIN/STRONG slips missing live floors,
#      then verify + rebuild rate card (-FillMissingTickets -RebuildRateCard).
#    UPDATE (midday / manual default): same script, but only slips still missing
#      payout_source=live_cdp (--only-missing-live). If fingerprint unchanged and
#      everything already live_cdp → CDP skipped (seconds). Pass -Force only to
#      re-scrape slips that already have live floors.
#    5AM daily does NOT run live CDP by default (pass -RunLivePayout to opt in).
#
#  Steps:
#    1) CDP scrape of generated MAIN/STRONG slips → power_min_x
#    2) Write payout_patch_<date>.json + write-back display_min_x
#    3) Verify outstanding floors + mix/Δ (optional fill / rate-card rebuild)
#    Optional: -IncludeMixGrid for once/day calibration (separate from tickets)
#
#  Usage:
#    .\scripts\run_live_payout_capture.ps1 -Date 2026-07-12                    # update
#    .\scripts\run_live_payout_capture.ps1 -Date 2026-07-12 -UpdateOnly         # same, explicit
#    .\scripts\run_live_payout_capture.ps1 -Date 2026-07-12 -Force              # full re-scrape
#    .\scripts\run_live_payout_capture.ps1 -Date 2026-07-12 -IncludeMixGrid
#    .\scripts\run_live_payout_capture.ps1 -Date 2026-07-12 -FillMissingTickets -RebuildRateCard  # main
#
#  Exit codes:
#    0  = capture attempted (ok or soft-fail / CDP skip / lock held)
#    1  = hard error (script missing, etc.)
#
#  Single-flight lock prevents dual scrapers. Midday UPDATE bails if MAIN is running.
# ============================================================
param(
    [Parameter(Mandatory = $false)]
    [string]$Date = "",
    [string]$Root = "",
    [string]$TicketsPath = "",
    [string]$CdpUrl = "http://127.0.0.1:9222",
    # Post-ticket default: scrape ONLY generated MAIN/STRONG slips (no mix-grid board crawl).
    [switch]$IncludeMixGrid,
    [switch]$SkipMixGrid,
    [switch]$NoWriteBack,
    [switch]$Force,
    # Explicit incremental mode (default behavior without -Force). Skips mix-grid.
    [switch]$UpdateOnly,
    # Default: exact line+Goblin only. Pass -AllowLineFallback to price moved proxies.
    [switch]$AllowLineFallback,
    # After capture: audit + optionally fill still-missing live floors / rebuild rate card.
    [switch]$SkipVerify,
    [switch]$FillMissingTickets,
    [switch]$RebuildRateCard,
    [switch]$Gentle,
    # Wall-clock budget for the CDP scrape (minutes). 0 = auto (25 MAIN / 15 UPDATE).
    [int]$MaxRuntimeMinutes = 0
)

$ErrorActionPreference = "Continue"
if (-not $Root) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
    if (-not (Test-Path (Join-Path $Root "scripts\collect_payout_data.py"))) {
        $Root = (Get-Location).Path
    }
}
if (-not $Date) {
    $Date = (Get-Date).ToString("yyyy-MM-dd")
}
$Date = $Date.Substring(0, [Math]::Min(10, $Date.Length))

$payoutScript = Join-Path $Root "scripts\collect_payout_data.py"
$payoutOut = Join-Path $Root "data\reports\payout_capture_$Date.json"
$mixGridOut = Join-Path $Root "data\reports\payout_mix_grid_$Date.json"
$rateCardOut = Join-Path $Root "data\reports\payout_rate_card.json"
$ticketsLatest = Join-Path $Root "ui_runner\templates\tickets_latest.json"
$mobileTickets = Join-Path $Root "mobile\www\tickets_latest.json"
$verifyScript = Join-Path $Root "scripts\verify_ticket_payout_rates.py"
$lockDir = Join-Path $Root "data\cache"
$lockFile = Join-Path $lockDir "payout_capture.lock"
$lockTtlHours = 2
$script:PayoutLockHeld = $false

# -UpdateOnly = incremental (never Force / never mix-grid). Apply before lock so we
# do not clear another job's lock with -Force.
if ($UpdateOnly) {
    $SkipMixGrid = $true
    if ($Force) {
        Write-Host "  [PAYOUT] -UpdateOnly ignores -Force (incremental only)" -ForegroundColor Yellow
        $Force = $false
    }
}

if ($MaxRuntimeMinutes -le 0) {
    # MAIN (fill/rebuild) gets a longer budget; midday UPDATE stays shorter.
    if ($FillMissingTickets -or $Force) { $MaxRuntimeMinutes = 25 }
    else { $MaxRuntimeMinutes = 15 }
}

function Clear-PayoutCaptureLock {
    if ($script:PayoutLockHeld -and (Test-Path -LiteralPath $lockFile)) {
        Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
        $script:PayoutLockHeld = $false
    }
}

function Test-PayoutLockOwnerAlive {
    param([string]$LockContent)
    if ($LockContent -match 'PID\s+(\d+)') {
        $lockPid = [int]$Matches[1]
        try {
            $null = Get-Process -Id $lockPid -ErrorAction Stop
            return $true
        } catch {
            return $false
        }
    }
    return $true
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    try {
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-ProcessTree -ProcessId ([int]$_.ProcessId) }
    } catch { }
    try { Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue } catch { }
}

function Invoke-PyWithTimeout {
    param(
        [string[]]$ArgumentList,
        [int]$TimeoutSec,
        [string]$Label = "py"
    )
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        Write-Host "  [PAYOUT] ERROR: py launcher not found" -ForegroundColor Red
        return 1
    }
    $stdout = Join-Path $env:TEMP ("proporacle_payout_{0}_{1}.out.txt" -f $PID, [guid]::NewGuid().ToString("n").Substring(0, 8))
    $stderr = Join-Path $env:TEMP ("proporacle_payout_{0}_{1}.err.txt" -f $PID, [guid]::NewGuid().ToString("n").Substring(0, 8))
    $proc = Start-Process -FilePath $pyCmd.Source `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $Root `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr
    $finished = $proc.WaitForExit([Math]::Max(1, $TimeoutSec) * 1000)
    if (-not $finished) {
        Write-Host "  [PAYOUT] TIMEOUT after ${TimeoutSec}s ($Label) — killing scrape so daily can continue" -ForegroundColor Yellow
        Stop-ProcessTree -ProcessId $proc.Id
        try { $proc.WaitForExit(5000) | Out-Null } catch { }
        if (Test-Path -LiteralPath $stdout) {
            Get-Content -LiteralPath $stdout -Tail 40 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        }
        if (Test-Path -LiteralPath $stderr) {
            Get-Content -LiteralPath $stderr -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ -ForegroundColor DarkYellow }
        }
        Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
        return 124
    }
    if (Test-Path -LiteralPath $stdout) {
        Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    }
    if (Test-Path -LiteralPath $stderr) {
        Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ -ForegroundColor DarkYellow }
    }
    $code = $proc.ExitCode
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    return $code
}

if (-not (Test-Path -LiteralPath $lockDir)) {
    New-Item -ItemType Directory -Path $lockDir -Force | Out-Null
}
if (Test-Path -LiteralPath $lockFile) {
    $lockAge = (Get-Date) - (Get-Item -LiteralPath $lockFile).LastWriteTime
    $lockContent = (Get-Content -LiteralPath $lockFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $lockContent) { $lockContent = "<unknown>" }
    $ownerAlive = Test-PayoutLockOwnerAlive -LockContent $lockContent
    if (-not $ownerAlive) {
        Write-Host "  [PAYOUT] Clearing dead lock (owner PID gone): $lockContent" -ForegroundColor Yellow
        Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
    } elseif ($lockAge.TotalHours -lt $lockTtlHours -and -not $Force) {
        Write-Host "  [PAYOUT] SKIP — another capture is running ($lockContent)" -ForegroundColor Yellow
        Write-Host "  [PAYOUT] Lock age: $([int]$lockAge.TotalMinutes) min (TTL $($lockTtlHours)h). Pass -Force only to clear a dead lock." -ForegroundColor Yellow
        exit 0
    } else {
        Write-Host "  [PAYOUT] Clearing stale lock ($([int]$lockAge.TotalMinutes) min old)" -ForegroundColor DarkGray
        Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
    }
}
Set-Content -LiteralPath $lockFile -Value ("$Date | PID $PID | $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Root")
$script:PayoutLockHeld = $true
$env:PROPORACLE_PAYOUT_LOCK_HELD = "1"
Write-Host "  [PAYOUT] Lock acquired" -ForegroundColor DarkGray

if (-not $TicketsPath) {
    $TicketsPath = Join-Path $Root "ui_runner\data\combined_slate_tickets_$Date.json"
    if (-not (Test-Path -LiteralPath $TicketsPath)) {
        $alt = Join-Path $Root "outputs\$Date\combined_slate_tickets_$Date.json"
        if (Test-Path -LiteralPath $alt) {
            $TicketsPath = $alt
        } elseif (Test-Path -LiteralPath (Join-Path $Root "ui_runner\templates\tickets_latest.json")) {
            $TicketsPath = Join-Path $Root "ui_runner\templates\tickets_latest.json"
        } elseif (Test-Path -LiteralPath (Join-Path $Root "ui_runner\data\tickets_latest.json")) {
            $TicketsPath = Join-Path $Root "ui_runner\data\tickets_latest.json"
        }
    }
}

function Test-CdpUp {
    param([string]$Url)
    try {
        $base = $Url.TrimEnd("/")
        $null = Invoke-WebRequest -Uri "$base/json/version" -TimeoutSec 2 -ErrorAction Stop
        return $true
    } catch {
        try {
            $null = Invoke-WebRequest -Uri "$base/json" -TimeoutSec 2 -ErrorAction Stop
            return $true
        } catch {
            return $false
        }
    }
}

function Invoke-PayoutVerify {
    param(
        [string]$VerifyRoot,
        [string]$VerifyDate,
        [string]$VerifyTickets,
        [string]$VerifyCdp,
        [bool]$DoFill,
        [bool]$DoRebuild,
        [bool]$DoGentle
    )
    if (-not (Test-Path -LiteralPath $verifyScript)) {
        Write-Host "  [PAYOUT-VERIFY] WARN: verify_ticket_payout_rates.py missing" -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path -LiteralPath $VerifyTickets)) {
        Write-Host "  [PAYOUT-VERIFY] WARN: tickets missing -- $VerifyTickets" -ForegroundColor Yellow
        return
    }
    Write-Host "  [PAYOUT-VERIFY] Auditing ticket floors + outstanding mix/Δ coverage..." -ForegroundColor Cyan
    $verifyArgs = @(
        "-3.14", "-X", "utf8", $verifyScript,
        "--date", $VerifyDate,
        "--tickets", $VerifyTickets,
        "--cdp-url", $VerifyCdp
    )
    if ($DoFill) { $verifyArgs += "--fill-missing-tickets" }
    if ($DoRebuild) { $verifyArgs += "--rebuild-rate-card" }
    if ($DoGentle) { $verifyArgs += "--gentle" }
    Push-Location $VerifyRoot
    try {
        & py @verifyArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [PAYOUT-VERIFY] WARN: verify exit $LASTEXITCODE (non-blocking)" -ForegroundColor Yellow
        } else {
            Write-Host "  [PAYOUT-VERIFY] OK -> data/reports/ticket_payout_verify_$VerifyDate.json" -ForegroundColor Green
        }
    } finally {
        Pop-Location
    }
}

Write-Host ""
$payoutMode = if ($Force) { "MAIN (full re-scrape)" } elseif ($UpdateOnly) { "UPDATE (only-missing)" } else { "UPDATE (only-missing default)" }
Write-Host "[LIVE PAYOUT] $payoutMode — PrizePicks scrape ($Date)" -ForegroundColor Magenta
if (-not (Test-Path -LiteralPath $payoutScript)) {
    Write-Host "  [PAYOUT] ERROR: collect_payout_data.py missing" -ForegroundColor Red
    Clear-PayoutCaptureLock
    exit 1
}

$cdpUp = Test-CdpUp -Url $CdpUrl
if (-not $cdpUp) {
    Write-Host "  [PAYOUT] CDP not running on $CdpUrl -- skip scrape (tickets keep board-avg / rate-card)" -ForegroundColor DarkGray
    # Still audit so daily reports show outstanding gaps.
    if (-not $SkipVerify) {
        Invoke-PayoutVerify -VerifyRoot $Root -VerifyDate $Date -VerifyTickets $TicketsPath `
            -VerifyCdp $CdpUrl -DoFill:$false -DoRebuild:$RebuildRateCard.IsPresent -DoGentle:$false
    }
    Clear-PayoutCaptureLock
    exit 0
}

Push-Location $Root
try {
    $doMixGrid = $IncludeMixGrid -and -not $SkipMixGrid
    if ($doMixGrid -and -not (Test-Path -LiteralPath $mixGridOut)) {
        Write-Host "  [PAYOUT-GRID] Capturing mix-grid calibration -> $mixGridOut" -ForegroundColor Cyan
        & py -3.14 -X utf8 $payoutScript `
            --mix-grid `
            --date $Date `
            --cdp-url $CdpUrl `
            --max-slips 24 `
            --output $mixGridOut
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $mixGridOut)) {
            Write-Host "  [PAYOUT-GRID] OK (rate card -> $rateCardOut)" -ForegroundColor Green
        } else {
            Write-Host "  [PAYOUT-GRID] WARN: mix-grid failed (non-blocking)" -ForegroundColor Yellow
        }
    } elseif ($doMixGrid -and (Test-Path -LiteralPath $mixGridOut)) {
        Write-Host "  [PAYOUT-GRID] already have $mixGridOut -- skip" -ForegroundColor DarkGray
    } else {
        Write-Host "  [PAYOUT] ticket-only mode (generated MAIN/STRONG slips) — mix-grid skipped" -ForegroundColor DarkGray
    }

    if (-not (Test-Path -LiteralPath $TicketsPath)) {
        Write-Host "  [PAYOUT] WARN: tickets JSON missing -- $TicketsPath" -ForegroundColor Yellow
        if (-not $SkipVerify) {
            Invoke-PayoutVerify -VerifyRoot $Root -VerifyDate $Date -VerifyTickets $TicketsPath `
                -VerifyCdp $CdpUrl -DoFill:$false -DoRebuild:$RebuildRateCard.IsPresent -DoGentle:$Gentle.IsPresent
        }
        Clear-PayoutCaptureLock
        exit 0
    }

    $skippedFullCapture = $false
    $onlyMissingLive = $true
    # Skip CDP when ticket set fingerprint is unchanged AND every slip already has live_cdp.
    # Otherwise scrape only slips missing live floors (unless -Force → full re-scrape).
    if (-not $Force) {
        try {
            $checkRaw = & py -3.14 -X utf8 $payoutScript `
                --tickets $TicketsPath `
                --output $payoutOut `
                --date $Date `
                --check-unchanged
            if ($LASTEXITCODE -eq 0 -and $checkRaw) {
                $check = ($checkRaw | Out-String) | ConvertFrom-Json
                $fpShort = ""
                if ($check.fingerprint) { $fpShort = [string]$check.fingerprint; if ($fpShort.Length -gt 12) { $fpShort = $fpShort.Substring(0, 12) } }
                Write-Host ("  [PAYOUT] fingerprint={0} slips={1} missing_live={2} unchanged={3} reason={4}" -f `
                    $fpShort, $check.n_slips, $check.n_missing_live, $check.unchanged, $check.reason) -ForegroundColor DarkGray
                if ($check.skip_scrape -eq $true) {
                    Write-Host "  [PAYOUT] tickets unchanged + all live_cdp -- skip CDP re-fetch (verify may still audit)" -ForegroundColor DarkGray
                    $skippedFullCapture = $true
                }
            }
        } catch {
            Write-Host "  [PAYOUT] WARN: fingerprint check failed ($($_.Exception.Message)); will scrape missing" -ForegroundColor Yellow
        }
    } else {
        $onlyMissingLive = $false
        Write-Host "  [PAYOUT] -Force: full re-scrape (including slips that already have live_cdp)" -ForegroundColor Cyan
    }

    $capExit = 0
    $nOk = 0
    if (-not $skippedFullCapture) {
        $runtimeSec = [Math]::Max(60, $MaxRuntimeMinutes * 60)
        Write-Host "  [PAYOUT] Capturing MAIN/STRONG floors from $TicketsPath (budget ${MaxRuntimeMinutes}m)" -ForegroundColor Cyan
        $ticketArgs = @(
            "-3.14", "-X", "utf8", $payoutScript,
            "--tickets", $TicketsPath,
            "--output", $payoutOut,
            "--date", $Date,
            "--cdp-url", $CdpUrl,
            "--fields", "power_min_x,power_first_x,min_guarantee,flex_min",
            "--max-runtime-sec", "$runtimeSec"
        )
        if ($NoWriteBack) { $ticketArgs += "--no-write-back" }
        if ($AllowLineFallback) { $ticketArgs += "--allow-line-fallback" }
        if ($Gentle) { $ticketArgs += "--gentle" }
        if ($onlyMissingLive) { $ticketArgs += "--only-missing-live" }
        # Soft backstop above Python's own max-runtime so a hung CDP call cannot idle forever.
        $capExit = Invoke-PyWithTimeout -ArgumentList $ticketArgs -TimeoutSec ($runtimeSec + 90) -Label "ticket-capture"

        if (Test-Path -LiteralPath $payoutOut) {
            try {
                $cap = Get-Content -LiteralPath $payoutOut -Raw | ConvertFrom-Json
                if ($null -ne $cap.summary) {
                    $nOk = [int]($cap.summary.n_ok)
                    $nFail = [int]($cap.summary.n_failed)
                    Write-Host "  [PAYOUT] summary ok=$nOk failed=$nFail -> $payoutOut" -ForegroundColor $(if ($nOk -gt 0) { "Green" } else { "Yellow" })
                }
            } catch { }
        }
        if ($capExit -eq 124) {
            Write-Host "  [PAYOUT] WARN: scrape timed out (exit 124) — continuing daily without blocking" -ForegroundColor Yellow
            $capExit = 0
        }

        if ($capExit -eq 0 -and $nOk -gt 0) {
            if ((Test-Path -LiteralPath $ticketsLatest) -and (Test-Path (Split-Path $mobileTickets -Parent))) {
                Copy-Item $ticketsLatest $mobileTickets -Force -ErrorAction SilentlyContinue
                Write-Host "  [PAYOUT] mirrored -> mobile/www/tickets_latest.json" -ForegroundColor Green
            }
            Write-Host "  [PAYOUT] Live floors applied (payout_source=live_cdp on patched slips)" -ForegroundColor Green
            $rateCardsScript = Join-Path $Root "scripts\build_payout_rate_cards.py"
            if (Test-Path -LiteralPath $rateCardsScript) {
                & py -3.14 -X utf8 $rateCardsScript | Out-Host
                Write-Host "  [PAYOUT] rate-cards deck rebuilt -> data/payout_rate_cards.json" -ForegroundColor Green
            }
        } elseif ($capExit -eq 0) {
            Write-Host "  [PAYOUT] WARN: capture finished but 0 live floors (board avg remains)" -ForegroundColor Yellow
        } else {
            Write-Host "  [PAYOUT] WARN: capture exit $capExit (non-blocking)" -ForegroundColor Yellow
        }

        if ($capExit -eq 0 -and (Test-Path -LiteralPath $payoutOut)) {
            try {
                Write-Host "  [PAYOUT] Pruning unplayable slips from live tickets_latest..." -ForegroundColor Cyan
                py -3.14 -X utf8 (Join-Path $Root "scripts\ticket_run_archive.py") `
                    --prune-live --date $Date --capture $payoutOut | Out-Host
            } catch {
                Write-Host "  [PAYOUT] WARN: live prune failed: $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    }

    if (-not $SkipVerify) {
        # MAIN / explicit fill: re-scrape gaps in verify. UPDATE: capture already did
        # only-missing; avoid a second CDP pass unless -FillMissingTickets was passed.
        if ($UpdateOnly) {
            $doFill = $FillMissingTickets.IsPresent
            $doRebuild = $RebuildRateCard.IsPresent -or ($nOk -gt 0)
        } else {
            $doFill = $FillMissingTickets -or $Force -or $cdpUp
            $doRebuild = $RebuildRateCard -or $doFill
        }
        Invoke-PayoutVerify -VerifyRoot $Root -VerifyDate $Date -VerifyTickets $TicketsPath `
            -VerifyCdp $CdpUrl -DoFill:$doFill -DoRebuild:$doRebuild -DoGentle:$Gentle.IsPresent
    }
} catch {
    Write-Host "  [PAYOUT] WARN: $($_.Exception.Message)" -ForegroundColor Yellow
} finally {
    Pop-Location
    Clear-PayoutCaptureLock
}

exit 0
