"""Tests for unified slip grade slice review."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from slip_grade_review_by_slice import (  # noqa: E402
    TRACK_MAIN,
    GradedLeg,
    _classify_pick_mix,
    _classify_sport_mix,
    _classify_tier_mix,
    _in_outage_window,
    _lookup_leg,
    _post_gate,
    build_slice_rows,
    grade_slip,
    leg_lookup_key,
)


def test_post_gate_and_outage_flags():
    assert _post_gate("2026-07-09") is False
    assert _post_gate("2026-07-10") is True
    assert _in_outage_window("2026-06-24") is True
    assert _in_outage_window("2026-06-22") is False


def test_mix_classifiers():
    legs = [
        {"sport": "WNBA", "pick_type": "Goblin", "tier": "A"},
        {"sport": "WNBA", "pick_type": "Goblin", "tier": "A"},
    ]
    assert _classify_sport_mix(legs) == "WNBA-only"
    assert _classify_pick_mix(legs) == "Goblin-only"
    assert _classify_tier_mix(legs) == "A-only"


def test_grade_slip_decided_and_paid():
    legs = [
        {
            "sport": "WNBA",
            "player": "Test Player",
            "prop_type": "Points",
            "direction": "OVER",
            "pick_type": "Goblin",
            "line": 10.5,
        },
        {
            "sport": "WNBA",
            "player": "Other Player",
            "prop_type": "Rebounds",
            "direction": "OVER",
            "pick_type": "Goblin",
            "line": 5.5,
        },
    ]
    slip = {"ticket_id": "t1", "legs": legs}
    index = {
        leg_lookup_key(legs[0]): GradedLeg(hit=1, void_reason=None, result="HIT"),
        leg_lookup_key(legs[1]): GradedLeg(hit=1, void_reason=None, result="HIT"),
    }
    out = grade_slip(slip, date_str="2026-06-20", track=TRACK_MAIN, graded_index=index)
    assert out.decided is True
    assert out.paid is True
    assert out.slip_void is False


def test_grade_slip_void_when_no_graded_row():
    leg = {
        "sport": "WNBA",
        "player": "Missing Player",
        "prop_type": "Points",
        "direction": "OVER",
        "pick_type": "Goblin",
        "line": 10.5,
    }
    out = grade_slip({"legs": [leg]}, date_str="2026-06-20", track=TRACK_MAIN, graded_index={})
    assert out.slip_void is True
    assert out.void_reason == "no_graded_row"
    assert out.decided is False


def test_lookup_leg_relaxed_prop_match():
    leg = {
        "sport": "WNBA",
        "player": "Test Player",
        "prop_type": "Point",
        "direction": "OVER",
        "pick_type": "Goblin",
        "line": 10.5,
    }
    key = ("WNBA", "test player", "points", "OVER", "Goblin", "10.5")
    index = {key: GradedLeg(hit=0, void_reason=None, result="MISS")}
    assert _lookup_leg(index, leg) is not None


def test_build_slice_rows_includes_strong_postgame_zero():
    rows = build_slice_rows([])
    tracks = {r["slice_value"] for r in rows if r["slice_type"] == "by_track"}
    assert "STRONG_postgame" in tracks
