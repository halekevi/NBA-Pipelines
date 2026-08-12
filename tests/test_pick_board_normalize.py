"""Tests for Goblin/Demon alt-board normalization."""
from __future__ import annotations

from utils.pick_board_normalize import (
    normalize_row_pick_type,
    normalize_rows_pick_types,
    resolve_true_standard_line,
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


def test_synthetic_std_offset_uses_true_standard_sibling():
    rows = [
        {"sport": "WNBA", "player": "Sabrina Ionescu", "prop": "Points", "pick_type": "Standard", "dir": "UNDER", "line": 18.5, "season_avg": 19.7, "projection": 17.85},
        {"sport": "WNBA", "player": "Sabrina Ionescu", "prop": "Points", "pick_type": "Goblin", "dir": "OVER", "line": 11.5, "standard_line": 13.0, "season_avg": 19.7, "projection": 17.85, "edge": 6.0},
        {"sport": "WNBA", "player": "Sabrina Ionescu", "prop": "Points", "pick_type": "Goblin", "dir": "OVER", "line": 34.5, "standard_line": 36.0, "season_avg": 19.7, "projection": 17.85, "edge": -16.0},
    ]
    assert resolve_true_standard_line(rows) == 18.5
    out = normalize_rows_pick_types(rows)
    by_line = {float(r["line"]): r for r in out}
    assert by_line[11.5]["pick_type"] == "Goblin"
    assert by_line[11.5]["standard_line"] == 18.5
    assert by_line[34.5]["pick_type"] == "Demon"


def test_tennis_hard_goblin_double_faults_not_treated_as_synthetic():
    rows = [
        {
            "sport": "TENNIS",
            "player": "Coco Gauff",
            "prop": "Double Faults",
            "pick_type": "Standard",
            "dir": "OVER",
            "line": 4.0,
            "season_avg": 4.1,
            "projection": 3.6,
            "edge": 0.1,
        },
        {
            "sport": "TENNIS",
            "player": "Coco Gauff",
            "prop": "Double Faults",
            "pick_type": "Goblin",
            "dir": "OVER",
            "line": 6.5,
            "standard_line": 4.0,
            "season_avg": 4.1,
            "projection": 3.6,
            "edge": -2.9,
        },
    ]
    out = normalize_rows_pick_types(rows)
    gob = next(r for r in out if float(r["line"]) == 6.5)
    assert gob["pick_type"] == "Demon"
    assert gob["standard_line"] == 4.0


def test_absurd_goblin_without_standard_uses_baseline():
    rows = [
        {
            "sport": "WNBA",
            "player": "X",
            "prop": "Points",
            "pick_type": "Goblin",
            "dir": "OVER",
            "line": 34.5,
            "standard_line": 36.0,
            "season_avg": 19.7,
            "projection": 17.85,
        },
        {
            "sport": "WNBA",
            "player": "X",
            "prop": "Points",
            "pick_type": "Goblin",
            "dir": "OVER",
            "line": 29.5,
            "standard_line": 31.0,
            "season_avg": 19.7,
            "projection": 17.85,
        },
    ]
    out = normalize_rows_pick_types(rows)
    assert all(r["pick_type"] == "Demon" for r in out)
