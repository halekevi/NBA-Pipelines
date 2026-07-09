# 🔧 ROOT CAUSE ANALYSIS + FIX: Why 3/2 NBA Games Missing

## The Problem

Your `run_pipeline.ps1` script **automatically uses TODAY'S date** for all operations:

```powershell
# Line 43 in your current script
$Date = Get-Date -Format "yyyy-MM-dd"
```

This means:
- **If you run on 3/1** → it fetches games for 3/1 only
- **If you run on 3/2** → it fetches games for 3/2 only
- **But if you run `-CombinedOnly` on 3/2** → it re-uses the OLD NBA file from 3/1 (which is correct!)

So the 3/2 games NOT appearing is **correct behavior** — they simply weren't in the original pipeline run on 3/1.

---

## Why You're Seeing 3/2 in Combined File

Your `combined_slate_tickets_2026-03-02.xlsx` file **HAS 3/2 games because CBB was run on 3/2**:

```
When run on 3/1:
  NBA pipeline → 3/1 games only
  CBB pipeline → 3/1 games only
  Combined     → 3/1 games only

When run on 3/2:
  NBA pipeline → Uses OLD cached data from 3/1 (via -CombinedOnly)
  CBB pipeline → 3/2 games (fresh run)
  Combined     → 3/1 (NBA) + 3/2 (CBB) ✓ Correct behavior!
```

---

## The Real Issue: Confusion About What Date to Use

**The script is working as designed, but it's confusing because:**

1. You ran the full pipeline on **3/1** → got 3/1 games
2. You ran with `-CombinedOnly` on **3/2** → combined old NBA (3/1) with new CBB (3/2)
3. You expected NBA to have 3/2, but it doesn't need to

**What you probably want:** To force the pipeline to re-fetch NBA games for 3/2.

---

## Solutions

### Solution 1: Re-Run Full NBA Pipeline for 3/2 (Recommended)

```powershell
# Delete old NBA output so -CombinedOnly doesn't re-use it
Remove-Item "NbaPropPipelineA\step8_all_direction_clean.xlsx"

# Re-run FULL pipeline (this will use TODAY's date = 3/2)
.\run_pipeline.ps1

# OR run NBA only for 3/2
.\run_pipeline.ps1 -NBAOnly
```

**Why this works:** The current script will use today's date (3/2) automatically.

---

### Solution 2: Use Explicit Date Parameter (Better for Reproducibility)

**Replace your `run_pipeline.ps1` with the fixed version provided.**

The fixed version adds a `-Date` parameter so you can explicitly specify which date to fetch for:

```powershell
# Fetch NBA games for 3/2 specifically
.\run_pipeline.ps1 -Date "2026-03-02" -NBAOnly

# Then combine
.\run_pipeline.ps1 -Date "2026-03-02" -CombinedOnly

# Or do it all in one run
.\run_pipeline.ps1 -Date "2026-03-02"
```

**Key benefit:** You can re-run the pipeline for any date, even historical dates.

---

### Solution 3: Understand the Date Parameter Flow

Currently, `--date` in step4 controls which day to fetch stats FOR:

```powershell
# Line 252 in current script
"--date $Date --days 35"
```

This tells step4:
- `--date 2026-03-02` = "I'm building a slate for 3/2"
- `--days 35` = "Look back 35 days of historical data (to 1/26)"

So ESPN will find games on/before 3/2 but won't have 3/3 data yet (which makes sense).

**The issue:** If you want 3/2 games in your slate, you MUST either:
1. Run on 3/2 (so `Get-Date` returns 3/2), OR
2. Use explicit `-Date "2026-03-02"` parameter

---

## Implementation Guide

### Quick Fix (No Code Changes)

On **3/2**, just run:

```powershell
cd "C:\Users\halek\OneDrive\Desktop\Vision Board\NbaPropPipelines\NBA-Pipelines"

# Option A: Full fresh run
.\run_pipeline.ps1

# Option B: NBA only 
.\run_pipeline.ps1 -NBAOnly

# Then combine
.\run_pipeline.ps1 -CombinedOnly
```

Since you're running on 3/2, `Get-Date` will be 3/2, and everything will include 3/2 games.

---

### Better Fix (Use Provided Script)

1. **Backup your current `run_pipeline.ps1`:**
   ```powershell
   Copy-Item run_pipeline.ps1 run_pipeline_backup.ps1
   ```

2. **Replace with the fixed version** that includes `-Date` parameter

3. **Now you can run for any date:**
   ```powershell
   # 3/2 games
   .\run_pipeline.ps1 -Date "2026-03-02"
   
   # 3/3 games (if it's not 3/3 yet)
   .\run_pipeline.ps1 -Date "2026-03-03"
   
   # 3/1 games (go back in time)
   .\run_pipeline.ps1 -Date "2026-03-01"
   ```

---

## Why Your Current Script Works

The script is actually **correct and well-designed**. Using `Get-Date` is good because:
- ✅ Automated daily runs always use today's date
- ✅ No hardcoding needed
- ✅ Natural workflow: run in morning, get today's props

The confusion arises because:
- ❌ You can't easily re-run for a different date
- ❌ `-CombinedOnly` mode confuses things (mixes dates)
- ❌ No explicit date parameter

---

## Summary

| Situation | What's Happening | What to Do |
|-----------|------------------|-----------|
| Run on 3/1, get 3/1 games | ✓ Correct | Normal operation |
| Run on 3/2, get 3/2 games | ✓ Correct | Normal operation |
| Run `-CombinedOnly` on 3/2, see mixed dates | ✓ Correct | This is expected (old NBA + new CBB) |
| Want fresh 3/2 for both | ❌ Need full rerun | Delete `step8_all_direction_clean.xlsx` then rerun |
| Want to run for arbitrary date | ❌ Not possible | Use fixed `run_pipeline.ps1` with `-Date` param |

---

## Files Provided

1. **DIAGNOSTIC_REPORT.md** — What's actually in your files
2. **FIX_GUIDE.md** — General troubleshooting steps
3. **run_pipeline_FIXED.ps1** — Enhanced script with explicit date parameter
4. **THIS FILE** — Full technical explanation

---

## Questions?

- **"But I want 3/2 games NOW"** → Run `.\run_pipeline.ps1` today (3/2)
- **"I want to backfill earlier dates"** → Use fixed script with `-Date` parameter
- **"Why does combined have 3/2 but NBA doesn't?"** → Because CBB was re-run on 3/2
- **"Do I need to change anything?"** → Only if you want explicit date control; otherwise it's working fine

You're all set! 🚀
