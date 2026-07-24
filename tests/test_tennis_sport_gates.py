"""Tennis sport-gate unit tests: Ace/DF ban, totals-only, L5 floors."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from combined_slate_tickets import (  # noqa: E402
    TENNIS_LEG_MIN_HIT_RATE,
    _main_leg_prop_banned,
    tennis_allowed_leg,
)


def _leg(**kwargs):
    base = {
        "sport": "TENNIS",
        "pick_type": "Goblin",
        "direction": "OVER",
        "prop_type": "Total Games",
        "l5_over": 4,
        "l5_under": 1,
        "tier": "B",
    }
    base.update(kwargs)
    return base


def test_tennis_ace_goblin_hard_banned():
    assert not tennis_allowed_leg(_leg(prop_type="Aces", l5_over=5))
    assert _main_leg_prop_banned(_leg(prop_type="Aces"))


def test_tennis_double_faults_goblin_hard_banned():
    assert not tennis_allowed_leg(_leg(prop_type="Double Faults", l5_over=5))
    assert _main_leg_prop_banned(_leg(prop_type="Double Faults"))


def test_tennis_goblin_totals_requires_l5():
    assert not tennis_allowed_leg(_leg(prop_type="Total Games", l5_over=2))
    assert tennis_allowed_leg(_leg(prop_type="Total Games", l5_over=3))
    assert tennis_allowed_leg(_leg(prop_type="Total Games Won", l5_over=4))


def test_tennis_standard_over_totals_allowed_with_l5():
    # Standard OVER totals preferred lane (Jul-22/23); needs L5 + not serve junk.
    assert tennis_allowed_leg(
        _leg(
            pick_type="Standard",
            direction="OVER",
            prop_type="Total Games Won",
            l5_over=4,
            tier="B",
        )
    )


def test_tennis_standard_under_totals_allowed_with_l5():
    assert tennis_allowed_leg(
        _leg(
            pick_type="Standard",
            direction="UNDER",
            prop_type="Total Games",
            l5_over=1,
            l5_under=4,
            tier="B",
        )
    )


def test_tennis_leg_min_hit_rate_raised():
    assert TENNIS_LEG_MIN_HIT_RATE[2] >= 0.68
    assert TENNIS_LEG_MIN_HIT_RATE[3] >= 0.72
