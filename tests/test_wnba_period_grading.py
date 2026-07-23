"""WNBA1H/WNBA1Q must grade against period actuals, never full-game WNBA."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from grading.period_actuals_guard import (  # noqa: E402
    assert_period_actuals_path,
    period_sport_from_path,
)


def test_period_sport_from_path_prefers_wnba_over_nba_substring():
    assert period_sport_from_path("outputs/2026-07-21/actuals_wnba1h_2026-07-21.csv") == "WNBA1H"
    assert period_sport_from_path("outputs/2026-07-21/actuals_wnba1q_2026-07-21.csv") == "WNBA1Q"
    assert period_sport_from_path("outputs/2026-07-21/graded_wnba1h_2026-07-21.xlsx") == "WNBA1H"
    assert period_sport_from_path("outputs/2026-03-25/actuals_nba1h_2026-03-25.csv") == "NBA1H"
    assert period_sport_from_path("outputs/2026-07-21/actuals_wnba_2026-07-21.csv") is None


def test_assert_period_actuals_accepts_period_filenames():
    assert_period_actuals_path("WNBA1H", "actuals_wnba1h_2026-07-21.csv")
    assert_period_actuals_path("WNBA1Q", Path("out/actuals_wnba1q_2026-07-21.csv"))
    assert_period_actuals_path("NBA1H", "actuals_nba1h_2026-03-25.csv")


def test_assert_period_actuals_rejects_full_game_wnba():
    with pytest.raises(RuntimeError, match="period actuals"):
        assert_period_actuals_path("WNBA1H", "actuals_wnba_2026-07-21.csv")
    with pytest.raises(RuntimeError, match="period actuals"):
        assert_period_actuals_path("WNBA1Q", "actuals_wnba_2026-07-21.csv")
    with pytest.raises(RuntimeError, match="period actuals"):
        assert_period_actuals_path("WNBA1H", "actuals_nba1h_2026-07-21.csv")


def test_lookup_actual_wnba1h_never_uses_full_game():
    from combined_ticket_grader import build_lookup, lookup_actual, player_norm

    pn = player_norm("A'ja Wilson")
    wnba_df = pd.DataFrame(
        [
            {
                "player": "A'ja Wilson",
                "team": "LV",
                "prop_type": "Points",
                "actual": 28.0,
                "player_norm": pn,
                "team_norm": "LV",
                "prop_norm": "points",
            }
        ]
    )
    wnba_lp, wnba_lpt = build_lookup(wnba_df)

    wnba1h_df = pd.DataFrame(
        [
            {
                "player": "A'ja Wilson",
                "team": "LV",
                "prop_type": "Points",
                "actual": 14.0,
                "player_norm": pn,
                "team_norm": "LV",
                "prop_norm": "points",
            }
        ]
    )
    wnba1h_lp, wnba1h_lpt = build_lookup(wnba1h_df)

    empty = {}
    got = lookup_actual(
        "WNBA1H",
        "A'ja Wilson",
        "LV",
        "points",
        empty,
        empty,
        empty,
        empty,
        wnba_lpt=wnba_lpt,
        wnba_lp=wnba_lp,
        wnba1h_lpt=wnba1h_lpt,
        wnba1h_lp=wnba1h_lp,
    )
    assert got == 14.0

    # Without period actuals, must NOT fall back to full-game 28.
    missing = lookup_actual(
        "WNBA1H",
        "A'ja Wilson",
        "LV",
        "points",
        empty,
        empty,
        empty,
        empty,
        wnba_lpt=wnba_lpt,
        wnba_lp=wnba_lp,
    )
    assert np.isnan(missing)

    q_missing = lookup_actual(
        "WNBA1Q",
        "A'ja Wilson",
        "LV",
        "points",
        empty,
        empty,
        empty,
        empty,
        wnba_lpt=wnba_lpt,
        wnba_lp=wnba_lp,
    )
    assert np.isnan(q_missing)
