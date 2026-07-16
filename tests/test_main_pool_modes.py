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
    _standard_over_elite_ok,
    build_graded_main_win_rate_payload,
    filter_main_high_prob_payload,
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
) -> dict:
    return {
        "sport": sport,
        "player": player,
        "prop_type": "Points",
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
