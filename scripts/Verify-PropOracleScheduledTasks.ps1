#requires -Version 5.1
<#
.SYNOPSIS
  Verify all PropOracle scheduled tasks point at the canonical main worktree.

.DESCRIPTION
  Expected root: PropORACLE_main_cp (or -ExpectedRoot). Exit 0 if all match;
  exit 2 if any task is missing or pointed at a feature-branch checkout.
#>
param(
    [string]$ExpectedRoot = "H:\PropORACLE_main_cp"
)

$ErrorActionPreference = "Continue"

if ([string]::IsNullOrWhiteSpace($ExpectedRoot)) {
    $ExpectedRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}
$ExpectedRoot = $ExpectedRoot.TrimEnd('\')
$names = @(
    "PropOracle - Daily 1AM",
    "PropOracle - Grader 3AM",
    "PropOracle - Daily 5AM",
    "PropOracle - Daily 8AM",
    "PropOracle - Refresh 945AM",
    "PropOracle - Refresh 1030AM",
    "PropOracle - Refresh 1PM",
    "PropOracle - Refresh 430PM"
)

$bad = @()
foreach ($name in $names) {
    $st = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $st) {
        $bad += "[MISSING] $name"
        continue
    }
    $a = @($st.Actions)[0]
    $wd = ([string]$a.WorkingDirectory).TrimEnd('\')
    $arg = [string]$a.Arguments
    if ($wd -ne $ExpectedRoot) {
        $bad += "[WRONG WD] $name -> $wd (want $ExpectedRoot)"
    }
    if ($arg -notlike "*$ExpectedRoot*") {
        $bad += "[WRONG SCRIPT] $name args do not include $ExpectedRoot"
    }
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Host ("{0,-32} WD={1} Last={2} Result={3}" -f $name, $wd, $info.LastRunTime, $info.LastTaskResult)
}

if ($bad.Count -gt 0) {
    Write-Host ""
    Write-Host "FAILED:" -ForegroundColor Red
    $bad | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "Fix: cd $ExpectedRoot\scripts; .\Register_Daily_Task.ps1  (elevated)" -ForegroundColor Yellow
    exit 2
}

Write-Host ""
Write-Host "OK: all PropOracle tasks point at $ExpectedRoot" -ForegroundColor Green
exit 0
