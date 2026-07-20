# Daily ops overview (audience + program structure)

Living operator overview for **who runs what**, **when**, and **how PrizePicks fetches stay unblocked**. For file contracts see [PROJECT_LAYOUT.md](../PROJECT_LAYOUT.md). For one-screen production knobs see [CURRENT_STATE.md](../CURRENT_STATE.md).

**As of:** 2026-07-20

---

## Audiences

| Audience | Needs | Primary surfaces |
|----------|--------|------------------|
| **Bettor / analyst** | Today’s slate, tickets, grades, income | Web (`ui_runner`), mobile (`mobile/www`) |
| **Operator** | Fresh boards by mid-morning, recover when CDP/HTTP fails | Scheduled tasks + `run_daily.ps1` / `run_refresh_with_log.ps1` |
| **Pipeline maintainer** | Path contracts, fetch modes, hang prevention | This doc + [CANONICAL_PIPELINES.md](../runbooks/CANONICAL_PIPELINES.md) + [BROWSER_FETCH_SETUP.md](BROWSER_FETCH_SETUP.md) |

---

## Daily program structure (scheduled)

Registered by `scripts/Register_Daily_Task.ps1` (re-run after moving the repo):

| Task | Typical time (local) | Role |
|------|----------------------|------|
| **Tennis Early 3AM** | 03:00 | Light tennis fetch + ticket rebuild for early tips |
| **Daily 5AM** | 05:00 | Full `run_daily.ps1` (grade yesterday, fetch today, combine, publish) |
| **Refresh 8AM / 9AM / 1030AM / 1PM** | Line-move window | `run_refresh_with_log.ps1` → `run_nba_late_fetch.ps1` (multi-sport step1 append + pipeline `-SkipFetch`) |
| **Payout CDP** | 11:00 | Live MAIN floors after the 10:30 board settles |

`pipeline_slate_status.json` under `outputs/<date>/` records per-sport `complete` / `no_slate` / `off_season`. **Empty `no_slate` is normal** when PrizePicks has no same-day games (e.g. Soccer board only listing tomorrow).

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

- PID-aware lock, **90-minute** soft TTL (was 4h).
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
