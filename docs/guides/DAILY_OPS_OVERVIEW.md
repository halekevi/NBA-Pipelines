# Daily ops overview (audience + program structure)

Living operator overview for **who runs what**, **when**, and **how PrizePicks fetches stay unblocked**. For file contracts see [PROJECT_LAYOUT.md](../PROJECT_LAYOUT.md). For one-screen production knobs see [CURRENT_STATE.md](../CURRENT_STATE.md).

**As of:** 2026-08-24

---

## Audiences

| Audience | Needs | Primary surfaces |
|----------|--------|------------------|
| **Bettor / analyst** | Today’s slate, tickets, grades, income | Web (`ui_runner`), mobile (`mobile/www`) |
| **Operator** | Fresh boards by mid-morning, recover when CDP/HTTP fails | Scheduled tasks + `run_daily.ps1` / `run_refresh_with_log.ps1` |
| **Pipeline maintainer** | Path contracts, fetch modes, hang prevention | This doc + [CANONICAL_PIPELINES.md](../runbooks/CANONICAL_PIPELINES.md) + [BROWSER_FETCH_SETUP.md](BROWSER_FETCH_SETUP.md) |

---

## Canonical scheduled-run root

**Task Scheduler runs against `PropORACLE_main_cp` (branch `main`), not a feature-branch Cursor checkout.**

| Check | Command / path |
|-------|----------------|
| Task action path | `Get-ScheduledTask -TaskName 'PropOracle - Daily 1AM' \| Select -Expand Actions` → should be `...\PropORACLE_main_cp\scripts\run_daily_1am.ps1` |
| Last run | `Get-ScheduledTaskInfo -TaskName 'PropOracle - Daily 1AM'` |
| Health stamp | `PropORACLE_main_cp\logs\LAST_5AM_STATUS.txt` (label **1AM**; also mirrored into sibling `PropORACLE*\logs\`) |
| Fresh board date | `mobile\www\slate_display_date.json` under **main_cp** |

If Cursor is open on `H:\PropORACLE` (feature branch), that tree can look “stale overnight” even when 1AM succeeded on `main_cp` and pushed to GitHub. `scripts/rank_best_props_today.py` now prefers the worktree whose step1 was **fetched on the slate date**, so a Saturday board in the feature branch will not beat Sunday’s 8AM board on `main_cp`. Still prefer ranking/ops from **main_cp**, or `git pull` / open that worktree.

---

## Daily program structure (scheduled)

Registered by `scripts/Register_Daily_Task.ps1` (re-run **from** `PropORACLE_main_cp\scripts` after moving the repo):

| Task | Typical time (local) | Role |
|------|----------------------|------|
| **Daily 1AM** | 01:00 | Complete **all-sport fetch** + live payout CDP + publish (skips grader/A1). Empty `no_slate` is OK; 8AM is the lock. |
| **Grader 3AM** | 03:00 | A1 historical actuals + grader for yesterday (split from 1AM so fetch and grade do not share RAM/CPU) |
| **Daily 5AM** | 05:00 | Second overnight **fetch + line snapshot + live payout CDP** (skips grader/A1 when 3AM finished). |
| **Daily 8AM** | 08:00 | **Primary same-day lock.** Fetch + Force CDP + `Publish-LiveSite.ps1` to origin/main |
| **Refresh 945AM** | 09:45 | Follow-up after 8AM (9:00 used to skip while 8AM still held `refresh.lock`) |
| **Refresh 1030AM** | 10:30 | PrizePicks morning move window |
| **Refresh 1PM** | 13:00 | Afternoon line-move |
| **Refresh 430PM** | 16:30 | Evening lock for 7pm WNBA/MLB boards |

Retired: Tennis Early 3AM, Grader 1AM (grader moved to 3AM).

`pipeline_slate_status.json` under `outputs/<date>/` records per-sport `complete` / `no_slate` / `off_season`. **Empty `no_slate` is normal** when PrizePicks has no same-day games (e.g. Soccer board only listing tomorrow). MLB/Soccer often fill at 8–10:30 refresh, not always at 1AM.

If 1AM finishes with tennis complete but WNBA/MLB/soccer still `no_slate`, that is expected. 8AM refresh remains the first reliable full same-day board.

### When to lock lines

| Window | What you get |
|--------|----------------|
| **Night before** | Watchlist only. Lines are up but they move (today: Cardoso PRA 26.5 → 28 overnight). |
| **1AM** | Complete fetch of whatever PP has posted (often tennis; MLB/soccer/WNBA may still be `no_slate`). Do not lock from a prior-day file. |
| **8AM–10:30AM** | Best lock window. Same-day board is posted; lines have taken the overnight move. |
| **4:30PM** | Evening lock when 7pm WNBA/MLB boards post or lines move again. |

Overs get worse when the line rises after you rank; wait for the 8AM board unless you are only scouting.

Every 8AM / 9:45 / 10:30 / 1PM / 4:30 refresh ends with `scripts/Publish-LiveSite.ps1` so Railway and GitHub raw tickets match the fetch (pipeline push happens *before* CDP payout scrape).

---

## Fetch architecture (why boards hang — and what we do)

PrizePicks DataDome blocks long HTTP retry stacks. Summer ops use **CDP-first when Chrome `:9222` is up**:

| Sport | Step1 entry | CDP / fail-fast |
|-------|-------------|-----------------|
| **WNBA** | `scripts/run_wnba_pipeline.ps1` | Browser-first when CDP listening; attach timeout ~30s |
| **Soccer** | `Sports/Soccer/scripts/step1_fetch_prizepicks_soccer.py` | `--cdp` + `--fail-fast` (no multi-board 90s cooldown stacks) |
| **Tennis** | `Sports/Tennis/scripts/step1_fetch_prizepicks_tennis.py` | `--cdp` + `--fail-fast` |
| **MLB** | `Sports/MLB/scripts/step1_fetch_prizepicks_mlb.py` | HTTP → CDP → Playwright; CDP attach timeout 30s |
| **Shared CDP helpers** | `utils/prizepicks_cdp.py` | Connect + in-page `fetch()` with AbortController |

**Late fetch safety (`scripts/run_nba_late_fetch.ps1`):**

- Probes CDP once; prefers CDP for WNBA / Soccer / Tennis when reachable.
- Per-sport **wall-clock kill** (~2.5–4 min) so one board cannot block MLB/pipeline.
- Skips off-season NBA/NHL fetches (no more burning retries on empty summer boards).
- Default HTTP retry budget capped low (2) for refresh labels.

**Refresh lock (`scripts/run_refresh_with_log.ps1`):**

- PID-aware lock, **90-minute** soft TTL (was 4h). A **live PID is never stolen**, even past TTL — 8AM often runs past 90 minutes.
- Soft-skip while another refresh is live exits **non-zero** if today’s slate is still incomplete (no false “success” when 10:30 skipped a hung 9AM).

**Daily catchup (`scripts/run_daily.ps1` late-fetch block):**

- Does **not** treat “hour ≥ 10” as “refresh will handle it” forever (that bug deferred forever to hung/soft-skipped tasks).
- Skips inline late-fetch only when a refresh is **actually running** (or a live lock &lt; 90 min); otherwise runs catchup when the day is still empty.

---

## Operator checklist (mid-morning empty tickets)

1. Confirm CDP Chrome is up: `http://127.0.0.1:9222/json/version` (solve DataDome in the visible board tab if needed).
2. Check lock: `data/cache/refresh.lock` — clear if PID is dead or age ≥ 90 min.
3. Check status: `outputs/<today>/pipeline_slate_status.json`.
4. Manual catchup:  
   `pwsh -NoProfile -File scripts\run_refresh_with_log.ps1 -RunLabel MANUAL_CDP_CATCHUP`
5. Or sport-only CDP step1, then:  
   `.\run_pipeline.ps1 -Date <today> -SkipFetch -SkipLivePayoutCapture`

---

## Related docs

- [PROPORACLE_RUN_COMMANDS.md](../runbooks/PROPORACLE_RUN_COMMANDS.md) — copy/paste commands  
- [ARCHITECTURE_USER_INTERACTIONS.md](../architecture/ARCHITECTURE_USER_INTERACTIONS.md) — bettor vs operator flows  
- [chrome_debug_setup.md](chrome_debug_setup.md) — launch CDP Chrome  
- [APP_SYSTEM_STATUS.md](APP_SYSTEM_STATUS.md) — deeper system tracker  
