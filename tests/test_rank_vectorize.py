"""Vectorized step7 scoring helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from utils.rank_vectorize import (
    avg_vs_line_series,
    blend_two_rates,
    def_adj_from_rank,
    def_rank_signal_series,
    directional_line_hit_rate,
    edge_transform_series,
    first_stat_projection,
    minutes_certainty_from_tier,
    over_only_line_hit_rate,
)


def test_first_stat_projection_prefers_l5():
    df = pd.DataFrame(
        {
            "stat_last5_avg": [10.0, None],
            "stat_last10_avg": [8.0, 7.0],
            "stat_season_avg": [9.0, 6.0],
        }
    )
    got = first_stat_projection(df)
    assert list(got) == [10.0, 7.0]


def test_directional_line_hit_rate_over_under():
    df = pd.DataFrame(
        {
            "line_hit_rate_over_ou_5": [0.8, 0.8],
            "line_hit_rate_over_ou_10": [0.6, 0.6],
            "line_hit_rate_under_ou_5": [0.2, 0.2],
            "line_hit_rate_under_ou_10": [0.4, 0.4],
            "bet_direction": ["OVER", "UNDER"],
        }
    )
    got = directional_line_hit_rate(df, df["bet_direction"])
    assert float(got.iloc[0]) == pytest.approx(0.7)
    assert float(got.iloc[1]) == pytest.approx(0.3)


def test_edge_transform_and_def_signal():
    edge = pd.Series([3.0, -3.0, float("nan")])
    tr = edge_transform_series(edge)
    assert round(float(tr.iloc[0]), 5) == round(3.0 ** 0.85, 5)
    assert round(float(tr.iloc[1]), 5) == round(-(3.0 ** 0.85), 5)
    assert pd.isna(tr.iloc[2])
    rank = pd.Series([1.0, 15.0])
    sig = def_rank_signal_series(rank, ["OVER", "UNDER"], 15)
    assert float(sig.iloc[0]) < 0
    assert float(def_adj_from_rank(rank, 15).iloc[0]) < 0


def test_avg_vs_line_flips_under():
    df = pd.DataFrame(
        {
            "stat_last5_avg_num": [12.0, 12.0],
            "stat_last10_avg_num": [12.0, 12.0],
            "stat_season_avg_num": [12.0, 12.0],
        }
    )
    over = avg_vs_line_series(df, pd.Series([10.0, 10.0]), ["OVER", "UNDER"])
    assert float(over.iloc[0]) > 0
    assert float(over.iloc[1]) < 0


def test_minutes_and_over_only():
    assert list(minutes_certainty_from_tier(["HIGH", "LOW", ""])) == [1.0, 0.75, 0.80]
    df = pd.DataFrame(
        {
            "line_hit_rate_over_ou_5": [1.0],
            "line_hit_rate_over_ou_10": [0.0],
        }
    )
    assert float(over_only_line_hit_rate(df).iloc[0]) == 0.5
    assert float(blend_two_rates(pd.Series([1.0]), pd.Series([0.0])).iloc[0]) == 0.5
