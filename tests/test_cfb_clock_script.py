"""CFB time-of-possession / run-heavy clock script."""

from __future__ import annotations

from utils.cfb_clock_script import (
    clock_script_multiplier,
    clock_tier,
    rush_rate,
    top_minutes,
)


def test_rush_rate_and_top_minutes():
    assert abs(rush_rate(40, 40) - 0.5) < 1e-9
    assert abs(rush_rate(60, 30) - (2 / 3)) < 1e-9
    assert top_minutes(1800) == 30.0
    assert clock_tier(0.62) == "Run-heavy clock"
    assert clock_tier(0.35) == "Pass-heavy"


def test_pass_over_hurt_by_own_and_opp_clock():
    m, note = clock_script_multiplier(
        "pass_yds",
        "OVER",
        team_rush_rate=0.62,
        opp_rush_rate=0.60,
    )
    assert m < 1.0
    assert "own" in note and "opp" in note


def test_rush_over_helped_by_own_clock_hurt_by_opp():
    own, _ = clock_script_multiplier(
        "rush_yds",
        "OVER",
        team_rush_rate=0.62,
        opp_rush_rate=0.40,
    )
    vs_clock, _ = clock_script_multiplier(
        "rush_yds",
        "OVER",
        team_rush_rate=0.50,
        opp_rush_rate=0.62,
    )
    assert own > 1.0
    assert vs_clock < 1.0


def test_pass_under_boosted_when_own_team_runs():
    m, _ = clock_script_multiplier(
        "pass_yds",
        "UNDER",
        team_rush_rate=0.62,
        opp_rush_rate=0.45,
    )
    assert m > 1.0
