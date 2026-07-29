#requires -Version 5.1
<#
.SYNOPSIS
  Mid-day full slate refresh: re-fetch all sports with step1 --append, then full pipeline with
  -SkipFetch -SkipLivePayoutCapture, then an incremental payout UPDATE (only-missing live floors).
.NOTES
  Scheduled via PropOracle - Daily 8AM / Refresh 9AM / 11AM / 1PM (run_refresh_with_log.ps1).
  First full fetch is Daily 5AM; these refreshes are line-move updates.
  MAIN payout CDP is PropOracle - Payout CDP @ 11:00 (after 10:30 refresh); midday only fills new/missing slips (-UpdateOnly).
  Writes step1 CSVs under outputs\<date>\<sport>\ (same paths as run_pipeline.ps1 -SkipFetch).
  Per-sport step1 failures are non-fatal; pipeline failure exits 1.
#>
param(
    [switch]$NoOverwrite,
    [string]$RunLabel = ""
)

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$SportsRoot = Join-Path $Root "Sports"
Set-Location $Root

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if (-not "$($env:PROPORACLE_CURL_IMPERSONATE)".Trim()) {
    $env:PROPORACLE_CURL_IMPERSONATE = "chrome131"
}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Resolve-PipelineSlateDate {
    $pipeDate = (Get-Date).ToString("yyyy-MM-dd")
    try {
        $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
        $etNow = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz)
        if ($etNow.Hour -ge 20) {
            $pipeDate = $etNow.Date.AddDays(1).ToString("yyyy-MM-dd")
        }
    } catch { }
    return $pipeDate
}

function Ensure-RunOutDir {
    param([string]$SportTag)
    $dir = Join-Path $Root "outputs\$PipeDate\$SportTag"
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    return $dir
}

function Copy-Step1Mirror {
    param([string]$Source, [string]$MirrorPath)
    if (-not (Test-Path -LiteralPath $Source)) { return }
    $mirrorDir = Split-Path -Parent $MirrorPath
    if (-not (Test-Path -LiteralPath $mirrorDir)) {
        New-Item -ItemType Directory -Force -Path $mirrorDir | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $MirrorPath -Force
}

Write-Host "[LATE_FETCH] Starting full slate re-fetch $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

$PipeDate = Resolve-PipelineSlateDate
Write-Host "[LATE_FETCH] Pipeline slate date: $PipeDate" -ForegroundColor Cyan

# Keep in sync with run_pipeline.ps1 summer off-season gates. Fetching off-season
# boards burns retries on 403s and can hang the whole refresh cadence for hours.
$NBA_SEASON_RESUME = "2026-10-01"
$NHL_SEASON_RESUME = "2026-09-01"
$NBAOffSeason = ([datetime]::ParseExact($PipeDate, "yyyy-MM-dd", $null) -lt [datetime]::ParseExact($NBA_SEASON_RESUME, "yyyy-MM-dd", $null))
$NHLOffSeason = ([datetime]::ParseExact($PipeDate, "yyyy-MM-dd", $null) -lt [datetime]::ParseExact($NHL_SEASON_RESUME, "yyyy-MM-dd", $null))

function Get-VersionedPath([string]$Path) {
    $dir = Split-Path -Parent $Path
    # Never drop *.bak_* next to live templates (Flask/OneDrive thrash).
    $templatesDir = Join-Path $Root "ui_runner\templates"
    if ($dir -and ($dir -eq $templatesDir -or $dir.StartsWith(($templatesDir.TrimEnd('\') + '\')))) {
        $dir = Join-Path $Root "ui_runner\data\backups"
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }
    # Sport-root live pointers: archive NoOverwrite baks under data/historical.
    $sportsDir = Join-Path $Root "Sports"
    $sportsPrefix = $sportsDir.TrimEnd('\') + '\'
    if ($dir -and ($dir -eq $sportsDir -or $dir.StartsWith($sportsPrefix))) {
        $rel = if ($dir.StartsWith($sportsPrefix)) { $dir.Substring($sportsPrefix.Length) } else { "" }
        $sportName = if ($rel) { ($rel -split '[\\/]', 2)[0] } else { "misc" }
        $dir = Join-Path $Root "data\historical\sport_root_backups\$sportName"
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }
    $name = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $ext = [System.IO.Path]::GetExtension($Path)
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $candidate = Join-Path $dir "$name.bak_$stamp$ext"
    $i = 1
    while (Test-Path $candidate) {
        $candidate = Join-Path $dir "$name.bak_${stamp}_$i$ext"
        $i++
    }
    return $candidate
}

function Preserve-ExistingFile([string]$Path, [string]$Reason = "") {
    if (-not $NoOverwrite) { return }
    if (-not (Test-Path $Path)) { return }
    $backup = Get-VersionedPath -Path $Path
    Copy-Item -LiteralPath $Path -Destination $backup -Force -ErrorAction SilentlyContinue
    if ($Reason) {
        Write-Host "[LATE_FETCH][NO-OVERWRITE] Preserved '$Path' -> '$backup' ($Reason)" -ForegroundColor DarkGray
    }
    else {
        Write-Host "[LATE_FETCH][NO-OVERWRITE] Preserved '$Path' -> '$backup'" -ForegroundColor DarkGray
    }
}

function Get-CsvDataRowCount([string]$CsvPath) {
    if (-not (Test-Path $CsvPath)) { return 0 }
    try {
        $raw = Import-Csv -Path $CsvPath
        if ($null -eq $raw) { return 0 }
        if ($raw -is [array]) { return $raw.Count }
        return 1
    }
    catch {
        return 0
    }
}

function Resolve-LateFetchMaxRetries {
    param([string]$Label)
    $lbl = "$Label".Trim()
    # Cap HTTP retries low — 5 boards × multi-wave 403 cooldowns was hanging Soccer
    # (and blocking MLB) for 30–120+ minutes during morning refresh.
    if ($lbl -match '^(MANUAL_FULL|MANUAL_RECOVERY)') { return 5 }
    if ($lbl -match '^(MANUAL_1800|MANUAL_1[3-9]|1PM|2PM|3PM)') { return 2 }
    if ($lbl -match '^(MANUAL_11|MANUAL_9|11AM|9AM|1030AM|8AM|MANUAL_CDP)') { return 2 }
    return 2
}

function Test-LateFetchCdp {
    param([string]$BaseUrl = "http://127.0.0.1:9222")
    try {
        $u = ($BaseUrl.TrimEnd("/")) + "/json/version"
        $null = Invoke-RestMethod -Uri $u -TimeoutSec 2 -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    try {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ParentProcessId -eq $ProcessId } |
            ForEach-Object { Stop-ProcessTree -ProcessId ([int]$_.ProcessId) }
    }
    catch { }
    try { Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue } catch { }
}

function Invoke-TimedCommand {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [int]$TimeoutSec
    )
    Write-Host "[LATE_FETCH] $Label (timeout ${TimeoutSec}s)..." -ForegroundColor DarkGray
    $p = Start-Process -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -NoNewWindow -PassThru
    if (-not $p) {
        Write-Host "[LATE_FETCH] $Label failed to start" -ForegroundColor Red
        return 1
    }
    $finished = $p.WaitForExit([Math]::Max(5, $TimeoutSec) * 1000)
    if (-not $finished) {
        Write-Host "[LATE_FETCH] $Label timed out after ${TimeoutSec}s — killing process tree" -ForegroundColor Yellow
        Stop-ProcessTree -ProcessId $p.Id
        try { $p.Refresh() } catch { }
        return 124
    }
    return [int]$p.ExitCode
}


function Resolve-Step1MorningFallback {
    param(
        [string]$Sport,
        [string]$Step1Path,
        [int]$MaxRetries,
        [bool]$FetchFailed
    )
    $rows = Get-CsvDataRowCount -CsvPath $Step1Path
    if (-not $FetchFailed) {
        return ($rows -gt 0)
    }
    if ($rows -gt 0) {
        Write-Host "[LATE_FETCH] ${Sport}: 403 after $MaxRetries retries — using morning step1 ($rows rows)"
        return $true
    }
    if (Test-Path -LiteralPath $Step1Path) {
        Write-Host "[LATE_FETCH] ${Sport}: 403 + empty step1 — skipping sport" -ForegroundColor Yellow
    }
    else {
        Write-Host "[LATE_FETCH] ${Sport}: 403 + no morning step1 — skipping sport" -ForegroundColor Yellow
    }
    return $false
}

$MaxRetries = Resolve-LateFetchMaxRetries -Label $RunLabel
$Quiet403 = ($MaxRetries -le 2)
$CdpUrl = if ($env:PROPORACLE_MLB_CDP_URL) { "$($env:PROPORACLE_MLB_CDP_URL)".Trim() } else { "http://127.0.0.1:9222" }
$CdpReachable = Test-LateFetchCdp -BaseUrl $CdpUrl
if ($RunLabel) {
    Write-Host "[LATE_FETCH] RunLabel=$RunLabel max_retries=$MaxRetries quiet_403=$Quiet403 cdp=$CdpReachable" -ForegroundColor DarkGray
}
else {
    Write-Host "[LATE_FETCH] max_retries=$MaxRetries quiet_403=$Quiet403 cdp=$CdpReachable" -ForegroundColor DarkGray
}

# NBA — append; dated output + legacy mirror
if ($NBAOffSeason) {
    Write-Host "[LATE_FETCH] Skipping NBA fetch (off-season until $NBA_SEASON_RESUME)" -ForegroundColor DarkGray
}
else {
    Write-Host "[LATE_FETCH] Fetching NBA props (append)..."
    $NBADir = Join-Path $SportsRoot "NBA"
    $nbaRunOut = Ensure-RunOutDir -SportTag "nba"
    $nbaStep1 = Join-Path $nbaRunOut "step1_pp_props_today.csv"
    $nbaLegacy = Join-Path $NBADir "data\outputs\step1_pp_props_today.csv"
    $nbaArgs = @(
        "--league_id", "7",
        "--game_mode", "pickem",
        "--per_page", "250",
        "--max_pages", "3",
        "--retries", "$MaxRetries",
        "--sleep", "2.0",
        "--cooldown_seconds", "180",
        "--max_cooldowns", "4",
        "--jitter_seconds", "14.0",
        "--append",
        "--date", $PipeDate,
        "--allow-nearest-future",
        "--output", $nbaStep1
    )
    Push-Location $NBADir
    try {
        & py -3.14 ".\scripts\step1_fetch_prizepicks_api.py" @nbaArgs
    }
    finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        [void](Resolve-Step1MorningFallback -Sport "NBA" -Step1Path $nbaStep1 -MaxRetries $MaxRetries -FetchFailed $true)
    }
    elseif ((Get-CsvDataRowCount -CsvPath $nbaStep1) -gt 0) {
        Copy-Step1Mirror -Source $nbaStep1 -MirrorPath $nbaLegacy
    }
    else {
        [void](Resolve-Step1MorningFallback -Sport "NBA" -Step1Path $nbaStep1 -MaxRetries $MaxRetries -FetchFailed $true)
    }
}

# WNBA — full step1 fetch into dated folder (pipeline -SkipFetch reads this path)
Write-Host "[LATE_FETCH] Fetching WNBA props..."
$wnbaPs1 = Join-Path $Root "scripts\run_wnba_pipeline.ps1"
$wnbaStep1 = Join-Path (Ensure-RunOutDir -SportTag "wnba") "step1_wnba_props.csv"
if (Test-Path -LiteralPath $wnbaPs1) {
    $wnbaArgs = @("-NoProfile", "-File", $wnbaPs1, "-Date", $PipeDate, "-Step1Only", "-Max403Retries", "$MaxRetries")
    if ($Quiet403) { $wnbaArgs += "-Quiet403" }
    # Prefer CDP whenever Chrome is listening — not only MANUAL_CDP labels.
    # HTTP-first with high retries was hanging refreshes on DataDome.
    if ($CdpReachable) {
        $wnbaArgs += "-CdpWhenListening"
        Write-Host "[LATE_FETCH] WNBA: CDP reachable — browser-first" -ForegroundColor DarkGray
    }
    $wnbaTimeout = if ($CdpReachable) { 240 } else { 180 }
    $wnbaExit = Invoke-TimedCommand -Label "WNBA step1" -FilePath "pwsh" -ArgumentList $wnbaArgs -WorkingDirectory $Root -TimeoutSec $wnbaTimeout
    $wnbaFailed = ($wnbaExit -ne 0) -or ((Get-CsvDataRowCount -CsvPath $wnbaStep1) -eq 0)
    if ($wnbaFailed) {
        [void](Resolve-Step1MorningFallback -Sport "WNBA" -Step1Path $wnbaStep1 -MaxRetries $MaxRetries -FetchFailed $true)
    }
}
else {
    Write-Host "[LATE_FETCH] WARN: missing $wnbaPs1 — skipping WNBA fetch" -ForegroundColor Yellow
}

# NHL — append
if ($NHLOffSeason) {
    Write-Host "[LATE_FETCH] Skipping NHL fetch (off-season until $NHL_SEASON_RESUME)" -ForegroundColor DarkGray
}
else {
    Write-Host "[LATE_FETCH] Fetching NHL props (append)..."
    $NHLDir = Join-Path $SportsRoot "NHL"
    $nhlRunOut = Ensure-RunOutDir -SportTag "nhl"
    $nhlStep1 = Join-Path $nhlRunOut "step1_nhl_props.csv"
    Push-Location $NHLDir
    try {
        & py -3.14 ".\scripts\step1_fetch_prizepicks_nhl.py" "--append" "--date" "$PipeDate" "--output" $nhlStep1 "--max-retries" "$MaxRetries"
    }
    finally {
        Pop-Location
    }
    $nhlFailed = ($LASTEXITCODE -ne 0) -or ((Get-CsvDataRowCount -CsvPath $nhlStep1) -eq 0)
    if ($nhlFailed) {
        [void](Resolve-Step1MorningFallback -Sport "NHL" -Step1Path $nhlStep1 -MaxRetries $MaxRetries -FetchFailed $true)
    }
    elseif ((Get-CsvDataRowCount -CsvPath $nhlStep1) -gt 0) {
        Copy-Step1Mirror -Source $nhlStep1 -MirrorPath (Join-Path $NHLDir "outputs\step1_nhl_props.csv")
    }
}

# Soccer — CDP when available; otherwise fail-fast HTTP (never multi-board 90s cooldown stacks)
Write-Host "[LATE_FETCH] Fetching Soccer props (append)..."
$SoccerDir = Join-Path $SportsRoot "Soccer"
$soccerRunOut = Ensure-RunOutDir -SportTag "soccer"
$soccerStep1 = Join-Path $soccerRunOut "step1_soccer_props.csv"
$soccerArgs = @(
    "-3.14", ".\scripts\step1_fetch_prizepicks_soccer.py",
    "--append", "--date", "$PipeDate", "--output", $soccerStep1,
    "--max-retries", "$MaxRetries", "--fail-fast"
)
if ($CdpReachable) {
    $soccerArgs += @("--cdp", $CdpUrl)
    Write-Host "[LATE_FETCH] Soccer: CDP reachable — in-page fetch" -ForegroundColor DarkGray
}
$soccerTimeout = if ($CdpReachable) { 240 } else { 150 }
$soccerExit = Invoke-TimedCommand -Label "Soccer step1" -FilePath "py" -ArgumentList $soccerArgs -WorkingDirectory $SoccerDir -TimeoutSec $soccerTimeout
$soccerFailed = ($soccerExit -ne 0) -or ((Get-CsvDataRowCount -CsvPath $soccerStep1) -eq 0)
if ($soccerFailed) {
    [void](Resolve-Step1MorningFallback -Sport "Soccer" -Step1Path $soccerStep1 -MaxRetries $MaxRetries -FetchFailed $true)
}
elseif ((Get-CsvDataRowCount -CsvPath $soccerStep1) -gt 0) {
    Copy-Step1Mirror -Source $soccerStep1 -MirrorPath (Join-Path $SoccerDir "outputs\step1_soccer_props.csv")
}

# Tennis — CDP when available; otherwise fail-fast HTTP (was hanging morning refreshes)
Write-Host "[LATE_FETCH] Fetching Tennis props..."
$TennisDir = Join-Path $SportsRoot "Tennis"
$tennisRunOut = Ensure-RunOutDir -SportTag "tennis"
$tennisStep1 = Join-Path $tennisRunOut "step1_tennis_props.csv"
$tennisArgs = @(
    "-3.14", ".\scripts\step1_fetch_prizepicks_tennis.py",
    "--league_id", "5",
    "--output", $tennisStep1,
    "--retries", "$MaxRetries",
    "--fail-fast",
    "--replace"
)
if ($CdpReachable) {
    $tennisArgs += @("--cdp", $CdpUrl)
    Write-Host "[LATE_FETCH] Tennis: CDP reachable — in-page fetch" -ForegroundColor DarkGray
}
$tennisTimeout = if ($CdpReachable) { 240 } else { 150 }
$tennisExit = Invoke-TimedCommand -Label "Tennis step1" -FilePath "py" -ArgumentList $tennisArgs -WorkingDirectory $TennisDir -TimeoutSec $tennisTimeout
$tennisFailed = ($tennisExit -ne 0) -or ((Get-CsvDataRowCount -CsvPath $tennisStep1) -eq 0)
if ($tennisFailed) {
    [void](Resolve-Step1MorningFallback -Sport "Tennis" -Step1Path $tennisStep1 -MaxRetries $MaxRetries -FetchFailed $true)
}
elseif ((Get-CsvDataRowCount -CsvPath $tennisStep1) -gt 0) {
    Copy-Step1Mirror -Source $tennisStep1 -MirrorPath (Join-Path $TennisDir "outputs\step1_tennis_props.csv")
}

# MLB — CDP-first when Chrome is listening (same DataDome pattern as WNBA).
# HTTP full waves only when CDP is down; never burn 20–40 min of 403 stacks with CDP already up.
Write-Host "[LATE_FETCH] Fetching MLB props (append)..." -ForegroundColor Cyan
$MLBDir = Join-Path $SportsRoot "MLB"
$mlbRunOut = Ensure-RunOutDir -SportTag "mlb"
$mlbStep1 = Join-Path $mlbRunOut "step1_mlb_props.csv"
$env:PROPORACLE_CURL_IMPERSONATE = "chrome131"
$mlbHttpArgs = @(
    "--date", "$PipeDate",
    "--output", $mlbStep1,
    "--per-page", "250",
    "--max-pages", "10",
    "--max-retries", "$MaxRetries",
    "--api-session-waves", "3",
    "--api-403-cooldown-after", "$([Math]::Max(2, $MaxRetries + 1))",
    "--api-403-cooldown-seconds", "90",
    "--api-403-cooldown-jitter-min", "12",
    "--api-403-cooldown-jitter-max", "40",
    "--append"
)
$mlbCdpUrl = if ($env:PROPORACLE_MLB_CDP_URL) { "$($env:PROPORACLE_MLB_CDP_URL)".Trim() } else { $CdpUrl }
$mlbCdpReachable = $CdpReachable
if (-not $mlbCdpReachable) {
    try {
        $mlbCdpProbe = Invoke-RestMethod -Uri "$mlbCdpUrl/json/version" -TimeoutSec 2 -ErrorAction Stop
        if ($mlbCdpProbe) { $mlbCdpReachable = $true }
    }
    catch { $mlbCdpReachable = $false }
}

Push-Location $MLBDir
try {
    if ($mlbCdpReachable) {
        Write-Host "[LATE_FETCH] MLB: CDP reachable — browser-first ($mlbCdpUrl)" -ForegroundColor DarkGray
        & py -3.14 -u ".\scripts\step1_fetch_prizepicks_mlb.py" `
            "--cdp" $mlbCdpUrl `
            "--timeout" "120" `
            "--retries" "1" `
            "--retry_delay" "5" `
            "--append" `
            "--date" "$PipeDate" `
            "--output" $mlbStep1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[LATE_FETCH] MLB CDP failed (exit $LASTEXITCODE) — HTTP fallback (full 403 backoff)" -ForegroundColor Yellow
            & py -3.14 -u ".\scripts\step1_fetch_prizepicks_mlb.py" @mlbHttpArgs
        }
    }
    else {
        Write-Host "[LATE_FETCH] MLB: CDP down — HTTP first (full 403 backoff)" -ForegroundColor DarkGray
        & py -3.14 -u ".\scripts\step1_fetch_prizepicks_mlb.py" @mlbHttpArgs
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[LATE_FETCH] MLB falling back to Playwright" -ForegroundColor Yellow
        & py -3.14 -u ".\scripts\step1_fetch_prizepicks_mlb.py" `
            "--playwright" `
            "--timeout" "240" `
            "--retries" "1" `
            "--retry_delay" "5" `
            "--append" `
            "--date" "$PipeDate" `
            "--output" $mlbStep1
    }
}
finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) {
    $mlbRows = Get-CsvDataRowCount -CsvPath $mlbStep1
    if (-not (Resolve-Step1MorningFallback -Sport "MLB" -Step1Path $mlbStep1 -MaxRetries $MaxRetries -FetchFailed $true)) {
        Write-Host "[LATE_FETCH][HIGH] MLB step1 failed and no fallback rows are available. Continuing pipeline for other sports." -ForegroundColor Red
    }
}
elseif ((Get-CsvDataRowCount -CsvPath $mlbStep1) -gt 0) {
    Copy-Step1Mirror -Source $mlbStep1 -MirrorPath (Join-Path $MLBDir "data\outputs\step1_mlb_props.csv")
}

$pipeScript = Join-Path $Root "run_pipeline.ps1"
if (-not (Test-Path $pipeScript)) {
    Write-Host "[LATE_FETCH] Missing run_pipeline.ps1 at $pipeScript" -ForegroundColor Red
    exit 1
}

# Mid-day refresh: lower ticket-gen (5AM keeps default 64). Cuts combined rebuild wall time hard.
$middayTicketStarts = 16
if ($env:PROPORACLE_REFRESH_TICKET_GEN_STARTS) {
    $parsedStarts = 0
    if ([int]::TryParse("$($env:PROPORACLE_REFRESH_TICKET_GEN_STARTS)".Trim(), [ref]$parsedStarts) -and $parsedStarts -gt 0) {
        $middayTicketStarts = $parsedStarts
    }
}
Write-Host "[LATE_FETCH] Running full pipeline -SkipFetch -SkipLivePayoutCapture -TicketGenStarts $middayTicketStarts -Date $PipeDate..."
# Pipeline skips embedded CDP; after tickets we run an incremental payout UPDATE
# (only slips missing live_cdp). MAIN full capture is PropOracle - Payout CDP @ 11:00 (after 10:30).
if ($NoOverwrite) {
    $preserveTargets = @(
        (Join-Path $Root "outputs\$PipeDate\combined_slate_tickets_$PipeDate.xlsx"),
        (Join-Path $Root "outputs\$PipeDate\combined_slate_tickets_$PipeDate.json"),
        (Join-Path $Root "ui_runner\templates\tickets_latest.html"),
        (Join-Path $Root "ui_runner\templates\tickets_latest.json"),
        (Join-Path $Root "ui_runner\templates\slate_latest.json"),
        (Join-Path $Root "ui_runner\templates\slate_eval_$PipeDate.html"),
        (Join-Path $Root "ui_runner\templates\ticket_eval_$PipeDate.html"),
        (Join-Path $Root "ui_runner\templates\graded_props_$PipeDate.json"),
        (Join-Path $Root "Sports\NBA\step8_all_direction_clean.xlsx"),
        (Join-Path $Root "Sports\Soccer\step8_soccer_direction_clean.xlsx"),
        (Join-Path $Root "Sports\MLB\data\outputs\step8_mlb_direction_clean.xlsx"),
        (Join-Path $Root "Sports\MLB\step8_mlb_direction_clean.xlsx"),
        (Join-Path $Root "Sports\Tennis\step8_tennis_direction_clean.xlsx")
    )
    foreach ($pt in $preserveTargets) {
        Preserve-ExistingFile -Path $pt -Reason "pre-LATE_FETCH pipeline snapshot"
    }
}
& pwsh -NoProfile -File $pipeScript -SkipFetch -SkipLivePayoutCapture -TicketGenStarts $middayTicketStarts -Date $PipeDate
if ($LASTEXITCODE -ne 0) {
    Write-Host "[LATE_FETCH] Pipeline failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

$livePayScript = Join-Path $Root "scripts\run_live_payout_capture.ps1"
if (Test-Path -LiteralPath $livePayScript) {
    Write-Host "[LATE_FETCH] Incremental payout UPDATE (only slips missing live_cdp)..." -ForegroundColor Cyan
    try {
        & pwsh -NoProfile -File $livePayScript -Date $PipeDate -Root $Root -UpdateOnly
        Write-Host "[LATE_FETCH] Payout update exit $LASTEXITCODE" -ForegroundColor DarkGray
    } catch {
        Write-Host "[LATE_FETCH] WARN: payout update failed (non-blocking): $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Host "[LATE_FETCH] WARN: run_live_payout_capture.ps1 missing — skip payout update" -ForegroundColor Yellow
}

Write-Host "[LATE_FETCH] Done $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Green
exit 0
