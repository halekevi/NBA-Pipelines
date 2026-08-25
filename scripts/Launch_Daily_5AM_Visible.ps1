#requires -Version 5.1
<#
.SYNOPSIS
  Kick off the full 5AM daily in a visible PowerShell console window.

.NOTES
  Scheduled 5AM (`PropOracle - Daily 5AM`) and manual catchup. Overnight 1AM is
  Launch_Daily_1AM_Visible.ps1 / "PropOracle - Daily 1AM".
#>
param()

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$Wrapper = Join-Path $PSScriptRoot "run_daily_5am.ps1"

if (-not (Test-Path -LiteralPath $Wrapper)) {
    Write-Error "Missing wrapper: $Wrapper"
    exit 1
}

$pwsh = $null
foreach ($cand in @(
    (Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "$env:ProgramFiles\PowerShell\7\pwsh.exe",
    (Get-Command powershell.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
)) {
    if ($cand -and (Test-Path -LiteralPath $cand)) { $pwsh = $cand; break }
}
if (-not $pwsh) {
    Write-Error "No pwsh.exe/powershell.exe found"
    exit 1
}

# Open a real console (do not RedirectStandardOutput / Hidden - that hides the UI).
Write-Host "Launching visible window: $Wrapper" -ForegroundColor Cyan
Start-Process -FilePath $pwsh `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Wrapper) `
    -WorkingDirectory $Root `
    -WindowStyle Normal

Write-Host "Started. Watch the new PowerShell window for progress." -ForegroundColor Green
exit 0
