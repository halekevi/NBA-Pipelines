# Fetch PrizePicks step1 into a snapshot folder (does not overwrite pipeline outputs).
#
#   pwsh -File scripts/fetch_pp_board_snap.ps1 -GameDate 2026-08-18 -Label 2300
#   pwsh -File scripts/fetch_pp_board_snap.ps1 -GameDate 2026-08-18 -Label 0800
param(
    [string]$GameDate = "2026-08-18",
    [string]$Label = "2300"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
. (Join-Path $Root "scripts\prizepicks_step1_cascade.ps1")

$out = Join-Path $Root "outputs\$GameDate\snaps\$Label"
New-Item -ItemType Directory -Force -Path `
    (Join-Path $out "wnba"), (Join-Path $out "mlb"), (Join-Path $out "soccer"), (Join-Path $out "tennis"), (Join-Path $out "golf") | Out-Null

$wnbaOut = Join-Path $out "wnba\step1_wnba_props.csv"
$mlbOut = Join-Path $out "mlb\step1_mlb_props.csv"
$soccerOut = Join-Path $out "soccer\step1_soccer_props.csv"
$tennisOut = Join-Path $out "tennis\step1_tennis_props.csv"
$golfOut = Join-Path $out "golf\step1_golf_props.csv"

Write-Host "PP board snap fetch label=$Label game_date=$GameDate -> $out" -ForegroundColor Cyan

$okW = Invoke-PrizePicksStep1Cascade -SportLabel "WNBA" `
    -WorkDir (Join-Path $Root "Sports\WNBA") `
    -ScriptRel ".\step1_fetch_prizepicks.py" `
    -OutputPath $wnbaOut `
    -PipelineDate $GameDate `
    -FailFastFlag "--fail-fast-403" `
    -HttpArgs @(
        "--league_id", "3", "--game_mode", "pickem", "--per_page", "250", "--max_pages", "10",
        "--sleep", "2.0", "--cooldown_seconds", "90", "--max_cooldowns", "3", "--jitter_seconds", "10.0",
        "--max_403_retries", "2", "--first-page-waves", "1", "--fail-fast-403",
        "--output", $wnbaOut, "--date", $GameDate
    )

$okM = Invoke-PrizePicksStep1Cascade -SportLabel "MLB" `
    -WorkDir (Join-Path $Root "Sports\MLB") `
    -ScriptRel ".\scripts\step1_fetch_prizepicks_mlb.py" `
    -OutputPath $mlbOut `
    -PipelineDate $GameDate `
    -HttpArgs @("--output", $mlbOut, "--date", $GameDate, "--fail-fast")

$okS = Invoke-PrizePicksStep1Cascade -SportLabel "Soccer" `
    -WorkDir (Join-Path $Root "Sports\Soccer") `
    -ScriptRel ".\scripts\step1_fetch_prizepicks_soccer.py" `
    -OutputPath $soccerOut `
    -PipelineDate $GameDate `
    -HttpArgs @("--output", $soccerOut, "--date", $GameDate, "--fail-fast")

$okT = Invoke-PrizePicksStep1Cascade -SportLabel "Tennis" `
    -WorkDir (Join-Path $Root "Sports\Tennis") `
    -ScriptRel ".\scripts\step1_fetch_prizepicks_tennis.py" `
    -OutputPath $tennisOut `
    -PipelineDate $GameDate `
    -SkipDateHealth `
    -HttpArgs @("--league_id", "5", "--replace", "--output", $tennisOut, "--fail-fast")

$okG = Invoke-PrizePicksStep1Cascade -SportLabel "Golf" `
    -WorkDir (Join-Path $Root "Sports\Golf") `
    -ScriptRel ".\scripts\step1_fetch_prizepicks_golf.py" `
    -OutputPath $golfOut `
    -PipelineDate $GameDate `
    -SkipDateHealth `
    -HttpArgs @("--league_id", "1", "--replace", "--output", $golfOut, "--fail-fast")

Write-Host "fetch results WNBA=$okW MLB=$okM Soccer=$okS Tennis=$okT Golf=$okG" -ForegroundColor Cyan

& py -3.14 (Join-Path $Root "scripts\pp_line_timeline.py") snapshot --label $Label --game-date $GameDate --src-dir $out
& py -3.14 (Join-Path $Root "scripts\pp_line_timeline.py") diff --game-date $GameDate --a 1907 --b $Label
& py -3.14 (Join-Path $Root "scripts\pp_line_timeline.py") diff --game-date $GameDate --a 1757 --b $Label

if ($okW -and $okM -and $okS -and $okT) { exit 0 }
exit 1
