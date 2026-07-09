# 🔍 Diagnostic Report: Missing 3/2 NBA Games

## Summary
Your `combined_slate_tickets_2026-03-02.xlsx` file **DOES contain 3/2 games**, but they are **ALL from CBB (College Basketball)**, not NBA.

The **NBA games only go through 3/1**.

## Root Cause
The issue is NOT in `combined_slate_tickets.py` or `step8_add_direction_context.py`.  
The issue is **earlier in the NBA pipeline**.

## File Comparison

### combined_slate_tickets_2026-03-02.xlsx (Full Slate)
- **NBA props**: 4,889 total
  - 3/1 games: 4,889 props ✅
  - 3/2 games: **0 props** ❌
  
- **CBB props**: 298 total  
  - 3/1 games: 0 props
  - 3/2 games: 298 props ✅

### step8_all_direction_clean.xlsx (ALL sheet)
- Total: 8,204 props
- **All 3/1 games only** — no 3/2

---

## What This Means

When you run `combined_slate_tickets.py`, it reads:
1. **NBA input**: `step8_all_direction_clean.xlsx` → Only has 3/1
2. **CBB input**: `step6_ranked_cbb.xlsx` → Has 3/2  
3. **Combined output**: Has both 3/1 (from NBA) + 3/2 (from CBB)

---

## Where the 3/2 NBA Games Are Missing

The 3/2 NBA games should be populated by:

```
step1 → step2 → step3 → step4 → step5 → step6 → step7 → step8
                                                         ↑
                                      Final NBA output (step8_all_direction_clean.xlsx)
                                      ❌ Only has 3/1 games
```

### The Problem: Your PowerShell script (run_pipeline.ps1)

Your PowerShell pipeline likely specifies:
- A **slate date** (e.g., `--date 2026-03-01`)
- A **game date** or **data range** that filters out 3/2

**Common culprits:**

1. **Step 4 date filtering** - It uses `--date YYYY-MM-DD` to define a lookback window:
   ```powershell
   py -3.14 step4_attach_player_stats_espn_cache.py --date 2026-03-01  # <-- Only 3/1
   ```
   
   Should be:
   ```powershell
   py -3.14 step4_attach_player_stats_espn_cache.py --date 2026-03-02  # <-- Include 3/2
   ```

2. **Step 3 or earlier** filtering props by game date

3. **ESPN API/Sportsbook** not returning 3/2 game lines yet (most likely!)

---

## Solution

### Quick Check
1. What date are you passing to your PowerShell script?
   ```powershell
   .\run_pipeline.ps1 0  # What is your --date parameter?
   ```

2. Check when ESPN/your sportsbook publishes 3/2 lines:
   - Many books don't release lines for 3/2 games until 3/1 evening
   - If the slate generator ran yesterday (3/1), it wouldn't have 3/2 games

### Fix
**If you want 3/2 games:**
1. Make sure ESPN has published 3/2 game lines
2. Update your PowerShell script to use `--date 2026-03-02` instead of `2026-03-01`
3. Re-run the full pipeline

**Example:**
```powershell
# Old (only 3/1 games)
.\run_pipeline.ps1 0 --date 2026-03-01

# New (includes 3/2 games)
.\run_pipeline.ps1 0 --date 2026-03-02
```

---

## Verification

Once you re-run with the correct date, you should see:
- ✅ `step8_all_direction_clean.xlsx` contains 3/2 games
- ✅ `combined_slate_tickets_2026-03-02.xlsx` NBA Slate has both 3/1 AND 3/2 games

---

## Notes

- **CBB is working correctly** — it has 3/2 games
- **Your combined_slate_tickets.py is working correctly** — it merges NBA + CBB properly
- **The issue is purely NBA game availability** in the earlier pipeline steps
