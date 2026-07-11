"""Unit tests for mix-grid planning (3-leg Goblin/Standard floors)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_payout_data import (  # noqa: E402
    MIX_GRID_RECIPES,
    build_mix_grid_plan,
    mix_avg_floors_from_grid,
    summarize_mix_grid_floors,
)


def _std(i: int) -> dict:
    return {
        "player": f"Std{i}",
        "line": 5.5,
        "prop_type": "Points",
        "pick_type": "standard",
    }


def _gob(i: int, dist: float = 1.0) -> dict:
    return {
        "player": f"Gob{i}",
        "line": 3.5,
        "prop_type": "Points",
        "pick_type": "goblin",
        "standard_line": 3.5 + dist,
        "line_distance": dist,
    }


def test_recipes_include_key_3leg_cells():
    labels = {t for t, _g, _s in MIX_GRID_RECIPES}
    for need in ("3S", "3G", "1G+2S", "2G+1S", "2G", "2S"):
        assert need in labels


def test_build_mix_grid_plan_includes_3g_with_n_legs():
    plans = build_mix_grid_plan(
        [_std(i) for i in range(6)],
        [_gob(i, 1.0) for i in range(6)],
        max_slips=40,
    )
    by_type = {p["type"]: p for p in plans}
    assert "3G" in by_type
    assert by_type["3G"]["n_legs"] == 3
    assert by_type["3G"]["n_goblin"] == 3
    assert by_type["3G"]["n_standard"] == 0
    assert "1G+2S" in by_type
    assert by_type["1G+2S"]["n_legs"] == 3
    assert "2G+1S" in by_type
    assert by_type["2G+1S"]["n_legs"] == 3
    # Priority order: baselines and all-Goblin before mixed
    types = [p["type"] for p in plans]
    assert types.index("3G") < types.index("1G+2S")
    assert types.index("2G") < types.index("1G+1S")


def test_mix_avg_and_floor_summary_log_3g():
    slips = [
        {
            "type": "3G",
            "n_legs": 3,
            "n_goblin": 3,
            "n_standard": 0,
            "min_x": 3.1,
            "avg_deviation": 1.0,
            "dev_bucket": 1.0,
            "status": "ok",
        },
        {
            "type": "1G+2S",
            "n_legs": 3,
            "n_goblin": 1,
            "n_standard": 2,
            "min_x": 4.75,
            "avg_deviation": 1.0,
            "dev_bucket": 1.0,
            "status": "ok",
        },
    ]
    floors = summarize_mix_grid_floors(slips)
    assert floors["by_composition"]["3L_3G"]["avg_min_x"] == 3.1
    assert floors["by_composition"]["3L_1G"]["avg_min_x"] == 4.75
    avg = mix_avg_floors_from_grid(slips)
    assert avg[(3, 3)] == 3.1
    assert avg[(3, 1)] == 4.75
