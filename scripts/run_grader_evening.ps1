#requires -Version 5.1
<#
  Scheduled hourly grader (7pm–1am) via Register_Daily_Task.ps1.

  Evening grader wrapper:
    - Prefer main worktree (Railway publishes from origin/main)
    - Ensure-CleanPull (same stash/repair as 5AM/3AM — raw git pull --ff-only
      used to abort every night on dirty publish JSON)
    - Transcript under logs/task_grader_*.log
    - run_grader.ps1 for yesterday's slate date

  There is no 2AM grader task — cadence is 7PM, 8PM, 9PM, 10PM, 11PM, 12AM, 1AM,
  then Tennis Early 3AM, then Daily 5AM (which also grades yesterday).
#>
param()

$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Evening Grader" } catch { }
$Root = Split-Path $PSScriptRoot -Parent
$Grader = Join-Path $Root "scripts\run_grader.ps1"

if (-not (Test-Path $Grader)) {
    Write-Error "Missing grader script: $Grader"
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

# Railway tracks origin/main. Hourly graders must run on main or grades never publish.
$branch = (git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
$mainWt = Get-MainWorktreeRoot
if ($branch -ne "main") {
    if ($mainWt -and (Test-Path -LiteralPath (Join-Path $mainWt "scripts\run_grader.ps1"))) {
        Write-Host "[EVENING GRADER] On '$branch' - running inside main worktree: $mainWt" -ForegroundColor Yellow
        $Root = $mainWt
        $Grader = Join-Path $Root "scripts\run_grader.ps1"
        Set-Location $Root
    }
    else {
        Write-Host "[EVENING GRADER] On '$branch' - no main worktree; grades will not push to Railway." -ForegroundColor Yellow
    }
}

$LogsDir = Join-Path $Root "logs"
if (-not (Test-Path -LiteralPath $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}
$WrapperLog = Join-Path $LogsDir ("task_grader_{0:yyyy-MM-dd_HHmmss}.log" -f (Get-Date))
try { Start-Transcript -Path $WrapperLog -Append | Out-Null } catch { }

Write-Host "[EVENING GRADER] Pulling latest repository (main)..." -ForegroundColor Cyan
$EnsurePull = Join-Path $PSScriptRoot "Ensure-CleanPull.ps1"
if (-not (Test-Path -LiteralPath $EnsurePull)) {
    $EnsurePull = Join-Path $Root "scripts\Ensure-CleanPull.ps1"
}
if (Test-Path -LiteralPath $EnsurePull) {
    & pwsh -NoProfile -File $EnsurePull -RepoRoot $Root -Label "[EVENING GRADER]" -StashMessage ("proporacle-grader-pre-pull-{0:yyyyMMdd_HHmmss}" -f (Get-Date))
    $pullPrepExit = $LASTEXITCODE
    if ($pullPrepExit -eq 2) {
        Write-Host "[EVENING GRADER] FAILED: source-code conflicts block pull (resolve manually)." -ForegroundColor Red
        try { Stop-Transcript | Out-Null } catch { }
        exit 128
    }
    if ($pullPrepExit -ne 0) {
        Write-Host "[EVENING GRADER] Pull prep warned (exit $pullPrepExit); continuing with local tree." -ForegroundColor Yellow
    }
}
else {
    git pull --ff-only 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[EVENING GRADER] git pull failed (exit $LASTEXITCODE)" -ForegroundColor Red
        try { Stop-Transcript | Out-Null } catch { }
        exit $LASTEXITCODE
    }
}

$gradeDate = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
Write-Host "[EVENING GRADER] Running run_grader.ps1 -Date $gradeDate" -ForegroundColor Cyan
# Stay in this console — do not spawn a nested pwsh (loses transcript + exit clarity).
& $Grader -Date $gradeDate
$graderExit = $LASTEXITCODE
if ($graderExit -ne 0) {
    Write-Host "[EVENING GRADER] run_grader failed (exit $graderExit)" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit $graderExit
}

Write-Host "[EVENING GRADER] Complete" -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch { }
exit 0
