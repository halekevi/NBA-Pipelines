"""CBB / WCBB prop-specific defense rebuild and category lookups."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.cbb_prop_defense import (  # noqa: E402
    clear_defense_cache,
    lookup_stat_defense,
    prop_category,
    rebuild_defense_by_stat,
)


def test_cbb_points_vs_rebounds_categories_differ():
    assert prop_category("Points") == "pts"
    assert prop_category("Rebounds") == "reb"

    clear_defense_cache()
    pts = lookup_stat_defense("CBB", "DUKE", "Points")
    reb = lookup_stat_defense("CBB", "DUKE", "Rebounds")
    assert pts["stat_def_category"] == "pts"
    assert reb["stat_def_category"] == "reb"
    assert pts["stat_def_rank"] is not None
    assert reb["stat_def_rank"] is not None
    assert pts["stat_def_rank"] != reb["stat_def_rank"]


def test_cbb_rebuild_produces_many_teams():
    clear_defense_cache()
    df = rebuild_defense_by_stat("CBB")
    assert len(df) >= 300
    assert "pts_rank" in df.columns
    assert df["pts_rank"].notna().sum() >= 300
    if "stat_source" in df.columns:
        assert (df["stat_source"] == "box").sum() >= 200
    n_teams = int(df["n_teams"].iloc[0]) if "n_teams" in df.columns else len(df)
    assert n_teams >= 300


def test_wcbb_rebuild_produces_teams_with_pts_rank():
    clear_defense_cache()
    df = rebuild_defense_by_stat("WCBB")
    assert len(df) > 0
    assert "pts_rank" in df.columns
    assert int(df["pts_rank"].notna().sum()) > 0
    # Slate-common abbr lookups should resolve when map/player match works
    for abbr in ("CONN", "UNC", "DUKE"):
        lu = lookup_stat_defense("WCBB", abbr, "Points")
        if lu.get("stat_def_rank") is not None:
            assert lu["stat_def_category"] == "pts"
            assert int(lu["stat_def_rank"]) >= 1
            break
    else:
        # At least some team key (abbr or id) must look up
        team = str(df.iloc[0]["team"])
        lu = lookup_stat_defense("WCBB", team, "Points")
        assert lu["stat_def_rank"] is not None
