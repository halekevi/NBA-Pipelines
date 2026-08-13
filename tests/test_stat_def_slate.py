"""Category-specific defense overlay for ticket slates."""
from __future__ import annotations

import pandas as pd

from utils.defense_tiers import normalize_def_tier_label
from utils.stat_def_slate import apply_category_def_to_ticket_tier, category_def_align_mask
from utils.wnba_prop_defense import lookup_stat_defense, prop_category


def test_pra_uses_pra_rank_not_overall():
    assert prop_category("Pts+Rebs+Asts") == "pra"
    pra = lookup_stat_defense("ATL", "Pts+Rebs+Asts")
    pts = lookup_stat_defense("ATL", "Points")
    assert pra["stat_def_category"] == "pra"
    assert pts["stat_def_category"] == "pts"
    assert pra["stat_def_rank"] != pts["stat_def_rank"]


def test_apply_overlays_def_tier_from_stat():
    df = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "player": "A",
                "opp": "ATL",
                "prop_type": "Pts+Rebs+Asts",
                "direction": "OVER",
                "def_tier": "Avg",
                "stat_def_category": "pra",
                "stat_def_rank": 4,
                "stat_def_tier": "HARD_MID",
            }
        ]
    )
    out = apply_category_def_to_ticket_tier(df)
    assert str(out.iloc[0]["overall_def_tier"]) == "Avg"
    assert normalize_def_tier_label(out.iloc[0]["def_tier"]) == "Above Avg"


def test_category_align_over_vs_weak():
    df = pd.DataFrame(
        [
            {"direction": "OVER", "def_tier": "Weak"},
            {"direction": "OVER", "def_tier": "Elite"},
            {"direction": "UNDER", "def_tier": "Elite"},
        ]
    )
    m = category_def_align_mask(df)
    assert bool(m.iloc[0]) is True
    assert bool(m.iloc[1]) is False
    assert bool(m.iloc[2]) is True
