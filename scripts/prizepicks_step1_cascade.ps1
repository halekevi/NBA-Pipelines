# PrizePicks step1 cascade: HTTP (chrome131) → CDP → Playwright.
# Dot-source from run_pipeline.ps1 / run_wnba_pipeline.ps1 / parallel jobs.
# Most reliable path matches MLB: fail-fast HTTP when Chrome 9222 is up, then CDP, then Playwright.

$script:PrizePicksCascadeDir = $PSScriptRoot

function Get-PrizePicksCdpUrl {
    foreach ($v in @($env:PROPORACLE_PP_CDP, $env:PRIZEPICKS_CDP, $env:PROPORACLE_MLB_CDP_URL)) {
        if ($v -and "$v".Trim()) { return "$v".Trim() }
    }
    return "http://127.0.0.1:9222"
}

function Test-PrizePicksCdpReachable {
    param([string]$CdpUrl = "")
    if (-not $CdpUrl) { $CdpUrl = Get-PrizePicksCdpUrl }
    try {
        $probe = Invoke-RestMethod -Uri "$($CdpUrl.TrimEnd('/'))/json/version" -TimeoutSec 2 -ErrorAction Stop
        if (-not $probe) { return $false }
    } catch {
        return $false
    }
    $repo = Split-Path $script:PrizePicksCascadeDir -Parent
    if (-not (Test-Path -LiteralPath (Join-Path $repo "utils\prizepicks_cdp.py"))) {
        return $true
    }
    try {
        Push-Location $repo
        & py -3.14 -c "import sys; from utils.prizepicks_cdp import probe_cdp_attach; sys.exit(0 if probe_cdp_attach(sys.argv[1], timeout_ms=8000) else 1)" $CdpUrl 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        Pop-Location
    }
}

function Get-PrizePicksStep1Health {
    param(
        [string]$CsvPath,
        [string]$TargetDate,
        [switch]$SkipDateMatch
    )
    if (-not (Test-Path -LiteralPath $CsvPath)) { return @{ ok = $false; rows = 0; reason = "missing_file" } }
    try {
        $rows = Import-Csv -LiteralPath $CsvPath
    } catch {
        return @{ ok = $false; rows = 0; reason = "read_error" }
    }
    if (-not $rows -or $rows.Count -eq 0) { return @{ ok = $false; rows = 0; reason = "empty_file" } }
    if ($SkipDateMatch -or -not $TargetDate) {
        return @{ ok = $true; rows = $rows.Count; reason = "ok" }
    }
    $names = @($rows[0].PSObject.Properties.Name)
    $match = @()
    if ($names -contains "game_date") {
        $match = @($rows | Where-Object { ("$($_.game_date)").Trim() -eq $TargetDate })
    } elseif ($names -contains "start_time") {
        $match = @($rows | Where-Object {
            $st = "$($_.start_time)"
            $okDate = ($st.Length -ge 10 -and $st.Substring(0, 10) -eq $TargetDate)
            $lg = if ($names -contains "league") { ("$($_.league)").Trim().ToUpper() } else { "" }
            $lid = if ($names -contains "league_id") { ("$($_.league_id)").Trim() } else { "" }
            $okDate -or ($lg -in @("NFLSZN", "SOCCERSZN")) -or ($lid -eq "163")
        })
    } elseif ($names -contains "game_start") {
        $match = @($rows | Where-Object { "$($_.game_start)".Length -ge 10 -and "$($_.game_start)".Substring(0, 10) -eq $TargetDate })
    } else {
        return @{ ok = $true; rows = $rows.Count; reason = "ok_no_date_col" }
    }
    $reason = if ($match.Count -gt 0) { "ok" } else { "date_mismatch" }
    return @{ ok = ($match.Count -gt 0); rows = $rows.Count; reason = $reason }
}

function Invoke-PrizePicksStep1Cascade {
    param(
        [string]$SportLabel,
        [string]$WorkDir,
        [string]$ScriptRel,
        [string]$OutputPath,
        [string]$PipelineDate = "",
        [string[]]$HttpArgs = @(),
        [string[]]$CdpExtraArgs = @(),
        [string[]]$PlaywrightExtraArgs = @(),
        [switch]$SkipDateHealth,
        [switch]$AsJobOutput,
        [string]$FailFastFlag = "--fail-fast"
    )

    function Write-PP {
        param([string]$Msg, [string]$Color = "DarkGray")
        if ($AsJobOutput) { Write-Output $Msg }
        else { Write-Host $Msg -ForegroundColor $Color }
    }

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    if (-not ("$env:PROPORACLE_CURL_IMPERSONATE").Trim()) {
        $env:PROPORACLE_CURL_IMPERSONATE = "chrome131"
    }

    $cdpUrl = Get-PrizePicksCdpUrl
    $cdpReachable = Test-PrizePicksCdpReachable -CdpUrl $cdpUrl
    Write-PP "  --> $SportLabel Step 1 - Fetch PrizePicks (HTTP first, then CDP, then Playwright)" "Yellow"
    if ($cdpReachable) {
        Write-PP "      [$SportLabel] CDP up at $cdpUrl — fail-fast HTTP then CDP" "DarkCyan"
    }

    Push-Location $WorkDir
    try {
        $outDir = Split-Path -Parent $OutputPath
        if ($outDir -and -not (Test-Path -LiteralPath $outDir) -and $outDir -ne ".") {
            New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        }

        $base = @($HttpArgs | Where-Object { $_ -notin @("--fail-fast", "--fail-fast-403") })
        $http = @($HttpArgs)
        if ($cdpReachable -and $FailFastFlag) {
            if ($http -notcontains $FailFastFlag) { $http += $FailFastFlag }
        }

        Write-PP "        CMD: py -3.14 -u $ScriptRel $($http -join ' ')"
        $output = & py -3.14 -u $ScriptRel @http 2>&1
        $exit = $LASTEXITCODE
        foreach ($line in $output) { Write-PP "        $line" }
        if ($exit -eq 0) {
            $h = Get-PrizePicksStep1Health -CsvPath $OutputPath -TargetDate $PipelineDate -SkipDateMatch:$SkipDateHealth
            if ($h.ok) { Write-PP "      OK (HTTP)" "Green"; return $true }
            if (-not $cdpReachable -and $h.reason -in @("empty_file", "missing_file")) {
                Write-PP "      OK (HTTP, 0 props — no slate)" "DarkGray"
                return $true
            }
            Write-PP "      [$SportLabel] HTTP unhealthy ($($h.reason)) — falling back to CDP" "Yellow"
        } else {
            Write-PP "      [$SportLabel] HTTP failed (exit $exit) — falling back to CDP" "Yellow"
        }

        if ($cdpReachable) {
            $cdpArgs = @("--cdp", $cdpUrl) + $base + @($CdpExtraArgs)
            Write-PP "        CMD: py -3.14 -u $ScriptRel $($cdpArgs -join ' ')"
            $output = & py -3.14 -u $ScriptRel @cdpArgs 2>&1
            $exit = $LASTEXITCODE
            foreach ($line in $output) { Write-PP "        $line" }
            if ($exit -eq 0) {
                $h = Get-PrizePicksStep1Health -CsvPath $OutputPath -TargetDate $PipelineDate -SkipDateMatch:$SkipDateHealth
                if ($h.ok) { Write-PP "      OK (CDP)" "Green"; return $true }
                Write-PP "      [$SportLabel] CDP unhealthy ($($h.reason)) — skipping Playwright (protect DataDome)" "Yellow"
                return $false
            }
            Write-PP "      [$SportLabel] CDP failed (exit $exit) — skipping Playwright (protect DataDome)" "Yellow"
            return $false
        }

        Write-PP "      CDP not reachable at $cdpUrl — trying Playwright" "Yellow"
        $pwArgs = @("--playwright") + $base + @($PlaywrightExtraArgs)
        Write-PP "        CMD: py -3.14 -u $ScriptRel $($pwArgs -join ' ')"
        $output = & py -3.14 -u $ScriptRel @pwArgs 2>&1
        $exit = $LASTEXITCODE
        foreach ($line in $output) { Write-PP "        $line" }
        if ($exit -ne 0) {
            Write-PP "      FAILED (exit $exit)" "Red"
            return $false
        }
        $h = Get-PrizePicksStep1Health -CsvPath $OutputPath -TargetDate $PipelineDate -SkipDateMatch:$SkipDateHealth
        if (-not $h.ok) {
            if ($h.reason -in @("empty_file", "missing_file")) {
                Write-PP "      OK (0 props — no slate)" "DarkGray"
                return $true
            }
            Write-PP "      FAILED: step1 unhealthy after all paths ($($h.reason))" "Red"
            return $false
        }
        Write-PP "      OK (Playwright)" "Green"
        return $true
    } catch {
        Write-PP "      EXCEPTION: $_" "Red"
        return $false
    } finally {
        Pop-Location
    }
}
