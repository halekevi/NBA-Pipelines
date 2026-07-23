"""Tests for Jul-22 cell HR priority boost / weak-lane downrank."""

from __future__ import annotations

import pandas as pd

from utils.cell_hr_priority import (
    cell_hr_priority_boost_series,
    load_jul22_cell_sets,
)


def test_jul22_priority_and_weak_sets_load():
    priority, weak = load_jul22_cell_sets()
    assert ("MLB", "pitcherstrikeouts", "Goblin", "OVER") in priority
    assert ("WNBA", "points", "Goblin", "OVER") in priority
    assert ("SOCCER", "shots", "Goblin", "OVER") in weak
    assert ("TENNIS", "aces", "Goblin", "OVER") in weak
    assert ("TENNIS", "doublefaults", "Goblin", "OVER") in weak


def test_boost_priority_and_penalize_weak():
    df = pd.DataFrame(
        [
            {
                "sport": "MLB",
                "prop_type": "Pitcher Strikeouts",
                "pick_type": "Goblin",
                "direction": "OVER",
                "category_hr": 0.5,
                "category_hr_n": 5,
            },
            {
                "sport": "SOCCER",
                "prop_type": "Shots",
                "pick_type": "Goblin",
                "direction": "OVER",
                "category_hr": 0.4,
                "category_hr_n": 200,
            },
            {
                "sport": "TENNIS",
                "prop_type": "Aces",
                "pick_type": "Goblin",
                "direction": "OVER",
            },
            {
                "sport": "WNBA",
                "prop_type": "Steals",
                "pick_type": "Standard",
                "direction": "OVER",
                "category_hr": 0.66,
                "category_hr_n": 40,
            },
        ]
    )
    boost = cell_hr_priority_boost_series(df)
    assert float(boost.iloc[0]) > 0  # Jul22 priority
    assert float(boost.iloc[1]) < 0  # Soccer OVER Shots weak
    assert float(boost.iloc[2]) < 0  # Tennis Ace Goblin weak
    assert float(boost.iloc[3]) > 0  # rolling category_hr ≥60% n≥10
