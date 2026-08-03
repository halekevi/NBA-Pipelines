"""Tests for L5 fill / alias mirroring used by all-sport step8 + graders."""
from __future__ import annotations

import pandas as pd

from utils.hit_tracking_columns import (
    attach_hit_window_columns,
    fill_l5_from_stat_games,
)
from utils.prop_signal_score import HOT_L5_PERFECT_BOOST, context_signal_adjustment_series


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


def test_soft_signal_gives_extra_boost_for_perfect_l5():
    base = pd.DataFrame(
        {
            "direction": ["OVER", "OVER"],
            "l5_over": [4.0, 5.0],
            "l5_under": [1.0, 0.0],
            "pick_type": ["Standard", "Standard"],
            "sport": ["WNBA", "WNBA"],
            "tier": ["A", "A"],
        }
    )
    adj = context_signal_adjustment_series(base)
    # L5=5 gets the >=4 bump plus HOT_L5_PERFECT_BOOST
    assert float(adj.iloc[1] - adj.iloc[0]) == float(HOT_L5_PERFECT_BOOST)
