"""MAIN pool modes: mixed / goblin_only / standard_only + elite Standard OVER gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from combined_slate_tickets import (  # noqa: E402
    MAIN_POOL_MODE,
    MAIN_POOL_MODE_GOBLIN,
    MAIN_POOL_MODE_STANDARD,
    _row_win_rate_eligible,
    _standard_direction_floor,
    _standard_over_elite_ok,
    build_graded_main_win_rate_payload,
    filter_main_high_prob_payload,
    prefer_main_min_payout_payload,
    soccer_allowed_leg,
)


def _base_leg(
    *,
    pick_type: str,
    direction: str,
    tier: str = "A",
    sport: str = "WNBA",
    player: str = "P One",
    leg_prob: float = 0.72,
    hit_rate: float = 0.72,
    prop_type: str = "Points",
) -> dict:
    return {
        "sport": sport,
        "player": player,
        "prop_type": prop_type,
        "pick_type": pick_type,
        "direction": direction,
        "line": 12.5,
        "hit_rate": hit_rate,
        "composite_hit_rate": hit_rate,
        "ml_prob": leg_prob,
        "leg_prob": leg_prob,
        "rank_score": 80,
        "tier": tier,
        "l5_over": 5.0,
        "l5_under": 4.0,
        "l10_over": 8.0,
        "l10_under": 7.0,
        "l10_over_pct": 0.80,
        "l10_under_pct": 0.70,
        "consistency_grade": "A",
        "def_tier": "WEAK" if direction == "OVER" else "ELITE",
        "team_top3_rank": 1 if direction == "OVER" else None,
        "team_bottom3_rank": 1 if direction == "UNDER" else None,
        "top3_weak_overperformer": 1 if direction == "OVER" else 0,
        "top3_elite_fader": 1 if direction == "UNDER" else 0,
        "strat_hit_rate": 0.75,
        "strat_n": 40,
    }


def test_standard_under_passes_without_elite_stack():
    row = _base_leg(pick_type="Standard", direction="UNDER", leg_prob=0.66, hit_rate=0.66)
    # Drop stack_70 matchup fields so elite OVER would fail; UNDER should still pass.
    row["def_tier"] = ""
    row["strat_hit_rate"] = 0.50
    row["strat_n"] = 5
    row["l5_under"] = 2.0
    assert _row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55, qualify_standard=True
    )


def test_standard_over_requires_elite_gate():
    weak = _base_leg(pick_type="Standard", direction="OVER", tier="B", leg_prob=0.72)
    assert not _standard_over_elite_ok(weak)
    assert not _row_win_rate_eligible(
        weak, min_leg_prob=0.62, min_composite_hr=0.55, qualify_standard=True
    )

    elite = _base_leg(pick_type="Standard", direction="OVER", tier="A", leg_prob=0.72)
    assert _standard_over_elite_ok(elite)
    assert _row_win_rate_eligible(
        elite, min_leg_prob=0.62, min_composite_hr=0.55, qualify_standard=True
    )


def test_soccer_standard_over_banned_under_allowed():
    """Soccer Shots OVER is hard-gated on Standard; UNDER stays allowed."""
    over = {
        "sport": "SOCCER",
        "pick_type": "Standard",
        "direction": "OVER",
        "prop_type": "Shots",
        "hit_rate": 0.80,
        "abs_edge": 0.20,
        "leg_prob": 0.80,
        "ml_prob": 0.80,
    }
    under = {
        "sport": "SOCCER",
        "pick_type": "Standard",
        "direction": "UNDER",
        "prop_type": "Shots",
        "hit_rate": 0.70,
        "abs_edge": 0.10,
        "leg_prob": 0.70,
        "ml_prob": 0.70,
    }
    assert soccer_allowed_leg(over) is False
    assert soccer_allowed_leg(under) is True


def test_standard_prop_gates_not_sport_wide():
    """Goblins stay open; Standards gate by prop×direction (ledger)."""
    from combined_slate_tickets import _leg_standard_prop_direction_gated

    # Banned Standard prop
    assert _leg_standard_prop_direction_gated(
        {
            "sport": "MLB",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Total Bases",
        }
    )
    # Keep-candidate Standard Singles OVER is NOT gated
    assert not _leg_standard_prop_direction_gated(
        {
            "sport": "MLB",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Singles",
        }
    )
    # Same prop as Goblin is never Standard-gated
    assert not _leg_standard_prop_direction_gated(
        {
            "sport": "WNBA",
            "pick_type": "Goblin",
            "direction": "OVER",
            "prop_type": "Rebounds",
        }
    )
    assert _leg_standard_prop_direction_gated(
        {
            "sport": "WNBA",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Rebounds",
        }
    )


def test_standard_prop_gate_clears_on_perfect_l5():
    """WNBA ledger ban/hard_gate clears at L5=5/5; MLB stays gated (negative lift)."""
    from combined_slate_tickets import _leg_standard_prop_direction_gated

    pra = {
        "sport": "WNBA",
        "pick_type": "Standard",
        "direction": "OVER",
        "prop_type": "Pts+Rebs+Asts",
        "l5_over": 4,
        "l5_under": 1,
    }
    assert _leg_standard_prop_direction_gated(pra)
    assert not _leg_standard_prop_direction_gated({**pra, "l5_over": 5, "l5_under": 0})

    pr = {
        "sport": "WNBA",
        "pick_type": "Standard",
        "direction": "OVER",
        "prop_type": "Pts+Rebs",
        "l5_over": 3,
        "l5_under": 2,
    }
    assert _leg_standard_prop_direction_gated(pr)
    assert not _leg_standard_prop_direction_gated({**pr, "l5_over": 5.0})

    hits = {
        "sport": "MLB",
        "pick_type": "Standard",
        "direction": "OVER",
        "prop_type": "Hits",
        "l5_over": 5,
        "l5_under": 0,
    }
    assert _leg_standard_prop_direction_gated(hits)
    assert _leg_standard_prop_direction_gated({**hits, "l5_over": 4})



def test_