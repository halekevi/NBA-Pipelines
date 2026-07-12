#requires -Version 7.2
# ============================================================
#  Live PrizePicks payout capture (post-ticket step)
#
#  Runs after combined_slate_tickets writes MAIN/STRONG slips:
#    1) CDP scrape of EACH generated MAIN/STRONG slip only → power_min_x
#       (navigates to that slip's sport board; does not crawl unrelated leagues)
#    2) Write payout_patch_<date>.json + write-back display_min_x
#       (payout_source=live_cdp) onto combined + tickets_latest.json
#    Optional: -IncludeMixGrid for once/day rate-card calibration (separate from tickets)
#
#  Usage:
#    .\scripts\run_live_payout_capture.ps1 -Date 2026-07-12
#    .\scripts\run_live_payout_capture.ps1 -Date 2026-07-12 -Force
#    .\scripts\run_live_payout_capture.ps1 -Date 2026-07-12 -IncludeMixGrid
#
#  Exit codes:
#    0  = capture attempted (ok or soft-fail / CDP skip)
#    1  = hard error (script missing, etc.)
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
    # Default: exact line+Goblin only. Pass -AllowLineFallback to price moved proxies.
    [switch]$AllowLineFallback
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

if (-not $TicketsPath) {
    $TicketsPath = Join-Path $Root "ui_runner\data\combined_slate_tickets_$Date.json"
    if (-not (Test-Path -LiteralPath $TicketsPath)) {
        $alt = Join-Path $Root "outputs\$Date\combined_slate_tickets_$Date.json"
        if (Test-Path -LiteralPath $alt) { $TicketsPath = $alt }
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

Write-Host ""
Write-Host "[LIVE PAYOUT] Post-ticket PrizePicks scrape ($Date)" -ForegroundColor Magenta

if (-not (Test-Path -LiteralPath $payoutScript)) {
    Write-Host "  [PAYOUT] ERROR: collect_payout_data.py missing" -ForegroundColor Red
    exit 1
}

$cdpUp = Test-CdpUp -Url $CdpUrl
if (-not $cdpUp) {
    Write-Host "  [PAYOUT] CDP not running on $CdpUrl -- skip (tickets keep board-avg / rate-card)" -ForegroundColor DarkGray
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
        exit 0
    }

    # Idempotent: skip re-scrape when today's capture already has live floors (unless -Force).
    if (-not $Force -and (Test-Path -LiteralPath $payoutOut)) {
        try {
            $prior = Get-Content -LiteralPath $payoutOut -Raw | ConvertFrom-Json
            $priorOk = 0
            if ($null -ne $prior.summary) { $priorOk = [int]($prior.summary.n_ok) }
            if ($priorOk -gt 0) {
                Write-Host "  [PAYOUT] already have live capture n_ok=$priorOk ($payoutOut) -- skip (pass -Force to redo)" -ForegroundColor DarkGray
                exit 0
            }
        } catch { }
    }

    Write-Host "  [PAYOUT] Capturing MAIN/STRONG floors from $TicketsPath" -ForegroundColor Cyan
    $ticketArgs = @(
        "-3.14", "-X", "utf8", $payoutScript,
        "--tickets", $TicketsPath,
        "--output", $payoutOut,
        "--date", $Date,
        "--cdp-url", $CdpUrl,
        "--fields", "power_min_x,power_first_x,min_guarantee,flex_min"
    )
    if ($NoWriteBack) { $ticketArgs += "--no-write-back" }
    if ($AllowLineFallback) { $ticketArgs += "--allow-line-fallback" }
    & py @ticketArgs
    $capExit = $LASTEXITCODE

    $nOk = 0
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

    if ($capExit -eq 0 -and $nOk -gt 0) {
        # Keep mobile mirror in sync when templates/tickets_latest was write-backed.
        if ((Test-Path -LiteralPath $ticketsLatest) -and (Test-Path (Split-Path $mobileTickets -Parent))) {
            Copy-Item $ticketsLatest $mobileTickets -Force -ErrorAction SilentlyContinue
            Write-Host "  [PAYOUT] mirrored -> mobile/www/tickets_latest.json" -ForegroundColor Green
        }
        Write-Host "  [PAYOUT] Live floors applied (payout_source=live_cdp on patched slips)" -ForegroundColor Green
    } elseif ($capExit -eq 0) {
        Write-Host "  [PAYOUT] WARN: capture finished but 0 live floors (board avg remains)" -ForegroundColor Yellow
    } else {
        Write-Host "  [PAYOUT] WARN: capture exit $capExit (non-blocking)" -ForegroundColor Yellow
    }

    # Remove slips that can no longer be built on PP from the LIVE site/app only.
    # Grade pool + per-run archives keep every historical slip for grading/compare.
    if ($capExit -eq 0 -and (Test-Path -LiteralPath $payoutOut)) {
        try {
            Write-Host "  [PAYOUT] Pruning unplayable slips from live tickets_latest..." -ForegroundColor Cyan
            py -3.14 -X utf8 (Join-Path $Root "scripts\ticket_run_archive.py") `
                --prune-live --date $Date --capture $payoutOut | Out-Host
        } catch {
            Write-Host "  [PAYOUT] WARN: live prune failed: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "  [PAYOUT] WARN: $($_.Exception.Message)" -ForegroundColor Yellow
} finally {
    Pop-Location
}

exit 0
