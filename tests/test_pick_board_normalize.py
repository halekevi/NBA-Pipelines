"""Tests for Goblin/Demon alt-board normalization."""
from __future__ import annotations

from utils.pick_board_normalize import (
    normalize_row_pick_type,
    should_reclassify_goblin_as_demon,
)


def test_goblin_over_harder_than_standard_is_demon():
    assert should_reclassify_goblin_as_demon(
        pick_type="Goblin",
        direction="OVER",
        line=48.5,
        standard_line=29.5,
    )
    row = normalize_row_pick_type(
        {
            "pick_type": "Goblin",
            "dir": "OVER",
            "line": 47.5,
            "standard_line": 29.5,
        }
    )
    assert row["pick_type"] == "Demon"
    assert row["pick_reclassified"] == "goblin_harder_than_standard"


def test_true_goblin_over_stays_goblin():
    assert not should_reclassify_goblin_as_demon(
        pick_type="Goblin",
        direction="OVER",
        line=24.5,
        standard_line=29.5,
    )
    row = normalize_row_pick_type(
        {"pick_type": "Goblin", "dir": "OVER", "line": 24.5, "standard_line": 29.5}
    )
    assert row["pick_type"] == "Goblin"
    assert "pick_reclassified" not in row


def test_goblin_under_harder_reclassifies():
    assert should_reclassify_goblin_as_demon(
        pick_type="Goblin",
        direction="UNDER",
        line=2.5,
        standard_line=6.5,
    )
