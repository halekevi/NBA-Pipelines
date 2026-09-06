#requires -Version 5.1
<#
.SYNOPSIS
  Kick off the full 1AM daily (complete all-sport fetch + grader) in a visible window.

.NOTES
  Use this for manual catchups. Scheduled tasks use the same visible-window
  pattern after you re-run Register_Daily_Task.ps1 (elevated).
#>
param()

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$Wrapper = Join-Path $PSScriptRoot "run_daily_1am.ps1"

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

Write-Host "Launching visible window: $Wrapper" -ForegroundColor Cyan
Start-Process -FilePath $pwsh `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Wrapper) `
    -WorkingDirectory $Root `
    -WindowStyle Normal

Write-Host "Started. Watch the new PowerShell window for progress." -ForegroundColor Green
exit 0
