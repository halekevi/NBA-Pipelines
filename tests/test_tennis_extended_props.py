"""Norm + Sackmann history keys for Total Sets / Tie Breaks / Break Points Won."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_TENNIS_SCRIPTS = _REPO / "Sports" / "Tennis" / "scripts"
sys.path.insert(0, str(_TENNIS_SCRIPTS))

from tennis_shared import (  # noqa: E402
    _parse_score_both_sides,
    build_sackmann_player_index,
    build_sackmann_player_log,
    history_value_key,
    norm_tennis_prop,
)


def test_norm_maps_prizepicks_board_labels():
    assert norm_tennis_prop("Total Sets") == "total_sets"
    assert norm_tennis_prop("Total Tie Breaks") == "total_tie_breaks"
    assert norm_tennis_prop("Break Points Won") == "break_points_won"
    assert norm_tennis_prop("Sets Won") == "sets_won"
    assert history_value_key("total_sets") == "total_sets"
    assert history_value_key("total_tie_breaks") == "total_tie_breaks"
    assert history_value_key("break_points_won") == "break_points_won"


def test_parse_score_counts_sets_and_tiebreaks():
    parsed = _parse_score_both_sides("6-4 7-6(5) 6-3")
    assert parsed is not None
    assert parsed["total_sets"] == 3.0
    assert parsed["total_tie_breaks"] == 1.0
    assert parsed["winner"]["sets_won"] == 3.0
    assert parsed["loser"]["sets_won"] == 0.0

    straight = _parse_score_both_sides("6-2 6-3")
    assert straight is not None
    assert straight["total_sets"] == 2.0
    assert straight["total_tie_breaks"] == 0.0


def test_sackmann_index_break_points_and_match_markets():
    df = pd.DataFrame(
        [
            {
                "winner_name": "Ada Player",
                "loser_name": "Bea Rival",
                "tourney_date": "20260801",
                "score": "7-6(3) 6-4",
                "w_ace": 5,
                "l_ace": 2,
                "w_df": 1,
                "l_df": 3,
                "w_bpSaved": 2,
                "w_bpFaced": 4,
                "l_bpSaved": 1,
                "l_bpFaced": 5,
            }
        ]
    )
    idx = build_sackmann_player_index(df)
    ada = idx["ada player"][0]
    bea = idx["bea rival"][0]
    assert ada["total_sets"] == 2.0
    assert ada["total_tie_breaks"] == 1.0
    assert bea["total_sets"] == 2.0
    assert bea["total_tie_breaks"] == 1.0
    # Winner break points won = loser faced - saved = 5 - 1
    assert ada["break_points_won"] == 4.0
    # Loser break points won = winner faced - saved = 4 - 2
    assert bea["break_points_won"] == 2.0

    assert build_sackmann_player_log(df, "ada player", "break_points_won", last_n=5) == [4.0]
    assert build_sackmann_player_log(df, "ada player", "total_tie_breaks", last_n=5) == [1.0]
    assert build_sackmann_player_log(df, "ada player", "total_sets", last_n=5) == [2.0]
