#requires -Version 7.2
<#
.SYNOPSIS
  Mid-day / iterative rebuild wrapper around run_pipeline.ps1 (faster defaults).

.DESCRIPTION
  Uses fewer ticket-gen starts (default 16 vs AM 64), and defaults to -SkipFetch when a sport
  flag is set so step2–8 rebuild from existing step1.
  Live PrizePicks payout scrape runs after tickets (fingerprint skip if unchanged).
  Pass -SkipLivePayoutCapture for offline rebuilds without CDP.

.EXAMPLE
  # Tickets only from on-disk step8s (fastest)
  .\scripts\run_fast_rebuild.ps1 -CombinedOnly

  # One sport rebuild without re-fetch, then combined tickets
  .\scripts\run_fast_rebuild.ps1 -MLBOnly
  .\scripts\run_fast_rebuild.ps1 -WNBAOnly -SkipFetch:$false   # force step1 re-fetch

  # Full parallel sports from cache + combined
  .\scripts\run_fast_rebuild.ps1 -AllSports -TicketGenStarts 8

.NOTES
  For AM publish use scripts\run_daily.ps1 (full search + single CDP in STEP D-payout).
#>
param(
    [string]$Date = "",
    [string]$TennisDate = "",
    [switch]$CombinedOnly,
    [switch]$AllSports,
    [switch]$NBAOnly,
    [switch]$CBBOnly,
    [switch]$CFBOnly,
    [switch]$NHLOnly,
    [switch]$MLBOnly,
    [switch]$SoccerOnly,
    [switch]$TennisOnly,
    [switch]$GolfOnly,
    [switch]$WNBAOnly,
    [switch]$NFLOnly,
    # Default on for sport rebuilds; CombinedOnly ignores fetch. Pass -SkipFetch:$false to re-fetch.
    [switch]$SkipFetch = $true,
    [int]$TicketGenStarts = 16,
    # Default: run live CDP payout after tickets (skips CDP when ticket fingerprint unchanged).
    [switch]$SkipLivePayoutCapture,
    [switch]$IncludeLivePayout,
    [switch]$SkipDailyGrader = $true,
    [switch]$SkipPush = $true,
    [switch]$WebEvOnly,
    [string]$WNBACdp = ""
)

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$pipe = Join-Path $Root "run_pipeline.ps1"
if (-not (Test-Path -LiteralPath $pipe)) {
    Write-Error "run_pipeline.ps1 not found: $pipe"
    exit 1
}

$sportFlags = @(
    $NBAOnly, $CBBOnly, $CFBOnly, $NHLOnly, $MLBOnly,
    $SoccerOnly, $TennisOnly, $GolfOnly, $WNBAOnly, $NFLOnly
) | Where-Object { $_ }
$sportCount = @($sportFlags).Count

if ($CombinedOnly -and ($AllSports -or $sportCount -gt 0)) {
    Write-Error "Use either -CombinedOnly or sport/-AllSports flags, not both."
    exit 1
}
if ($AllSports -and $sportCount -gt 0) {
    Write-Error "Use -AllSports alone (no *Only sport switches)."
    exit 1
}
if (-not $CombinedOnly -and -not $AllSports -and $sportCount -eq 0) {
    Write-Host "No mode set — defaulting to -CombinedOnly (tickets from existing step8s)." -ForegroundColor Yellow
    $CombinedOnly = $true
}
if ($sportCount -gt 1) {
    Write-Error "Pass only one *Only sport switch (or -AllSports / -CombinedOnly)."
    exit 1
}

if ($IncludeLivePayout) {
    $SkipLivePayoutCapture = $false
}

$argsList = [System.Collections.Generic.List[string]]::new()
if ($Date) { $argsList.AddRange([string[]]@("-Date", $Date)) }
if ($TennisDate) { $argsList.AddRange([string[]]@("-TennisDate", $TennisDate)) }
if ($TicketGenStarts -gt 0) { $argsList.AddRange([string[]]@("-TicketGenStarts", "$TicketGenStarts")) }
if ($SkipLivePayoutCapture) { $argsList.Add("-SkipLivePayoutCapture") }
if ($SkipDailyGrader) { $argsList.Add("-SkipDailyGrader") }
if ($SkipPush) { $argsList.Add("-SkipPush") }
if ($WebEvOnly) { $argsList.Add("-WebEvOnly") }
if ($WNBACdp) { $argsList.AddRange([string[]]@("-WNBACdp", $WNBACdp)) }

if ($CombinedOnly) {
    $argsList.Add("-CombinedOnly")
} else {
    if ($SkipFetch) { $argsList.Add("-SkipFetch") }
    if ($AllSports) {
        # No *Only → full parallel block in run_pipeline.ps1
    } elseif ($NBAOnly) { $argsList.Add("-NBAOnly") }
    elseif ($CBBOnly) { $argsList.Add("-CBBOnly") }
    elseif ($CFBOnly) { $argsList.Add("-CFBOnly") }
    elseif ($NHLOnly) { $argsList.Add("-NHLOnly") }
    elseif ($MLBOnly) { $argsList.Add("-MLBOnly") }
    elseif ($SoccerOnly) { $argsList.Add("-SoccerOnly") }
    elseif ($TennisOnly) { $argsList.Add("-TennisOnly") }
    elseif ($GolfOnly) { $argsList.Add("-GolfOnly") }
    elseif ($WNBAOnly) { $argsList.Add("-WNBAOnly") }
    elseif ($NFLOnly) { $argsList.Add("-NFLOnly") }
}

$mode = if ($CombinedOnly) { "CombinedOnly" } elseif ($AllSports) { "AllSports" } else { "SportOnly" }
Write-Host "[FAST_REBUILD] mode=$mode TicketGenStarts=$TicketGenStarts SkipFetch=$SkipFetch SkipLivePayout=$SkipLivePayoutCapture" -ForegroundColor Cyan
Write-Host "[FAST_REBUILD] pwsh -File run_pipeline.ps1 $($argsList -join ' ')" -ForegroundColor DarkGray

Push-Location $Root
try {
    & pwsh -NoProfile -File $pipe @argsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
