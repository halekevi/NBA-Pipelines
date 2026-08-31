"""Filters for the daily best-props / Top Edges board."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

from rank_best_props_today import (  # noqa: E402
    _atp_tier_from_rank,
    _avg_windows,
    _over_d_ok,
    _under_d_ok,
    bucket,
    filter_step8_to_slate_date,
    l5_window_sort_key,
    recs,
    step8_empty_reason,
)


def test_soccer_avg_does_not_pass_d_gate():
    assert _over_d_ok("SOCCER", "Weak")
    assert _over_d_ok("SOCCER", "Below Avg")
    assert not _over_d_ok("SOCCER", "Avg")
    assert _under_d_ok("SOCCER", "Elite")
    assert _under_d_ok("SOCCER", "Above Avg")
    assert not _under_d_ok("SOCCER", "Avg")


def test_all_sports_wide_d_bands():
    """Default: OVER Weak|Below Avg; UNDER Elite|Above Avg. Avg never passes."""
    for sport in ("WNBA", "MLB", "SOCCER", "TENNIS", "NBA", "CFB", "CBB", "NHL", "NFL"):
        assert _over_d_ok(sport, "Weak")
        assert _over_d_ok(sport, "Below Avg")
        assert not _over_d_ok(sport, "Avg")
        assert not _over_d_ok(sport, "Elite")
        assert not _over_d_ok(sport, "Above Avg")
        assert _under_d_ok(sport, "Elite")
        assert _under_d_ok(sport, "Above Avg")
        assert not _under_d_ok(sport, "Avg")
        assert not _under_d_ok(sport, "Weak")
        assert not _under_d_ok(sport, "Below Avg")


def test_mlb_hitter_strikeouts_d_invert():
    """Hitter Ks invert wide: OVER Elite|Above Avg; UNDER Weak|Below Avg."""
    for prop in ("Hitter Strikeouts", "hitter_strikeouts", "Batter Strikeouts"):
        assert _over_d_ok("MLB", "Elite", prop)
        assert _over_d_ok("MLB", "Above Avg", prop)
        assert not _over_d_ok("MLB", "Weak", prop)
        assert not _over_d_ok("MLB", "Below Avg", prop)
        assert not _over_d_ok("MLB", "Avg", prop)
        assert _under_d_ok("MLB", "Weak", prop)
        assert _under_d_ok("MLB", "Below Avg", prop)
        assert not _under_d_ok("MLB", "Elite", prop)
        assert not _under_d_ok("MLB", "Above Avg", prop)
        assert not _under_d_ok("MLB", "Avg", prop)
    # Pitcher Ks / Hits keep production alignment (wide bands).
    assert _over_d_ok("MLB", "Weak", "Pitcher Strikeouts")
    assert _over_d_ok("MLB", "Below Avg", "Pitcher Strikeouts")
    assert not _over_d_ok("MLB", "Elite", "Pitcher Strikeouts")
    assert _over_d_ok("MLB", "Weak", "Hits")
    assert _over_d_ok("MLB", "Below Avg", "Hits")
    assert not _over_d_ok("MLB", "Elite", "Hits")
    assert _under_d_ok("MLB", "Elite", "Hits")
    assert _under_d_ok("MLB", "Above Avg", "Hits")


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
    """Unknown opp fails D (badge miss) but still clears the L5 list gate."""
    df = pd.DataFrame([_row(opp_team="UNKNOWN_OPP", opponent_rank=75)])
    so, su, gob = bucket(recs(df), "TENNIS")
    assert so == []
    assert su == []
    assert len(gob) == 1
    assert gob[0]["checks"]["D"] is False
    assert "D" in gob[0]["misses"]


def test_tennis_total_games_goblin_5_of_0_still_eligible():
    df = pd.DataFrame([_row(prop_type="Total Games", l5_over=5, l5_under=0, opponent_rank=80)])
    so, su, gob = bucket(recs(df), "TENNIS")
    assert len(gob) == 1
    assert gob[0]["player"] == "Test"
    assert gob[0]["prop"] == "Total Games"
    assert not gob[0].get("matchup_note")


def test_tennis_total_games_under_vs_nakashima_band_gets_tight_note():
    df = pd.DataFrame(
        [
            _row(
                player="Taylor Fritz",
                prop_type="Total Games",
                pick_type="Standard",
                final_bet_direction="UNDER",
                line=25.5,
                l5_over=0,
                l5_under=5,
                opp_team="Brandon Nakashima",
                opponent_rank=22,
                stat_season_avg=22.3,
                model_dir="UNDER",
            )
        ]
    )
    _so, su, _gob = bucket(recs(df), "TENNIS")
    assert len(su) == 1
    note = su[0].get("matchup_note") or ""
    assert "Nakashima" in note
    assert "OVER fades" in note
    assert "UNDER also fades" in note


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
    below = _row(
        sport="WNBA",
        player="Below Star",
        pick_type="Standard",
        prop_type="Points",
        def_tier="Below Avg",
        OVERALL_DEF_RANK=10,
        opp_team="IND",
        team="NY",
        opponent_rank=None,
    )
    df = pd.DataFrame([over, under, mid, below])
    so, su, gob = bucket(recs(df), "WNBA")
    # L5 gate only — Avg still listed but fails D; Below Avg now passes D.
    by_name = {r["player"]: r for r in so}
    assert set(by_name) == {"Over Star", "Below Star", "Mid D"}
    assert by_name["Over Star"]["checks"]["D"] is True
    assert by_name["Below Star"]["checks"]["D"] is True
    assert by_name["Mid D"]["checks"]["D"] is False
    assert [r["player"] for r in su] == ["Under Star"]
    assert gob == []


def test_nfl_step8_display_columns_feed_recs():
    """NFL/NFLP share the step8 sheet; display columns must still badge D."""
    df = pd.DataFrame(
        [
            {
                "sport": "NFL",
                "Player": "Cam Ward",
                "Team": "TEN",
                "Opp": "SEA",
                "Prop": "passing_yards",
                "Pick Type": "Standard",
                "Direction": "OVER",
                "Line": 189.5,
                "L5 Over": 4,
                "L5 Under": 1,
                "Def Tier": "Above Avg",
                "Def Rank": 10,
                "Projection": 210.0,
                "League": "NFLP",
            },
            {
                "sport": "NFL",
                "Player": "Jason Myers",
                "Team": "SEA",
                "Opp": "TEN",
                "Prop": "fg_made",
                "Pick Type": "Standard",
                "Direction": "UNDER",
                "Line": 1.5,
                "L5 Over": 1,
                "L5 Under": 4,
                "Def Tier": "Above Avg",
                "Def Rank": 9,
                "Projection": 1.2,
                "League": "NFLP",
            },
        ]
    )
    so, su, gob = bucket(recs(df), "NFL")
    # NFLP: 2025 L5 skill OVER is Sit — not listed even though L5=4.
    assert so == []
    assert len(su) == 1
    assert su[0]["player"] == "Jason Myers"
    assert su[0]["checks"]["D"] is True  # UNDER vs Above Avg
    assert su[0]["starter_policy"] == "plays"
    assert gob == []


def test_nflp_lists_backup_d_over_without_l5():
    df = pd.DataFrame(
        [
            {
                "sport": "NFL",
                "Player": "Drew Lock",
                "Team": "SEA",
                "Opp": "TEN",
                "Prop": "passing_yards",
                "Pick Type": "Standard",
                "Direction": "OVER",
                "Line": 91.5,
                "L5 Over": None,
                "L5 Under": None,
                "Def Tier": "Below Avg",
                "Def Rank": 23,
                "Projection": 91.5,
                "League": "NFLP",
            }
        ]
    )
    so, su, gob = bucket(recs(df), "NFL")
    assert len(so) == 1
    assert so[0]["player"] == "Drew Lock"
    assert so[0]["starter_policy"] == "backup"
    assert so[0]["checks"]["D"] is True
    assert su == []
    assert gob == []


def test_nfl_regular_season_keeps_l5_gate():
    df = pd.DataFrame(
        [
            {
                "sport": "NFL",
                "Player": "Cam Ward",
                "Team": "TEN",
                "Opp": "SEA",
                "Prop": "passing_yards",
                "Pick Type": "Standard",
                "Direction": "OVER",
                "Line": 189.5,
                "L5 Over": 4,
                "L5 Under": 1,
                "Def Tier": "Above Avg",
                "Def Rank": 10,
                "Projection": 210.0,
                "League": "NFL",
            }
        ]
    )
    so, su, gob = bucket(recs(df), "NFL")
    assert len(so) == 1
    assert so[0]["player"] == "Cam Ward"
    assert so[0]["checks"]["D"] is False  # OVER vs Above Avg still listed
    assert so[0]["starter_policy"] == "normal"


def test_l5_zero_unders_not_treated_as_missing():
    """5/0 must stay 5/0. `or` short-circuit used to print tennis L5 as 5/None."""
    df = pd.DataFrame(
        [
            {
                "sport": "TENNIS",
                "player": "Mary Stoiana",
                "prop_type": "Total Games",
                "pick_type": "Standard",
                "final_bet_direction": "OVER",
                "line": 20.0,
                "l5_over": 5,
                "l5_under": 0,
                "stat_season_avg": 25.2,
                "DEF_TIER": "Weak",
                "opponent_rank": 250,
                "team": "MARY STOIANA",
                "opp_team": "HARMONY TAN",
                "league": "WTA / HARD",
            }
        ]
    )
    rows = recs(df)
    assert rows[0]["l5_over"] == 5
    assert rows[0]["l5_under"] == 0


def test_day_ahead_uses_start_time_not_fetch_game_date():
    df = pd.DataFrame(
        [
            {
                "start_time": "2026-08-26T00:00:00-04:00",
                "game_date": "2026-08-25",
                "player": "A",
            },
            {
                "start_time": "2026-08-25T20:00:00-04:00",
                "game_date": "2026-08-25",
                "player": "B",
            },
        ]
    )
    out = filter_step8_to_slate_date(df, "2026-08-26", "WNBA")
    assert list(out["player"]) == ["A"]


def test_tennis_list_window_keeps_monday_slam():
    df = pd.DataFrame(
        [
            {
                "start_time": "2026-08-29T13:00:00-04:00",
                "player": "Sat",
            },
            {
                "start_time": "2026-08-31T20:10:00-04:00",
                "player": "Tiafoe",
            },
            {
                "start_time": "2026-09-02T12:00:00-04:00",
                "player": "Wed",
            },
        ]
    )
    out = filter_step8_to_slate_date(df, "2026-08-29", "TENNIS")
    assert list(out["player"]) == ["Sat", "Tiafoe"]
    wnba = filter_step8_to_slate_date(df, "2026-08-29", "WNBA")
    assert list(wnba["player"]) == ["Sat"]


def test_recs_skips_bo5_total_games_on_bo3_tape():
    df = pd.DataFrame(
        [
            {
                "sport": "TENNIS",
                "player": "Frances Tiafoe",
                "prop_type": "Total Games",
                "pick_type": "Standard",
                "final_bet_direction": "UNDER",
                "line": 40.5,
                "last5_over": 0,
                "last5_under": 5,
                "stat_last5_avg": 23.4,
                "stat_g1": 22,
                "stat_g2": 21,
                "stat_g3": 25,
                "stat_g4": 19,
                "stat_g5": 30,
                "opp_team": "Martin Damm Jr.",
                "DEF_TIER": "Weak",
            }
        ]
    )
    assert recs(df) == []


def test_step8_empty_reason_warns_when_step1_exists(tmp_path):
    tennis = tmp_path / "outputs" / "2026-08-29" / "tennis"
    tennis.mkdir(parents=True)
    (tennis / "step1_tennis_props.csv").write_text("player\nX\n", encoding="utf-8")
    msg = step8_empty_reason(
        tmp_path, "2026-08-29", "TENNIS", "tennis", "step8_tennis_direction.csv"
    )
    assert "WARN" in msg
    assert "step1 exists" in msg


def test_avg_windows_prefers_last5_not_season():
    r = pd.Series(
        {
            "stat_last5_avg": 94.0,
            "stat_last10_avg": 70.0,
            "stat_season_avg": 70.0,
            "stat_g1": 92,
            "stat_g2": 99,
            "stat_g3": 94,
            "stat_g4": 95,
            "stat_g5": 90,
        }
    )
    l5, l10, seas = _avg_windows(r)
    assert l5 == 94.0
    assert l10 == 70.0
    assert seas == 70.0


def test_recs_l5_dist_does_not_replace_season_cover():
    df = pd.DataFrame(
        [
            _row(
                sport="MLB",
                player="Rhett Lowder",
                prop_type="Pitches Thrown",
                pick_type="Standard",
                line=89.5,
                l5_over=5,
                l5_under=0,
                stat_last5_avg=94.0,
                stat_last10_avg=70.0,
                stat_season_avg=70.0,
                model_dir="OVER",
            )
        ]
    )
    rows = recs(df)
    assert len(rows) == 1
    r = rows[0]
    assert r["avg_l5"] == 94.0
    assert r["dist_l5"] == 4.5
    assert r["avg_l10"] == 70.0
    assert r["avg_season"] == 70.0
    assert r["cover"] == -19.5


def test_l5_window_sort_uses_l5_then_l10_then_season():
    a = {"dist_l5": 4.5, "dist_l10": -19.5, "dist_season": -19.5, "sport": "MLB", "player": "A"}
    b = {"dist_l5": 4.5, "dist_l10": 10.0, "dist_season": 1.0, "sport": "MLB", "player": "B"}
    c = {"dist_l5": 12.0, "dist_l10": 1.0, "dist_season": 1.0, "sport": "CFB", "player": "C"}
    ranked = sorted([a, b, c], key=l5_window_sort_key)
    assert [r["player"] for r in ranked] == ["C", "A", "B"]


def test_l10_reads_tennis_line_hits_over_10():
    from rank_best_props_today import _l10

    row = {"line_hits_over_10": 10, "line_hits_under_10": 0}
    assert _l10(row, True) == 10
    assert _l10(row, False) == 0
    named = {"l10_over": 8, "line_hits_over_10": 10}
    assert _l10(named, True) == 8

