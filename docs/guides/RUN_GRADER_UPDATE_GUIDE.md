# PropOracle run_grader.ps1 Update Guide
## How to Integrate Advanced Multi-Sport Graders into Root Script

**Status**: OPTIONAL UPDATE (backward compatible)  
**Date**: March 2026  
**Complexity**: Medium (modular changes)  

---

## Quick Answer

**YES** - The `run_grader.ps1` file in the root folder should be updated to support:
1. ✅ Advanced graders (opponent analysis, confidence scoring)
2. ✅ Sport-specific recommendation files
3. ✅ HTML visual dashboards per sport
4. ✅ Backward compatibility (legacy graders still work)

---

## What Changes

### Current State (Legacy)
```powershell
# Only basic HIT/MISS grading
.\run_grader.ps1 -NBAOnly
  Output: nba_graded_2026-02-21.xlsx (basic grades)

# All sports use same "slate_grader.py"
Run-Py "NHL Grade" ... slate_grader.py --sport NHL ...
```

### After Update (Advanced)
```powershell
# Advanced grading with recommendations
.\run_grader.ps1 -NBAOnly
  Output: graded_nba_2026-02-21.xlsx (with confidence scores)
          grades_report_nba_2026-02-21.html (visual dashboard)
          
# NHL gets dedicated grader
Run-Py "NHL Advanced Grade" ... nhl_grader_advanced.py ...
  Output: graded_nhl_2026-02-21.xlsx
          nhl_pick_recommendations_2026-02-21.csv
          nhl_opponent_analysis_2026-02-21.csv
```

---

## Step-by-Step Update

### Step 1: Copy Advanced Grader Scripts to Root

Create folder structure:
```
PropOracle/
├── grader/                          (NEW FOLDER)
│   ├── unified_grader_with_analytics.py
│   ├── nhl_grader_advanced.py
│   └── soccer_grader_advanced.py
├── run_grader.ps1                   (UPDATED)
├── run_pipeline.ps1
└── ... (existing folders)
```

**Commands**:
```powershell
# Create grader folder if not exists
if (!(Test-Path "PropOracle\grader")) { New-Item -ItemType Directory -Path "PropOracle\grader" }

# Copy advanced graders (from outputs folder)
Copy-Item "graded_files\unified_grader_with_analytics.py" "PropOracle\grader\"
Copy-Item "graded_files\nhl_grader_advanced.py" "PropOracle\grader\"
Copy-Item "graded_files\soccer_grader_advanced.py" "PropOracle\grader\"
```

### Step 2: Update run_grader.ps1

**Option A: Replace Entire File** (Recommended)
```powershell
# Backup current
Copy-Item "PropOracle\run_grader.ps1" "PropOracle\run_grader_BACKUP.ps1"

# Copy updated version
Copy-Item "graded_files\run_grader_UPDATED.ps1" "PropOracle\run_grader.ps1"
```

**Option B: Manual Integration** (Cautious)

See "Key Changes" section below for specific line changes.

### Step 3: Verify Structure

```powershell
# Check folder layout
ls -Recurse PropOracle\grader\*.py
# Should show 3 files: unified, nhl_advanced, soccer_advanced

# Check run_grader.ps1 has new variables
grep -n "AdvancedMode" PropOracle\run_grader.ps1
# Should show ~4 hits
```

### Step 4: Test Updated Script

```powershell
# Test with NHL (uses new advanced grader)
cd PropOracle
.\run_grader.ps1 -NHLOnly -Date 2026-02-21

# Check outputs
ls outputs\2026-02-21\*nhl*
# Should show:
#   graded_nhl_2026-02-21.xlsx
#   nhl_opponent_analysis_2026-02-21.csv
#   nhl_pick_recommendations_2026-02-21.csv
```

---

## Key Changes Made

### 1. Add Advanced Grader Paths (New Lines ~15-18)

**Add after existing path definitions**:
```powershell
$GraderDir = "$Root\grader"  # NEW: advanced graders location

# ── Advanced graders (NEW) ──
$UnifiedGrader   = "$GraderDir\unified_grader_with_analytics.py"
$NHLAdvGrader    = "$GraderDir\nhl_grader_advanced.py"
$SoccerAdvGrader = "$GraderDir\soccer_grader_advanced.py"

# ── Legacy graders (backward compat) ──
$LegacySlateGrader = "$Root\scripts\grading\slate_grader.py"
```

### 2. Add Mode Parameters (New Lines ~10-11)

**Add to param block**:
```powershell
param(
    # ... existing params ...
    [switch]$AdvancedMode = $true,  # Default: use advanced graders
    [switch]$LegacyMode             # Optional: use old graders
)
```

### 3. Add Auto-Fallback Logic (New Lines ~35-40)

**Add after parameter validation**:
```powershell
# Force legacy mode if advanced graders don't exist
if ((-not (Test-Path $UnifiedGrader)) -or (-not (Test-Path $NHLAdvGrader))) {
    Write-Host "  NOTE: Advanced graders not found. Using legacy mode." -ForegroundColor Yellow
    $LegacyMode = $true
    $AdvancedMode = $false
}
```

### 4. Update Header Output (New Lines ~44-47)

**Replace existing header**:
```powershell
Write-Host "  PropOracle ADVANCED GRADER  |  $Date  |  $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Cyan
if ($AdvancedMode -and -not $LegacyMode) {
    Write-Host "  Mode: ADVANCED (opponent analysis, confidence scoring)" -ForegroundColor Green
} else {
    Write-Host "  Mode: LEGACY (basic HIT/MISS grading)" -ForegroundColor Yellow
}
```

### 5. NHL Grading Block (Lines ~165-197)

**Replace entire NHL section**:
```powershell
# =============================================================================
#  NHL GRADING (ADVANCED)
# =============================================================================
if ($NHLOnly -or (-not $NBAOnly -and -not $CBBOnly -and -not $SoccerOnly)) {
    Write-Host "[ NHL GRADING ]" -ForegroundColor Magenta
    Write-Host ""

    $NHLSlate = "$NHLDir\step8_nhl_direction_clean.xlsx"
    
    if (Test-Path $NHLSlate) {
        $ok = Run-Py "NHL Fetch Actuals" $Root $FetchActuals @("--sport", "NHL", "--date", $Date, "--output", $NHLActuals)

        if ($ok -or (Test-Path $NHLActuals)) {
            if ($AdvancedMode -and -not $LegacyMode -and (Test-Path $NHLAdvGrader)) {
                # Use advanced NHL grader with opponent analysis
                $OppCache = "$NHLDir\s6a_nhl_opp_stats_cache.csv"
                if (Test-Path $OppCache) {
                    Run-Py "NHL Advanced Grade (with opponent analysis)" $Root $NHLAdvGrader `
                        @("--date", $Date, "--actuals", $NHLActuals, "--slate", $NHLSlate, `
                          "--opp-cache", $OppCache, "--output-dir", $DateDir)
                } else {
                    Run-Py "NHL Advanced Grade (no opponent cache)" $Root $NHLAdvGrader `
                        @("--date", $Date, "--actuals", $NHLActuals, "--slate", $NHLSlate, "--output-dir", $DateDir)
                }
                if (Test-Path "$DateDir\graded_nhl_$Date.xlsx") { 
                    Write-Host "  NHL advanced graded -> graded_nhl_$Date.xlsx" -ForegroundColor Green 
                }
                if (Test-Path "$DateDir\nhl_pick_recommendations_$Date.csv") { 
                    Write-Host "  Recommendations -> nhl_pick_recommendations_$Date.csv" -ForegroundColor Green 
                }
            } else {
                # Legacy grader (backward compat)
                Run-Py "NHL Grade (Legacy)" $Root $LegacySlateGrader `
                    @("--sport", "NHL", "--slate", $NHLSlate, "--actuals", $NHLActuals, `
                      "--output", "$DateDir\nhl_graded_$Date.xlsx", "--date", $Date)
            }
        } else {
            Write-Host "  Skipping NHL - actuals fetch failed" -ForegroundColor Yellow
        }
    }
    Write-Host ""
}
```

### 6. Soccer Grading Block (Lines ~200-233)

**Replace entire Soccer section** (similar to NHL):
```powershell
# =============================================================================
#  SOCCER GRADING (ADVANCED)
# =============================================================================
if ($SoccerOnly -or (-not $NBAOnly -and -not $CBBOnly -and -not $NHLOnly)) {
    Write-Host "[ SOCCER GRADING ]" -ForegroundColor Magenta
    Write-Host ""

    $SoccerSlate = "$SoccerDir\step8_soccer_direction_clean.xlsx"
    
    if (Test-Path $SoccerSlate) {
        $ok = Run-Py "Soccer Fetch Actuals" $Root $FetchActuals @("--sport", "Soccer", "--date", $Date, "--output", $SoccerActuals)

        if ($ok -or (Test-Path $SoccerActuals)) {
            if ($AdvancedMode -and -not $LegacyMode -and (Test-Path $SoccerAdvGrader)) {
                # Use advanced soccer grader
                $OppCache = "$SoccerDir\s6a_soccer_opp_stats_cache.csv"
                if (Test-Path $OppCache) {
                    Run-Py "Soccer Advanced Grade" $Root $SoccerAdvGrader `
                        @("--date", $Date, "--actuals", $SoccerActuals, "--slate", $SoccerSlate, `
                          "--opp-cache", $OppCache, "--output-dir", $DateDir)
                } else {
                    Run-Py "Soccer Advanced Grade" $Root $SoccerAdvGrader `
                        @("--date", $Date, "--actuals", $SoccerActuals, "--slate", $SoccerSlate, "--output-dir", $DateDir)
                }
                if (Test-Path "$DateDir\graded_soccer_$Date.xlsx") { 
                    Write-Host "  Soccer advanced graded" -ForegroundColor Green 
                }
            } else {
                # Legacy grader
                Run-Py "Soccer Grade (Legacy)" $Root $LegacySlateGrader `
                    @("--sport", "Soccer", "--slate", $SoccerSlate, "--actuals", $SoccerActuals, `
                      "--output", "$DateDir\soccer_graded_$Date.xlsx", "--date", $Date)
            }
        }
    }
    Write-Host ""
}
```

### 7. Update Summary Section (Lines ~287-308)

**Add recommendation output display**:
```powershell
$found = Get-ChildItem $DateDir -Filter "*graded*" -ErrorAction SilentlyContinue
if ($found) {
    Write-Host "  Output: $DateDir" -ForegroundColor Green
    $found | ForEach-Object { Write-Host "    $($_.Name)" -ForegroundColor Green }
    Write-Host ""
    Write-Host "  Recommendations & Analysis:" -ForegroundColor Green
    $recs = Get-ChildItem $DateDir -Filter "*recommendation*" -ErrorAction SilentlyContinue
    if ($recs) {
        $recs | ForEach-Object { Write-Host "    $($_.Name)" -ForegroundColor Green }
    }
}
```

### 8. Update HTML Builder (Lines ~310-320)

**Add note about advanced analytics**:
```powershell
if ($AdvancedMode -and -not $LegacyMode) {
    Write-Host "  Advanced analytics HTML will be generated by individual graders" -ForegroundColor Green
    Write-Host "  Check outputs for:" -ForegroundColor Green
    Write-Host "    - grades_report_[sport]_$Date.html (visual dashboards)" -ForegroundColor DarkGray
    Write-Host "    - [sport]_opponent_analysis_$Date.csv (consistent hitters)" -ForegroundColor DarkGray
    Write-Host "    - [sport]_pick_recommendations_$Date.csv (actionable plays)" -ForegroundColor DarkGray
} else {
    # Legacy HTML builder (existing code)
    ...
}
```

---

## Usage After Update

### Default (Advanced Mode)
```powershell
.\run_grader.ps1
# Uses advanced graders for all sports
# Generates recommendations, dashboards, opponent analysis
```

### Legacy Mode (if needed)
```powershell
.\run_grader.ps1 -LegacyMode
# Uses old graders (basic HIT/MISS only)
# For backward compatibility
```

### Single Sport (Advanced)
```powershell
.\run_grader.ps1 -NHLOnly
# Advanced NHL grader with:
#   - Confidence scoring
#   - Opponent analysis
#   - Goalie vs skater handling
#   - Recommendations CSV

.\run_grader.ps1 -SoccerOnly
# Advanced Soccer grader with:
#   - Multi-league calibration
#   - Position-specific analysis
#   - League edges
#   - Recommendations CSV
```

### Specific Date
```powershell
.\run_grader.ps1 -Date 2026-02-21
# Grade that specific date (advanced mode)

.\run_grader.ps1 -Date 2026-02-21 -NHLOnly
# NHL only for that date
```

---

## Output Files After Update

### Per Sport, Per Day

**NHL**:
```
outputs/2026-02-21/
  ├── graded_nhl_2026-02-21.xlsx              (grades + confidence)
  ├── nhl_opponent_analysis_2026-02-21.csv    (consistent hitters)
  ├── nhl_pick_recommendations_2026-02-21.csv (actionable plays)
  └── grades_report_nhl_2026-02-21.html       (visual dashboard)
```

**Soccer**:
```
outputs/2026-02-21/
  ├── graded_soccer_2026-02-21.xlsx
  ├── soccer_position_analysis_2026-02-21.csv
  ├── soccer_recommendations_2026-02-21.csv
  ├── soccer_league_calibration_2026-02-21.csv
  └── grades_report_soccer_2026-02-21.html
```

**NBA/CBB** (via unified grader):
```
outputs/2026-02-21/
  ├── graded_nba_2026-02-21.xlsx
  ├── graded_cbb_2026-02-21.xlsx
  ├── grades_report_nba_2026-02-21.html
  └── grades_report_cbb_2026-02-21.html
```

---

## Backward Compatibility

✅ **Fully backward compatible**:
- Old legacy graders still work if advanced ones missing
- Script auto-detects and falls back
- Existing output formats unchanged (just enhanced)
- No breaking changes to pipeline

**Auto-Fallback Logic**:
```powershell
if ((-not (Test-Path $UnifiedGrader)) -or (-not (Test-Path $NHLAdvGrader))) {
    Write-Host "Advanced graders not found. Using legacy mode." -ForegroundColor Yellow
    $LegacyMode = $true
    $AdvancedMode = $false
}
```

---

## Troubleshooting

### Issue: "Advanced graders not found" warning

**Fix**:
```powershell
# Verify files exist
ls PropOracle/grader/*.py

# Should show:
#   - unified_grader_with_analytics.py
#   - nhl_grader_advanced.py
#   - soccer_grader_advanced.py

# If missing, copy from outputs:
cp grader_files/*.py PropOracle/grader/
```

### Issue: "Can't find opponent cache"

**Expected behavior**: Script will continue without opponent cache
- Opponent analysis features disabled
- Basic confidence scoring still works
- Output files still generated

**To enable opponent analysis**:
```powershell
# Run S6a first to generate opponent cache
py S6a_attach_opponent_stats.py ...

# Then run grader
.\run_grader.ps1 -NHLOnly
# Will detect s6a_nhl_opp_stats_cache.csv and use it
```

### Issue: Script runs but no recommendations CSV

**Possible causes**:
1. Opponent cache missing (expected, recommendations less useful)
2. Python version (need 3.8+)
3. pandas/numpy not installed

**Fix**:
```powershell
# Check Python version
py --version
# Should be 3.8+

# Install dependencies
pip install pandas numpy openpyxl matplotlib

# Try again
.\run_grader.ps1 -NHLOnly
```

---

## Comparison: Before vs After

| Feature | Before (Legacy) | After (Advanced) |
|---------|-----------------|------------------|
| HIT/MISS grading | ✅ | ✅ |
| Confidence scoring | ❌ | ✅ (0-100) |
| Opponent history | ❌ | ✅ |
| Recommendations | ❌ | ✅ (10+ per day) |
| Visual dashboards | ❌ | ✅ (HTML) |
| Goalie-specific logic | ❌ | ✅ (NHL) |
| League calibration | ❌ | ✅ (Soccer) |
| Position analysis | ❌ | ✅ (Soccer) |
| Backward compatible | N/A | ✅ |

---

## Implementation Timeline

| Step | Time | Action |
|------|------|--------|
| 1 | 5 min | Create `PropOracle/grader/` folder |
| 2 | 2 min | Copy 3 advanced grader scripts |
| 3 | 10 min | Update `run_grader.ps1` (or replace) |
| 4 | 5 min | Test with NHL only |
| 5 | 5 min | Test with Soccer only |
| 6 | 5 min | Verify outputs in folder |

**Total time**: ~30 minutes

---

## Summary

**Should you update run_grader.ps1?**

✅ **YES** - If you want:
- Opponent-specific recommendations
- Confidence scoring for picks
- Visual analytics dashboards
- Sport-specific advanced logic (goalie handling, league calibration)

❌ **NO** - If you:
- Only need basic HIT/MISS tracking
- Can't update script right now
- Want to stay with legacy system

**Either way**: Both systems work. Update whenever convenient (backward compatible).

---

**Files Provided**:
- `run_grader_UPDATED.ps1` - Complete updated version (ready to use)
- This guide - Step-by-step instructions

**Next Step**: Copy updated script or follow manual changes above.
