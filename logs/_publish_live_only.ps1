#requires -Version 7.2
$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $Root "run_pipeline.ps1"))) { $Root = "H:\PropORACLE_main_cp" }
$Date = "2026-08-24"
Set-Location $Root
# Parse Publish-LiveSiteJsonToMain from run_pipeline without executing the rest:
$src = Get-Content (Join-Path $Root "run_pipeline.ps1") -Raw
# Extract function block by invoking via scriptblock of just the helpers we need
# Safer: duplicate minimal publish inline
$liveRel = @(
  "ui_runner/templates/tickets_latest.json",
  "ui_runner/docs/tickets_latest.json",
  "mobile/www/tickets_latest.json",
  "ui_runner/templates/slate_latest.json",
  "ui_runner/templates/slate_display_date.json",
  "mobile/www/slate_display_date.json",
  "ui_runner/templates/pipeline_status.json",
  "mobile/www/pipeline_status.json",
  "mobile/www/slate_latest.json",
  "ui_runner/templates/tickets_winrate_latest.json",
  "ui_runner/templates/sport_breakdown.json"
)
Get-ChildItem -LiteralPath (Join-Path $Root "ui_runner\templates") -Filter "slate_sport_*.json" -EA SilentlyContinue | ForEach-Object { $liveRel += ("ui_runner/templates/" + $_.Name) }
Get-ChildItem -LiteralPath (Join-Path $Root "mobile\www") -Filter "slate_sport_*.json" -EA SilentlyContinue | ForEach-Object { $liveRel += ("mobile/www/" + $_.Name) }
$toPublish = @()
foreach ($rel in $liveRel) { if (Test-Path -LiteralPath (Join-Path $Root ($rel -replace "/","\"))) { $toPublish += $rel } }
Write-Host "[publish] files=$($toPublish.Count)"
git -C $Root pull --ff-only origin main
foreach ($rel in $toPublish) { git -C $Root add -- $rel }
$msg = "chore: live tickets/slate $Date $(Get-Date -Format 'HH:mm')"
git -C $Root commit -m $msg
if ($LASTEXITCODE -eq 0) {
  git -C $Root push origin main
  if ($LASTEXITCODE -eq 0) {
    Write-Host "OK - LIVE PUSHED"
    "$Date $(Get-Date -Format 'HH:mm:ss') - LIVE PUSHED: $msg" | Out-File (Join-Path $Root "git_push_log.txt") -Append -Encoding utf8
  } else { Write-Host "PUSH FAILED exit=$LASTEXITCODE"; exit 1 }
} else {
  Write-Host "NO COMMIT (maybe already published)"
  git -C $Root status --porcelain -- $toPublish | Select-Object -First 25
}
git -C $Root log -1 --oneline
