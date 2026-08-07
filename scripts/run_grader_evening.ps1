#requires -Version 5.1
<#
  Overnight grader (1AM) via Register_Daily_Task.ps1.

  Evening grader wrapper:
    - Prefer main worktree (Railway publishes from origin/main)
    - Ensure-CleanPull (same stash/repair as 5AM/3AM)
    - STEP A1 historical actuals refresh (so 5AM can skip it)
    - Transcript under logs/task_grader_*.log
    - run_grader.ps1 for yesterday's slate date

  Single overnight grader at 1AM only, then Tennis Early 3AM (fetch only),
  then Daily 5AM (pipeline/publish; skips grader + A1 when overnight outputs/stamp exist).
#>
param(
    [int]$A1TimeoutMinutes = 30
)

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
        Write-Host "[EVENING GRADER] Source conflict reported — retrying publish-artifact repair..." -ForegroundColor Yellow
        & pwsh -NoProfile -File $EnsurePull -RepoRoot $Root -Label "[EVENING GRADER]" -SkipPull
        $pullPrepExit = $LASTEXITCODE
    }
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
$stampDay = (Get-Date).ToString("yyyy-MM-dd")

# A1 historical actuals — owned overnight so 5AM daily stays on critical path.
$fetchScript = Join-Path $Root "scripts\fetch_historical_actuals.py"
$a1StampPath = Join-Path $Root "data\cache\historical_actuals_ok_$stampDay.flag"
if (Test-Path -LiteralPath $fetchScript) {
    Write-Host "[EVENING GRADER] Historical actuals refresh (A1) START..." -ForegroundColor Cyan
    Push-Location $Root
    try {
        $a1Proc = Start-Process -FilePath "py" `
            -ArgumentList @("-3.14", "-u", $fetchScript) `
            -NoNewWindow -PassThru
        $waitSec = [Math]::Max(60, $A1TimeoutMinutes * 60)
        $a1Finished = $a1Proc.WaitForExit($waitSec * 1000)
        if (-not $a1Finished) {
            Write-Host "[EVENING GRADER] A1 WARN: timeout ${A1TimeoutMinutes}m — continuing to grader" -ForegroundColor Yellow
            try { Stop-Process -Id $a1Proc.Id -Force -ErrorAction SilentlyContinue } catch { }
        }
        elseif ($a1Proc.ExitCode -ne 0) {
            Write-Host "[EVENING GRADER] A1 WARN: exit $($a1Proc.ExitCode) — continuing to grader" -ForegroundColor Yellow
        }
        else {
            Write-Host "[EVENING GRADER] A1 OK" -ForegroundColor Green
            try {
                $stampDir = Split-Path $a1StampPath -Parent
                if (-not (Test-Path -LiteralPath $stampDir)) {
                    New-Item -ItemType Directory -Path $stampDir -Force | Out-Null
                }
                Set-Content -LiteralPath $a1StampPath -Value ("ok {0:o} overnight-grader" -f (Get-Date)) -Encoding utf8
            }
            catch { }
        }
    }
    catch {
        Write-Host "[EVENING GRADER] A1 WARN: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "[EVENING GRADER] A1 SKIP (fetch_historical_actuals.py missing)" -ForegroundColor DarkYellow
}

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
