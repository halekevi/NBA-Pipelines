"""MAIN pool modes: mixed / goblin_only / standard_only + elite Standard OVER gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from combined_slate_tickets import (  # noqa: E402
    MAIN_POOL_MODE,
    MAIN_POOL_MODE_GOBLIN,
    MAIN_POOL_MODE_STANDARD,
    _row_win_rate_eligible,
    _standard_direction_floor,
    _standard_over_elite_ok,
    build_graded_main_win_rate_payload,
    filter_main_high_prob_payload,
    prefer_main_min_payout_payload,
    soccer_allowed_leg,
)


def _base_leg(
    *,
    pick_type: str,
    direction: str,
    tier: str = "A",
    sport: str = "WNBA",
    player: str = "P One",
    leg_prob: float = 0.72,
    hit_rate: float = 0.72,
    prop_type: str = "Points",
) -> dict:
    return {
        "sport": sport,
        "player": player,
        "prop_type": prop_type,
        "pick_type": pick_type,
        "direction": direction,
        "line": 12.5,
        "hit_rate": hit_rate,
        "composite_hit_rate": hit_rate,
        "ml_prob": leg_prob,
        "leg_prob": leg_prob,
        "rank_score": 80,
        "tier": tier,
        "l5_over": 5.0,
        "l5_under": 4.0,
        "l10_over": 8.0,
        "l10_under": 7.0,
        "l10_over_pct": 0.80,
        "l10_under_pct": 0.70,
        "consistency_grade": "A",
        "def_tier": "WEAK" if direction == "OVER" else "ELITE",
        "team_top3_rank": 1 if direction == "OVER" else None,
        "team_bottom3_rank": 1 if direction == "UNDER" else None,
        "top3_weak_overperformer": 1 if direction == "OVER" else 0,
        "top3_elite_fader": 1 if direction == "UNDER" else 0,
        "strat_hit_rate": 0.75,
        "strat_n": 40,
    }


def test_standard_under_passes_without_elite_stack():
    row = _base_leg(pick_type="Standard", direction="UNDER", leg_prob=0.66, hit_rate=0.66)
    # Drop stack_70 matchup fields so elite OVER would fail; UNDER should still pass.
    row["def_tier"] = ""
    row["strat_hit_rate"] = 0.50
    row["strat_n"] = 5
    row["l5_under"] = 2.0
    assert _row_win_rate_eligible(
        row, min_leg_prob=0.62, min_composite_hr=0.55, qualify_standard=True
    )


def test_standard_over_requires_elite_gate():
    weak = _base_leg(pick_type="Standard", direction="OVER", tier="B", leg_prob=0.72)
    assert not _standard_over_elite_ok(weak)
    assert not _row_win_rate_eligible(
        weak, min_leg_prob=0.62, min_composite_hr=0.55, qualify_standard=True
    )

    elite = _base_leg(pick_type="Standard", direction="OVER", tier="A", leg_prob=0.72)
    assert _standard_over_elite_ok(elite)
    assert _row_win_rate_eligible(
        elite, min_leg_prob=0.62, min_composite_hr=0.55, qualify_standard=True
    )


def test_soccer_standard_over_banned_under_allowed():
    """Soccer Shots OVER is hard-gated on Standard; UNDER stays allowed."""
    over = {
        "sport": "SOCCER",
        "pick_type": "Standard",
        "direction": "OVER",
        "prop_type": "Shots",
        "hit_rate": 0.80,
        "abs_edge": 0.20,
        "leg_prob": 0.80,
        "ml_prob": 0.80,
    }
    under = {
        "sport": "SOCCER",
        "pick_type": "Standard",
        "direction": "UNDER",
        "prop_type": "Shots",
        "hit_rate": 0.70,
        "abs_edge": 0.10,
        "leg_prob": 0.70,
        "ml_prob": 0.70,
    }
    assert soccer_allowed_leg(over) is False
    assert soccer_allowed_leg(under) is True


def test_standard_prop_gates_not_sport_wide():
    """Goblins stay open; Standards gate by prop×direction (ledger)."""
    from combined_slate_tickets import _leg_standard_prop_direction_gated

    # Banned Standard prop
    assert _leg_standard_prop_direction_gated(
        {
            "sport": "MLB",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Total Bases",
        }
    )
    # Keep-candidate Standard Singles OVER is NOT gated
    assert not _leg_standard_prop_direction_gated(
        {
            "sport": "MLB",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Singles",
        }
    )
    # Same prop as Goblin is never Standard-gated
    assert not _leg_standard_prop_direction_gated(
        {
            "sport": "WNBA",
            "pick_type": "Goblin",
            "direction": "OVER",
            "prop_type": "Rebounds",
        }
    )
    assert _leg_standard_prop_direction_gated(
        {
            "sport": "WNBA",
            "pick_type": "Standard",
            "direction": "OVER",
            "prop_type": "Rebounds",
        }
    )


def test_standard_direction_floors_by_sport():
    assert _standard_direction_floor(
        {"sport": "MLB", "direction": "UNDER", "pick_type": "Standard"}
    ) >= 0.64
    assert _standard_direction_floor(
        {"sport": "WNBA", "direction": "OVER", "pick_type": "Standard"}
    ) >= 0.70
    assert _standard_direction_floor(
        {"sport": "WNBA", "direction": "UNDER", "pick_type": "Standard"}
    ) >= 0.62
    assert _standard_direction_floor(
        {"sport": "SOCCER", "direction": "OVER", "pick_type": "Standard"}
    ) >= 0.74


def test_mlb_standard_under_needs_higher_floor():
    weak = _base_leg(
        pick_type="Standard",
        direction="UNDER",
        sport="MLB",
        prop_type="Hits",
        leg_prob=0.61,
        hit_rate=0.61,
    )
    # Below MLB UNDER floor (0.64)
    assert not _row_win_rate_eligible(
        weak, min_leg_prob=0.60, min_composite_hr=0.55, qualify_standard=True
    )
    strong = dict(weak, leg_prob=0.66, ml_prob=0.66, hit_rate=0.66, composite_hit_rate=0.66)
    assert _row_win_rate_eligible(
        strong, min_leg_prob=0.60, min_composite_hr=0.55, qualify_standard=True
    )


def test_goblin_only_rejects_standard():
    std = _base_leg(pick_type="Standard", direction="UNDER")
    gob = _base_leg(pick_type="Goblin", direction="OVER")
    assert not _row_win_rate_eligible(
        std, min_leg_prob=0.62, min_composite_hr=0.55, goblin_only=True
    )
    assert _row_win_rate_eligible(
        gob, min_leg_prob=0.62, min_composite_hr=0.55, goblin_only=True
    )


def test_standard_only_rejects_goblin():
    std = _base_leg(pick_type="Standard", direction="UNDER")
    gob = _base_leg(pick_type="Goblin", direction="OVER")
    assert _row_win_rate_eligible(
        std, min_leg_prob=0.62, min_composite_hr=0.55, standard_only=True
    )
    assert not _row_win_rate_eligible(
        gob, min_leg_prob=0.62, min_composite_hr=0.55, standard_only=True
    )


def test_build_payload_pool_modes_tag_correctly():
    frames = [
        (
            "WNBA",
            pd.DataFrame(
                [
                    _base_leg(pick_type="Goblin", direction="OVER", player="G1"),
                    _base_leg(pick_type="Goblin", direction="OVER", player="G2"),
                    _base_leg(pick_type="Goblin", direction="OVER", player="G3"),
                    _base_leg(pick_type="Standard", direction="UNDER", player="S1"),
                    _base_leg(pick_type="Standard", direction="UNDER", player="S2"),
                    _base_leg(pick_type="Standard", direction="UNDER", player="S3"),
                ]
            ),
        )
    ]
    for mode in (MAIN_POOL_MODE, MAIN_POOL_MODE_GOBLIN, MAIN_POOL_MODE_STANDARD):
        payload = build_graded_main_win_rate_payload(
            frames,
            "2099-01-01",
            {},
            bankroll=100.0,
            curve_stake_usd=5.0,
            pool_mode=mode,
            max_tickets=5,
        )
        assert payload.get("pool_mode") in (mode, "goblin_only_3leg") or (
            mode == MAIN_POOL_MODE_GOBLIN and payload.get("pool_mode") == MAIN_POOL_MODE_GOBLIN
        )
        filtered = filter_main_high_prob_payload(payload)
        for g in filtered.get("groups") or []:
            for t in g.get("tickets") or []:
                if t.get("strong_builder"):
                    continue
                picks = {
                    str(leg.get("pick_type") or "").strip().lower()
                    for leg in (t.get("legs") or [])
                    if isinstance(leg, dict)
                }
                if mode == MAIN_POOL_MODE_GOBLIN:
                    assert picks and all("goblin" in p for p in picks)
                elif mode == MAIN_POOL_MODE_STANDARD:
                    assert picks and all(("standard" in p) and ("goblin" not in p) for p in picks)


def test_prefer_main_payout_floor_cuts_low_when_nothing_clears():
    """Jul-24: cut ~1.6× volume rather than ship a sub-hard-floor board."""
    payload = {
        "pool_mode": MAIN_POOL_MODE,
        "groups": [
            {
                "group_name": "WNBA Goblin 2",
                "n_legs": 2,
                "tickets": [
                    {
                        "legs": [
                            {"sport": "WNBA", "pick_type": "Goblin"},
                            {"sport": "WNBA", "pick_type": "Goblin"},
                        ],
                        "p_win": 0.55,
                        "payout": {
                            "display_min_x": 1.6,
                            "power_min_x": 1.6,
                            "payout_source": "live_cdp",
                        },
                    }
                ],
            }
        ],
    }
    filtered = prefer_main_min_payout_payload(payload)
    assert sum(len(g.get("tickets") or []) for g in filtered.get("groups") or []) == 0


def test_prefer_main_keeps_high_pwin_strong_below_preferred():
    """STRONG below preferred floor ships only with very high p_win bypass."""
    payload = {
        "pool_mode": MAIN_POOL_MODE,
        "groups": [
            {
                "group_name": "STRONG 2-Leg",
                "n_legs": 2,
                "tickets": [
                    {
                        "strong_builder": True,
                        "p_win": 0.72,
                        "est_win_prob": 0.72,
                        "legs": [
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                        ],
                        "payout": {
                            "display_min_x": 1.3,
                            "power_min_x": 1.3,
                            "payout_source": "live_cdp",
                        },
                    },
                    {
                        "strong_builder": True,
                        "p_win": 0.50,
                        "est_win_prob": 0.50,
                        "legs": [
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                        ],
                        "payout": {
                            "display_min_x": 2.7,
                            "power_min_x": 2.7,
                            "payout_source": "live_cdp",
                        },
                    },
                ],
            },
            {
                "group_name": "WNBA Goblin 3",
                "n_legs": 3,
                "tickets": [
                    {
                        "p_win": 0.55,
                        "legs": [
                            {"sport": "WNBA", "pick_type": "Goblin"},
                            {"sport": "WNBA", "pick_type": "Goblin"},
                            {"sport": "WNBA", "pick_type": "Goblin"},
                        ],
                        "payout": {
                            "display_min_x": 1.8,
                            "power_min_x": 1.8,
                            "payout_source": "live_cdp",
                        },
                    }
                ],
            },
        ],
    }
    filtered = prefer_main_min_payout_payload(payload)
    slips = [t for g in filtered.get("groups") or [] for t in (g.get("tickets") or [])]
    # Preferred ≥2.2 keeps 2.7; high-p_win 1.3 also clears preferred via bypass.
    # 1.8 non-STRONG deferred.
    assert len(slips) == 2
    assert all(t.get("strong_builder") for t in slips)
    assert {float(t["payout"]["display_min_x"]) for t in slips} == {1.3, 2.7}


def test_prefer_main_drops_low_strong_when_preferred_exists():
    payload = {
        "pool_mode": MAIN_POOL_MODE,
        "groups": [
            {
                "group_name": "STRONG 2-Leg",
                "n_legs": 2,
                "tickets": [
                    {
                        "strong_builder": True,
                        "p_win": 0.50,
                        "est_win_prob": 0.50,
                        "legs": [
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                        ],
                        "payout": {
                            "display_min_x": 2.7,
                            "power_min_x": 2.7,
                            "payout_source": "live_cdp",
                        },
                    },
                    {
                        "strong_builder": True,
                        "p_win": 0.50,
                        "est_win_prob": 0.50,
                        "legs": [
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                        ],
                        "payout": {
                            "display_min_x": 1.2,
                            "power_min_x": 1.2,
                            "payout_source": "live_cdp",
                        },
                    },
                ],
            },
            {
                "group_name": "WNBA Goblin 3",
                "n_legs": 3,
                "tickets": [
                    {
                        "p_win": 0.55,
                        "legs": [
                            {"sport": "WNBA", "pick_type": "Goblin"},
                            {"sport": "WNBA", "pick_type": "Goblin"},
                            {"sport": "WNBA", "pick_type": "Goblin"},
                        ],
                        "payout": {
                            "display_min_x": 1.8,
                            "power_min_x": 1.8,
                            "payout_source": "live_cdp",
                        },
                    }
                ],
            },
        ],
    }
    # High-prob filter keeps everything; 2.2x prefer is the last step.
    mid = filter_main_high_prob_payload(payload)
    assert sum(len(g.get("tickets") or []) for g in mid.get("groups") or []) == 3
    filtered = prefer_main_min_payout_payload(mid)
    slips = [t for g in filtered.get("groups") or [] for t in (g.get("tickets") or [])]
    # Only ≥2.2 STRONG kept; low STRONG + 1.8 non-STRONG deferred.
    assert len(slips) == 1
    assert slips[0].get("strong_builder")
    assert float(slips[0]["payout"]["display_min_x"]) == 2.7


def test_prefer_main_hard_floor_keeps_2x_when_no_preferred():
    """Board of ≥2.0× / <2.2× ships via hard floor when nothing hits preferred."""
    payload = {
        "pool_mode": MAIN_POOL_MODE,
        "groups": [
            {
                "group_name": "MLB Goblin 3",
                "n_legs": 3,
                "tickets": [
                    {
                        "p_win": 0.55,
                        "legs": [
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                        ],
                        "payout": {
                            "display_min_x": 2.0,
                            "power_min_x": 2.0,
                            "payout_source": "live_cdp",
                        },
                    }
                ],
            }
        ],
    }
    filtered = prefer_main_min_payout_payload(payload)
    slips = [t for g in filtered.get("groups") or [] for t in (g.get("tickets") or [])]
    assert len(slips) == 1
    assert float(slips[0]["payout"]["display_min_x"]) == 2.0


def test_prefer_main_defers_pending_when_require_live(monkeypatch):
    """Empty board is correct when nothing has exact live_cdp ≥ floor."""
    monkeypatch.setenv("PROPORACLE_REQUIRE_LIVE_PAYOUT", "1")
    monkeypatch.setenv("PROPORACLE_ALLOW_SG_DELTA_PAYOUT", "0")
    payload = {
        "pool_mode": MAIN_POOL_MODE,
        "groups": [
            {
                "group_name": "MLB Goblin 3",
                "n_legs": 3,
                "tickets": [
                    {
                        "p_win": 0.55,
                        "legs": [
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                        ],
                        "payout": {"payout_source": "pending_live"},
                        "display_min_x": None,
                    },
                    {
                        "p_win": 0.55,
                        "legs": [
                            {"sport": "MLB", "pick_type": "Goblin"},
                            {"sport": "MLB", "pick_type": "Goblin"},
                        ],
                        "payout": {
                            "display_min_x": 3.375,
                            "power_min_x": 3.375,
                            "payout_source": "sg_delta_live",
                        },
                    },
                ],
            }
        ],
    }
    filtered = prefer_main_min_payout_payload(payload)
    assert filtered.get("groups") == []
