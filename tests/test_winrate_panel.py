"""Win-rate Today's Best panel guards (bench legs, sort score)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import combined_slate_tickets as cst  # noqa: E402


def test_bench_risk_detects_support_low():
    leg = {
        "sport": "NBA",
        "min_tier": "LOW",
        "usage_role": "SUPPORT",
        "shot_role": "LOW_VOL",
    }
    assert cst._winrate_leg_bench_risk(leg) is True


def test_bench_risk_false_for_starter():
    leg = {
        "sport": "NBA",
        "min_tier": "HIGH",
        "usage_role": "PRIMARY",
        "shot_role": "HIGH_VOL",
    }
    assert cst._winrate_leg_bench_risk(leg) is False


def test_same_game_bench_stack():
    ticket = {
        "legs": [
            {
                "sport": "NBA",
                "team": "NYK",
                "opp": "CLE",
                "min_tier": "LOW",
                "usage_role": "SUPPORT",
                "shot_role": "LOW_VOL",
            },
            {
                "sport": "NBA",
                "team": "NYK",
                "opp": "CLE",
                "min_tier": "LOW",
                "usage_role": "SUPPORT",
                "shot_role": "LOW_VOL",
            },
        ]
    }
    assert cst._winrate_ticket_same_game_bench_stack(ticket) is True


def test_same_game_overstack_cap():
    ok2 = [
        {"sport": "WNBA", "team": "ATL", "opp": "TOR", "player": "A"},
        {"sport": "WNBA", "team": "ATL", "opp": "TOR", "player": "B"},
    ]
    bad3 = [
        {"sport": "WNBA", "team": "ATL", "opp": "TOR", "player": "A"},
        {"sport": "WNBA", "team": "ATL", "opp": "TOR", "player": "B"},
        {"sport": "WNBA", "team": "ATL", "opp": "TOR", "player": "C"},
    ]
    assert not cst._ticket_same_game_overstack(ok2)
    assert cst._ticket_same_game_overstack(bad3)
    assert cst._winrate_ticket_construction_reject({"legs": bad3})
    # build_tickets stores pandas Series in rows — must still reject.
    import pandas as pd

    series_rows = [pd.Series(x) for x in bad3]
    assert cst._ticket_same_game_overstack(series_rows)
    assert cst._winrate_ticket_construction_reject({"rows": series_rows})


def test_win_prob_prefers_est_win_prob_over_pcash():
    ticket = {"p_win": 0.64, "ticket_model_p_cash": 0.41, "est_win_prob": 0.58}
    assert cst._winrate_ticket_win_prob(ticket) == pytest.approx(0.58, rel=1e-3)
    # Rank score is floor-EV (p_win × floor); default floor=1.0 → equals p_win.
    assert cst._winrate_ticket_rank_score(ticket) == pytest.approx(0.58, rel=1e-3)


def test_rank_score_uses_floor_ev_not_wr_alone():
    low_floor = {
        "est_win_prob": 0.60,
        "payout": {"display_min_x": 1.5, "power_min_x": 1.5, "payout_source": "live_cdp"},
        "legs": [{"sport": "WNBA", "pick_type": "Goblin"}] * 2,
    }
    high_floor = {
        "est_win_prob": 0.45,
        "payout": {"display_min_x": 4.0, "power_min_x": 4.0, "payout_source": "live_cdp"},
        "legs": [{"sport": "WNBA", "pick_type": "Goblin"}] * 2,
    }
    # 0.45 × 4.0 = 1.80 > 0.60 × 1.5 = 0.90
    assert cst._winrate_ticket_rank_score(high_floor) > cst._winrate_ticket_rank_score(low_floor)


def test_mlb_goblin_4l_rank_boost():
    base = {
        "est_win_prob": 0.40,
        "payout": {"display_min_x": 5.0, "power_min_x": 5.0, "payout_source": "live_cdp"},
        "legs": [
            {"sport": "MLB", "pick_type": "Goblin"},
            {"sport": "MLB", "pick_type": "Goblin"},
            {"sport": "MLB", "pick_type": "Goblin"},
            {"sport": "MLB", "pick_type": "Goblin"},
        ],
    }
    other = {
        "est_win_prob": 0.40,
        "payout": {"display_min_x": 5.0, "power_min_x": 5.0, "payout_source": "live_cdp"},
        "legs": [
            {"sport": "WNBA", "pick_type": "Goblin"},
            {"sport": "WNBA", "pick_type": "Goblin"},
            {"sport": "WNBA", "pick_type": "Goblin"},
            {"sport": "WNBA", "pick_type": "Goblin"},
        ],
    }
    assert cst._ticket_is_mlb_goblin_n(base, 4)
    assert not cst._ticket_is_mlb_goblin_n(other, 4)
    assert cst._winrate_ticket_rank_score(base) > cst._winrate_ticket_rank_score(other)


def test_rank_score_not_driven_by_ticket_model_p_cash():
    ticket = {"p_win": 0.50, "ticket_model_p_cash": 0.90, "est_win_prob": 0.52}
    assert cst._winrate_ticket_win_prob(ticket) == pytest.approx(0.52, rel=1e-3)


def test_leg_prob_cap_lower_for_bench():
    leg = {
        "leg_prob_used": 0.99,
        "sport": "NBA",
        "min_tier": "LOW",
        "usage_role": "SUPPORT",
        "shot_role": "LOW_VOL",
    }
    assert cst._leg_prob_for_p_win_from_mapping(leg) <= 0.62
