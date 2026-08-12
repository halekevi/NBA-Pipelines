"""Debug + fix CBB D1 coverage."""
from __future__ import annotations

import importlib

import pandas as pd

import utils.cbb_prop_defense as m

importlib.reload(m)

sport_u = "CBB"
cache = m._pick_box_cache(sport_u)
raw = pd.read_csv(cache, encoding="utf-8-sig", low_memory=False)
work = m._normalize_box(raw, sport_u)
stat_cols = [c for c in ("pts", "reb", "ast", "stl", "blk", "tov", "fg3m") if c in work.columns]
for c in stat_cols:
    work[c] = pd.to_numeric(work[c], errors="coerce").fillna(0.0)
gcols = ["event_id", "game_date", "offense_team_id", "defense_team_id", "defense_team_key"] + stat_cols
gcols = [c for c in gcols if c in work.columns]
group_keys = [c for c in ("event_id", "offense_team_id", "defense_team_key") if c in gcols]
team_game = (
    work[gcols]
    .groupby(group_keys, as_index=False)
    .agg(
        **{c: (c, "sum") for c in stat_cols},
        **({"game_date": ("game_date", "first")} if "game_date" in gcols else {}),
        **({"defense_team_id": ("defense_team_id", "first")} if "defense_team_id" in gcols else {}),
    )
)
allowed = team_game.rename(columns={"defense_team_key": "team"})
for c in stat_cols:
    allowed[f"opp_{c}"] = allowed[c]
allowed["opp_pra"] = allowed["opp_pts"] + allowed["opp_reb"] + allowed["opp_ast"]
allowed["opp_pr"] = allowed["opp_pts"] + allowed["opp_reb"]
allowed["opp_pa"] = allowed["opp_pts"] + allowed["opp_ast"]
allowed["opp_ra"] = allowed["opp_reb"] + allowed["opp_ast"]
allowed["opp_bs"] = allowed["opp_stl"] + allowed["opp_blk"]
metrics = [c for c in allowed.columns if c.startswith("opp_")]
agg_kwargs = {mm: (mm, "mean") for mm in metrics}
agg_kwargs["games"] = ("game_date", "nunique")
agg_kwargs["team_id"] = ("defense_team_id", "first")
summary = allowed.groupby("team", as_index=False).agg(**agg_kwargs)
print("A", len(summary), "games describe", summary["games"].describe().to_dict())

# maybe min games filter somewhere in live rebuild? check games distribution for 69
# Compare to current csv teams
cur = pd.read_csv(m.default_csv_path("CBB"))
print("cur", len(cur))
overlap = set(cur["team"]) & set(summary["team"])
print("overlap", len(overlap))
# Is current the high-game subset?
sub = summary[summary["team"].isin(cur["team"])]
print("cur teams games min/median/max", sub["games"].min(), sub["games"].median(), sub["games"].max())
print("all teams games min/median", summary["games"].min(), summary["games"].median())

# Hypothesis: only teams with games >= N
for n in (10, 15, 20, 25, 30):
    print(f"games>={n}", (summary["games"] >= n).sum())
