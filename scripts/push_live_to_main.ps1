#requires -Version 7.0
<#
.SYNOPSIS
  Publish live Railway-facing tickets/slate JSON (and optional code paths) to origin/main.

.DESCRIPTION
  Railway + raw.githubusercontent.com/.../main serve production. This always commits
  on the worktree that has `main` checked out (this repo or a linked worktree such as
  PropORACLE_main_cp), then leaves the caller branch untouched.
  Daily automation uses STEP E in scripts/run_daily.ps1 (same main-worktree rule).
#>
param(
    [string]$CommitMessage = "",
    [string[]]$AlsoPaths = @(),
    [switch]$IncludePublishHelpers
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Get-MainWorktreeRoot {
    param([string]$RepoRoot)
    $porcelain = git -C $RepoRoot worktree list --porcelain 2>$null
    if (-not $porcelain) { return $RepoRoot }
    $wt = $null
    foreach ($line in $porcelain) {
        if ($line -match '^worktree (.+)$') {
            $wt = $Matches[1].Trim()
        }
        elseif ($line -match '^branch refs/heads/main$' -and $wt) {
            return $wt
        }
        elseif ($line -eq "") {
            $wt = $null
        }
    }
    # Fallback: current checkout if already on main
    $br = (git -C $RepoRoot rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
    if ($br -eq "main") { return $RepoRoot }
    return $null
}

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
        "scripts/run_daily_5am.ps1",
        "scripts/run_daily_8am.ps1",
        "scripts/Ensure-CleanPull.ps1",
        "scripts/push_live_to_main.ps1",
        "scripts/combined_slate_tickets.py",
        "scripts/assert_live_board_sync.py",
        "scripts/assert_active_sports_fresh.py",
        "scripts/Assert-ActiveSportsFresh.ps1",
        "scripts/generate_mobile_bundle.py",
        "scripts/run_refresh_with_log.ps1",
        "utils/ticket_ev_tiers.py"
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

$assertScript = Join-Path $Root "scripts\assert_live_board_sync.py"
if (Test-Path -LiteralPath $assertScript) {
    $todayEt = (Get-Date).ToString("yyyy-MM-dd")
    try {
        $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
        $todayEt = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz).ToString("yyyy-MM-dd")
    } catch { }
    Write-Host "Checking tickets_latest vs slate_latest ($todayEt)..." -ForegroundColor DarkGray
    & py -3.14 -X utf8 $assertScript --today $todayEt --templates-dir (Join-Path $Root "ui_runner\templates")
    if ($LASTEXITCODE -eq 2) {
        Write-Host "REFUSING to publish: tickets_latest lags slate_latest." -ForegroundColor Red
        Write-Host "Run CombinedOnly --write-web, then retry. Slate-only publish is what left /tickets on yesterday." -ForegroundColor Yellow
        exit 2
    }
}

$MainRoot = Get-MainWorktreeRoot -RepoRoot $Root
if (-not $MainRoot) {
    throw "No worktree has 'main' checked out. Open PropORACLE_main_cp (or checkout main) then retry."
}
Write-Host "Publishing into main worktree: $MainRoot" -ForegroundColor Cyan

# When publishing from main_cp itself, never stash first — that hid fresh
# slate_sport_*.json and left Railway on Soccer-only boards.
$sameTree = ([System.IO.Path]::GetFullPath($Root) -eq [System.IO.Path]::GetFullPath($MainRoot))
$liveSnap = $null
if (-not $sameTree) {
    $liveSnap = Join-Path $env:TEMP ("proporacle_push_live_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $liveSnap -Force | Out-Null
    foreach ($rel in $toPublish) {
        $src = Join-Path $Root ($rel -replace "/", "\")
        if (Test-Path -LiteralPath $src) {
            $dst = Join-Path $liveSnap ($rel -replace "/", "\")
            New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    }
}

$stashed = $false
try {
    Push-Location $MainRoot
    if (-not $sameTree -and (git status --porcelain)) {
        git stash push -m "proporacle-push-live-temp" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $stashed = $true }
    }
    git pull --ff-only origin main

    foreach ($rel in $toPublish) {
        if ($sameTree) {
            $src = Join-Path $Root ($rel -replace "/", "\")
        } else {
            $src = Join-Path $liveSnap ($rel -replace "/", "\")
            if (-not (Test-Path -LiteralPath $src)) {
                $src = Join-Path $Root ($rel -replace "/", "\")
            }
        }
        $dst = Join-Path $MainRoot ($rel -replace "/", "\")
        $srcFull = [System.IO.Path]::GetFullPath($src)
        $dstFull = [System.IO.Path]::GetFullPath($dst)
        if ((Test-Path -LiteralPath $src) -and ($srcFull -ne $dstFull)) {
            New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
        if (Test-Path -LiteralPath $dst) {
            git add -f -- $rel
        }
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

    $assertFresh = Join-Path $Root "scripts\Assert-ActiveSportsFresh.ps1"
    if (-not (Test-Path -LiteralPath $assertFresh)) {
        $assertFresh = Join-Path $MainRoot "scripts\Assert-ActiveSportsFresh.ps1"
    }
    if (Test-Path -LiteralPath $assertFresh) {
        $todayEt = (Get-Date).ToString("yyyy-MM-dd")
        try {
            $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
            $todayEt = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz).ToString("yyyy-MM-dd")
        } catch { }
        Write-Host "Asserting active sports FRESH ($todayEt)..." -ForegroundColor Cyan
        & pwsh -NoProfile -File $assertFresh -RepoRoot $MainRoot -Today $todayEt
        if ($LASTEXITCODE -ne 0) {
            throw "Active sports freshness gate failed (exit $LASTEXITCODE)"
        }
    }
}
finally {
    if ($stashed) { git stash pop 2>&1 | Out-Null }
    if ($liveSnap -and (Test-Path -LiteralPath $liveSnap)) {
        Remove-Item -LiteralPath $liveSnap -Recurse -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
}
