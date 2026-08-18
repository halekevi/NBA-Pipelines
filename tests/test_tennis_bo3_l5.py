"""BO3 PrizePicks lines must not average slam / best-of-5 match totals."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_TENNIS_SCRIPTS = _REPO / "Sports" / "Tennis" / "scripts"
sys.path.insert(0, str(_TENNIS_SCRIPTS))

from tennis_shared import (  # noqa: E402
    apply_format_matched_stat_g,
    build_sackmann_player_log,
    collect_history_values,
    line_expects_best_of_three,
    match_is_best_of_five,
)


def _safiullin_espn_hist() -> list[dict]:
    # Mixed L5 that produced the fake +21 Total Games edge: 40, 27, 47, 54, 55.
    return [
        {"opponent": "Djokovic", "match_total_games": 40, "games_won": 13, "total_sets": 5, "sets_won": 1},
        {"opponent": "Fonseca", "match_total_games": 27, "games_won": 16, "total_sets": 3, "sets_won": 2},
        {"opponent": "Alcaraz", "match_total_games": 47, "games_won": 19, "total_sets": 5, "sets_won": 2},
        {"opponent": "Sinner", "match_total_games": 54, "games_won": 22, "total_sets": 5, "sets_won": 2},
        {"opponent": "Medvedev", "match_total_games": 55, "games_won": 24, "total_sets": 5, "sets_won": 2},
        {"opponent": "Norrie", "match_total_games": 25, "games_won": 15, "total_sets": 2, "sets_won": 2},
        {"opponent": "Draper", "match_total_games": 22, "games_won": 13, "total_sets": 2, "sets_won": 2},
        {"opponent": "Shelton", "match_total_games": 38, "games_won": 20, "total_sets": 3, "sets_won": 2},
        {"opponent": "Fritz", "match_total_games": 36, "games_won": 19, "total_sets": 3, "sets_won": 1},
    ]


def test_bo3_line_caps_and_slam_detection():
    assert line_expects_best_of_three("match_total_games", 23.5)
    assert line_expects_best_of_three("match_total_games", 28.5)
    assert not line_expects_best_of_three("match_total_games", 32.5)
    assert line_expects_best_of_three("games_won", 12.5)
    assert not line_expects_best_of_three("games_won", 21.5)
    assert match_is_best_of_five({"total_sets": 5, "match_total_games": 40, "games_won": 13})
    assert not match_is_best_of_five({"total_sets": 3, "match_total_games": 27, "games_won": 16})


def test_safiullin_total_games_skips_wimbledon_bo5():
    vals = collect_history_values(_safiullin_espn_hist(), "match_total_games", 5, line=23.5)
    assert vals == [27.0, 25.0, 22.0, 38.0, 36.0]
    assert sum(vals) / 5 == 29.6
    mixed = [40.0, 27.0, 47.0, 54.0, 55.0]
    assert sum(mixed) / 5 == 44.6
    assert abs((sum(vals) / 5) - 23.5) < 10
    assert (sum(mixed) / 5) - 23.5 > 20


def test_faa_games_won_drops_slam_24_plus():
    hist = [
        {"games_won": 13, "match_total_games": 21, "total_sets": 2},
        {"games_won": 28, "match_total_games": 57, "total_sets": 5},
        {"games_won": 31, "match_total_games": 55, "total_sets": 5},
        {"games_won": 19, "match_total_games": 28, "total_sets": 3},
        {"games_won": 20, "match_total_games": 34, "total_sets": 3},
        {"games_won": 18, "match_total_games": 26, "total_sets": 2},
        {"games_won": 15, "match_total_games": 31, "total_sets": 3},
    ]
    vals = collect_history_values(hist, "games_won", 5, line=13.5)
    assert vals == [13.0, 19.0, 20.0, 18.0, 15.0]
    assert sum(vals) / 5 == 17.0


def test_bo5_posted_line_keeps_slam_totals():
    vals = collect_history_values(_safiullin_espn_hist(), "match_total_games", 5, line=36.5)
    assert vals == [40.0, 27.0, 47.0, 54.0, 55.0]


def test_apply_format_matched_stat_g_strips_flattened_slam_totals():
    df = pd.DataFrame(
        [
            {
                "prop_norm": "match_total_games",
                "line": 23.5,
                "stat_g1": 40,
                "stat_g2": 27,
                "stat_g3": 47,
                "stat_g4": 54,
                "stat_g5": 55,
            }
        ]
    )
    changed = apply_format_matched_stat_g(df)
    assert changed == 1
    assert df.loc[0, "stat_g1"] == 27.0
    assert pd.isna(df.loc[0, "stat_g2"])
    assert abs(float(df.loc[0, "stat_last5_avg"]) - 27.0) < 1e-9
    edge = float(df.loc[0, "stat_last5_avg"]) - 23.5
    assert edge < 8


def test_sackmann_log_skips_five_set_scores_on_bo3_total_games():
    df = pd.DataFrame(
        [
            {
                "winner_name": "Ada Player",
                "loser_name": "Bea Rival",
                "tourney_date": "20260701",
                "match_num": 5,
                "score": "6-4 6-4 6-4 3-6 6-4",
                "w_ace": 8,
                "l_ace": 4,
                "w_df": 1,
                "l_df": 2,
            },
            {
                "winner_name": "Ada Player",
                "loser_name": "Cara Rival",
                "tourney_date": "20260620",
                "match_num": 3,
                "score": "6-4 6-3",
                "w_ace": 3,
                "l_ace": 1,
                "w_df": 1,
                "l_df": 1,
            },
            {
                "winner_name": "Ada Player",
                "loser_name": "Dee Rival",
                "tourney_date": "20260610",
                "match_num": 2,
                "score": "7-6(4) 6-4",
                "w_ace": 5,
                "l_ace": 2,
                "w_df": 2,
                "l_df": 1,
            },
        ]
    )
    mixed = build_sackmann_player_log(df, "ada player", "match_total_games", last_n=5)
    # Missing line defaults to BO3 so slam totals cannot leak onto summer boards.
    assert 49.0 not in mixed
    assert mixed == [19.0, 23.0]
    slam_line = build_sackmann_player_log(df, "ada player", "match_total_games", last_n=5, line=36.5)
    assert 49.0 in slam_line
    bo3 = build_sackmann_player_log(df, "ada player", "match_total_games", last_n=5, line=23.5)
    assert 49.0 not in bo3
    assert bo3 == [19.0, 23.0]
