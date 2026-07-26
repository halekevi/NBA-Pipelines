#requires -Version 5.1
<#
  Scheduled hourly grader (7pm–1am) via Register_Daily_Task.ps1.
  Evening grader wrapper: git pull, then run_grader.ps1 for yesterday's slate date.
  (Standalone run_grader_5am.ps1 was removed — morning grading is inside Daily 5AM.)
#>
param()

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$Grader = Join-Path $Root "scripts\run_grader.ps1"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Evening Grader" } catch { }

if (-not (Test-Path $Grader)) {
    Write-Error "Missing grader script: $Grader"
    exit 1
}

Set-Location $Root
Write-Host "[EVENING GRADER] Pulling latest repository..." -ForegroundColor Cyan
git pull --ff-only 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Write-Host "[EVENING GRADER] git pull failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

$gradeDate = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
Write-Host "[EVENING GRADER] Running run_grader.ps1 -Date $gradeDate" -ForegroundColor Cyan
# Stay in this console — do not spawn a second pwsh window.
& $Grader -Date $gradeDate
if ($LASTEXITCODE -ne 0) {
    Write-Host "[EVENING GRADER] run_grader failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "[EVENING GRADER] Complete" -ForegroundColor Green
exit 0
