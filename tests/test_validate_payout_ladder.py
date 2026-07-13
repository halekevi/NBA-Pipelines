"""Unit tests for payout ladder validation helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import collect_payout_data as cpd  # noqa: E402
import validate_payout_ladder as vpl  # noqa: E402


def test_rejects_live_game_clock_as_player():
    player, line, prop = cpd.parse_card_lines(
        ["Q2 9:08", "7.5", "Assists", "More", "Less"]
    )
    assert player is None or not cpd._GAME_CLOCK_RE.match(str(player))
    assert not cpd._is_valid_board_card(
        {"player": "Q2 9:08", "prop_type": "Assists", "line": 7.5, "pick_type": "goblin"}
    )
    assert not cpd._is_valid_board_card(
        {"player": "Halftime", "prop_type": "Points", "line": 31.5, "pick_type": "demon"}
    )
    assert cpd._is_valid_board_card(
        {"player": "Erica Wheeler", "prop_type": "Assists", "line": 5.5, "pick_type": "goblin"}
    )


def test_discovery_builds_diverse_goblin_delta_recipes():
    standard = [
        {"player": f"Std{i}", "prop_type": "Points", "line": 20.5 + i, "pick_type": "standard"}
        for i in range(6)
    ]
    goblins = [
        {"player": "Gob1", "prop_type": "Points", "line": 16.5, "pick_type": "goblin", "line_distance": 1.5, "standard_line": 18.0},
        {"player": "Gob2", "prop_type": "Assists", "line": 4.5, "pick_type": "goblin", "line_distance": 2.0, "standard_line": 6.5},
        {"player": "Gob3", "prop_type": "Rebounds", "line": 3.5, "pick_type": "goblin", "line_distance": 3.5, "standard_line": 7.0},
        {"player": "Gob4", "prop_type": "Points", "line": 12.5, "pick_type": "goblin", "line_distance": 5.0, "standard_line": 17.5},
        {"player": "Gob5", "prop_type": "Assists", "line": 2.5, "pick_type": "goblin", "line_distance": 1.5, "standard_line": 4.0},
    ]
    recipes = vpl.build_discovery_recipes_from_board(
        standard=standard, goblins=goblins, demons=[], max_cases=40, exhaustive=True
    )
    assert recipes
    assert any(r.get("composition") == "0S+2G+0D" for r in recipes)
    assert any(r.get("goblin_delta_sig") for r in recipes)
    # Uniform-Δ 2G for a known bin
    assert any(r.get("goblin_delta_sig") == "1.5+1.5" for r in recipes)


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
