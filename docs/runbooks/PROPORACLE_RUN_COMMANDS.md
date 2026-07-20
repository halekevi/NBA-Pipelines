# propORacle Run Commands (PowerShell)

This is a single reference for the most common PowerShell run commands in this repo.

## Open PowerShell in Project Root

```powershell
cd "H:\halek\ProfileFromC\Desktop\PropORACLE"
```

## Main Pipeline (`run_pipeline.ps1` at repo root)

```powershell
# Full parallel run (NBA + CBB + NHL + Soccer + Combined)
.\run_pipeline.ps1

# Specific date
.\run_pipeline.ps1 -Date 2026-03-20

# Sport-only runs
.\run_pipeline.ps1 -NBAOnly
.\run_pipeline.ps1 -CBBOnly
.\run_pipeline.ps1 -NHLOnly
.\run_pipeline.ps1 -MLBOnly
.\run_pipeline.ps1 -SoccerOnly
.\run_pipeline.ps1 -WNBAOnly

# Combined slate only (from existing sport outputs)
.\run_pipeline.ps1 -CombinedOnly

# Skip step1 fetch for whichever sport(s) run
.\run_pipeline.ps1 -SkipFetch
.\run_pipeline.ps1 -NBAOnly -SkipFetch
.\run_pipeline.ps1 -NHLOnly -SkipFetch
.\run_pipeline.ps1 -SoccerOnly -SkipFetch

# Cache controls (NBA ESPN cache)
.\run_pipeline.ps1 -RefreshCache
.\run_pipeline.ps1 -CacheAgeDays 7

# Optional API key override for game context step
.\run_pipeline.ps1 -NBAOnly -OddsApiKey "YOUR_ODDS_API_KEY"
```

## Grader Runner (`scripts/run_grader.ps1`)

```powershell
# Grade yesterday (default)
.\scripts\run_grader.ps1

# Grade specific date
.\scripts\run_grader.ps1 -Date 2026-03-19
```

## WNBA Runner (`scripts/run_wnba_pipeline.ps1`)

```powershell
.\scripts\run_wnba_pipeline.ps1
.\scripts\run_wnba_pipeline.ps1 -Date 2026-07-15
.\scripts\run_wnba_pipeline.ps1 -RefreshCache
.\scripts\run_wnba_pipeline.ps1 -SkipFetch
```

## Soccer Runner (`Soccer/scripts/run_soccer_pipeline.ps1`)

```powershell
.\Soccer\scripts\run_soccer_pipeline.ps1
.\Soccer\scripts\run_soccer_pipeline.ps1 -SkipFetch
.\Soccer\scripts\run_soccer_pipeline.ps1 -LeagueId 1234
.\Soccer\scripts\run_soccer_pipeline.ps1 -NTeams 20
```

## Daily Grades (`scripts/daily_grades.ps1`)

```powershell
.\scripts\daily_grades.ps1
.\scripts\daily_grades.ps1 -Date 2026-03-19
```

## Ticket eval backfill (`scripts/backfill_ticket_evals.ps1`)

```powershell
.\scripts\backfill_ticket_evals.ps1
.\scripts\backfill_ticket_evals.ps1 -Date 2026-04-01
```

## Legacy UI patch (`scripts/patch_slateiq.ps1`)

One-off index/app patcher; requires `archive\root-text\patch_replacement.txt`. Run from repo root after pulling:

```powershell
.\scripts\patch_slateiq.ps1
```

## Register Scheduled Tasks (`scripts/Register_Daily_Task.ps1`)

After moving the repo (e.g. from OneDrive to `H:\halek\ProfileFromC\Desktop\PropORACLE`), open **elevated** PowerShell **in that folder** and re-run this script so every task action points at the new path.

```powershell
# Run once in elevated PowerShell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
cd "H:\halek\ProfileFromC\Desktop\PropORACLE"
.\scripts\Register_Daily_Task.ps1

# Registered tasks (see scripts\Register_Daily_Task.ps1):
#  - PropOracle - Tennis Early 3AM
#  - PropOracle - Daily 5AM
#  - PropOracle - Refresh 8AM / 9AM / 1030AM / 1PM  (run_refresh_with_log.ps1 → run_nba_late_fetch.ps1)
#  - PropOracle - Payout CDP @ 11:00
# Ops overview: docs\guides\DAILY_OPS_OVERVIEW.md

# Inspect what Windows will actually run (look for old OneDrive paths)
schtasks /query /fo LIST /v | findstr /i "PropOracle PropORACLE"

# Manual kick
Start-ScheduledTask -TaskName "PropOracle - Refresh 1030AM"
pwsh -NoProfile -File .\scripts\run_refresh_with_log.ps1 -RunLabel MANUAL_CDP_CATCHUP

# Check task status
Get-ScheduledTask | Where-Object TaskName -like "PropOracle -*" | Select TaskName, State
Get-ScheduledTaskInfo -TaskName "PropOracle - Refresh 9AM" | Select LastRunTime, LastTaskResult

# Remove all PropOracle tasks
Get-ScheduledTask | Where-Object TaskName -like "PropOracle -*" | ForEach-Object {
  Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
}
```

## CDP / fail-fast step1 (DataDome)

Keep Chrome on `--remote-debugging-port=9222` with a warmed PrizePicks board tab.

```powershell
# Soccer
py -3.14 .\Sports\Soccer\scripts\step1_fetch_prizepicks_soccer.py `
  --date 2026-07-20 --output .\outputs\2026-07-20\soccer\step1_soccer_props.csv `
  --fail-fast --cdp http://127.0.0.1:9222

# Tennis
py -3.14 .\Sports\Tennis\scripts\step1_fetch_prizepicks_tennis.py `
  --league_id 5 --output .\outputs\2026-07-20\tennis\step1_tennis_props.csv `
  --fail-fast --replace --cdp http://127.0.0.1:9222

# WNBA (browser-first when CDP listening)
.\scripts\run_wnba_pipeline.ps1 -Date 2026-07-20 -Step1Only -CdpWhenListening

# Then rebuild without re-fetch
.\run_pipeline.ps1 -Date 2026-07-20 -SkipFetch -SkipLivePayoutCapture
```

## Optional Python Direct Commands

These are usually called by the PowerShell runners above:

```powershell
# Build grade HTML directly
py -3.14 .\scripts\grading\build_grades_html.py --date 2026-03-19 --out .\ui_runner\templates

# Build combined slate tickets directly
py -3.14 .\scripts\combined_slate_tickets.py --help

# Ticket evaluation HTML (after pipeline)
py -3.14 .\scripts\build_ticket_eval.py --date 2026-04-04

# PrizePicks entries harvest (browser)
py -3.14 -u .\scripts\capture_entries.py
```

## Notes

- Folder map and what to edit after moving files: [../PROJECT_LAYOUT.md](../PROJECT_LAYOUT.md).
- Daily cadence / audiences / hang recovery: [../guides/DAILY_OPS_OVERVIEW.md](../guides/DAILY_OPS_OVERVIEW.md).
- Date format: `yyyy-MM-dd` is safest.
- `-SkipFetch` assumes prior step1 output files already exist.
- `no_slate` in `outputs/<date>/pipeline_slate_status.json` can mean PrizePicks has no **same-day** games (Soccer often posts tomorrow’s board first).
- Full run auto-combines available sport outputs into final tickets.
