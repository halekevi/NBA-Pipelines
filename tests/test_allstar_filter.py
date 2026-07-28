"""Tests for All-Star game/prop exclusion."""

from __future__ import annotations

import pandas as pd

from utils.allstar_filter import (
    drop_allstar_game_rows,
    drop_allstar_props,
    is_allstar_date,
    is_allstar_team,
    is_allstar_text,
    is_espn_summary_allstar,
)


def test_wnba_allstar_team_codes():
    assert is_allstar_team("COOP", "WNBA")
    assert is_allstar_team("spo", "WNBA")
    assert is_allstar_team("CLA", "WNBA")
    assert is_allstar_team("COL", "WNBA")
    assert not is_allstar_team("NY", "WNBA")
    assert not is_allstar_team("NYL", "WNBA")


def test_drop_allstar_game_rows_purges_2025_roster_players():
    df = pd.DataFrame(
        {
            "game_date": ["2025-07-20"] * 3 + ["2025-07-18"],
            "TEAM": ["CLA", "COL", "CLA", "NY"],
            "event_id": ["401781604", "401781604", "401781604", "999"],
            "REB": [11, 9, 7, 8],
            "PLAYER_NAME": [
                "Breanna Stewart",
                "A'ja Wilson",
                "Kayla McBride",
                "Breanna Stewart",
            ],
        }
    )
    filtered, n = drop_allstar_game_rows(df, sport="WNBA")
    assert n == 3
    assert list(filtered["PLAYER_NAME"]) == ["Breanna Stewart"]
    assert list(filtered["REB"]) == [8]


def test_allstar_text_detection():
    assert is_allstar_text("AT&T WNBA All-Star Game")
    assert is_allstar_text("allstar special")
    assert not is_allstar_text("Points")


def test_wnba_allstar_date_window():
    assert is_allstar_date("2026-07-25", "WNBA")
    assert not is_allstar_date("2026-07-22", "WNBA")


def test_drop_allstar_game_rows_fixes_stewart_l5():
    df = pd.DataFrame(
        {
            "game_date": [
                "2026-07-25",
                "2026-07-22",
                "2026-07-20",
                "2026-07-18",
                "2026-07-12",
                "2026-07-11",
            ],
            "TEAM": ["COOP", "NY", "NY", "NY", "NY", "NY"],
            "REB": [13, 9, 13, 8, 8, 7],
            "PLAYER_NAME": ["Breanna Stewart"] * 6,
        }
    )
    filtered, n = drop_allstar_game_rows(df, sport="WNBA")
    assert n == 1
    assert list(filtered["REB"]) == [9, 13, 8, 8, 7]
    # vs 7.5 → 4 overs (9,13,8,8) + 1 under (7)
    overs = sum(1 for v in filtered["REB"].head(5) if v > 7.5)
    assert overs == 4


def test_drop_allstar_props_by_team():
    df = pd.DataFrame(
        {
            "player": ["A", "B"],
            "team": ["COOP", "NYL"],
            "opp_team": ["SPO", "LAS"],
            "prop_type": ["Points", "Points"],
            "line": [10.5, 11.5],
        }
    )
    out, n = drop_allstar_props(df, sport="WNBA")
    assert n == 1
    assert list(out["player"]) == ["B"]


def test_espn_summary_allstar_game_note():
    summary = {
        "header": {
            "gameNote": "AT&T WNBA All-Star Game",
            "competitions": [
                {
                    "competitors": [
                        {"team": {"abbreviation": "COOP", "displayName": "TEAM COOP"}},
                        {"team": {"abbreviation": "SPO", "displayName": "TEAM SPOON"}},
                    ]
                }
            ],
        }
    }
    assert is_espn_summary_allstar(summary, sport="WNBA")
    assert not is_espn_summary_allstar(
        {"header": {"gameNote": "", "competitions": [{"competitors": [{"team": {"abbreviation": "NY"}}]}]}},
        sport="WNBA",
    )
