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
    assert tet.STRONG_MIN_P_WIN_3LEG >= 0.35
    # STRONG leg cap must allow 3-leg product above the 3-leg floor.
    assert tet.STRONG_MAX_LEG_PROB_FOR_P_WIN**3 >= tet.STRONG_MIN_P_WIN_3LEG
    assert tet.STRONG_MAX_LEG_PROB_FOR_P_WIN > cst.MAX_LEG_PROB_FOR_P_WIN
    # Common 0.72-clip Goblin legs must still clear the 3-leg floor.
    assert 0.72**3 >= tet.STRONG_MIN_P_WIN_3LEG


def test_main_max_legs_default_is_three():
    assert cst.MAIN_GRADED_MAX_LEGS == 3
    assert cst.MAIN_GRADED_MIN_LEGS == 2
    assert cst.MAIN_MLB_GOBLIN_MIN_LEG_PROB >= 0.68
    assert cst.MAIN_MLB_GOBLIN_STRESS_MIN_LEG_PROB >= 0.72
    assert cst.MLB_MAX_LEGS <= 3
    assert cst.CROSS_PIPELINE_MAX_LEGS <= 3
    assert cst.HIGH_PROB_PARLAY_MAX_LEGS <= 3
    assert cst.GOBLIN_MAX_LEGS >= 6
    assert cst.LONG_PARLAY_ENABLED is True
    # Jul-24 construction defaults
    assert cst.MAIN_PREFERRED_MIN_PAYOUT_X >= 2.2
    assert cst.SHORT_FLOOR_HARD_X >= 2.0
    assert cst.SHORT_FLOOR_HIGH_P_WIN >= 0.70
    assert cst.LONG_PARLAY_MAX_SLIPS <= 8
    assert cst.WEB_TICKET_TEMPLATE_BY_LEGS[4] >= cst.WEB_TICKET_TEMPLATE_BY_LEGS[3]
    assert cst.WEB_TICKET_TEMPLATE_BY_LEGS[5] <= 4
    assert cst.WEB_TICKET_TEMPLATE_BY_LEGS[6] <= 3


def test_tighten_long_parlay_keeps_top_floor_ev():
    payload = {
        "groups": [
            {
                "group_name": "MLB Goblin 5",
                "n_legs": 5,
                "tickets": [
                    {
                        # floor_ev = 0.10*4 - 1 = -0.6 → drop
                        "est_win_prob": 0.10,
                        "legs": [{"sport": "MLB", "pick_type": "Goblin"}] * 5,
                        "payout": {
                            "display_min_x": 4.0,
                            "power_min_x": 4.0,
                            "payout_source": "live_cdp",
                        },
                    },
                    {
                        # floor_ev = 0.25*5 - 1 = +0.25 → keep
                        "est_win_prob": 0.25,
                        "legs": [{"sport": "MLB", "pick_type": "Goblin"}] * 5,
                        "payout": {
                            "display_min_x": 5.0,
                            "power_min_x": 5.0,
                            "payout_source": "live_cdp",
                        },
                    },
                    {
                        # floor_ev = 0.05*8 - 1 = -0.6 → drop
                        "est_win_prob": 0.05,
                        "legs": [{"sport": "MLB", "pick_type": "Goblin"}] * 6,
                        "payout": {
                            "display_min_x": 8.0,
                            "power_min_x": 8.0,
                            "payout_source": "live_cdp",
                        },
                    },
                ],
            }
        ]
    }
    out = cst.tighten_long_parlay_payload(payload)
    slips = [t for g in out.get("groups") or [] for t in (g.get("tickets") or [])]
    assert len(slips) == 1
    assert float(slips[0]["est_win_prob"]) == 0.25
    assert float(slips[0].get("floor_ev") or -1) >= 0.0


def test_demons_excluded_from_main_pool():
    row = {
        "sport": "WNBA",
        "pick_type": "demon",
        "tier": "A",
        "direction": "OVER",
        "prop_type": "Points",
        "composite_hit_rate": 0.90,
        "hit_rate": 0.90,
        "ml_prob": 0.90,
        "l5_over": 5,
        "l5_under": 0,
    }
    assert not cst._row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55
    )


def test_strong_max_legs_hard_capped_at_three():
    assert tet.STRONG_MAX_LEGS == 3
    assert cst.STRONG_MAX_LEGS == 3


def test_mlb_goblin_hits_banned_on_main():
    """Jul-18 miss engine: Hits/TB Goblin OVER no longer eligible for MAIN."""
    row = {
        "sport": "MLB",
        "pick_type": "goblin",
        "tier": "A",
        "direction": "OVER",
        "prop_type": "Hits",
        "composite_hit_rate": 0.85,
        "hit_rate": 0.85,
        "ml_prob": 0.85,
        "l5_over": 5,
        "l5_under": 0,
    }
    assert cst._main_leg_prop_banned(row)
    assert not cst._row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55
    )
    row["prop_type"] = "Total Bases"
    assert not cst._row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55
    )
    # Pitcher K Goblin OVER still allowed above MLB stress floor (strikeouts is stressed).
    row["prop_type"] = "Strikeouts"
    row["composite_hit_rate"] = 0.73
    row["hit_rate"] = 0.73
    row["ml_prob"] = 0.73
    assert not cst._main_leg_prop_banned(row)
    assert cst._row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55
    )
    # Pitching Outs allowed at base MLB Goblin floor 0.68.
    row["prop_type"] = "Pitching Outs"
    row["composite_hit_rate"] = 0.69
    row["hit_rate"] = 0.69
    row["ml_prob"] = 0.69
    assert not cst._main_leg_prop_banned(row)
    assert cst._row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55
    )


def test_mlb_standard_over_banned_on_main():
    """Ledger-gated Standard props (Hits OVER) stay off MAIN; Singles OVER can pass gate."""
    hits = {
        "sport": "MLB",
        "pick_type": "standard",
        "tier": "A",
        "direction": "OVER",
        "prop_type": "Hits",
        "composite_hit_rate": 0.80,
        "hit_rate": 0.80,
        "ml_prob": 0.80,
        "l5_over": 4,
        "l5_under": 1,
    }
    assert not cst._row_win_rate_eligible(
        hits, min_leg_prob=0.62, min_composite_hr=0.55
    )
    assert cst._leg_standard_prop_direction_gated(hits)
    assert not cst._leg_standard_prop_direction_gated(
        {**hits, "prop_type": "Singles"}
    )


def test_mlb_construction_ban_shared_across_builders():
    hits_gob = {
        "sport": "MLB",
        "pick_type": "Goblin",
        "direction": "OVER",
        "prop_type": "Hits",
    }
    std_over = {
        "sport": "MLB",
        "pick_type": "Standard",
        "direction": "OVER",
        "prop_type": "Hits",
    }
    pitcher = {
        "sport": "MLB",
        "pick_type": "Goblin",
        "direction": "OVER",
        "prop_type": "Pitching Outs",
    }
    assert cst._leg_mlb_construction_banned(hits_gob)
    assert cst._leg_mlb_construction_banned(std_over)
    assert not cst._leg_mlb_construction_banned(pitcher)
    assert cst._mlb_leg_sizes_capped([2, 3, 4, 5, 6]) == [2, 3]


def test_filter_payload_mlb_construction_hygiene():
    payload = {
        "groups": [
            {
                "group_name": "MLB 5",
                "tickets": [
                    {
                        "legs": [
                            {
                                "sport": "MLB",
                                "pick_type": "Goblin",
                                "direction": "OVER",
                                "prop_type": "Hits",
                            },
                            {
                                "sport": "MLB",
                                "pick_type": "Goblin",
                                "direction": "OVER",
                                "prop_type": "Strikeouts",
                            },
                        ]
                    },
                    {
                        "legs": [
                            {
                                "sport": "MLB",
                                "pick_type": "Goblin",
                                "direction": "OVER",
                                "prop_type": "Strikeouts",
                            },
                            {
                                "sport": "MLB",
                                "pick_type": "Goblin",
                                "direction": "OVER",
                                "prop_type": "Pitching Outs",
                            },
                        ]
                    },
                ],
            }
        ]
    }
    out = cst.filter_payload_mlb_construction_hygiene(payload)
    kept = out["groups"][0]["tickets"]
    assert len(kept) == 1
    assert kept[0]["legs"][0]["prop_type"] == "Strikeouts"


def test_mlb_same_game_hitter_stack_is_audit_only():
    """Stack detector still flags correlated hitters; construction no longer rejects on it."""
    ticket = {
        "legs": [
            {
                "sport": "MLB",
                "team": "NYY",
                "opp": "BOS",
                "prop_type": "Hits",
                "player": "A",
            },
            {
                "sport": "MLB",
                "team": "NYY",
                "opp": "BOS",
                "prop_type": "Total Bases",
                "player": "B",
            },
            {
                "sport": "MLB",
                "team": "LAD",
                "opp": "SF",
                "prop_type": "Strikeouts",
                "player": "C",
            },
        ]
    }
    assert cst._winrate_ticket_mlb_same_game_hitter_stack(ticket)
    assert not cst._winrate_ticket_construction_reject(ticket)


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
