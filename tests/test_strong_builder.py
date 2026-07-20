"""Tests for STRONG-eligible Goblin+HOT ticket builder."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import combined_slate_tickets as cst  # noqa: E402
from combined_slate_tickets import (  # noqa: E402
    _apply_strong_per_slate_player_cap,
    _apply_strong_rolling_hr_gate,
    _emit_strong_mix_shadow_payload,
    _emit_strong_standard_shadow_payload,
    _ok_strong_pair,
    _row_standard_high_prob_eligible,
    _standard_direction_floor,
    _strong_candidate_legs,
    _strong_candidate_legs_mixed,
    _strong_candidate_legs_standard,
    _strong_candidate_legs_standard_prob,
    _strong_combo_players_ok,
    _ticket_rows_have_goblin_and_standard,
    build_strong_tickets,
    split_strong_tickets_by_leg_count,
)
from utils.ticket_ev_tiers import apply_slate_ev_tier_recommendations  # noqa: E402


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sport": "NBA",
                "player": "Alpha One",
                "team": "BOS",
                "opp": "NYK",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "line": 18.5,
                "hit_rate": 0.72,
                "rank_score": 90,
                "ml_prob": 0.72,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.85,
            },
            {
                "sport": "NBA",
                "player": "Beta Two",
                "team": "LAL",
                "opp": "GSW",
                "prop_type": "Rebounds",
                "pick_type": "Goblin",
                "tier": "B",
                "direction": "OVER",
                "line": 7.5,
                "hit_rate": 0.68,
                "rank_score": 80,
                "ml_prob": 0.68,
                "l10_over": 7.0,
                "l10_under": 3.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.80,
            },
            {
                "sport": "NBA",
                "player": "Cold Three",
                "team": "MIA",
                "opp": "CHI",
                "prop_type": "Assists",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "line": 5.5,
                "hit_rate": 0.40,
                "rank_score": 50,
                "ml_prob": 0.40,
                "l10_over": 2.0,
                "l10_under": 8.0,
                "l10_streak": "COLD",
                "prop_quality_score": 0.30,
            },
            {
                "sport": "NBA",
                "player": "Std Four",
                "team": "PHX",
                "opp": "DAL",
                "prop_type": "Points",
                "pick_type": "Standard",
                "tier": "A",
                "direction": "OVER",
                "line": 22.5,
                "hit_rate": 0.75,
                "rank_score": 95,
                "ml_prob": 0.75,
                "l10_over": 9.0,
                "l10_under": 1.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.90,
            },
        ]
    )


def test_strong_candidate_legs_filters_goblin_hot_ab():
    df = _sample_df()
    out = _strong_candidate_legs(df)
    assert len(out) == 2
    players = set(out["player"].astype(str))
    assert players == {"Alpha One", "Beta Two"}


def test_strong_candidate_legs_standard_only_hot_ab():
    df = _sample_df()
    out = _strong_candidate_legs_standard(df)
    assert len(out) == 1
    assert str(out.iloc[0]["player"]) == "Std Four"
    assert str(out.iloc[0]["pick_type"]).lower() == "standard"
    # Standard HOT pool must never include Goblin legs.
    assert not out["pick_type"].astype(str).str.contains("goblin", case=False, na=False).any()
    assert "Alpha One" not in set(out["player"].astype(str))


def test_standard_direction_floor_under_lower_than_over():
    under = _standard_direction_floor({"sport": "WNBA", "direction": "UNDER"})
    over = _standard_direction_floor({"sport": "WNBA", "direction": "OVER"})
    assert under < over
    assert over >= 0.68


def test_row_standard_high_prob_eligible_over_needs_higher_bar():
    weak_over = {
        "sport": "WNBA",
        "pick_type": "Standard",
        "tier": "A",
        "direction": "OVER",
        "prop_type": "Points",
        "hit_rate": 0.64,
        "ml_prob": 0.64,
        "composite_hit_rate": 0.64,
        "l10_streak": "HOT",
        "l5_over": 4,
        "l10_over": 7,
        "l10_under": 3,
    }
    strong_over = dict(
        weak_over,
        hit_rate=0.72,
        ml_prob=0.72,
        composite_hit_rate=0.72,
        l5_over=5,
        l10_over=8,
        l10_under=2,
    )
    under_ok = {
        "sport": "WNBA",
        "pick_type": "Standard",
        "tier": "B",
        "direction": "UNDER",
        "prop_type": "Points",
        "hit_rate": 0.62,
        "ml_prob": 0.62,
        "composite_hit_rate": 0.62,
        "l10_streak": "HOT",
        "l5_under": 4,
        "l10_over": 3,
        "l10_under": 7,
    }
    assert not _row_standard_high_prob_eligible(weak_over)
    assert _row_standard_high_prob_eligible(strong_over)
    assert _row_standard_high_prob_eligible(under_ok)


def test_strong_candidate_legs_standard_prob_no_hot_required():
    df = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "player": "Cold High",
                "team": "LVA",
                "opp": "NYL",
                "prop_type": "Points",
                "pick_type": "Standard",
                "tier": "A",
                "direction": "UNDER",
                "line": 14.5,
                "hit_rate": 0.72,
                "rank_score": 88,
                "ml_prob": 0.72,
                "composite_hit_rate": 0.72,
                "l10_over": 2.0,
                "l10_under": 8.0,
                "l10_streak": "COLD",
                "prop_quality_score": 0.85,
            },
            {
                "sport": "WNBA",
                "player": "Goblin Hot",
                "team": "NYL",
                "opp": "LVA",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "line": 8.5,
                "hit_rate": 0.80,
                "rank_score": 90,
                "ml_prob": 0.80,
                "composite_hit_rate": 0.80,
                "l10_over": 9.0,
                "l10_under": 1.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.90,
            },
            {
                "sport": "WNBA",
                "player": "Weak Over",
                "team": "CHI",
                "opp": "DAL",
                "prop_type": "Rebounds",
                "pick_type": "Standard",
                "tier": "A",
                "direction": "OVER",
                "line": 6.5,
                "hit_rate": 0.63,
                "rank_score": 70,
                "ml_prob": 0.63,
                "composite_hit_rate": 0.63,
                "l10_over": 6.0,
                "l10_under": 4.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.70,
            },
        ]
    )
    out = _strong_candidate_legs_standard_prob(df)
    players = set(out["player"].astype(str)) if not out.empty else set()
    assert "Cold High" in players
    assert "Goblin Hot" not in players
    assert "Weak Over" not in players


def test_build_strong_tickets_standard_prob_labels_and_policy():
    df = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "player": f"StdP {i}",
                "team": "LVA",
                "opp": "NYL",
                "prop_type": "Points",
                "pick_type": "Standard",
                "tier": "A" if i % 2 == 0 else "B",
                "direction": "UNDER" if i % 2 else "OVER",
                "line": 12.5 + i,
                "hit_rate": 0.72,
                "rank_score": 80 + i,
                "ml_prob": 0.72,
                "composite_hit_rate": 0.72,
                "l10_over": 3.0,
                "l10_under": 7.0,
                "l10_streak": "COLD",
                "prop_quality_score": 0.80,
            }
            for i in range(6)
        ]
    )
    tickets = build_strong_tickets(
        df,
        pick_mode="standard_prob",
        max_tickets=10,
        max_legs=2,
        exhaust_pool=False,
        min_p_win_2leg=0.01,
    )
    assert tickets
    assert all(t.get("strong_builder_pick") == "Standard" for t in tickets)
    assert all(t.get("pool_policy") == "standard_high_prob" for t in tickets)
    assert all(
        all(str(r.get("pick_type")).lower() == "standard" for r in t.get("rows") or [])
        for t in tickets
    )


def test_build_strong_tickets_standard_pick_mode_labels_slips():
    df = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "player": f"Player {i}",
                "team": "LVA",
                "opp": "NYL",
                "prop_type": "Points",
                "pick_type": "Standard",
                "tier": "A" if i % 2 == 0 else "B",
                "direction": "OVER",
                "line": 12.5 + i,
                "hit_rate": 0.70,
                "rank_score": 80 + i,
                "ml_prob": 0.70,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.80,
            }
            for i in range(6)
        ]
    )
    tickets = build_strong_tickets(
        df,
        pick_mode="standard",
        max_tickets=10,
        max_legs=2,
        exhaust_pool=False,
        min_p_win_2leg=0.01,
    )
    assert tickets
    assert all(t.get("strong_builder") for t in tickets)
    assert all(t.get("strong_builder_pick") == "Standard" for t in tickets)
    assert all(
        all(str(r.get("pick_type")).lower() == "standard" for r in t.get("rows") or [])
        for t in tickets
    )


def test_strong_candidate_legs_excludes_non_core_props():
    df = pd.DataFrame(
        [
            {
                "sport": "MLB",
                "player": "Hitter One",
                "prop_type": "Hits",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "l10_streak": "HOT",
                "hit_rate": 0.80,
                "ml_prob": 0.80,
            },
            {
                "sport": "MLB",
                "player": "Pitcher One",
                "prop_type": "Home Runs",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "l10_streak": "HOT",
                "hit_rate": 0.80,
                "ml_prob": 0.80,
            },
            {
                "sport": "MLB",
                "player": "Pitcher Two",
                "prop_type": "Pitching Outs",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "l10_streak": "HOT",
                "hit_rate": 0.80,
                "ml_prob": 0.80,
            },
            {
                "sport": "WNBA",
                "player": "Shooter One",
                "prop_type": "3-PT Made",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "l10_streak": "HOT",
                "hit_rate": 0.80,
                "ml_prob": 0.80,
            },
            {
                "sport": "WNBA",
                "player": "Scorer One",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "l10_streak": "HOT",
                "hit_rate": 0.80,
                "ml_prob": 0.80,
            },
        ]
    )
    out = _strong_candidate_legs(df)
    players = set(out["player"].astype(str))
    # Hits / HR / 3PT banned from STRONG core; pitching outs + WNBA points remain.
    assert players == {"Pitcher Two", "Scorer One"}


def test_build_strong_tickets_produces_labeled_slips():
    tickets = build_strong_tickets(_sample_df(), max_tickets=5, date_str="2026-06-14")
    assert len(tickets) >= 1
    t = tickets[0]
    assert t.get("strong_builder") is True
    # Sample pool only has 2 HOT Goblin players → 2-leg fallback.
    assert t.get("n_legs") == 2
    assert float(t.get("est_win_prob") or 0) >= 0.45
    for row in t.get("rows") or []:
        assert "goblin" in str(row.get("pick_type", "")).lower()
        assert str(row.get("tier", "")).upper() in ("A", "B")
        assert str(row.get("l10_streak", "")).upper() == "HOT"


def _many_hot_goblin_df(n: int = 6) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            {
                "sport": "WNBA",
                "player": f"Player {i}",
                "team": f"T{i}",
                "opp": "OPP",
                "prop_type": "Points" if i % 2 == 0 else "Assists",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "line": 5.5 + i,
                "hit_rate": 0.80,
                "rank_score": 90 - i,
                "ml_prob": 0.80,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.90 - 0.01 * i,
            }
        )
    return pd.DataFrame(rows)


def test_build_strong_tickets_prefers_three_plus_legs_when_pool_allows():
    tickets = build_strong_tickets(_many_hot_goblin_df(6), max_tickets=10, date_str="2026-07-14")
    assert tickets
    lengths = sorted({int(t.get("n_legs") or 0) for t in tickets}, reverse=True)
    assert max(lengths) >= 3
    # Board should lead with longer slips within the max-legs cap (default 3).
    assert int(tickets[0].get("n_legs") or 0) >= 3
    assert max(int(t.get("n_legs") or 0) for t in tickets) <= 3
    three = [t for t in tickets if int(t.get("n_legs") or 0) == 3]
    assert three
    assert all(float(t.get("est_win_prob") or 0) >= 0.40 for t in three)


def test_strong_win_prob_uses_raised_leg_cap_for_three_legs():
    """L5/hit-rate legs at 0.75 clear 3-leg floor only under STRONG cap (not MAIN 0.72)."""
    from utils.ticket_ev_tiers import STRONG_MAX_LEG_PROB_FOR_P_WIN, STRONG_MIN_P_WIN_3LEG

    legs = [(0.75, "l5_over_proxy"), (0.75, "l5_over_proxy"), (0.75, "l5_over_proxy")]
    main_ep = cst.win_prob(legs, 3)
    strong_ep = cst.win_prob(legs, 3, max_leg_prob=float(STRONG_MAX_LEG_PROB_FOR_P_WIN))
    assert main_ep < STRONG_MIN_P_WIN_3LEG  # 0.72^3 ≈ 0.373
    assert strong_ep >= STRONG_MIN_P_WIN_3LEG
    assert abs(strong_ep - (0.75**3)) < 1e-9


def test_build_strong_tickets_includes_five_and_six_legs_when_max_raised():
    """Opt-in long STRONG (shadow/experiments) still works when max_legs=6."""
    import utils.ticket_ev_tiers as _tet

    old = _tet.STRONG_MAX_LEGS
    old_cst = cst.STRONG_MAX_LEGS
    try:
        _tet.STRONG_MAX_LEGS = 6
        cst.STRONG_MAX_LEGS = 6
        tickets = build_strong_tickets(
            _many_hot_goblin_df(8),
            exhaust_pool=True,
            max_legs=6,
            date_str="2026-07-14",
        )
        assert tickets
        lengths = {int(t.get("n_legs") or 0) for t in tickets}
        assert 5 in lengths or 6 in lengths
        assert max(lengths) >= 5
    finally:
        _tet.STRONG_MAX_LEGS = old
        cst.STRONG_MAX_LEGS = old_cst


def test_build_strong_tickets_exhausts_unique_player_pool():
    # Exhaust + raised prop exposure yields more than a tiny soft board quota.
    old_cap = cst.STRONG_MAX_TICKETS_PER_PLAYER_PROP
    try:
        cst.STRONG_MAX_TICKETS_PER_PLAYER_PROP = 99
        tickets = build_strong_tickets(
            _many_hot_goblin_df(5),
            max_tickets=3,
            exhaust_pool=True,
            date_str="2026-07-14",
        )
        assert len(tickets) > 3
        assert any(int(t.get("n_legs") or 0) >= 3 for t in tickets)
        assert max(int(t.get("n_legs") or 0) for t in tickets) <= 3
    finally:
        cst.STRONG_MAX_TICKETS_PER_PLAYER_PROP = old_cap


def test_split_strong_tickets_by_leg_count_orders_longest_first():
    from combined_slate_tickets import split_strong_tickets_by_leg_count

    tickets = build_strong_tickets(
        _many_hot_goblin_df(8),
        exhaust_pool=True,
        date_str="2026-07-14",
    )
    buckets = split_strong_tickets_by_leg_count(tickets)
    assert buckets
    names = [b[0] for b in buckets]
    lengths = [b[2] for b in buckets]
    assert lengths == sorted(lengths, reverse=True)
    assert all(name == f"STRONG {n}-Leg" for name, _, n in buckets)
    assert names[0].startswith("STRONG ")
    for name, slips, n in buckets:
        assert slips
        assert all(
            (int(t.get("n_legs") or len(t.get("rows") or [])) == n) for t in slips
        )


def test_strong_player_prop_capped_at_two_per_leg_count():
    tickets = build_strong_tickets(
        _many_hot_goblin_df(8),
        exhaust_pool=True,
        date_str="2026-07-14",
    )
    assert tickets
    by_n: dict[int, Counter[str]] = {}
    for t in tickets:
        n = int(t.get("n_legs") or 0)
        by_n.setdefault(n, Counter())
        for row in t.get("rows") or []:
            key = (
                f"{str(row.get('player') or '').strip().lower()}::"
                f"{str(row.get('prop_type') or '').strip().lower()}"
            )
            by_n[n][key] += 1
    assert by_n, "expected strong legs"
    for n, counts in by_n.items():
        assert max(counts.values()) <= 2, f"{n}-leg exceeded 2 uses/player-prop"


def test_strong_builder_slips_keep_strong_recommendation():
    tickets = build_strong_tickets(_sample_df(), max_tickets=3, date_str="2026-06-14")
    assert tickets
    payload = {
        "date": "2026-06-14",
        "groups": [
            {
                "group_name": "STRONG Goblin HOT",
                "tickets": [
                    {
                        "strong_builder": True,
                        "n_legs": t["n_legs"],
                        "p_win": t["est_win_prob"],
                        "legs": [
                            {
                                "sport": r.get("sport"),
                                "player": r.get("player"),
                                "pick_type": r.get("pick_type"),
                                "tier": r.get("tier"),
                                "l10_streak": r.get("l10_streak"),
                                "prop_type": r.get("prop_type"),
                                "line": r.get("line"),
                            }
                            for r in t["rows"]
                        ],
                        "payout": {"ev": float(t.get("ev_power") or 1.0)},
                    }
                    for t in tickets[:1]
                ],
            }
        ],
    }
    apply_slate_ev_tier_recommendations(payload, log=False)
    rec = payload["groups"][0]["tickets"][0]["payout"]["recommendation"]
    assert rec == "STRONG"


def test_strong_rolling_hr_gate_excludes_low_hr_player():
    df = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "player": "Leonie Fiebich",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "l10_streak": "HOT",
                "prop_quality_score": 0.9,
            },
            {
                "sport": "WNBA",
                "player": "Rhyne Howard",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "l10_streak": "HOT",
                "prop_quality_score": 0.8,
            },
        ]
    )
    rolling = {"Leonie Fiebich": {"hr": 0.03, "n": 35, "last_updated": "2026-07-07"}}
    out = _apply_strong_rolling_hr_gate(df, rolling)
    assert list(out["player"]) == ["Rhyne Howard"]


def test_strong_per_slate_player_cap_limits_appearances():
    rows = [
        {"player": "Natasha Cloud", "prop_quality_score": 0.9},
        {"player": "Natasha Cloud", "prop_quality_score": 0.8},
        {"player": "Natasha Cloud", "prop_quality_score": 0.7},
        {"player": "Other Player", "prop_quality_score": 0.6},
    ]
    capped = _apply_strong_per_slate_player_cap(rows, max_per_player=2)
    assert len(capped) == 3
    assert sum(1 for r in capped if r["player"] == "Natasha Cloud") == 2


def test_strong_costack_guard_blocks_two_weak_anchors():
    rolling = {
        "Weak A": {"hr": 0.10, "n": 25},
        "Weak B": {"hr": 0.15, "n": 22},
        "Strong": {"hr": 0.90, "n": 30},
    }
    assert not _ok_strong_pair({"player": "Weak A"}, {"player": "Weak B"}, rolling)
    assert _ok_strong_pair({"player": "Weak A"}, {"player": "Strong"}, rolling)
    assert _strong_combo_players_ok(
        [{"player": "Weak A"}, {"player": "Strong"}],
        rolling,
    )


def _mixed_hot_pool_df() -> pd.DataFrame:
    rows = []
    for i in range(3):
        rows.append(
            {
                "sport": "WNBA",
                "player": f"Goblin {i}",
                "team": f"G{i}",
                "opp": "OPP",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "line": 8.5 + i,
                "hit_rate": 0.78,
                "rank_score": 90 - i,
                "ml_prob": 0.78,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.90 - 0.01 * i,
            }
        )
    for i in range(3):
        rows.append(
            {
                "sport": "WNBA",
                "player": f"Standard {i}",
                "team": f"S{i}",
                "opp": "OPP",
                "prop_type": "Rebounds",
                "pick_type": "Standard",
                "tier": "B",
                "direction": "OVER",
                "line": 6.5 + i,
                "hit_rate": 0.74,
                "rank_score": 85 - i,
                "ml_prob": 0.74,
                "l10_over": 7.0,
                "l10_under": 3.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.85 - 0.01 * i,
            }
        )
    return pd.DataFrame(rows)


def test_strong_candidate_legs_mixed_unions_goblin_and_standard_hot():
    out = _strong_candidate_legs_mixed(_mixed_hot_pool_df())
    players = set(out["player"].astype(str))
    assert "Goblin 0" in players
    assert "Standard 0" in players
    picks = {str(p).lower() for p in out["pick_type"]}
    assert any("goblin" in p for p in picks)
    assert any("standard" in p for p in picks)


def test_build_strong_tickets_mixed_requires_both_pick_types():
    tickets = build_strong_tickets(
        _mixed_hot_pool_df(),
        pick_mode="mixed",
        max_tickets=20,
        max_legs=3,
        exhaust_pool=False,
        min_p_win_2leg=0.01,
        min_p_win_3leg=0.01,
        date_str="2026-07-14",
    )
    assert tickets
    assert all(t.get("strong_builder_pick") == "Mixed" for t in tickets)
    assert all(t.get("pool_policy") == "goblin_standard_mixed" for t in tickets)
    for t in tickets:
        rows = t.get("rows") or []
        assert _ticket_rows_have_goblin_and_standard(rows)


def test_split_strong_keeps_goblin_and_mix_groups_separate():
    goblin = build_strong_tickets(
        _many_hot_goblin_df(4),
        pick_mode="goblin",
        max_tickets=5,
        max_legs=2,
        exhaust_pool=False,
        min_p_win_2leg=0.01,
    )
    mixed = build_strong_tickets(
        _mixed_hot_pool_df(),
        pick_mode="mixed",
        max_tickets=5,
        max_legs=2,
        exhaust_pool=False,
        min_p_win_2leg=0.01,
    )
    buckets = split_strong_tickets_by_leg_count([*goblin, *mixed])
    names = [b[0] for b in buckets]
    assert any(n.startswith("STRONG ") and "Mix" not in n for n in names)
    assert any(n.startswith("STRONG Mix ") for n in names)


def test_build_strong_tickets_respects_rolling_hr_file(monkeypatch):
    base = _sample_df()
    fiebich = pd.DataFrame(
        [
            {
                "sport": "NBA",
                "player": "Leonie Fiebich",
                "team": "NYL",
                "opp": "IND",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "line": 10.5,
                "hit_rate": 0.8,
                "rank_score": 95,
                "ml_prob": 0.75,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.99,
            }
        ]
    )
    df = pd.concat([fiebich, base], ignore_index=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(
            {
                "Leonie Fiebich": {"hr": 0.03, "n": 35, "last_updated": "2026-07-07"},
                "Alpha One": {"hr": 0.94, "n": 33, "last_updated": "2026-07-07"},
                "Beta Two": {"hr": 0.47, "n": 36, "last_updated": "2026-07-07"},
                "Gamma Three": {"hr": 0.50, "n": 25, "last_updated": "2026-07-07"},
            },
            fh,
        )
        hr_path = fh.name
    monkeypatch.setenv("PROPORACLE_STRONG_ROLLING_HR_PATH", hr_path)
    tickets = build_strong_tickets(df, max_tickets=5, date_str="2026-07-07")
    players = {r.get("player") for t in tickets for r in t.get("rows", [])}
    assert "Leonie Fiebich" not in players
    assert tickets


def test_strong_standard_shadow_emit_does_not_touch_main(monkeypatch, tmp_path):
    """Shadow JSON must write only shadow paths — never tickets_latest / MAIN combined."""
    written: list[str] = []

    def _capture_write(path: str, payload) -> None:
        written.append(os.path.normpath(path))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(cst, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(cst, "_write_json_file", _capture_write)
    monkeypatch.setattr(cst, "STRONG_STANDARD_SHADOW_ENABLED", True)
    # Enough Standard HOT A/B legs for a 2-leg shadow slip.
    df = pd.DataFrame(
        [
            {
                "sport": "WNBA",
                "player": f"Std {i}",
                "team": "LVA",
                "opp": "NYL",
                "prop_type": "Points",
                "pick_type": "Standard",
                "tier": "A",
                "direction": "OVER",
                "line": 12.5 + i,
                "hit_rate": 0.72,
                "rank_score": 85,
                "ml_prob": 0.72,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.85,
            }
            for i in range(4)
        ]
    )
    _emit_strong_standard_shadow_payload(
        frames=[df],
        date_str="2026-07-13",
        thresholds={},
        bankroll=100.0,
        curve_stake_usd=1.0,
        max_tickets=5,
        max_legs=2,
    )
    assert written
    for p in written:
        name = Path(p).name.lower()
        assert "tickets_latest" not in name
        assert not name.startswith("combined_slate_tickets_2026")
        assert "strong_standard" in name
    latest = tmp_path / "ui_runner" / "data" / "strong_standard_shadow_latest.json"
    dated = tmp_path / "ui_runner" / "data" / "combined_slate_tickets_strong_standard_2026-07-13.json"
    assert latest.is_file()
    assert dated.is_file()
    payload = json.loads(dated.read_text(encoding="utf-8"))
    assert payload.get("ticket_track") == "strong_standard_shadow"
    assert payload.get("shadow_track") is True
    assert all(
        str(g.get("group_name") or "").startswith("STRONG Standard HOT")
        for g in payload.get("groups") or []
    )


def test_strong_mix_shadow_emit_does_not_touch_main(monkeypatch, tmp_path):
    """Mix shadow writes only strong_mix paths; never tickets_latest / MAIN."""
    written: list[str] = []

    def _capture_write(path: str, payload) -> None:
        written.append(os.path.normpath(path))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(cst, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(cst, "_write_json_file", _capture_write)
    monkeypatch.setattr(cst, "STRONG_MIX_SHADOW_ENABLED", True)
    rows = []
    for i in range(3):
        rows.append(
            {
                "sport": "WNBA",
                "player": f"Gob {i}",
                "team": "LVA",
                "opp": "NYL",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "direction": "OVER",
                "line": 10.5 + i,
                "hit_rate": 0.74,
                "rank_score": 88,
                "ml_prob": 0.74,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.88,
            }
        )
    for i in range(3):
        rows.append(
            {
                "sport": "WNBA",
                "player": f"Std {i}",
                "team": "NYL",
                "opp": "LVA",
                "prop_type": "Points",
                "pick_type": "Standard",
                "tier": "A",
                "direction": "OVER",
                "line": 14.5 + i,
                "hit_rate": 0.72,
                "rank_score": 85,
                "ml_prob": 0.72,
                "l10_over": 8.0,
                "l10_under": 2.0,
                "l10_streak": "HOT",
                "prop_quality_score": 0.85,
            }
        )
    _emit_strong_mix_shadow_payload(
        frames=[pd.DataFrame(rows)],
        date_str="2026-07-14",
        thresholds={},
        bankroll=100.0,
        curve_stake_usd=1.0,
        max_tickets=8,
        max_legs=2,
    )
    assert written
    for p in written:
        name = Path(p).name.lower()
        assert "tickets_latest" not in name
        assert "strong_mix" in name
    dated = tmp_path / "ui_runner" / "data" / "combined_slate_tickets_strong_mix_2026-07-14.json"
    assert dated.is_file()
    payload = json.loads(dated.read_text(encoding="utf-8"))
    assert payload.get("ticket_track") == "strong_mix_shadow"
    assert payload.get("shadow_track") is True
    assert all(
        str(g.get("group_name") or "").startswith("STRONG Mix")
        for g in payload.get("groups") or []
    )
    # Every Mix slip must include both pick types.
    for g in payload.get("groups") or []:
        for t in g.get("tickets") or []:
            assert t.get("strong_builder_pick") == "Mixed"
            legs = t.get("legs") or t.get("rows") or []
            picks = {str(leg.get("pick_type") or "").lower() for leg in legs}
            assert any("goblin" in p for p in picks)
            assert any("standard" in p for p in picks)
