#requires -Version 5.1
<#
.SYNOPSIS
  Compatibility shim — the morning line-move update moved to 8:00 AM.

.NOTES
  Forwards to scripts\run_daily_8am.ps1. Prefer PropOracle - Daily 8AM.
#>
param()

$ErrorActionPreference = "Continue"
$Next = Join-Path $PSScriptRoot "run_daily_8am.ps1"
Write-Host "[LEGACY 7AM] Forwarding to run_daily_8am.ps1 (scheduled at 8:00 AM)." -ForegroundColor Yellow
& pwsh -NoProfile -File $Next
exit $LASTEXITCODE
