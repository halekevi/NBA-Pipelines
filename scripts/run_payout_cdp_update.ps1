#requires -Version 5.1
<#
.SYNOPSIS
  Afternoon UpdateOnly live PrizePicks CDP fill for slips still missing live_cdp.

.NOTES
  MAIN capture is PropOracle - Payout CDP @ 11:00.
  Ticket rebuilds after 11:00 often leave the board on pending_live; this job
  re-scrapes only missing slips (FillMissingTickets) so the board recovers.
  Registered by scripts\Register_Daily_Task.ps1 as "PropOracle - Payout CDP Update" @ 15:00.
#>
param(
    [string]$Date = ""
)

$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Payout CDP Update" } catch { }
$Root = Split-Path $PSScriptRoot -Parent
$Capture = Join-Path $Root "scripts\run_live_payout_capture.ps1"

if (-not (Test-Path -LiteralPath $Capture)) {
    Write-Error "Missing payout capture script: $Capture"
    exit 1
}

Set-Location $Root

if (-not $Date) {
    $Date = (Get-Date).ToString("yyyy-MM-dd")
}
$Date = $Date.Substring(0, [Math]::Min(10, $Date.Length))

$TicketsPath = Join-Path $Root "ui_runner\templates\tickets_latest.json"
if (-not (Test-Path -LiteralPath $TicketsPath)) {
    $TicketsPath = Join-Path $Root "ui_runner\data\tickets_latest.json"
}

Write-Host "[PAYOUT CDP UPDATE] UpdateOnly + FillMissing for $Date ..." -ForegroundColor Magenta
& pwsh -NoProfile -File $Capture -Date $Date -Root $Root -TicketsPath $TicketsPath -UpdateOnly -FillMissingTickets
$exit = $LASTEXITCODE
Write-Host "[PAYOUT CDP UPDATE] exit=$exit" -ForegroundColor $(if ($exit -eq 0) { "Green" } else { "Yellow" })
exit $exit
