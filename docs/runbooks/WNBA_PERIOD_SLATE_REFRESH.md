# WNBA 1H / 1Q slate refresh

PrizePicks exposes period boards as separate league tabs (not stat pills on the full WNBA board).

## League IDs (CDP `/leagues`, 2026-07-22)

| Tab | `league_id` | Sport key |
|-----|-------------|-----------|
| WNBA | 3 | `wnba` |
| WNBA1H | **193** | `wnba1h` |
| WNBA1Q | **308** | `wnba1q` |
| WNBA2H | 194 | (not wired yet) |
| WNBA4Q | 195 | (not wired yet) |

Canonical constants: `Sports/WNBA/prizepicks_league_ids.py`.

Re-verify anytime CDP Chrome is up:

```powershell
py -3 Sports\WNBA\step1_fetch_prizepicks.py --print-leagues --cdp http://127.0.0.1:9222 --playwright --league_id 3 --output logs\_leagues_dummy.csv
```

## Period-only pipeline (no full WNBA / no tickets)

```powershell
powershell -File scripts\_run_wnba_period_refresh.ps1 -Date 2026-07-22
# DataDome: prefer browser
powershell -File scripts\_run_wnba_period_refresh.ps1 -Date 2026-07-22 -Cdp http://127.0.0.1:9222
```

Writes under `outputs/<date>/wnba1h/` and `outputs/<date>/wnba1q/`, copies step8 clean xlsx to `Sports/WNBA/`, and builds matchup-edge JSON.

MVP uses **full-game ESPN rolling stats** as a period proxy (same early pattern as NBA1H/1Q). Period-specific history / ticket pools are TODO.

## Matchup edge + mobile

```bash
py -3 scripts/build_matchup_edge_json.py --sport wnba1h
py -3 scripts/build_matchup_edge_json.py --sport wnba1q
py -3 scripts/generate_mobile_bundle.py
```

## Period actuals (grading later)

```bash
py -3 Sports/NBA/scripts/fetch_nba_period_actuals.py --sport WNBA --date YYYY-MM-DD --segment 1H --output outputs/YYYY-MM-DD/actuals_wnba1h_YYYY-MM-DD.csv
py -3 Sports/NBA/scripts/fetch_nba_period_actuals.py --sport WNBA --date YYYY-MM-DD --segment 1Q --output outputs/YYYY-MM-DD/actuals_wnba1q_YYYY-MM-DD.csv
```

ESPN play-by-play only (no NBA.com). Wire into `combined_ticket_grader.py` when tickets start carrying WNBA1H/1Q legs.

## Still TODO

- `combined_slate_tickets.py` ACTIVE_SPORTS + path resolution for WNBA1H/1Q
- Ticket pools / gates / payout ladders
- Period-specific hit-rate history (not full-game proxy)
- Optional WNBA2H / WNBA4Q refresh tags
