"""Soccer ticket hygiene: Demon / Goblin UNDER / excluded props only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from combined_slate_tickets import (  # noqa: E402
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


def test_soccer_goblin_over_allowed():
    assert soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Goblin",
            "direction": "OVER",
            "prop_type": "Shots",
            "hit_rate": 0.40,
            "abs_edge": 0.01,
            "ml_prob": 0.40,
        }
    )


def test_soccer_standard_shots_over_allowed():
    assert soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Shots",
            "hit_rate": 0.40,
            "abs_edge": 0.01,
            "ml_prob": 0.40,
            "leg_prob": 0.40,
        }
    )


def test_soccer_excluded_prop_rejected():
    assert not soccer_allowed_leg(
        {
            "sport": "SOCCER",
            "pick_type": "Standard",
            "direction": "UNDER",
            "prop_type": "Tackles",
            "hit_rate": 0.90,
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
