#requires -Version 5.1
<#
.SYNOPSIS
  Manual afternoon FillMissing live PrizePicks CDP for slips still missing live_cdp.

.NOTES
  Not scheduled. Primary scrapes ride with 8/9/10:30/1 refreshes after fetch.
  Use only for manual catchup when a refresh left pending_live.
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
