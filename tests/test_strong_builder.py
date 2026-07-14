"""Tests for STRONG-eligible Goblin+HOT ticket builder."""
from __future__ import annotations

import json
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

from combined_slate_tickets import (  # noqa: E402
    _apply_strong_per_slate_player_cap,
    _apply_strong_rolling_hr_gate,
    _ok_strong_pair,
    _strong_candidate_legs,
    _strong_candidate_legs_standard,
    _strong_combo_players_ok,
    build_strong_tickets,
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
                "l10_streak": "HOT",
            },
            {
                "sport": "MLB",
                "player": "Pitcher One",
                "prop_type": "Home Runs",
                "pick_type": "Goblin",
                "tier": "A",
                "l10_streak": "HOT",
            },
            {
                "sport": "WNBA",
                "player": "Shooter One",
                "prop_type": "3-PT Made",
                "pick_type": "Goblin",
                "tier": "A",
                "l10_streak": "HOT",
            },
            {
                "sport": "WNBA",
                "player": "Scorer One",
                "prop_type": "Points",
                "pick_type": "Goblin",
                "tier": "A",
                "l10_streak": "HOT",
            },
        ]
    )
    out = _strong_candidate_legs(df)
    assert len(out) == 2
    players = set(out["player"].astype(str))
    assert players == {"Hitter One", "Scorer One"}


def test_build_strong_tickets_produces_labeled_slips():
    tickets = build_strong_tickets(_sample_df(), max_tickets=5, date_str="2026-06-14")
    assert len(tickets) >= 1
    t = tickets[0]
    assert t.get("strong_builder") is True
    # Sample pool only has 2 HOT Goblin players → 2-leg fallback.
    assert t.get("n_legs") == 2
    assert float(t.get("est_win_prob") or 0) >= 0.33
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
    # Board should lead with longer slips, not fill exclusively with 2-legs.
    assert int(tickets[0].get("n_legs") or 0) >= 3
    two_leg = sum(1 for t in tickets if int(t.get("n_legs") or 0) == 2)
    longer = sum(1 for t in tickets if int(t.get("n_legs") or 0) >= 3)
    assert longer >= two_leg


def test_build_strong_tickets_includes_five_and_six_legs():
    tickets = build_strong_tickets(
        _many_hot_goblin_df(8),
        exhaust_pool=True,
        date_str="2026-07-14",
    )
    assert tickets
    lengths = {int(t.get("n_legs") or 0) for t in tickets}
    assert 5 in lengths
    assert 6 in lengths
    assert int(tickets[0].get("n_legs") or 0) >= 5


def test_build_strong_tickets_exhausts_unique_player_pool():
    # With exhaust on, a 5-player pool should yield many more slips than --max-tickets=3.
    tickets = build_strong_tickets(
        _many_hot_goblin_df(5),
        max_tickets=3,
        exhaust_pool=True,
        date_str="2026-07-14",
    )
    assert len(tickets) > 3
    assert any(int(t.get("n_legs") or 0) >= 3 for t in tickets)


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
