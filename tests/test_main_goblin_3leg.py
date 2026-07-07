"""Tests for Goblin-only 3-leg primary MAIN track."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from combined_slate_tickets import (  # noqa: E402
    MAIN_DEFAULT_LEGS,
    MAIN_POOL_MODE,
    MAIN_THIN_POOL_MIN_LEGS,
    _row_main_four_leg_eligible,
    _row_win_rate_eligible,
    _ticket_passes_main_four_leg_gate,
    build_graded_main_win_rate_payload,
    build_win_rate_ticket_groups,
)


def _leg(**kwargs) -> dict:
    base = {
        "sport": "WNBA",
        "player": "Player One",
        "prop_type": "Points",
        "pick_type": "Goblin",
        "tier": "A",
        "direction": "OVER",
        "line": 10.5,
        "hit_rate": 0.72,
        "ml_prob": 0.70,
        "composite_hit_rate": 0.70,
        "l10_streak": "HOT",
        "l10_over": 8.0,
    }
    base.update(kwargs)
    return base


def _frame(n: int, *, tier: str = "A", pick_type: str = "Goblin", ml_prob: float = 0.70) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            _leg(
                player=f"Player {i}",
                prop_type="Points" if i % 2 == 0 else "Rebounds",
                tier=tier,
                pick_type=pick_type,
                ml_prob=ml_prob,
            )
        )
    return pd.DataFrame(rows)


def test_goblin_only_excludes_standard():
    std = _leg(pick_type="Standard", tier="A")
    gob = _leg(pick_type="Goblin", tier="A")
    assert _row_win_rate_eligible(gob, min_leg_prob=0.62, min_composite_hr=0.52, goblin_only=True)
    assert not _row_win_rate_eligible(std, min_leg_prob=0.62, min_composite_hr=0.52, goblin_only=True)


def test_four_leg_gate_requires_tier_a_hot_ml():
    ok = _leg(tier="A", l10_streak="HOT", ml_prob=0.70)
    bad = _leg(tier="B", l10_streak="HOT", ml_prob=0.70)
    assert _row_main_four_leg_eligible(ok)
    assert not _row_main_four_leg_eligible(bad)
    assert _ticket_passes_main_four_leg_gate([ok, ok, ok, ok])
    assert not _ticket_passes_main_four_leg_gate([ok, ok, ok, bad])


def test_build_win_rate_prefers_three_leg_when_goblin_only_3leg():
    frames = [("WNBA", _frame(8))]
    groups = build_win_rate_ticket_groups(
        frames,
        min_leg_prob=0.62,
        min_composite_hr=0.52,
        max_legs=4,
        max_tickets=5,
        goblin_only=True,
        goblin_only_3leg=True,
    )
    assert groups
    leg_counts = {len(t.get("rows") or []) for _, tickets, _ in groups for t in tickets}
    assert MAIN_DEFAULT_LEGS in leg_counts
    assert all(n <= 4 for n in leg_counts)
    assert not any(n >= 5 for n in leg_counts)


def test_thin_pool_allows_two_leg_fallback():
    frames = [("WNBA", _frame(MAIN_THIN_POOL_MIN_LEGS - 1))]
    groups = build_win_rate_ticket_groups(
        frames,
        min_leg_prob=0.62,
        min_composite_hr=0.52,
        max_legs=4,
        max_tickets=5,
        goblin_only=True,
        goblin_only_3leg=True,
    )
    leg_counts = {len(t.get("rows") or []) for _, tickets, _ in groups for t in tickets}
    assert 2 in leg_counts


def test_filter_main_goblin_only_3leg_payload():
    from combined_slate_tickets import filter_main_goblin_only_3leg_payload

    payload = {
        "pool_mode": MAIN_POOL_MODE,
        "groups": [
            {
                "group_name": "Test",
                "tickets": [
                    {
                        "legs": [
                            _leg(pick_type="Goblin"),
                            _leg(pick_type="Goblin", player="P2"),
                            _leg(pick_type="Goblin", player="P3"),
                        ]
                    },
                    {
                        "legs": [
                            _leg(pick_type="Standard"),
                            _leg(pick_type="Goblin", player="P2"),
                            _leg(pick_type="Goblin", player="P3"),
                        ]
                    },
                ],
            }
        ],
    }
    out = filter_main_goblin_only_3leg_payload(payload)
    tickets = out["groups"][0]["tickets"]
    assert len(tickets) == 1
    assert all("goblin" in str(l.get("pick_type", "")).lower() for l in tickets[0]["legs"])


def test_graded_main_payload_sets_pool_mode():
    frames = [("WNBA", _frame(8))]
    payload = build_graded_main_win_rate_payload(
        frames,
        "2026-07-10",
        {},
        bankroll=0.0,
        curve_stake_usd=0.0,
        goblin_only_3leg=True,
    )
    assert payload.get("pool_mode") == MAIN_POOL_MODE
    assert payload.get("goblin_only") is True
    filters = payload.get("filters") or {}
    assert filters.get("pool_mode") == MAIN_POOL_MODE
