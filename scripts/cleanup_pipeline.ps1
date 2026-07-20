# ============================================================
#  PIPELINE FOLDER CLEANUP SCRIPT
#  Run from: PropOracle root
#
#  Usage:
#    .\cleanup_pipeline.ps1           # Preview mode (safe, no changes)
#    .\cleanup_pipeline.ps1 -Execute  # Actually run the cleanup
# ============================================================
param(
    [switch]$Execute
)

# Script lives in scripts\; project root is the parent folder.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Root   = Split-Path -Parent $ScriptDir
$NBADir = Join-Path $Root "Sports\NBA"
if (-not (Test-Path $NBADir)) { $NBADir = Join-Path $Root "NBA" }
$Date   = Get-Date -Format "yyyy-MM-dd"

if (-not $Execute) {
    Write-Host ""
    Write-Host "=====================================================" -ForegroundColor Cyan
    Write-Host "  PREVIEW MODE - No changes will be made" -ForegroundColor Cyan
    Write-Host "  Run with -Execute to apply cleanup" -ForegroundColor Cyan
    Write-Host "=====================================================" -ForegroundColor Cyan
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "=====================================================" -ForegroundColor Yellow
    Write-Host "  EXECUTE MODE - Applying cleanup now..." -ForegroundColor Yellow
    Write-Host "=====================================================" -ForegroundColor Yellow
    Write-Host ""
}

function Do-Action {
    param([string]$Label, [string]$Type, [string]$From, [string]$To = "")

    if ($Type -eq "DELETE") {
        Write-Host "  [DELETE] $Label" -ForegroundColor Red
    } elseif ($Type -eq "MOVE") {
        Write-Host "  [MOVE]   $Label" -ForegroundColor Yellow
    } else {
        Write-Host "  [MKDIR]  $Label" -ForegroundColor Green
    }

    if ($From) { Write-Host "           FROM: $From" -ForegroundColor DarkGray }
    if ($To)   { Write-Host "             TO: $To"   -ForegroundColor DarkGray }

    if ($Execute) {
        if ($Type -eq "DELETE") {
            try {
                Remove-Item $From -Force -Recurse -ErrorAction Stop
                Write-Host "           OK - Deleted" -ForegroundColor Green
            } catch {
                Write-Host "           FAILED: $_" -ForegroundColor Red
            }
        } elseif ($Type -eq "MOVE") {
            try {
                $destDir = Split-Path $To -Parent
                if (-not (Test-Path $destDir)) {
                    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
                }
                Move-Item $From $To -Force -ErrorAction Stop
                Write-Host "           OK - Moved" -ForegroundColor Green
            } catch {
                Write-Host "           FAILED: $_" -ForegroundColor Red
            }
        } elseif ($Type -eq "MKDIR") {
            try {
                New-Item -ItemType Directory -Force -Path $From | Out-Null
                Write-Host "           OK - Created" -ForegroundColor Green
            } catch {
                Write-Host "           FAILED: $_" -ForegroundColor Red
            }
        }
    }
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host "[ 1 ] Duplicate tickets_latest files in root + docs\" -ForegroundColor Magenta
Write-Host ""

foreach ($f in @("tickets_latest.html", "tickets_latest.json")) {
    $rootFile = "$Root\$f"
    $docsFile = "$Root\docs\$f"
    if (Test-Path $rootFile) {
        Do-Action "Remove root duplicate: $f" "DELETE" $rootFile
    }
    if (Test-Path $docsFile) {
        Do-Action "Remove docs\ duplicate: $f" "DELETE" $docsFile
    }
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 2 ] combined_slate_tickets_*.xlsx files loose in root" -ForegroundColor Magenta
Write-Host ""

Get-ChildItem "$Root\combined_slate_tickets_*.xlsx" -ErrorAction SilentlyContinue | ForEach-Object {
    $fileDate = $_.BaseName -replace "combined_slate_tickets_", ""
    $destFolder = "$Root\outputs\$fileDate"
    $dest = "$destFolder\$($_.Name)"
    if (Test-Path $dest) {
        Do-Action "Already in outputs\, delete root copy: $($_.Name)" "DELETE" $_.FullName
    } else {
        Do-Action "Move to outputs\$fileDate\: $($_.Name)" "MOVE" $_.FullName $dest
    }
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 3 ] Loose files in outputs\ root (not in dated subfolder)" -ForegroundColor Magenta
Write-Host ""

Get-ChildItem "$Root\outputs\*" -File -ErrorAction SilentlyContinue | ForEach-Object {
    # Keep live "latest" contracts at outputs\ root (UI/API paths).
    if ($_.Name -match '_latest\.(json|xlsx|html|csv)$' -or $_.Name -eq 'combo_table_latest.json') {
        Write-Host "  [KEEP]   Live latest artifact: $($_.Name)" -ForegroundColor DarkCyan
        return
    }
    $matched = $_.Name -match "(\d{4}-\d{2}-\d{2})"
    if ($matched) {
        $fileDate = $Matches[1]
        $destFolder = "$Root\outputs\$fileDate"
        $dest = "$destFolder\$($_.Name)"
        if (Test-Path $dest) {
            Do-Action "Already in dated folder, delete loose copy: $($_.Name)" "DELETE" $_.FullName
        } else {
            Do-Action "Move to outputs\$fileDate\: $($_.Name)" "MOVE" $_.FullName $dest
        }
    } else {
        Do-Action "No date in filename, move to outputs\misc\: $($_.Name)" "MOVE" $_.FullName "$Root\outputs\misc\$($_.Name)"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 4 ] NBA\Result Files\ -> move to outputs\$Date\ResultFiles\" -ForegroundColor Magenta
Write-Host ""

$resultFiles = "$NBADir\Result Files"
if (Test-Path $resultFiles) {
    Get-ChildItem $resultFiles -File -ErrorAction SilentlyContinue | ForEach-Object {
        $dest = "$Root\outputs\$Date\ResultFiles\$($_.Name)"
        Do-Action "Move: $($_.Name)" "MOVE" $_.FullName $dest
    }
    if ($Execute) {
        Start-Sleep -Milliseconds 300
        $remaining = Get-ChildItem $resultFiles -Recurse -File -ErrorAction SilentlyContinue
        if ($remaining.Count -eq 0) {
            Remove-Item $resultFiles -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "  [DELETE] Removed empty Result Files\ folder" -ForegroundColor Red
        }
    }
} else {
    Write-Host "  (not found - skipping)" -ForegroundColor DarkGray
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 5 ] NBA\ui_runner\ duplicate -> delete" -ForegroundColor Magenta
Write-Host ""

$innerUIRunner = "$NBADir\ui_runner"
if (Test-Path $innerUIRunner) {
    Do-Action "Remove duplicate ui_runner inside NBA\" "DELETE" $innerUIRunner
} else {
    Write-Host "  (not found - skipping)" -ForegroundColor DarkGray
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 6 ] __pycache__ in root -> delete" -ForegroundColor Magenta
Write-Host ""

$pycache = "$Root\__pycache__"
if (Test-Path $pycache) {
    Do-Action "Remove __pycache__\" "DELETE" $pycache
} else {
    Write-Host "  (not found - skipping)" -ForegroundColor DarkGray
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 7 ] docs\ folder in root -> delete if empty" -ForegroundColor Magenta
Write-Host ""

$rootDocs = "$Root\docs"
if (Test-Path $rootDocs) {
    $remaining = Get-ChildItem $rootDocs -Recurse -File -ErrorAction SilentlyContinue
    if ($remaining.Count -eq 0) {
        Do-Action "Remove empty docs\ folder" "DELETE" $rootDocs
    } else {
        Write-Host "  docs\ still has $($remaining.Count) file(s) after step 1 cleanup - skipping" -ForegroundColor DarkGray
    }
} else {
    Write-Host "  (not found - skipping)" -ForegroundColor DarkGray
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=====================================================" -ForegroundColor Cyan
if (-not $Execute) {
    Write-Host "  PREVIEW COMPLETE" -ForegroundColor Cyan
    Write-Host "  Run with -Execute to apply all changes" -ForegroundColor Cyan
} else {
    Write-Host "  CLEANUP COMPLETE" -ForegroundColor Green
}
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host ""

