# ✅ How to Fix: Get 3/2 NBA Games in Your Pipeline

## Problem Summary
- Your NBA slate ONLY has 3/1 games
- CBB has 3/2 games (working correctly)
- The issue is in how you're calling step4 (or earlier steps)

---

## Step 1: Find Your PowerShell Script

Look for `run_pipeline.ps1` or wherever you run the NBA pipeline. It probably looks like:

```powershell
.\step1_fetch_salaries.ps1 --date 2026-03-01
py -3.14 step2_add_lines.py --date 2026-03-01
py -3.14 step3_add_defense.py --date 2026-03-01
py -3.14 step4_attach_player_stats_espn_cache.py --date 2026-03-01
```

---

## Step 2: Change the Date to 3/2

**IMPORTANT:** The `--date` parameter should match your target slate date:

```powershell
# OLD ❌
py -3.14 step4_attach_player_stats_espn_cache.py --date 2026-03-01

# NEW ✅  
py -3.14 step4_attach_player_stats_espn_cache.py --date 2026-03-02
```

Also check **all other Python scripts** — they likely have `--date` parameters too:

```powershell
.\run_pipeline.ps1 0 --date 2026-03-02  # OR
python step4_attach_player_stats_espn_cache.py --date 2026-03-02 --slate ...
```

---

## Step 3: Verify ESPN Has 3/2 Game Lines

**CRITICAL:** ESPN might not have published 3/2 lines yet!

Run this to check:

```powershell
# Windows PowerShell
$date = "2026-03-02"
$url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=$date"
(Invoke-WebRequest $url).Content | ConvertFrom-Json | jq '.events | length'
```

If you get **0 events**, ESPN doesn't have 3/2 games published yet. Wait and retry later.

---

## Step 4: Re-Run the Pipeline

After changing the date, run:

```powershell
cd C:\Users\halek\OneDrive\Desktop\Vision Board\NbaPropPipelines\NBA-Pipelines
.\run_pipeline.ps1 0  # Runs with fresh data (no cache)
```

Or if you're using manual step calls:

```powershell
py -3.14 step4_attach_player_stats_espn_cache.py --date 2026-03-02 --slate step3_with_defense.csv --out step4_with_stats.csv
py -3.14 step5_with_injury_status.py --input step4_with_stats.csv --output step5_injuries.csv
py -3.14 step6_with_team_role_context.py --input step5_injuries.csv --output step6_team_role.csv
py -3.14 step7_rank_props.py --input step6_team_role.csv --output step7_ranked_props.xlsx
py -3.14 step8_add_direction_context.py --input step7_ranked_props.xlsx --output step8_all_direction.csv --xlsx step8_all_direction_clean.xlsx
```

---

## Step 5: Verify Success

Check that step8 now has 3/2 games:

```powershell
# Windows PowerShell
$excel = New-Object -ComObject Excel.Application
$wb = $excel.Workbooks.Open("$pwd\step8_all_direction_clean.xlsx")
$ws = $wb.Sheets.Item(1)

# Count rows with "03/02" in Game Time column
$count = 0
for ($i = 2; $i -le $ws.UsedRange.Rows.Count; $i++) {
    if ($ws.Cells($i, 7).Value2 -like "*03/02*") { $count++ }  # Column 7 = Game Time
}

Write-Host "Found $count 3/2 games in step8_all_direction_clean.xlsx"
$excel.Quit()
```

Or simpler - just open the file and search for "03/02".

---

## Troubleshooting

### Issue: Still Only 3/1 Games After Running
**Possible causes:**

1. **Old cache** — Step 4 caches ESPN data. Clear it:
   ```powershell
   Remove-Item nba_espn_boxscore_cache.csv  # Delete the cache file
   .\run_pipeline.ps1 0  # Re-run with fresh ESPN fetch
   ```

2. **Input slate only has 3/1 props** — Check step3_with_defense.csv:
   ```powershell
   # See what dates are in the sportsbook slate
   grep -o "03/[0-9][0-9]" step3_with_defense.csv | sort -u
   ```
   
   If only 03/01, the problem is **earlier** (step1-3), not step4.

3. **ESPN doesn't have 3/2 lines published yet** — Wait a few hours and retry.

### Issue: Date Parameter Not Working
- Make sure you're updating **ALL** Python scripts, not just step4
- Some scripts might have different parameter names (check help):
  ```powershell
  py -3.14 step4_attach_player_stats_espn_cache.py --help
  ```

---

## Summary

| Issue | Cause | Fix |
|-------|-------|-----|
| 3/2 NBA games missing | `--date` parameter set to 2026-03-01 | Change to `--date 2026-03-02` |
| Still missing after fix | Old ESPN cache | Delete `nba_espn_boxscore_cache.csv` and rerun with `--days 0` flag |
| ESPN returning 0 games | Lines not published yet | Wait 2-3 hours and retry |
| CBB has 3/2 but NBA doesn't | NBA pipeline using wrong date | Check CBB script uses `--date 2026-03-02` |

---

## Need More Help?

Share your `run_pipeline.ps1` file and I can show you exactly which lines to change! 🚀
