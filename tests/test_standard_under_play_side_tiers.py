"""Standard UNDER tiers use play-side ml_prob (no 1 - ml flip)."""
from __future__ import annotations

import pandas as pd
from utils.group_rank_tier import (
    SPORT_STANDARD_DIRECTION_CUTS,
    _resolve_standard_direction_cuts,
    _tier_from_group,
    assign_tier_column,
)


def test_soccer_standard_direction_cuts_aligned():
    assert _resolve_standard_direction_cuts("soccer", "UNDER") == SPORT_STANDARD_DIRECTION_CUTS["soccer"][
        "UNDER"
    ]
    assert _resolve_standard_direction_cuts("soccer", "OVER") == SPORT_STANDARD_DIRECTION_CUTS["soccer"][
        "OVER"
    ]


def test_scalar_under_does_not_invert_ml_prob():
    # Play-side Under ~0.66 must not become Tier D via (1 - 0.66).
    assert (
        _tier_from_group("standard", "UNDER", 0.66, 1.5, None, sport="soccer") == "A"
    )
    assert _tier_from_group("standard", "OVER", 0.66, 1.5, None, sport="soccer") == "A"


def test_assign_tier_column_soccer_standard_under_high_ml():
    df = pd.DataFrame(
        [
            {
                "pick_type": "Standard",
                "direction": "UNDER",
                "ml_prob": 0.648,
                "prop_type": "Shots",
            },
            {
                "pick_type": "Standard",
                "direction": "UNDER",
                "ml_prob": 0.676,
                "prop_type": "Shots",
            },
            {
                "pick_type": "Standard",
                "direction": "UNDER",
                "ml_prob": 0.687,
                "prop_type": "Shots On Target (Combo)",
            },
            {
                "pick_type": "Standard",
                "direction": "OVER",
                "ml_prob": 0.648,
                "prop_type": "Shots",
            },
        ]
    )
    tiers = assign_tier_column(df, sport="soccer")
    assert list(tiers) == ["A", "A", "A", "A"]


def test_default_under_cuts_on_raw_play_side_ml():
    # Default UNDER A-cut 0.58 — raw 0.65 is A; flipped 0.35 would have been D.
    assert _tier_from_group("standard", "UNDER", 0.65, 1.5, None, sport="nba") == "A"
    assert _tier_from_group("standard", "UNDER", 0.35, 1.5, None, sport="nba") == "D"


def test_cbb_wcbb_cfb_standard_under_uses_direction_cuts():
    for sport in ("cbb", "wcbb", "cfb"):
        assert _resolve_standard_direction_cuts(sport, "UNDER") == SPORT_STANDARD_DIRECTION_CUTS[sport][
            "UNDER"
        ]
        assert _tier_from_group("standard", "UNDER", 0.65, 1.5, None, sport=sport) == "A"
        # Would be D only under the old (1 - ml) flip.
        assert _tier_from_group("standard", "UNDER", 0.60, 1.5, None, sport=sport) == "A"


def test_assign_tier_column_cbb_standard_under():
    df = pd.DataFrame(
        [
            {"pick_type": "Standard", "direction": "UNDER", "ml_prob": 0.66, "prop_type": "Points"},
            {"pick_type": "Standard", "direction": "OVER", "ml_prob": 0.71, "prop_type": "Points"},
        ]
    )
    assert list(assign_tier_column(df, sport="cbb")) == ["A", "A"]
    assert list(assign_tier_column(df, sport="wcbb")) == ["A", "A"]
    assert list(assign_tier_column(df, sport="cfb")) == ["A", "A"]
