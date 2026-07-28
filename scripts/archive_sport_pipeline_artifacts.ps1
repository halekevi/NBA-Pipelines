#Requires -Version 5.1
<#
.SYNOPSIS
  Move stale sport-folder pipeline artifacts into data/historical/ without deleting.

.DESCRIPTION
  Keeps historical data for review/analysis while cleaning live sport roots.
  Canonical dated history remains outputs/<YYYY-MM-DD>/.

  Moves (never deletes):
    - Sports/<Sport>/outputs/**          -> data/historical/sport_outputs/<Sport>/
    - Sports/<Sport>/*.bak_*             -> data/historical/sport_root_backups/<Sport>/
    - Stale intermediate step CSVs/XLSX  -> data/historical/sport_root_stale/<Sport>/<mtime-date>/

  Keeps at sport root:
    - step8_*_direction_clean.xlsx (live pointer)
    - step7_*_ranked.xlsx (if present; useful mid-pipeline)
    - caches, scripts, data/, defense summaries, README

.PARAMETER Execute
  Actually move files. Default is preview-only.

.PARAMETER Sports
  Optional sport folder names. Default: all under Sports/.
#>
param(
  [switch]$Execute,
  [string[]]$Sports = @()
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "Sports"))) {
  $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$HistRoot = Join-Path $Root "data\historical"
$Manifest = Join-Path $HistRoot ("archive_manifest_{0}.txt" -f $Stamp)
$OutBackups = Join-Path $HistRoot "sport_outputs"
$RootBaks = Join-Path $HistRoot "sport_root_backups"
$RootStale = Join-Path $HistRoot "sport_root_stale"

function Ensure-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
  }
}

function Move-Safe {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$DestDir,
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
  $line = "[MOVE] $Source -> $dest$(if ($Note) { ' | ' + $Note })"
  Add-Content -LiteralPath $Manifest -Value $line
  Write-Host $line
  if ($Execute) {
    Move-Item -LiteralPath $Source -Destination $dest -Force
  }
  return $true
}

function Move-Tree {
  param(
    [Parameter(Mandatory = $true)][string]$SourceDir,
    [Parameter(Mandatory = $true)][string]$DestDir,
    [string]$Note = ""
  )
  if (-not (Test-Path -LiteralPath $SourceDir)) { return }
  Ensure-Dir $DestDir
  Get-ChildItem -LiteralPath $SourceDir -Force | ForEach-Object {
    $target = Join-Path $DestDir $_.Name
    if (Test-Path -LiteralPath $target) {
      if ($_.PSIsContainer) {
        Move-Tree -SourceDir $_.FullName -DestDir $target -Note $Note
        if ($Execute -and (Test-Path -LiteralPath $_.FullName)) {
          $left = @(Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue)
          if ($left.Count -eq 0) {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
          }
        }
      }
      else {
        Move-Safe -Source $_.FullName -DestDir $DestDir -Note $Note | Out-Null
      }
    }
    else {
      $line = "[MOVE] $($_.FullName) -> $target$(if ($Note) { ' | ' + $Note })"
      Add-Content -LiteralPath $Manifest -Value $line
      Write-Host $line
      if ($Execute) {
        Move-Item -LiteralPath $_.FullName -Destination $target -Force
      }
    }
  }
}

function Test-KeepSportRootFile([string]$Name) {
  $n = $Name.ToLowerInvariant()
  if ($n -like '*.bak_*') { return $false }
  if ($n -match '^step8_.*_direction_clean\.xlsx$') { return $true }
  if ($n -match '^step8_all_direction_clean\.xlsx$') { return $true }
  if ($n -match '^step7_.*_ranked\.xlsx$') { return $true }
  if ($n -match '_espn_cache\.csv$|_id_cache\.csv$|_roster_cache\.csv$') { return $true }
  if ($n -match 'defense_summary') { return $true }
  if ($n -match 'no_espn_debug') { return $true }
  if ($n -match '\.(py|ps1|md|json)$') { return $true }
  if ($n -eq '.gitkeep') { return $true }
  return $false
}

function Test-StaleStepArtifact([string]$Name) {
  $n = $Name.ToLowerInvariant()
  if ($n -like '*.bak_*') { return $false }
  if ($n -match '^step[1-9]_') { return $true }
  if ($n -match '_best_tickets\.xlsx$') { return $true }
  if ($n -match '^_test_|^test_') { return $true }
  return $false
}

Ensure-Dir $HistRoot
Ensure-Dir $OutBackups
Ensure-Dir $RootBaks
Ensure-Dir $RootStale

$hdr = "PropORACLE sport artifact archive  $Stamp  Execute=$Execute"
Set-Content -LiteralPath $Manifest -Value $hdr
Add-Content -LiteralPath $Manifest -Value "Canonical history: outputs/<YYYY-MM-DD>/"
Add-Content -LiteralPath $Manifest -Value ""

if (-not $Execute) {
  Write-Host "PREVIEW ONLY — re-run with -Execute to apply" -ForegroundColor Cyan
}

$sportDirs = @()
if ($Sports -and $Sports.Count -gt 0) {
  foreach ($s in $Sports) {
    $p = Join-Path $Root "Sports\$s"
    if (Test-Path -LiteralPath $p) { $sportDirs += Get-Item -LiteralPath $p }
  }
}
else {
  $sportDirs = @(Get-ChildItem (Join-Path $Root "Sports") -Directory)
}

$movedBytes = [int64]0
$movedCount = 0

foreach ($sportDir in $sportDirs) {
  $sport = $sportDir.Name
  Write-Host "`n=== $sport ===" -ForegroundColor Magenta

  # 1) Entire Sports/<Sport>/outputs tree (skip pointer README)
  $outDir = Join-Path $sportDir.FullName "outputs"
  if (Test-Path -LiteralPath $outDir) {
    $dest = Join-Path $OutBackups $sport
    $toMove = @(Get-ChildItem -LiteralPath $outDir -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -ne "README_HISTORICAL.txt" })
    $files = @(Get-ChildItem -LiteralPath $outDir -Recurse -File -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -ne "README_HISTORICAL.txt" })
    $sizeBefore = ($files | Measure-Object Length -Sum).Sum
    $fileCount = $files.Count
    if ($fileCount -gt 0) {
      Write-Host ("  outputs/ -> historical/sport_outputs/{0}/  ({1} files, {2:N1} MB)" -f $sport, $fileCount, ($sizeBefore / 1MB))
      foreach ($item in $toMove) {
        if ($item.PSIsContainer) {
          $target = Join-Path $dest $item.Name
          if (Test-Path -LiteralPath $target) {
            Move-Tree -SourceDir $item.FullName -DestDir $target -Note "sport outputs tree"
            if ($Execute -and (Test-Path -LiteralPath $item.FullName)) {
              $left = @(Get-ChildItem -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue)
              if ($left.Count -eq 0) {
                Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue
              }
            }
          }
          else {
            $line = "[MOVE] $($item.FullName) -> $target | sport outputs tree"
            Add-Content -LiteralPath $Manifest -Value $line
            Write-Host $line
            if ($Execute) {
              Ensure-Dir $dest
              Move-Item -LiteralPath $item.FullName -Destination $target -Force
            }
          }
        }
        else {
          Move-Safe -Source $item.FullName -DestDir $dest -Note "sport outputs tree" | Out-Null
        }
      }
      $movedBytes += [int64]$sizeBefore
      $movedCount += $fileCount
    }
    # Leave a pointer so accidental writes are obvious
    if ($Execute) {
      Ensure-Dir $outDir
      $pointer = Join-Path $outDir "README_HISTORICAL.txt"
      if (-not (Test-Path -LiteralPath $pointer)) {
        @"
Sports/$sport/outputs has been migrated.

Canonical dated runs:  outputs/<YYYY-MM-DD>/  (and outputs/<date>/$($sport.ToLower())/)
Archived copies:       data/historical/sport_outputs/$sport/

Do not rebuild large dated trees here. Live step8 pointer stays at Sports/$sport/.
"@ | Set-Content -LiteralPath $pointer -Encoding UTF8
      }
    }
  }

  # 2) Root .bak_* next to live files
  $bakDest = Join-Path $RootBaks $sport
  Get-ChildItem -LiteralPath $sportDir.FullName -File -Force |
    Where-Object { $_.Name -like '*.bak_*' } |
    ForEach-Object {
      $movedBytes += $_.Length
      $movedCount += 1
      Move-Safe -Source $_.FullName -DestDir $bakDest -Note "sport-root bak" | Out-Null
    }

  # 3) Stale intermediate step artifacts (not live step8/step7/caches)
  Get-ChildItem -LiteralPath $sportDir.FullName -File -Force |
    Where-Object {
      -not (Test-KeepSportRootFile $_.Name) -and (Test-StaleStepArtifact $_.Name)
    } |
    ForEach-Object {
      $day = $_.LastWriteTime.ToString("yyyy-MM-dd")
      $dest = Join-Path (Join-Path $RootStale $sport) $day
      $movedBytes += $_.Length
      $movedCount += 1
      Move-Safe -Source $_.FullName -DestDir $dest -Note "stale sport-root step" | Out-Null
    }
}

Add-Content -LiteralPath $Manifest -Value ""
Add-Content -LiteralPath $Manifest -Value ("TOTAL files={0} bytes={1} MB={2:N1}" -f $movedCount, $movedBytes, ($movedBytes / 1MB))
Write-Host ("`nDone. files={0} ~{1:N1} MB  manifest={2}" -f $movedCount, ($movedBytes / 1MB), $Manifest) -ForegroundColor Green
if (-not $Execute) {
  Write-Host "Preview only — nothing moved." -ForegroundColor Yellow
}
