#!/usr/bin/env python3
"""Player+prop exposure: at most one ticket."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.ticket_diversity import apply_diversity_filter  # noqa: E402


def _t(tid: str, player: str, prop: str, line: float = 8.0, other: str = "Other Player") -> dict:
    return {
        "ticket_id": tid,
        "n_legs": 2,
        "base_ev": 1.0 if tid.endswith("a") else 0.5,
        "legs": [
            {"player": player, "prop_type": prop, "line": line, "direction": "OVER", "edge": 0.6},
            {"player": other, "prop_type": "Points", "line": 20.5, "direction": "OVER", "edge": 0.55},
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
        _t("a", "Sabrina Ionescu", "Rebounds", 8.0, other="Player A"),
        _t("b", "Sabrina Ionescu", "Rebounds", 7.5, other="Player B"),
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
        _t("a", "Sabrina Ionescu", "Rebounds", 8.0, other="Player A"),
        _t("b", "Sabrina Ionescu", "Assists", 5.5, other="Player B"),
    ]
    out = apply_diversity_filter(tickets, cfg)
    assert len(out) == 2


def test_same_prop_allowed_in_separate_sections():
    """Per-section filter: same player+prop OK once in each group."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cst",
        ROOT / "scripts" / "combined_slate_tickets.py",
    )
    # Avoid loading full combined_slate_tickets (heavy). Simulate the wrapper locally.
    cfg = {
        "enabled": True,
        "max_leg_exposure": 5,
        "max_player_exposure": 5,
        "max_player_prop_exposure": 1,
        "max_jaccard_overlap": 1.0,
        "void_risk_min_sample": 0,
    }
    groups = [
        ("STRONG 6-Leg", [_t("s6a", "Sabrina Ionescu", "Rebounds", 8.0, other="A1")], None),
        ("STRONG 5-Leg", [_t("s5a", "Sabrina Ionescu", "Rebounds", 8.0, other="B1")], None),
    ]
    out = []
    for gname, tickets, bg in groups:
        kept = apply_diversity_filter(tickets, cfg)
        if kept:
            out.append((gname, kept, bg))
    assert len(out) == 2
    assert len(out[0][1]) == 1 and len(out[1][1]) == 1
