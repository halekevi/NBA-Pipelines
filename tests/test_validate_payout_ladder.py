"""Unit tests for payout ladder validation helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_payout_ladder as vpl  # noqa: E402


def test_verdict_in_range_and_near():
    recipe = {"ladder_min_x": 2.1, "ladder_max_x": 2.8, "ladder_avg_x": 2.5}
    assert vpl._verdict(2.6, recipe) == "in_range"
    assert vpl._verdict(2.55, recipe) in ("in_range", "near_avg")
    assert vpl._verdict(5.0, recipe) == "mismatch"


def test_pick_cards_matches_goblin_count():
    standard = [
        {"player": f"S{i}", "prop_type": "Points", "line": 20.5 + i, "pick_type": "standard"}
        for i in range(5)
    ]
    goblins = [
        {"player": "G1", "prop_type": "Points", "line": 16.5, "pick_type": "goblin", "line_distance": 1.5, "standard_line": 18.0},
        {"player": "G2", "prop_type": "Rebounds", "line": 4.5, "pick_type": "goblin", "line_distance": 2.0, "standard_line": 6.5},
        {"player": "G3", "prop_type": "Assists", "line": 3.5, "pick_type": "goblin", "line_distance": 1.0, "standard_line": 4.5},
    ]
    recipe = {
        "n_standard": 0,
        "n_goblin": 2,
        "n_demon": 0,
        "goblin_delta_sig": "1.5+2",
    }
    pick = vpl._pick_cards_for_recipe(recipe, standard=standard, goblins=goblins, demons=[])
    assert pick is not None
    assert len(pick["legs"]) == 2
    assert all(l["pick_type"] == "Goblin" for l in pick["legs"])
