"""NFL PrizePicks boards: game + preseason + latest season-long (NFLSZN)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_NFL_ROOT = _REPO / "Sports" / "NFL"
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_NFL_ROOT) not in sys.path:
    sys.path.insert(0, str(_NFL_ROOT))

from prizepicks_league_ids import (  # noqa: E402
    DEFAULT_NFL_BOARDS,
    NFL,
    NFLP,
    NFLSZN,
    SEASON_BOARD_IDS,
)


def test_default_boards_include_latest_season():
    assert DEFAULT_NFL_BOARDS[NFL] == "NFL"
    assert DEFAULT_NFL_BOARDS[NFLP] == "NFLP"
    assert DEFAULT_NFL_BOARDS[NFLSZN] == "NFLSZN"
    assert NFLSZN in SEASON_BOARD_IDS
    assert NFLSZN == "163"


def test_season_rows_skip_game_date_filter_logic():
    df = pd.DataFrame(
        {
            "league_id": ["9", "163"],
            "start_time": ["2026-08-15T00:00:00Z", "2026-09-10T00:00:00Z"],
        }
    )
    szn_mask = df["league_id"].astype(str).isin(SEASON_BOARD_IDS)
    assert int(szn_mask.sum()) == 1
    assert df.loc[szn_mask, "league_id"].iloc[0] == "163"
