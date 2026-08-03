"""Tests for L5 fill / alias mirroring used by all-sport step8 + graders."""
from __future__ import annotations

import pandas as pd

from utils.hit_tracking_columns import (
    assign_l5_aliases_from_hits,
    attach_hit_window_columns,
    fill_l5_from_stat_games,
)
from utils.l5_recency_policy import (
    L5_GE4_GATE_CLEAR_SPORTS,
    L5_PERFECT_EXTRA_BOOST,
    L5_PERFECT_GATE_CLEAR_SPORTS,
    L5_PERFECT_ONLY_GATE_CLEAR_SPORTS,
    MLB_STD_OVER_PERFECT_L5_PENALTY,
    l5_clears_standard_prop_gate,
    l5_gate_clear_min_hits,
    l5_perfect_gate_clear_sport,
    l5_perfect_score_boost_allowed,
    mlb_standard_over_perfect_l5,
)
from utils.prop_signal_score import (
    HOT_L5_GE4_BOOST,
    HOT_L5_PERFECT_BOOST,
    MLB_STD_OVER_L5_PERFECT_PENALTY,
    context_signal_adjustment_series,
)


def test_fill_l5_from_stat_games_counts_vs_line():
    df = pd.DataFrame(
        {
            "line": [10.5, 10.5],
            "stat_g1": [12, 9],
            "stat_g2": [11, 8],
            "stat_g3": [14, 10],
            "stat_g4": [13, 7],
            "stat_g5": [15, 6],
        }
    )
    out = fill_l5_from_stat_games(df, line_col="line")
    assert float(out.loc[0, "l5_over"]) == 5.0
    assert float(out.loc[0, "l5_under"]) == 0.0
    assert float(out.loc[0, "last5_over"]) == 5.0
    assert float(out.loc[1, "l5_over"]) == 0.0
    assert float(out.loc[1, "l5_under"]) == 5.0


def test_attach_hit_window_coalesces_line_hits_to_l5_and_last5():
    df = pd.DataFrame(
        {
            "line": [2.5],
            "line_hits_over_5": [4],
            "line_hits_under_5": [1],
        }
    )
    out = attach_hit_window_columns(df, line_col="line")
    assert float(out.loc[0, "l5_over"]) == 4.0
    assert float(out.loc[0, "last5_over"]) == 4.0
    assert float(out.loc[0, "l5_under"]) == 1.0


def test_assign_l5_aliases_from_hits_dual_writes():
    df = pd.DataFrame({"line": [1.5, 1.5]})
    mask = pd.Series([True, False])
    # Values align to True rows only (same as step5 ok5 pattern).
    assign_l5_aliases_from_hits(df, mask, [4.0], [1.0], [0.0])
    assert float(df.loc[0, "l5_over"]) == 4.0
    assert float(df.loc[0, "last5_over"]) == 4.0
    assert float(df.loc[0, "line_hits_over_5"]) == 4.0
    assert pd.isna(df.loc[1, "l5_over"])


def test_soft_signal_gives_extra_boost_for_perfect_l5():
    base = pd.DataFrame(
        {
            "direction": ["OVER", "OVER"],
            "l5_over": [4.0, 5.0],
            "l5_under": [1.0, 0.0],
            "pick_type": ["Standard", "Standard"],
            "sport": ["NBA", "NBA"],
            "tier": ["A", "A"],
        }
    )
    adj = context_signal_adjustment_series(base)
    # L5=5 gets the >=4 bump plus HOT_L5_PERFECT_BOOST
    assert abs(float(adj.iloc[1] - adj.iloc[0]) - float(HOT_L5_PERFECT_BOOST)) < 1e-9
    assert float(HOT_L5_PERFECT_BOOST) == float(L5_PERFECT_EXTRA_BOOST)


def test_mlb_standard_over_perfect_l5_penalized():
    assert not l5_perfect_score_boost_allowed("MLB", "Standard")
    assert l5_perfect_score_boost_allowed("MLB", "Goblin")
    assert mlb_standard_over_perfect_l5("MLB", "Standard", "OVER", 5.0)
    assert not mlb_standard_over_perfect_l5("MLB", "Goblin", "OVER", 5.0)

    base = pd.DataFrame(
        {
            "direction": ["OVER", "OVER"],
            "l5_over": [4.0, 5.0],
            "l5_under": [1.0, 0.0],
            "pick_type": ["Standard", "Standard"],
            "sport": ["MLB", "MLB"],
            "tier": ["A", "A"],
        }
    )
    adj = context_signal_adjustment_series(base)
    # L5=5: GE4 boost is reversed and avoid penalty applied vs L5=4 GE4-only.
    expected = float(MLB_STD_OVER_L5_PERFECT_PENALTY - HOT_L5_GE4_BOOST)
    assert abs(float(adj.iloc[1] - adj.iloc[0]) - expected) < 1e-9
    assert float(MLB_STD_OVER_L5_PERFECT_PENALTY) == float(MLB_STD_OVER_PERFECT_L5_PENALTY)


def test_gate_clear_thresholds_by_sport_family():
    for sport in L5_GE4_GATE_CLEAR_SPORTS:
        assert l5_gate_clear_min_hits(sport) == 4.0
        assert l5_clears_standard_prop_gate(sport, 4.0)
        assert not l5_clears_standard_prop_gate(sport, 3.0)
    for sport in L5_PERFECT_ONLY_GATE_CLEAR_SPORTS:
        assert l5_gate_clear_min_hits(sport) == 5.0
        assert l5_clears_standard_prop_gate(sport, 5.0)
        assert not l5_clears_standard_prop_gate(sport, 4.0)
    for sport in ("NBA", "NFL", "CBB", "WCBB", "CFB", "NHL", "WNBA"):
        assert sport in L5_PERFECT_GATE_CLEAR_SPORTS
        assert l5_perfect_gate_clear_sport(sport)
    assert not l5_perfect_gate_clear_sport("MLB")
    assert not l5_perfect_gate_clear_sport("SOCCER")
