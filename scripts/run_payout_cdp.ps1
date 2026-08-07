#requires -Version 5.1
<#
.SYNOPSIS
  Manual live PrizePicks CDP payout capture (MAIN/STRONG floors).

.NOTES
  Not scheduled. Primary ticket CDP rides with each mid-day refresh after fetch
  (8/9/10:30/1 → run_nba_late_fetch Force re-scrape). Use this script only for
  manual catchup when a refresh left pending_live or CDP was down.
#>
param(
    [string]$Date = ""
)

$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Payout CDP" } catch { }
$Root = Split-Path $PSScriptRoot -Parent
$Capture = Join-Path $Root "scripts\run_live_payout_capture.ps1"

if (-not (Test-Path -LiteralPath $Capture)) {
    Write-Error "Missing payout capture script: $Capture"
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

$branch = (git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
$mainWt = Get-MainWorktreeRoot
if ($branch -ne "main") {
    if ($mainWt -and (Test-Path -LiteralPath (Join-Path $mainWt "scripts\run_live_payout_capture.ps1"))) {
        Write-Host "[PAYOUT CDP] On '$branch' - running inside main worktree: $mainWt" -ForegroundColor Yellow
        $Root = $mainWt
        $Capture = Join-Path $Root "scripts\run_live_payout_capture.ps1"
        Set-Location $Root
    }
    else {
        Write-Host "[PAYOUT CDP] On '$branch' - switching to main for Railway freshness..." -ForegroundColor Yellow
        git checkout main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[PAYOUT CDP] FAILED: cannot checkout main. Abort." -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host "[PAYOUT CDP] Pulling latest repository (main)..." -ForegroundColor Cyan
git pull --ff-only origin main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Write-Host "[PAYOUT CDP] git pull failed (exit $LASTEXITCODE) — continuing with local tree" -ForegroundColor Yellow
}

if (-not $Date) {
    $Date = (Get-Date).ToString("yyyy-MM-dd")
}
$Date = $Date.Substring(0, [Math]::Min(10, $Date.Length))

$TicketsPath = Join-Path $Root "ui_runner\data\combined_slate_tickets_$Date.json"
if (-not (Test-Path -LiteralPath $TicketsPath)) {
    $alt = Join-Path $Root "outputs\$Date\combined_slate_tickets_$Date.json"
    if (Test-Path -LiteralPath $alt) { $TicketsPath = $alt }
}

Write-Host "[PAYOUT CDP] MAIN capture for $Date (FillMissingTickets + RebuildRateCard)..." -ForegroundColor Magenta
& pwsh -NoProfile -File $Capture -Date $Date -Root $Root -TicketsPath $TicketsPath -FillMissingTickets -RebuildRateCard
$exit = $LASTEXITCODE

if ($exit -ne 0) {
    Write-Host "[PAYOUT CDP] Finished with exit $exit (non-fatal for schedule)" -ForegroundColor Yellow
    exit $exit
}

Write-Host "[PAYOUT CDP] Complete" -ForegroundColor Green
exit 0
