"""Tests for Matchup Edge category-specific defense resolution."""
from __future__ import annotations

from utils.matchup_edge.stat_defense import (
    display_tier_from_stat,
    prop_label_for_cat,
    resolve_category_defense,
)


def test_prop_label_for_cat_stocks_and_threes():
    assert prop_label_for_cat("stocks") == "Blks+Stls"
    assert prop_label_for_cat("fg3m") == "3-PT Made"
    assert prop_label_for_cat("pra", "Pts+Reb+Ast") == "Pts+Rebs+Asts"


def test_display_tier_mapping():
    assert display_tier_from_stat("HARD") == "Elite"
    assert display_tier_from_stat("EASY") == "Weak"
    assert display_tier_from_stat("MID") == "Avg"
    assert display_tier_from_stat("HARD_MID") == "Above Avg"


def test_wnba_resolve_category_differs_by_cat():
    # NY: pts_rank=9 MID, reb_rank=4 HARD_MID (from defense_by_stat CSV)
    pts = resolve_category_defense(
        sport="wnba",
        opponent="NYL",
        cat_id="pts",
        overall_rank=9,
        overall_tier="Avg",
    )
    reb = resolve_category_defense(
        sport="wnba",
        opponent="NYL",
        cat_id="reb",
        overall_rank=9,
        overall_tier="Avg",
    )
    assert pts["stat_def_rank"] == 9
    assert reb["stat_def_rank"] == 4
    assert pts["def_rank"] != reb["def_rank"]
    assert reb["def_tier"] in ("Elite", "Above Avg")
    assert pts["overall_def_rank"] == 9
