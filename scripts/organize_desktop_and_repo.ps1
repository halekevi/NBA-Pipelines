#Requires -Version 5.1
<#
.SYNOPSIS
  Organize Desktop + PropORACLE clutter without moving live app/site roots.

SAFETY:
  - NEVER moves PropORACLE or PropORACLE_main_cp (active feature + Railway main worktree)
  - NEVER moves ui_runner/, Sports/, scripts/, data/, mobile/, .git, .env
  - Only moves/archives obvious clutter; writes a manifest
#>
param(
  [switch]$Execute,
  [switch]$DeleteOfficeLocks
)

$ErrorActionPreference = "Stop"
$Desktop = "H:\halek\ProfileFromC\Desktop"
$Repo = Join-Path $Desktop "PropORACLE"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ManifestDir = Join-Path $Desktop "_Archive"
$Manifest = Join-Path $ManifestDir ("organize_manifest_{0}.txt" -f $Stamp)

function Ensure-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
  }
}

function Move-Safe {
  param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$DestDir,
    [string]$Note = ""
  )
  if (-not (Test-Path -LiteralPath $Source)) { return $false }
  Ensure-Dir $DestDir
  $name = Split-Path -Leaf $Source
  $dest = Join-Path $DestDir $name
  if (Test-Path -LiteralPath $dest) {
    $base = [IO.Path]::GetFileNameWithoutExtension($name)
    $ext = [IO.Path]::GetExtension($name)
    $dest = Join-Path $DestDir ("{0}__{1}{2}" -f $base, $Stamp, $ext)
  }
  $line = "[MOVE] $Source -> $dest$(if($Note){' | '+$Note})"
  Add-Content -LiteralPath $Manifest -Value $line
  Write-Host $line -ForegroundColor Yellow
  if ($Execute) {
    Move-Item -LiteralPath $Source -Destination $dest -Force
  }
  return
}

Ensure-Dir $ManifestDir
"PropORACLE / Desktop organize  $Stamp  Execute=$Execute" | Set-Content -LiteralPath $Manifest
"KEEP IN PLACE: PropORACLE, PropORACLE_main_cp (app/site)" | Add-Content -LiteralPath $Manifest
"" | Add-Content -LiteralPath $Manifest

if (-not $Execute) {
  Write-Host "PREVIEW ONLY - re-run with -Execute to apply" -ForegroundColor Cyan
}

# ── Desktop archive layout ───────────────────────────────────────────────────
$ArchClones = Join-Path $ManifestDir "PropORACLE_old_clones"
$ArchZips   = Join-Path $ManifestDir "PropORACLE_zip_backups"
$ArchMisc   = Join-Path $ManifestDir "Desktop_misc"
$ArchGames  = Join-Path $ManifestDir "Games_urls"
$ArchTools  = Join-Path $ManifestDir "Tools_scripts"
$ArchLogs   = Join-Path $ManifestDir "Old_logs"
$ArchFin    = Join-Path $ManifestDir "Finance_docs"
$DeskShortcuts = Join-Path $Desktop "Shortcuts"
$DeskGames = Join-Path $Desktop "Games"

Write-Host "`n=== Desktop: archive old PropORACLE clones/zips ===" -ForegroundColor Magenta
foreach ($n in @(
  "PropORACLE_main_fix",
  "PropORACLE_publish_jul24",
  "PropORACLE-grades-main",
  "PropORACLE-main-mobile-sync"
)) {
  Move-Safe (Join-Path $Desktop $n) $ArchClones "old clone/worktree"
}

foreach ($n in @("PropORACLE.zip", "PropORACLE (2).zip")) {
  Move-Safe (Join-Path $Desktop $n) $ArchZips "Apr 2026 zip snapshot (~1.7GB each)"
}

Write-Host "`n=== Desktop: leftover empty-ish PropORACLE spill folders ===" -ForegroundColor Magenta
# Only move if they are NOT the live repo Sports/
foreach ($n in @("outputs", "docs")) {
  $p = Join-Path $Desktop $n
  if (Test-Path -LiteralPath $p) {
    Move-Safe $p (Join-Path $ManifestDir "Desktop_spill") "desktop-level spill folder"
  }
}
# Desktop\Sports is separate from PropORACLE\Sports - archive if present
$deskSports = Join-Path $Desktop "Sports"
if ((Test-Path -LiteralPath $deskSports) -and ($deskSports -ne (Join-Path $Repo "Sports"))) {
  Move-Safe $deskSports (Join-Path $ManifestDir "Desktop_spill") "desktop Sports (not PropORACLE/Sports)"
}

Write-Host "`n=== Desktop: group games / tools / misc ===" -ForegroundColor Magenta
$gameUrls = @(
  "Apex Legends.url", "Assassin's Creed Shadows.url", "Fortnite.url", "Phasmophobia.url"
)
foreach ($n in $gameUrls) { Move-Safe (Join-Path $Desktop $n) $DeskGames }

$tools = @(
  "apex_mb4_cycle_hold_holster.ahk",
  "apex_mouse_y_NOTE_use_RawAccel.ahk",
  "RAW_ACCEL_Y_REDUCE.txt",
  "RawAccel_Apex_LowY_settings.json",
  "disable-mongodb-admin.bat",
  "machine.config",
  "OBS Scenes.json"
)
foreach ($n in $tools) { Move-Safe (Join-Path $Desktop $n) $ArchTools }

$misc = @(
  "flask_stderr.log", "flask_stdout.log",
  "mqdefault_6s.webp",
  "Screenshot 2025-08-01 134530.png",
  "Sports.xlsx", "SportsFootball.xlsx",
  "Firefox-DESKTOP-9KLKTUD.exe", "Firefox.exe",
  ".gitignore"
)
foreach ($n in $misc) { Move-Safe (Join-Path $Desktop $n) $ArchMisc }

$fin = @(
  "Chase5836_Activity20250628_20250727_20250826.CSV",
  "Payment Confirmation _ Fulton County Tax Commissioner.pdf"
)
foreach ($n in $fin) { Move-Safe (Join-Path $Desktop $n) $ArchFin }

# Duplicate DESKTOP- machine shortcuts → archive; keep primary shortcuts on Desktop
$dupShortcuts = @(
  "Discord-DESKTOP-9KLKTUD.lnk",
  "Google Docs-DESKTOP-9KLKTUD.lnk",
  "Google Drive-DESKTOP-9KLKTUD.lnk",
  "Google Sheets-DESKTOP-9KLKTUD.lnk",
  "Microsoft Edge-DESKTOP-9KLKTUD.lnk",
  "Ubisoft Connect - Copy.lnk"
)
foreach ($n in $dupShortcuts) {
  Move-Safe (Join-Path $Desktop $n) (Join-Path $ArchMisc "duplicate_shortcuts")
}

# Optional: move less-used app shortcuts into Shortcuts\ (keep Cursor/Discord/Edge/VS Code/GitHub on Desktop)
$lessUsedShortcuts = @(
  "Adobe XD.lnk", "Blitz.lnk", "Google Calendar.lnk", "Google Keep.lnk",
  "Insomnia.lnk", "MongoDBCompass.lnk", "PerformanceTest.lnk",
  "R5Reloaded.lnk", "Unreal Engine.lnk", "UserBenchmark.lnk",
  "Kevin - Chrome.lnk"
)
foreach ($n in $lessUsedShortcuts) {
  Move-Safe (Join-Path $Desktop $n) $DeskShortcuts
}

Write-Host "`n=== Desktop: Office lock orphans (~`$*) ===" -ForegroundColor Magenta
Get-ChildItem -LiteralPath $Desktop -Force -File -Filter "~$*" -ErrorAction SilentlyContinue | ForEach-Object {
  $line = "[LOCK] $($_.FullName)"
  Add-Content -LiteralPath $Manifest -Value $line
  Write-Host $line -ForegroundColor DarkGray
  if ($Execute -and $DeleteOfficeLocks) {
    Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
    Add-Content -LiteralPath $Manifest -Value "  deleted"
  } elseif ($Execute) {
    Move-Safe $_.FullName (Join-Path $ArchMisc "office_lock_files") | Out-Null
  }
}

# ── PropORACLE internal clutter (safe) ───────────────────────────────────────
Write-Host "`n=== PropORACLE: logs scratch + old txt logs ===" -ForegroundColor Magenta
$logsScratch = Join-Path $Repo "logs\scratch"
$logsArchive = Join-Path $Repo "logs\archive_$Stamp"
Ensure-Dir $logsScratch

# One-off underscore scripts
Get-ChildItem -LiteralPath (Join-Path $Repo "logs") -File -Filter "_*.py" -ErrorAction SilentlyContinue | ForEach-Object {
  Move-Safe $_.FullName $logsScratch "one-off scratch script"
}

# Old run logs (txt) - keep last 14 days in logs\, archive older
$cutoff = (Get-Date).AddDays(-14)
Get-ChildItem -LiteralPath (Join-Path $Repo "logs") -File -ErrorAction SilentlyContinue |
  Where-Object {
    ($_.Extension -in @(".txt", ".log")) -and ($_.LastWriteTime -lt $cutoff)
  } |
  ForEach-Object {
    Move-Safe $_.FullName $logsArchive "log older than 14d"
  }

Write-Host "`n=== PropORACLE: outputs *.bak* ===" -ForegroundColor Magenta
$outBak = Join-Path $Repo "outputs\_backups"
Get-ChildItem -LiteralPath (Join-Path $Repo "outputs") -Recurse -File -Filter "*bak*" -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch '\\outputs\\_backups\\' } |
  ForEach-Object {
  # preserve relative dated folder under _backups
  $rel = $_.DirectoryName.Substring((Join-Path $Repo "outputs").Length).TrimStart('\')
  $dest = if ($rel) { Join-Path $outBak $rel } else { $outBak }
  Move-Safe $_.FullName $dest "xlsx backup"
}

Write-Host "`n=== Verify live roots still present ===" -ForegroundColor Magenta
$checks = @(
  (Join-Path $Desktop "PropORACLE"),
  (Join-Path $Desktop "PropORACLE_main_cp"),
  (Join-Path $Repo "ui_runner\app.py"),
  (Join-Path $Repo "ui_runner\templates\tickets_latest.json"),
  (Join-Path $Repo "ui_runner\templates\slate_latest.json"),
  (Join-Path $Repo "run_pipeline.ps1"),
  (Join-Path $Repo "Sports"),
  (Join-Path $Desktop "PropORACLE_main_cp\ui_runner\app.py"),
  (Join-Path $Desktop "PropORACLE_main_cp\ui_runner\templates\tickets_latest.json")
)
$ok = $true
foreach ($c in $checks) {
  $exists = Test-Path -LiteralPath $c
  $line = "$(if($exists){'[OK]'}else{'[MISSING]'}) $c"
  Add-Content -LiteralPath $Manifest -Value $line
  Write-Host $line -ForegroundColor $(if ($exists) { "Green" } else { "Red" })
  if (-not $exists) { $ok = $false }
}

$readme = Join-Path $ManifestDir "README.txt"
@"
Desktop / PropORACLE organize ($Stamp)

LEFT IN PLACE (required for site/app):
  Desktop\PropORACLE              feature worktree (Cursor)
  Desktop\PropORACLE_main_cp      main / Railway publish worktree

ARCHIVED HERE:
  PropORACLE_old_clones\   unused clones (main_fix, publish_jul24, etc.)
  PropORACLE_zip_backups\  Apr 2026 full zips (~3.4GB) - safe to delete later if unneeded
  Desktop_misc\            loose logs/screenshots/exes
  Tools_scripts\           AHK / RawAccel / bat helpers
  Finance_docs\            bank/tax files
  Desktop_spill\           leftover Desktop outputs/docs/Sports folders

PropORACLE internal:
  logs\scratch\            one-off _*.py helpers
  logs\archive_*\          txt logs older than 14 days
  outputs\_backups\        combined_slate *.bak* workbooks

Desktop folders created:
  Games\                   game .url shortcuts
  Shortcuts\               less-used app shortcuts

Manifest: $Manifest
"@ | Set-Content -LiteralPath $readme -Encoding UTF8

Write-Host "`nManifest: $Manifest" -ForegroundColor Cyan
Write-Host "README:   $readme" -ForegroundColor Cyan
if (-not $Execute) {
  Write-Host "`nPreview done. Apply with:" -ForegroundColor Cyan
  Write-Host "  powershell -File `"$PSCommandPath`" -Execute -DeleteOfficeLocks" -ForegroundColor White
} elseif ($ok) {
  Write-Host "`nOrganize complete. Live PropORACLE roots verified OK." -ForegroundColor Green
} else {
  Write-Host "`nOrganize finished with MISSING path(s) - review manifest!" -ForegroundColor Red
  exit 1
}
