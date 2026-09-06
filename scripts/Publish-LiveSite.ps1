#requires -Version 5.1
<#
.SYNOPSIS
  Push live tickets/slate JSON to origin/main (Railway + GitHub raw) from the main worktree.

.NOTES
  Called after 8AM/9:45/10:30/1PM/4:30 refreshes so the site is not left on the 1AM board.
  Mirrors run_pipeline.ps1 Publish-LiveSiteJsonToMain.
#>
param(
    [string]$RepoRoot = "",
    [string]$CommitMessage = ""
)

$ErrorActionPreference = "Continue"
$Root = if ($RepoRoot) { $RepoRoot } else { Split-Path $PSScriptRoot -Parent }

function Get-MainWorktreeRoot {
    param([string]$RepoRoot = $Root)
    $porcelain = git -C $RepoRoot worktree list --porcelain 2>$null
    if (-not $porcelain) { return $RepoRoot }
    $wt = $null
    foreach ($line in $porcelain) {
        if ($line -match '^worktree (.+)$') { $wt = $Matches[1].Trim() }
        elseif ($line -match '^branch refs/heads/main$' -and $wt) { return $wt }
        elseif ($line -eq "") { $wt = $null }
    }
    $br = (git -C $RepoRoot rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
    if ($br -eq "main") { return $RepoRoot }
    return $null
}

$MainRoot = Get-MainWorktreeRoot
if (-not $MainRoot) {
    Write-Host "[PUBLISH] FAILED: no worktree has main checked out" -ForegroundColor Red
    exit 1
}

Write-Host "[PUBLISH] Live site JSON -> origin/main ($MainRoot)" -ForegroundColor Cyan

$assertPy = Join-Path $Root "scripts\assert_live_publish.py"
if (Test-Path -LiteralPath $assertPy) {
    Write-Host "[PUBLISH] assert dual-card + runtime/templates sync" -ForegroundColor DarkGray
    & py -3.14 $assertPy --root $Root --fix
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[PUBLISH] FAILED: live JSON guard (Goblin-70+mixer, matching dates)" -ForegroundColor Red
        exit 1
    }
}

# templates/ = GitHub raw contract (Railway). runtime/ = canonical disk copy.
# mobile/www is not live (Android loads Railway remotely).
$liveRel = @(
    "ui_runner/runtime/tickets_latest.json",
    "ui_runner/templates/tickets_latest.json",
    "ui_runner/runtime/slate_latest.json",
    "ui_runner/templates/slate_latest.json",
    "ui_runner/runtime/slate_display_date.json",
    "ui_runner/templates/slate_display_date.json",
    "ui_runner/runtime/pipeline_status.json",
    "ui_runner/templates/pipeline_status.json",
    "ui_runner/runtime/tickets_winrate_latest.json",
    "ui_runner/templates/tickets_winrate_latest.json",
    "ui_runner/runtime/sport_breakdown.json",
    "ui_runner/templates/sport_breakdown.json",
    "ui_runner/runtime/last_fetch_window.json",
    "ui_runner/templates/last_fetch_window.json",
    "data/reports/bet_windows_latest.json"
)
Get-ChildItem -LiteralPath (Join-Path $Root "ui_runner\runtime") -Filter "slate_sport_*.json" -ErrorAction SilentlyContinue |
    ForEach-Object { $liveRel += ("ui_runner/runtime/" + $_.Name) }
Get-ChildItem -LiteralPath (Join-Path $Root "ui_runner\templates") -Filter "slate_sport_*.json" -ErrorAction SilentlyContinue |
    ForEach-Object { $liveRel += ("ui_runner/templates/" + $_.Name) }

$toPublish = @()
foreach ($rel in $liveRel) {
    $full = Join-Path $Root ($rel -replace "/", "\")
    if (Test-Path -LiteralPath $full) { $toPublish += $rel }
}
if (-not $toPublish.Count) {
    Write-Host "[PUBLISH] No live site JSON found" -ForegroundColor Yellow
    exit 0
}

Push-Location $MainRoot
try {
    git pull --ff-only origin main 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    foreach ($rel in $toPublish) {
        $src = Join-Path $Root ($rel -replace "/", "\")
        $dst = Join-Path $MainRoot ($rel -replace "/", "\")
        $samePath = $false
        try {
            if ((Test-Path -LiteralPath $src) -and (Test-Path -LiteralPath $dst)) {
                $samePath = (
                    [IO.Path]::GetFullPath($src).TrimEnd('\') -eq
                    [IO.Path]::GetFullPath($dst).TrimEnd('\')
                )
            }
        } catch { $samePath = ($src -eq $dst) }
        if (-not $samePath) {
            $dstDir = Split-Path $dst -Parent
            if (-not (Test-Path -LiteralPath $dstDir)) {
                New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
            }
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
        git add -- $rel 2>&1 | Out-Null
    }
    $msg = if ($CommitMessage) { $CommitMessage } else { "chore: live tickets/slate $(Get-Date -Format 'yyyy-MM-dd HH:mm')" }
    git commit -m $msg 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $pushOut = git push origin main 2>&1
        foreach ($line in $pushOut) { Write-Host "    $line" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[PUBLISH] OK — origin/main updated" -ForegroundColor Green
            exit 0
        }
        Write-Host "[PUBLISH] FAILED: git push origin main" -ForegroundColor Red
        exit 1
    }
    Write-Host "[PUBLISH] no JSON changes vs main" -ForegroundColor DarkGray
    exit 0
} finally {
    Pop-Location
}
