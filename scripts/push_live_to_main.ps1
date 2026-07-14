#requires -Version 7.0
<#
.SYNOPSIS
  Publish live Railway-facing tickets/slate JSON (and optional code paths) to origin/main.

.DESCRIPTION
  Railway + raw.githubusercontent.com/.../main serve production. This script always
  commits on a checked-out main tip, then restores the prior branch.
  Used by operators after CombinedOnly rebuilds; daily automation uses STEP E in
  scripts/run_daily.ps1 (same main-checkout rule).
#>
param(
    [string]$CommitMessage = "",
    [string[]]$AlsoPaths = @(),
    [switch]$IncludePublishHelpers
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$liveRel = @(
    "ui_runner/templates/tickets_latest.json",
    "ui_runner/docs/tickets_latest.json",
    "mobile/www/tickets_latest.json",
    "ui_runner/templates/slate_latest.json",
    "mobile/www/slate_latest.json",
    "ui_runner/templates/pipeline_status.json",
    "mobile/www/pipeline_status.json",
    "ui_runner/templates/tickets_winrate_latest.json",
    "ui_runner/templates/sport_breakdown.json"
)
Get-ChildItem -LiteralPath (Join-Path $Root "ui_runner\templates") -Filter "slate_sport_*.json" -ErrorAction SilentlyContinue |
    ForEach-Object { $liveRel += ("ui_runner/templates/" + $_.Name) }
Get-ChildItem -LiteralPath (Join-Path $Root "mobile\www") -Filter "slate_sport_*.json" -ErrorAction SilentlyContinue |
    ForEach-Object { $liveRel += ("mobile/www/" + $_.Name) }

if ($IncludePublishHelpers) {
    $AlsoPaths += @(
        "run_pipeline.ps1",
        "scripts/run_daily.ps1",
        "scripts/run_daily_7am.ps1",
        "scripts/push_live_to_main.ps1",
        "scripts/combined_slate_tickets.py"
    )
}
$AlsoPaths = @($AlsoPaths | Where-Object { $_ } | Select-Object -Unique)

$toPublish = @()
foreach ($rel in (@($liveRel) + $AlsoPaths)) {
    $full = Join-Path $Root ($rel -replace "/", "\")
    if (Test-Path -LiteralPath $full) { $toPublish += $rel }
}
if (-not $toPublish.Count) {
    Write-Host "Nothing to publish." -ForegroundColor Yellow
    exit 0
}

$tmp = Join-Path $env:TEMP ("proporacle_push_live_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$prevBranch = $null
$stashed = $false
try {
    foreach ($rel in $toPublish) {
        $src = Join-Path $Root ($rel -replace "/", "\")
        $dst = Join-Path $tmp ($rel -replace "/", "\")
        New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }

    $prevBranch = (git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
    if (-not $prevBranch) { $prevBranch = "HEAD" }

    if (git status --porcelain) {
        git stash push -m "proporacle-push-live-temp" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $stashed = $true }
    }

    if ($prevBranch -ne "main") {
        git checkout main
        if ($LASTEXITCODE -ne 0) { throw "Cannot checkout main" }
    }
    git pull --ff-only origin main

    foreach ($rel in $toPublish) {
        $src = Join-Path $tmp ($rel -replace "/", "\")
        $dst = Join-Path $Root ($rel -replace "/", "\")
        New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
        git add -f -- $rel
    }

    $msg = if ($CommitMessage) {
        $CommitMessage
    } else {
        "chore: live tickets/slate $(Get-Date -Format 'yyyy-MM-dd HH:mm') [auto]"
    }
    git commit -m $msg
    if ($LASTEXITCODE -eq 0) {
        git push origin main
        if ($LASTEXITCODE -ne 0) { throw "git push origin main failed" }
        Write-Host "OK - pushed to origin/main" -ForegroundColor Green
    } else {
        Write-Host "(no changes vs main)" -ForegroundColor DarkGray
    }
}
finally {
    $cur = (git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
    if ($prevBranch -and $prevBranch -ne "main" -and $prevBranch -ne "HEAD" -and $cur -eq "main") {
        git checkout $prevBranch 2>&1 | Out-Null
    }
    if ($stashed) { git stash pop 2>&1 | Out-Null }
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
