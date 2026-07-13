#requires -Version 7.2
# Scrape live PrizePicks and validate ladder payout rates with REAL board slips.
#
# Usage:
#   .\scripts\run_validate_payout_ladder.ps1              # dry-run plan
#   .\scripts\run_validate_payout_ladder.ps1 -Run         # scrape PP + capture real Min Guarantees
#   .\scripts\run_validate_payout_ladder.ps1 -Run -MaxCases 25 -DeltaOnly
param(
    [string]$Date = "",
    [string]$CdpUrl = "http://127.0.0.1:9222",
    [int]$MaxCases = 40,
    [switch]$Run,
    [switch]$MixOnly,
    [switch]$DeltaOnly,
    [switch]$LaunchChrome
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Date) { $Date = (Get-Date).ToString("yyyy-MM-dd") }

Set-Location $Root

if ($LaunchChrome -or $Run) {
    $up = $false
    try {
        $null = Invoke-WebRequest -Uri ($CdpUrl.TrimEnd("/") + "/json/version") -TimeoutSec 2
        $up = $true
    } catch { $up = $false }
    if (-not $up) {
        Write-Host "[validate] CDP down — launching PrizePicks Chrome..." -ForegroundColor Yellow
        & pwsh -NoProfile -File (Join-Path $Root "scripts\launch_prizepicks_chrome_cdp.ps1") -OpenBoard
        Start-Sleep -Seconds 5
        Write-Host "[validate] Log into PrizePicks in that Chrome window if prompted, then re-run -Run if needed." -ForegroundColor Yellow
    }
}

$argsList = @(
    "-3.14", "-X", "utf8", (Join-Path $Root "scripts\validate_payout_ladder.py"),
    "--date", $Date,
    "--cdp-url", $CdpUrl,
    "--max-cases", "$MaxCases"
)
if ($MixOnly) { $argsList += "--mix-only" }
if ($DeltaOnly) { $argsList += "--delta-only" }
if ($Run) { $argsList += "--run" } else { $argsList += "--dry-run" }

Write-Host "[validate] py $($argsList -join ' ')" -ForegroundColor Cyan
& py @argsList
exit $LASTEXITCODE
