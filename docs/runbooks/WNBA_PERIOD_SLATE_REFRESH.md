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

Step4 still uses **full-game ESPN rolling stats** as a period *history proxy* for projections (same early NBA1H/1Q pattern). Grading does **not** use that proxy — see below.

## Matchup edge + mobile

```bash
py -3 scripts/build_matchup_edge_json.py --sport wnba1h
py -3 scripts/build_matchup_edge_json.py --sport wnba1q
py -3 scripts/generate_mobile_bundle.py
```

## Period actuals + grading (1H / 1Q box, not full game)

Fetch ESPN play-by-play period stats (`1H` = Q1+Q2, `1Q` = Q1 only). Do **not** pass `actuals_wnba_*.csv` into period grading.

```powershell
$Date = "YYYY-MM-DD"
py -3 scripts/fetch_nba_period_actuals.py --sport WNBA --date $Date --segment 1H --output outputs/$Date/actuals_wnba1h_$Date.csv
py -3 scripts/fetch_nba_period_actuals.py --sport WNBA --date $Date --segment 1Q --output outputs/$Date/actuals_wnba1q_$Date.csv
```

### Slate grade (per board)

```powershell
py -3 scripts/grading/slate_grader.py --sport WNBA --slate outputs/$Date/wnba1h/step8_wnba1h_direction_clean.xlsx --actuals outputs/$Date/actuals_wnba1h_$Date.csv --output outputs/$Date/graded_wnba1h_$Date.xlsx --date $Date
py -3 scripts/grading/slate_grader.py --sport WNBA --slate outputs/$Date/wnba1q/step8_wnba1q_direction_clean.xlsx --actuals outputs/$Date/actuals_wnba1q_$Date.csv --output outputs/$Date/graded_wnba1q_$Date.xlsx --date $Date
```

`slate_grader` / `combined_ticket_grader` **hard-fail** if a period sport is paired with full-game `actuals_wnba_YYYY-MM-DD.csv` (filename must contain `wnba1h` / `wnba1q`).

### Combined tickets

```powershell
py -3 scripts/combined_ticket_grader.py `
  --tickets ui_runner/data/combined_slate_tickets_$Date.json `
  --nba_actuals outputs/$Date/actuals_nba_$Date.csv `
  --wnba_actuals outputs/$Date/actuals_wnba_$Date.csv `
  --wnba1h_actuals outputs/$Date/actuals_wnba1h_$Date.csv `
  --wnba1q_actuals outputs/$Date/actuals_wnba1q_$Date.csv `
  --out outputs/$Date/combined_tickets_graded_$Date.xlsx
```

`run_grader.ps1` auto-fetches WNBA 1H/1Q period CSVs and passes `--wnba1h_actuals` / `--wnba1q_actuals`. WNBA1H/1Q legs never fall back to full-game WNBA actuals (same rule as NBA1H/1Q vs full-game NBA).

### Sanity check (suspect full-game totals)

```powershell
py -3 scripts/grading/flag_suspect_nba1q_grades.py --dry-run
```

Flags NBA1Q/1H and WNBA1Q/1H rows whose `actual_value` exceeds plausible period caps.

## Still TODO

- `combined_slate_tickets.py` ACTIVE_SPORTS + path resolution for WNBA1H/1Q
- Ticket pools / gates / payout ladders
- Period-specific hit-rate history (not full-game proxy) for projections
- Optional WNBA2H / WNBA4Q refresh tags
