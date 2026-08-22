#requires -Version 5.1
<#
.SYNOPSIS
  Hard gate: all active sports for the ET day must be FRESH on slate_latest.

.DESCRIPTION
  Thin wrapper around scripts/assert_active_sports_fresh.py.
  Exit 0 = OK, exit 2 = expected sport PENDING/STALE/failed, exit 1 = tool error.
  Use after STEP E publish / refresh success so partial Soccer-only boards fail the job.

  Default expected set: WNBA+MLB+Soccer+Tennis (summer), skipping off_season /
  intentional empty PP fetch. Pass -Require to force an exact list.
#>
param(
    [string]$RepoRoot = "",
    [string]$Today = "",
    [string]$TemplatesDir = "",
    [string]$JsonOut = "",
    [string]$Require = "",
    [switch]$DryRun,
    [switch]$NoGameDay
)

$ErrorActionPreference = "Continue"
if (-not $RepoRoot) {
    $RepoRoot = Split-Path $PSScriptRoot -Parent
}
$RepoRoot = $RepoRoot.TrimEnd('\')
$py = Join-Path $RepoRoot "scripts\assert_active_sports_fresh.py"
if (-not (Test-Path -LiteralPath $py)) {
    Write-Host "[ACTIVE-SPORTS-FRESH] FAILED: missing $py" -ForegroundColor Red
    exit 1
}

$argsList = @("-X", "utf8", $py, "--repo", $RepoRoot)
if ($Today) { $argsList += @("--today", $Today) }
if ($TemplatesDir) { $argsList += @("--templates-dir", $TemplatesDir) }
if ($JsonOut) { $argsList += @("--json-out", $JsonOut) }
if ($Require) { $argsList += @("--require", $Require) }
if ($DryRun) { $argsList += "--dry-run" }
if ($NoGameDay) { $argsList += "--no-game-day" }

& py -3.14 @argsList
exit $LASTEXITCODE