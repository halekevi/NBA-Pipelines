"""Profitability-path defaults: STRONG/MAIN ≤3 legs + MLB Goblin floors."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import combined_slate_tickets as cst  # noqa: E402
from utils import ticket_ev_tiers as tet  # noqa: E402


def test_strong_max_legs_default_is_three():
    assert tet.STRONG_MAX_LEGS == 3
    assert tet.STRONG_MIN_P_WIN_2LEG >= 0.45
    assert tet.STRONG_MIN_P_WIN_3LEG >= 0.38


def test_main_max_legs_default_is_three():
    assert cst.MAIN_GRADED_MAX_LEGS == 3
    assert cst.MAIN_MLB_GOBLIN_MIN_LEG_PROB >= 0.68
    assert cst.MAIN_MLB_GOBLIN_STRESS_MIN_LEG_PROB >= 0.72


def test_mlb_goblin_hits_need_stress_floor():
    row = {
        "sport": "MLB",
        "pick_type": "goblin",
        "tier": "A",
        "direction": "OVER",
        "prop_type": "Hits",
        "composite_hit_rate": 0.69,
        "hit_rate": 0.69,
        "ml_prob": 0.69,
        "l5_over": 4,
        "l5_under": 1,
    }
    # Below stress floor 0.72
    assert not cst._row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55
    )
    row["composite_hit_rate"] = 0.73
    row["hit_rate"] = 0.73
    row["ml_prob"] = 0.73
    assert cst._row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55
    )


def test_strong_builder_excludes_mlb_hits_prop():
    assert not cst._strong_builder_prop_allowed("Hits", "MLB")
    assert not cst._strong_builder_prop_allowed("Total Bases", "MLB")
    assert cst._strong_builder_prop_allowed("Pitching Outs", "MLB")


def test_strong_builder_respects_max_legs_default(monkeypatch):
    monkeypatch.setattr(cst, "STRONG_MAX_LEGS", 3)
    monkeypatch.setattr(tet, "STRONG_MAX_LEGS", 3)
    rows = []
    for i, name in enumerate(["A", "B", "C", "D", "E", "F"]):
        rows.append(
            {
                "sport": "WNBA",
                "player": f"Player {name}",
                "team": "NY",
                "opp": "LA",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "line": 10.5,
                "hit_rate": 0.80,
                "rank_score": 90,
                "ml_prob": 0.80,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.9 - i * 0.01,
            }
        )
    df = pd.DataFrame(rows)
    tickets = cst.build_strong_tickets(
        df,
        max_tickets=50,
        min_p_win_2leg=0.01,
        min_p_win_3leg=0.01,
        exhaust_pool=True,
        pick_mode="goblin",
    )
    assert tickets
    assert max(len(t.get("rows") or []) for t in tickets) <= 3
