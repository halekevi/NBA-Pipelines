"""WNBA prop-specific defense soft priority + same-game density preference."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from combined_slate_tickets import (  # noqa: E402
    _attach_ticket_pick_order,
    _same_game_density_multiplier,
)
from utils.wnba_prop_defense import (  # noqa: E402
    attach_stat_defense_columns,
    clear_defense_cache,
    lookup_stat_defense,
    prop_category,
    soft_priority_delta,
)


def test_lookup_falls_back_to_overall_rank(tmp_path):
    csv = tmp_path / "wnba_defense_by_stat.csv"
    pd.DataFrame(
        [
            {
                "team": "WSH",
                "pts_rank": 13,
                "pts_tier": "EASY",
                "overall_rank": 3,
                "n_teams": 15,
            }
        ]
    ).to_csv(csv, index=False)
    clear_defense_cache()
    pts = lookup_stat_defense("WSH", "Points", csv_path=str(csv))
    assert pts["stat_def_rank"] == 13
    unknown = lookup_stat_defense("WSH", "Steals", csv_path=str(csv))
    assert unknown["stat_def_rank"] == 3
    clear_defense_cache()


def test_prop_category_mapping():
    assert prop_category("Rebounds") == "reb"
    assert prop_category("Pts+Rebs+Asts") == "pra"
    assert prop_category("3-PT Made") == "fg3m"
    assert prop_category("Free Throws Attempted") == "fta"
    assert prop_category("Free Throws Made") == "ftm"
    assert prop_category("FG Made") == "fgm"
    assert prop_category("FG Attempted") == "fga"
    assert prop_category("Two Pointers Made") == "fg2m"
    assert prop_category("Two Pointers Attempted") == "fg2a"
    assert prop_category("Steals") == "stl"
    assert prop_category("Unknown Prop XYZ") == ""


def test_soft_priority_deltas():
    assert soft_priority_delta(
        sport="WNBA", prop="Rebounds", direction="OVER", stat_def_tier="EASY"
    ) == pytest.approx(0.06)
    assert soft_priority_delta(
        sport="WNBA", prop="Rebounds", direction="OVER", stat_def_tier="HARD"
    ) == pytest.approx(-0.04)
    assert soft_priority_delta(
        sport="WNBA", prop="Rebounds", direction="UNDER", stat_def_tier="HARD"
    ) == pytest.approx(0.04)
    assert soft_priority_delta(
        sport="WNBA", prop="Rebounds", direction="UNDER", stat_def_tier="EASY"
    ) == pytest.approx(-0.03)
    # Non-whitelist
    assert soft_priority_delta(
        sport="WNBA", prop="Steals", direction="OVER", stat_def_tier="EASY"
    ) == 0.0
    # Non-WNBA
    assert soft_priority_delta(
        sport="NBA", prop="Rebounds", direction="OVER", stat_def_tier="EASY"
    ) == 0.0


def test_soft_priority_kill_switch(monkeypatch):
    monkeypatch.setenv("PROPORACLE_WNBA_STAT_DEF_SOFT", "0")
    assert soft_priority_delta(
        sport="WNBA", prop="Rebounds", direction="OVER", stat_def_tier="EASY"
    ) == 0.0


def test_attach_absent_stat_def_no_crash():
    df = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "player": "A",
                "opp": "ZZZ_FAKE",
                "prop_type": "Rebounds",
                "direction": "OVER",
                "def_tier": "WEAK",
            }
        ]
    )
    out = attach_stat_defense_columns(df)
    assert "stat_def_tier" in out.columns
    assert "stat_def_rank" in out.columns
    # Unknown opp → empty tier, no exception
    assert str(out.iloc[0]["stat_def_tier"] or "") in ("", "UNK")


def test_rule_sort_prefers_easy_reb_opp_over_hard():
    rows = [
        {
            "sport": "WNBA",
            "player": "Easy Opp",
            "team": "ATL",
            "opp": "CHI",
            "prop_type": "Rebounds",
            "pick_type": "Goblin",
            "direction": "OVER",
            "line": 8.5,
            "ml_prob": 0.70,
            "rank_score": 80,
            "tier": "A",
            "def_tier": "AVG",
            "stat_def_tier": "EASY",
            "l5_over": 4,
            "l5_under": 1,
            "l10_over": 8,
            "l10_under": 2,
            "l5_avg": 9.0,
            "szn_avg": 9.0,
            "edge": 1.0,
            "min_tier": "MID",
            "usage_role": "",
            "shot_role": "",
        },
        {
            "sport": "WNBA",
            "player": "Hard Opp",
            "team": "NY",
            "opp": "LV",
            "prop_type": "Rebounds",
            "pick_type": "Goblin",
            "direction": "OVER",
            "line": 8.5,
            "ml_prob": 0.70,
            "rank_score": 80,
            "tier": "A",
            "def_tier": "AVG",
            "stat_def_tier": "HARD",
            "l5_over": 4,
            "l5_under": 1,
            "l10_over": 8,
            "l10_under": 2,
            "l5_avg": 9.0,
            "szn_avg": 9.0,
            "edge": 1.0,
            "min_tier": "MID",
            "usage_role": "",
            "shot_role": "",
        },
    ]
    df = pd.DataFrame(rows)
    ranked = _attach_ticket_pick_order(df, "rule")
    easy_pri = float(ranked.loc[ranked["player"] == "Easy Opp", "__ts_pri"].iloc[0])
    hard_pri = float(ranked.loc[ranked["player"] == "Hard Opp", "__ts_pri"].iloc[0])
    assert easy_pri > hard_pri


def test_overall_def_still_works_without_stat_def():
    df = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "player": "Weak D",
                "team": "ATL",
                "opp": "CHI",
                "prop_type": "Points",
                "pick_type": "Standard",
                "direction": "OVER",
                "line": 18.5,
                "ml_prob": 0.65,
                "rank_score": 70,
                "tier": "B",
                "def_tier": "WEAK",
                "l5_over": 3,
                "l5_under": 2,
                "l10_over": 6,
                "l10_under": 4,
                "l5_avg": 19.0,
                "szn_avg": 18.5,
                "edge": 1.5,
                "min_tier": "MID",
                "usage_role": "",
                "shot_role": "",
            }
        ]
    )
    ranked = _attach_ticket_pick_order(df, "rule")
    assert "__ts_pri" in ranked.columns
    assert float(ranked["__ts_pri"].iloc[0]) > 0.5


def test_same_game_density_maxsg2_below_maxsg1(monkeypatch):
    monkeypatch.setenv("PROPORACLE_SAME_GAME_DENSITY_BASE", "0.90")
    maxsg1 = [
        {"team": "ATL", "opp": "CHI"},
        {"team": "NY", "opp": "LV"},
        {"team": "LA", "opp": "SEA"},
    ]
    maxsg2 = [
        {"team": "ATL", "opp": "CHI"},
        {"team": "CHI", "opp": "ATL"},  # same game
        {"team": "NY", "opp": "LV"},
    ]
    m1 = _same_game_density_multiplier(maxsg1)
    m2 = _same_game_density_multiplier(maxsg2)
    assert m1 == pytest.approx(1.0)
    assert m2 == pytest.approx(0.90)
    assert m2 < m1
