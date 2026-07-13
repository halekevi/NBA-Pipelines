#requires -Version 7.2
# Discover payout rates with anti-bot-friendly defaults:
#   HTTP prefetch (chrome131 + rotating headers + warmup) for Standard/Goblin Δ
#   Gentle CDP only for Min Guarantee capture (no multi-filter board expand)
#
# Example:
#   .\scripts\run_validate_payout_ladder.ps1 -Run -Discover -PrefetchHttp -Gentle -SlateDate 2026-07-13 -MaxCases 20
param(
    [string]$Date = "",
    [string]$SlateDate = "",
    [string]$CdpUrl = "http://127.0.0.1:9222",
    [string]$Step1Csv = "",
    [int]$MaxCases = 20,
    [double]$DelaySec = 0.0,
    [switch]$Run,
    [switch]$Discover,
    [switch]$Exhaustive,
    [switch]$MixOnly,
    [switch]$DeltaOnly,
    [switch]$PrefetchHttp,
    [switch]$Gentle,
    [switch]$SkipCdpScrape,
    [switch]$LaunchChrome
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Date) { $Date = (Get-Date).ToString("yyyy-MM-dd") }
if (-not $SlateDate) { $SlateDate = $Date }

Set-Location $Root

# Same TLS impersonation that clears DataDome 403s on WNBA step1.
$env:PROPORACLE_CURL_IMPERSONATE = "chrome131"

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
        Write-Host "[validate] Log into PrizePicks in that Chrome window if prompted." -ForegroundColor Yellow
    }
}

# Default anti-bot path for discovery runs.
if ($Run -and -not $MixOnly -and -not $DeltaOnly) {
    if (-not $PSBoundParameters.ContainsKey("PrefetchHttp")) { $PrefetchHttp = $true }
    if (-not $PSBoundParameters.ContainsKey("Gentle")) { $Gentle = $true }
}

$argsList = @(
    "-3.14", "-X", "utf8", (Join-Path $Root "scripts\validate_payout_ladder.py"),
    "--date", $Date,
    "--slate-date", $SlateDate,
    "--cdp-url", $CdpUrl,
    "--max-cases", "$MaxCases"
)
if ($Step1Csv) { $argsList += @("--step1-csv", $Step1Csv) }
if ($Discover -or ($Run -and -not $MixOnly -and -not $DeltaOnly)) { $argsList += "--discover" }
if ($Exhaustive) { $argsList += "--exhaustive" }
if ($MixOnly) { $argsList += "--mix-only" }
if ($DeltaOnly) { $argsList += "--delta-only" }
if ($PrefetchHttp) { $argsList += "--prefetch-http" }
if ($Gentle) { $argsList += "--gentle" }
if ($SkipCdpScrape) { $argsList += "--skip-cdp-scrape" }
if ($DelaySec -gt 0) { $argsList += @("--delay-sec", "$DelaySec") }
if ($Run) { $argsList += "--run" } else { $argsList += "--dry-run" }

Write-Host "[validate] PROPORACLE_CURL_IMPERSONATE=$env:PROPORACLE_CURL_IMPERSONATE" -ForegroundColor DarkGray
Write-Host "[validate] py $($argsList -join ' ')" -ForegroundColor Cyan
& py @argsList
exit $LASTEXITCODE
