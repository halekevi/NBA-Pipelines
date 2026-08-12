"""Multi-sport prop-specific defense lookups and NFL rebuild integrity."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.football_prop_defense import (  # noqa: E402
    lookup_stat_defense,
    prop_category as fb_prop_category,
    rebuild_nfl_defense_by_stat,
)
from utils.mlb_prop_defense import (  # noqa: E402
    lookup_stat_defense as mlb_lookup,
    prop_category as mlb_prop_category,
)


def test_nfl_pass_vs_rush_categories_differ_when_ranks_differ():
    """Same team: Passing Yards vs Rushing Yards map to different cats/ranks when D splits."""
    assert fb_prop_category("Passing Yards") == "pass"
    assert fb_prop_category("Rushing Yards") == "rush"

    pass_lu = lookup_stat_defense("NFL", "SEA", "Passing Yards")
    rush_lu = lookup_stat_defense("NFL", "SEA", "Rushing Yards")

    assert pass_lu["stat_def_category"] == "pass"
    assert rush_lu["stat_def_category"] == "rush"
    assert pass_lu["stat_def_rank"] is not None
    assert rush_lu["stat_def_rank"] is not None
    # SEA historically has a strong rush D vs middling pass D in reference data
    assert pass_lu["stat_def_rank"] != rush_lu["stat_def_rank"]


def test_cfb_lookup_rushing_yards():
    lu = lookup_stat_defense("CFB", "OSU", "Rushing Yards")
    assert lu["stat_def_category"] == "rush"
    assert lu["stat_def_rank"] is not None
    assert int(lu["stat_def_rank"]) >= 1
    assert lu["stat_def_coarse"] in ("HARD", "HARD_MID", "MID", "EASY_MID", "EASY", "UNK")


def test_mlb_hits_maps_to_obp():
    assert mlb_prop_category("Hits") == "obp"
    lu = mlb_lookup("NYY", "Hits")
    assert lu["stat_def_category"] == "obp"
    assert lu["stat_def_rank"] is not None
    assert int(lu["stat_def_rank"]) >= 1


def test_nfl_rebuild_replaces_stub_sequential_ranks(tmp_path):
    """Rebuild must write real pass_def_rank values, not team-row index stubs."""
    out = rebuild_nfl_defense_by_stat()
    assert not out.empty

    legacy = ROOT / "Sports" / "NFL" / "data" / "defense_rankings.csv"
    assert legacy.is_file()
    leg = pd.read_csv(legacy, encoding="utf-8-sig")
    assert "team" in leg.columns
    assert "pass_def_rank" in leg.columns

    sea_rows = leg[leg["team"].astype(str).str.upper() == "SEA"]
    assert not sea_rows.empty
    sea_pass = int(float(sea_rows.iloc[0]["pass_def_rank"]))
    # Stub sequential ranks used team index (0-based or 1-based position in file)
    teams = [str(t).strip().upper() for t in leg["team"].tolist()]
    sea_idx = teams.index("SEA")
    assert sea_pass != sea_idx, (
        f"SEA pass_def_rank={sea_pass} equals team index stub {sea_idx}"
    )
    assert sea_pass != sea_idx + 1, (
        f"SEA pass_def_rank={sea_pass} equals 1-based team index stub {sea_idx + 1}"
    )
    # Sanity: rank is in league range
    assert 1 <= sea_pass <= int(out.iloc[0]["n_teams"])
