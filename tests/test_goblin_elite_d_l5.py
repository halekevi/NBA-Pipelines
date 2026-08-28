"""Goblin OVER with L5>=4 is not faded vs Elite D; Standard OVER still is."""

from __future__ import annotations

import pandas as pd
from utils.l5_recency_policy import goblin_over_clears_tough_defense
from utils.prop_signal_score import context_signal_adjustment_series


def test_jackie_goblin_points_clears_elite_d():
    assert goblin_over_clears_tough_defense("Goblin", "OVER", 5.0) is True
    assert goblin_over_clears_tough_defense("Goblin", "OVER", 4.0) is True
    assert goblin_over_clears_tough_defense("Goblin", "OVER", 3.0) is False
    assert goblin_over_clears_tough_defense("Standard", "OVER", 5.0) is False
    assert goblin_over_clears_tough_defense("Goblin", "UNDER", 5.0) is False


def test_signal_score_skips_elite_penalty_on_hot_goblin():
    rows = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "pick_type": "Goblin",
                "direction": "OVER",
                "def_tier": "Elite",
                "l5_over": 5.0,
                "l5_under": 0.0,
                "l10_over": 8.0,
                "l10_under": 2.0,
            },
            {
                "sport": "WNBA",
                "pick_type": "Standard",
                "direction": "OVER",
                "def_tier": "Elite",
                "l5_over": 5.0,
                "l5_under": 0.0,
                "l10_over": 8.0,
                "l10_under": 2.0,
            },
        ]
    )
    adj = context_signal_adjustment_series(rows)
    # Same L5/L10; Standard should be 0.03 lower from Elite OVER fade.
    assert float(adj.iloc[0] - adj.iloc[1]) == 0.03
