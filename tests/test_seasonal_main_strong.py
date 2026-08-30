"""Seasonal MAIN excludes + expanded STRONG sports."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from combined_slate_tickets import (  # noqa: E402
    STRONG_BUILDER_SPORTS,
    _strong_builder_prop_allowed,
    _strong_candidate_legs,
    _sport_in_season_for_main,
    _sport_slug_off_season,
    main_exclude_sports_for_date,
)
import pandas as pd


def test_main_excludes_nfl_before_season():
    # Golf has no resume calendar; year-round when a board exists (not in default exclude).
    excl = main_exclude_sports_for_date("2026-07-14")
    assert "NFL" in excl
    assert "CFB" in excl
    assert "CBB" in excl
    assert "WCBB" in excl
    assert "GOLF" not in excl


def test_main_reactivates_nfl_near_kickoff():
    # Resume 2026-09-09 with 7 lead days → open 2026-09-02
    assert "NFL" not in main_exclude_sports_for_date("2026-09-02")
    assert "NFL" not in main_exclude_sports_for_date("2026-09-09")
    assert "NFL" in main_exclude_sports_for_date("2026-09-01")


def test_main_reactivates_cfb_before_week_zero():
    # CFB resume 2026-08-27 − 7d = 2026-08-20
    assert "CFB" not in main_exclude_sports_for_date("2026-08-20")
    assert "CFB" in main_exclude_sports_for_date("2026-08-19")


def test_nflp_preseason_opens_nfl_main():
    from combined_slate_tickets import _nflp_slate_exists

    if not _nflp_slate_exists("2026-08-23"):
        return
    assert "NFL" not in main_exclude_sports_for_date("2026-08-23")
    assert _sport_in_season_for_main("NFL", "2026-08-23")
    assert not _sport_slug_off_season("nfl", "2026-08-23")


def test_sport_slug_off_season_uses_resume():
    assert _sport_slug_off_season("nfl", "2026-07-14")
    assert not _sport_slug_off_season("nfl", "2026-09-09")
    assert _sport_in_season_for_main("CBB", "2026-11-01")
    assert not _sport_in_season_for_main("CBB", "2026-10-01")


def test_wnba_allstar_pause_window():
    from combined_slate_tickets import _wnba_family_off_season, WNBA_OFF_SEASON_RESUME

    assert _wnba_family_off_season("2026-07-25")
    assert _sport_slug_off_season("wnba", "2026-07-25")
    assert _sport_slug_off_season("wnba1h", "2026-07-25")
    assert _sport_slug_off_season("wnba1q", "2026-07-25")
    assert not _wnba_family_off_season("2026-07-18")
    assert not _wnba_family_off_season(WNBA_OFF_SEASON_RESUME)
    assert not _sport_slug_off_season("wnba", "2026-07-28")
    assert not _sport_slug_off_season("mlb", "2026-07-25")
    assert not _sport_slug_off_season("soccer", "2026-07-25")
    assert not _sport_slug_off_season("tennis", "2026-07-25")


def test_strong_sports_include_soccer_tennis_nhl():
    assert {"SOCCER", "TENNIS", "NHL", "WNBA", "MLB"} <= set(STRONG_BUILDER_SPORTS)


def test_strong_prop_allowlists_by_sport():
    assert _strong_builder_prop_allowed("Shots", "SOCCER")
    assert not _strong_builder_prop_allowed("Fouls", "SOCCER")
    assert _strong_builder_prop_allowed("Total Games Won", "TENNIS")
    assert not _strong_builder_prop_allowed("Aces", "TENNIS")
    assert _strong_builder_prop_allowed("Shots On Goal", "NHL")
    assert not _strong_builder_prop_allowed("Goals", "NHL")


def test_strong_candidate_tennis_goblin_games_hot():
    df = pd.DataFrame(
        [
            {
                "sport": "TENNIS",
                "player": "Ace Player",
                "prop_type": "Total Games Won",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "l10_streak": "HOT",
                "hit_rate": 0.75,
                "ml_prob": 0.75,
                "prop_quality_score": 0.9,
            },
            {
                "sport": "TENNIS",
                "player": "Fault Player",
                "prop_type": "Aces",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "l10_streak": "HOT",
                "hit_rate": 0.90,
                "ml_prob": 0.90,
                "prop_quality_score": 0.9,
            },
        ]
    )
    out = _strong_candidate_legs(df, pick_mode="goblin")
    assert len(out) == 1
    assert str(out.iloc[0]["player"]) == "Ace Player"
