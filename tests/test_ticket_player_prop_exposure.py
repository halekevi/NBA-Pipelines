#!/usr/bin/env python3
"""Player+prop exposure: at most one ticket."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.ticket_diversity import apply_diversity_filter  # noqa: E402


def _t(tid: str, player: str, prop: str, line: float = 8.0) -> dict:
    return {
        "ticket_id": tid,
        "n_legs": 2,
        "base_ev": 1.0 if tid.endswith("a") else 0.5,
        "legs": [
            {"player": player, "prop_type": prop, "line": line, "direction": "OVER", "edge": 0.6},
            {"player": "Other Player", "prop_type": "Points", "line": 20.5, "direction": "OVER", "edge": 0.55},
        ],
    }


def test_player_prop_capped_at_one():
    cfg = {
        "enabled": True,
        "max_leg_exposure": 5,
        "max_player_exposure": 5,
        "max_player_prop_exposure": 1,
        "max_jaccard_overlap": 1.0,
        "void_risk_min_sample": 0,
    }
    # Same player+prop, different lines — still one ticket only.
    tickets = [
        _t("a", "Sabrina Ionescu", "Rebounds", 8.0),
        _t("b", "Sabrina Ionescu", "Rebounds", 7.5),
    ]
    out = apply_diversity_filter(tickets, cfg)
    assert len(out) == 1
    assert out[0]["ticket_id"] == "a"


def test_different_props_allowed():
    cfg = {
        "enabled": True,
        "max_leg_exposure": 5,
        "max_player_exposure": 5,
        "max_player_prop_exposure": 1,
        "max_jaccard_overlap": 1.0,
        "void_risk_min_sample": 0,
    }
    tickets = [
        _t("a", "Sabrina Ionescu", "Rebounds", 8.0),
        _t("b", "Sabrina Ionescu", "Assists", 5.5),
    ]
    out = apply_diversity_filter(tickets, cfg)
    assert len(out) == 2
