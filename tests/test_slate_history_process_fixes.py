"""Tests for tennis Sackmann log filtering + WNBA accent-safe names."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_TENNIS = _REPO / "Sports" / "Tennis" / "scripts"
if str(_TENNIS) not in sys.path:
    sys.path.insert(0, str(_TENNIS))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tennis_shared import build_sackmann_player_index, build_sackmann_player_log  # noqa: E402


def test_sackmann_prefers_best_of_3_for_total_games():
    matches = pd.DataFrame(
        [
            {
                "winner_name": "Rafael Jodar",
                "loser_name": "A Opp",
                "tourney_date": "20260525",
                "score": "6-4 3-6 6-3 6-2 6-4",  # BO5-ish total
                "best_of": 5,
                "w_ace": 5,
                "l_ace": 2,
                "w_df": 1,
                "l_df": 2,
            },
            {
                "winner_name": "Rafael Jodar",
                "loser_name": "B Opp",
                "tourney_date": "20260801",
                "score": "6-4 6-3",
                "best_of": 3,
                "w_ace": 3,
                "l_ace": 1,
                "w_df": 2,
                "l_df": 1,
            },
            {
                "winner_name": "C Opp",
                "loser_name": "Rafael Jodar",
                "tourney_date": "20260805",
                "score": "7-6(5) 6-4",
                "best_of": 3,
                "w_ace": 4,
                "l_ace": 2,
                "w_df": 1,
                "l_df": 3,
            },
            {
                "winner_name": "Rafael Jodar",
                "loser_name": "D Opp",
                "tourney_date": "20260808",
                "score": "6-3 3-6 7-5",
                "best_of": 3,
                "w_ace": 6,
                "l_ace": 2,
                "w_df": 2,
                "l_df": 2,
            },
        ]
    )
    idx = build_sackmann_player_index(matches)
    vals = build_sackmann_player_log(
        matches, "rafael jodar", "match_total_games", last_n=5, player_index=idx
    )
    # Should prefer BO3 matches (newest first): 6+3+6+5=20, 7+6+6+4=23, 6+4+6+3=19
    assert len(vals) >= 3
    assert max(vals) < 40  # BO5 inflated total excluded when enough BO3 exist


def test_sackmann_serve_does_not_skip_nan_window():
    matches = pd.DataFrame(
        [
            {
                "winner_name": "Alina Korneeva",
                "loser_name": "X",
                "tourney_date": "20260811",
                "score": "6-3 6-2",
                "best_of": 3,
                "w_ace": float("nan"),
                "l_ace": 0,
                "w_df": float("nan"),
                "l_df": 0,
            },
            {
                "winner_name": "Alina Korneeva",
                "loser_name": "Y",
                "tourney_date": "20260809",
                "score": "6-4 6-4",
                "best_of": 3,
                "w_ace": float("nan"),
                "l_ace": 0,
                "w_df": float("nan"),
                "l_df": 0,
            },
            {
                "winner_name": "Alina Korneeva",
                "loser_name": "Z",
                "tourney_date": "20260101",
                "score": "6-1 6-1",
                "best_of": 3,
                "w_ace": 1,
                "l_ace": 0,
                "w_df": 13,
                "l_df": 1,
            },
        ]
    )
    idx = build_sackmann_player_index(matches)
    vals = build_sackmann_player_log(
        matches, "alina korneeva", "double_faults", last_n=5, player_index=idx
    )
    # Newest window has NaN DF — must NOT fall through to ancient DF=13
    assert 13 not in vals


def test_sackmann_sparse_bo3_does_not_mix_bo5():
    matches = pd.DataFrame(
        [
            {
                "winner_name": "Michael Zheng",
                "loser_name": "A",
                "tourney_date": "20260801",
                "score": "6-4 6-3",
                "best_of": 3,
                "w_ace": 1,
                "l_ace": 0,
                "w_df": 1,
                "l_df": 1,
            },
            {
                "winner_name": "Michael Zheng",
                "loser_name": "B",
                "tourney_date": "20260720",
                "score": "6-4 3-6 6-3",
                "best_of": 3,
                "w_ace": 1,
                "l_ace": 0,
                "w_df": 1,
                "l_df": 1,
            },
            {
                "winner_name": "Michael Zheng",
                "loser_name": "C",
                "tourney_date": "20260601",
                "score": "6-4 3-6 6-3 6-2 6-4",
                "best_of": 5,
                "w_ace": 1,
                "l_ace": 0,
                "w_df": 1,
                "l_df": 1,
            },
        ]
    )
    idx = build_sackmann_player_index(matches)
    vals = build_sackmann_player_log(
        matches, "michael zheng", "match_total_games", last_n=5, player_index=idx
    )
    assert len(vals) == 2
    assert max(vals) < 40


def test_wnba_norm_name_accents():
    spec = importlib.util.spec_from_file_location(
        "wnba_step4",
        _REPO / "Sports" / "WNBA" / "step4_fetch_player_stats.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Avoid running heavy imports side effects if possible — load still imports pandas etc.
    spec.loader.exec_module(mod)
    assert mod._norm_name("Azurá Stevens") == "azura stevens"
    assert mod._norm_name("Janelle Salaün") == "janelle salaun"
    assert mod._norm_name("Laura Juškaitė") == "laura juskaite"
