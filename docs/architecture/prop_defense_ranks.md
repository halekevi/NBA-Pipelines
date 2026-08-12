# Prop-specific opponent defense ranks

Utilities under `utils/*_prop_defense.py` attach `stat_def_category`, `stat_def_rank`, and `stat_def_tier` for ticket ranking soft signals.

| Sport | Module | Source | Rank cols |
|-------|--------|--------|-----------|
| WNBA | `utils/wnba_prop_defense.py` | box logs / CSV | `pts_rank`, `reb_rank`, … |
| NFL/CFB | `utils/football_prop_defense.py` | unit ranking CSVs | `pass_rank`, `rush_rank`, … |
| MLB | `utils/mlb_prop_defense.py` | `mlb_defense_summary.csv` | `era_rank`, `whip_rank`, `obp_rank` |
| NHL | `utils/nhl_prop_defense.py` | `step3_nhl_with_defense.csv` | `gaa_rank`, `saa_rank` |
| Soccer | `utils/soccer_prop_defense.py` | defense summary / step3 / step8 Def Rank | `overall_rank`, `shots_rank`, `saves_rank` |
| NBA | `utils/nba_prop_defense.py` | `nba_opp_defense_by_position.json` | `pts_rank`, `reb_rank`, `ast_rank`, … |

## Player category ranks (Matchup Edge)

Every Matchup Edge player row (all sports with box/rate stats) now includes:

| Field | Meaning |
|-------|---------|
| `league_rank` / `league_n` | Season-avg rank among **all qualifying players in the league** for that prop category (1 = highest) |
| `rank_on_team` | Season-avg rank **on that player's team** for the category |
| `category_rank_label` | Compact UI string, e.g. `L#3 · T1 · vs #5 reb D` |
| block `opponent.stat_def_rank` | Opponent **category** defense rank (1 = stingiest = HARD for OVER) |

Shared helpers: `utils/matchup_edge/player_ranks.py`. Rebuild with:

```bash
py -3 scripts/build_matchup_edge_json.py --sport all
```

## Soccer notes

- Goals map to category `overall`; lookup uses `f"{cat}_rank"` → **`overall_rank`** (not a bare `overall` column).
- If `opp_saa` is present but all-NaN, do **not** call `.rank()` on it — fall back `shots_rank`/`saves_rank` = `overall_rank`.
- Prefer `Sports/Soccer/soccer_defense_summary.csv` (from `soccer_defense_report.py`). When missing, rebuild merges step3 `OVERALL_DEF_RANK` with step8 `Opp` + `Def Rank`.

## NHL notes

- When `opp_saa` is all zeros (standings-only fallback), `saa_rank` proxies from `gaa_rank` so SOG/saves lookups still return integers.

## NBA notes

- Position JSON currently duplicates the same pts/reb/ast allowed for G/F/C. Rebuild averages to **team-level** ranks and sets `positions_identical=True` on the CSV.
- Wired into `load_nba` via `_overlay_sport_stat_defense(..., "NBA")`.

Rebuild examples:

```bash
python -c "from utils.nhl_prop_defense import rebuild_defense_by_stat; rebuild_defense_by_stat()"
python -c "from utils.soccer_prop_defense import rebuild_defense_by_stat; rebuild_defense_by_stat()"
python -c "from utils.nba_prop_defense import rebuild_defense_by_stat; rebuild_defense_by_stat()"
```
