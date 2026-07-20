"""Soccer sport-gate unit tests: UNDER preferred (Standard), Goblin OVER-only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from combined_slate_tickets import (  # noqa: E402
    SOCCER_OVER_MIN_EDGE,
    SOCCER_OVER_MIN_HIT_RATE,
    goblin_direction_ok,
    soccer_allowed_leg,
)


def test_goblin_under_never_ok():
    assert not goblin_direction_ok(
        {"pick_type": "Goblin", "direction": "UNDER"}
    )
    assert goblin_direction_ok(
        {"pick_type": "Goblin", "direction": "OVER"}
    )
    assert goblin_direction_ok(
        {"pick_type": "Standard", "direction": "UNDER"}
    )


def test_soccer_goblin_under_rejected():
    assert not soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Goblin",
            "direction": "UNDER",
            "prop_type": "Shots",
            "hit_rate": 0.80,
            "abs_edge": 0.2,
            "ml_prob": 0.75,
        }
    )


def test_soccer_standard_under_allowed():
    assert soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Standard",
            "direction": "UNDER",
            "prop_type": "Shots",
            "hit_rate": 0.80,
            "abs_edge": 0.1,
            "ml_prob": 0.72,
        }
    )


def test_soccer_hq_over_goblin_allowed():
    assert soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Goblin",
            "direction": "OVER",
            "prop_type": "Shots",
            "hit_rate": max(0.85, SOCCER_OVER_MIN_HIT_RATE),
            "abs_edge": max(0.25, SOCCER_OVER_MIN_EDGE),
            "ml_prob": 0.80,
        }
    )


def test_soccer_standard_shots_over_hard_gated_even_if_hq():
    """Standard Shots OVER is hard-gated; Goblin OVER remains the HQ path."""
    assert not soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Shots",
            "hit_rate": max(0.85, SOCCER_OVER_MIN_HIT_RATE),
            "abs_edge": max(0.25, SOCCER_OVER_MIN_EDGE),
            "ml_prob": 0.80,
            "leg_prob": 0.80,
        }
    )


def test_soccer_standard_shots_combo_over_banned():
    assert not soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Shots (Combo)",
            "hit_rate": 0.90,
            "abs_edge": 0.30,
            "ml_prob": 0.85,
            "leg_prob": 0.85,
        }
    )


def test_soccer_low_quality_over_rejected():
    assert not soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Shots",
            "hit_rate": 0.40,
            "abs_edge": 0.01,
            "ml_prob": 0.40,
        }
    )


def test_soccer_demon_rejected():
    assert not soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Demon",
            "direction": "OVER",
            "prop_type": "Shots",
            "hit_rate": 0.95,
            "abs_edge": 1.0,
            "ml_prob": 0.90,
        }
    )
