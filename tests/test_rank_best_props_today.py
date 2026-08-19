"""Filters for the daily best-props / Top Edges board."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

from rank_best_props_today import (  # noqa: E402
    _atp_tier_from_rank,
    _over_d_ok,
    _under_d_ok,
    bucket,
    recs,
)


def test_soccer_avg_does_not_pass_d_gate():
    assert _over_d_ok("SOCCER", "Weak")
    assert _over_d_ok("SOCCER", "Below Avg")
    assert not _over_d_ok("SOCCER", "Avg")
    assert _under_d_ok("SOCCER", "Elite")
    assert _under_d_ok("SOCCER", "Above Avg")
    assert not _under_d_ok("SOCCER", "Avg")


def test_wnba_mlb_weak_over_elite_under_only():
    for sport in ("WNBA", "MLB"):
        assert _over_d_ok(sport, "Weak")
        assert not _over_d_ok(sport, "Below Avg")
        assert not _over_d_ok(sport, "Avg")
        assert _under_d_ok(sport, "Elite")
        assert not _under_d_ok(sport, "Above Avg")


def test_tennis_atp_tiers():
    assert _atp_tier_from_rank(8) == "Elite"
    assert _atp_tier_from_rank(20) == "Above Avg"
    assert _atp_tier_from_rank(40) == "Avg"
    assert _atp_tier_from_rank(80) == "Below Avg"
    assert _atp_tier_from_rank(120) == "Weak"


def _row(**kwargs):
    base = {
        "sport": "TENNIS",
        "player": "Test",
        "prop_type": "Total Games",
        "pick_type": "Goblin",
        "final_bet_direction": "OVER",
        "line": 21.5,
        "l5_over": 5,
        "l5_under": 0,
        "opp_team": "Rival",
        "opponent_rank": 80,
        "stat_season_avg": 24.0,
        "model_dir": "OVER",
    }
    base.update(kwargs)
    return base


def test_tennis_unknown_opp_does_not_pass_d():
    df = pd.DataFrame([_row(opp_team="UNKNOWN_OPP", opponent_rank=75)])
    so, su, gob = bucket(recs(df), "TENNIS")
    assert so == []
    assert su == []
    assert gob == []


def test_tennis_total_games_goblin_5_of_0_still_eligible():
    df = pd.DataFrame([_row(prop_type="Total Games", l5_over=5, l5_under=0, opponent_rank=80)])
    so, su, gob = bucket(recs(df), "TENNIS")
    assert len(gob) == 1
    assert gob[0]["player"] == "Test"
    assert gob[0]["prop"] == "Total Games"


def test_tennis_fills_opp_rank_from_slate_player_and_skips_placeholder():
    from rank_best_props_today import fill_tennis_opp_rank_from_slate

    df = pd.DataFrame(
        [
            {
                "player": "Frances Tiafoe",
                "opp_team": "LEARNER TIEN",
                "player_atp_rank": 23,
                "opponent_rank": 75,
            },
            {
                "player": "Learner Tien",
                "opp_team": "FRANCES TIAFOE",
                "player_atp_rank": 12,
                "opponent_rank": 75,
            },
            {
                "player": "Unknown Player",
                "opp_team": "UNKNOWN_OPP",
                "player_atp_rank": 40,
                "opponent_rank": 75,
            },
        ]
    )
    out = fill_tennis_opp_rank_from_slate(df)
    assert int(out.loc[0, "opponent_rank"]) == 12
    assert int(out.loc[1, "opponent_rank"]) == 23
    assert pd.isna(out.loc[2, "opponent_rank"]) or out.loc[2, "opponent_rank"] is None


def test_wnba_weak_over_and_elite_under_buckets():
    over = _row(
        sport="WNBA",
        player="Over Star",
        pick_type="Standard",
        prop_type="Points",
        def_tier="Weak",
        OVERALL_DEF_RANK=12,
        opp_team="CHI",
        team="NY",
        opponent_rank=None,
    )
    under = _row(
        sport="WNBA",
        player="Under Star",
        pick_type="Standard",
        prop_type="Points",
        final_bet_direction="UNDER",
        model_dir="UNDER",
        l5_over=1,
        l5_under=4,
        def_tier="Elite",
        OVERALL_DEF_RANK=2,
        opp_team="NY",
        team="CHI",
        stat_season_avg=10.0,
        line=14.5,
        opponent_rank=None,
    )
    mid = _row(
        sport="WNBA",
        player="Mid D",
        pick_type="Standard",
        prop_type="Points",
        def_tier="Avg",
        OVERALL_DEF_RANK=7,
        opp_team="DAL",
        opponent_rank=None,
    )
    df = pd.DataFrame([over, under, mid])
    so, su, gob = bucket(recs(df), "WNBA")
    assert [r["player"] for r in so] == ["Over Star"]
    assert [r["player"] for r in su] == ["Under Star"]
    assert gob == []
