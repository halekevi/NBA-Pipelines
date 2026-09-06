"""Tests for Elite→Weak defense tiers + WNBA/NBA prop-by-stat attach."""
from __future__ import annotations

import pandas as pd

from utils.defense_tiers import (
    DEF_TIER_LABELS,
    d_aligned,
    def_tier_from_overall_rank,
    normalize_def_tier_label,
)
from utils.wnba_prop_defense import lookup_stat_defense, soft_priority_delta


def test_normalize_maps_legacy_hard_easy():
    assert normalize_def_tier_label("HARD") == "Elite"
    assert normalize_def_tier_label("HARD_MID") == "Above Avg"
    assert normalize_def_tier_label("MID") == "Avg"
    assert normalize_def_tier_label("EASY_MID") == "Below Avg"
    assert normalize_def_tier_label("EASY") == "Weak"
    assert normalize_def_tier_label("Below Avg") == "Below Avg"
    assert normalize_def_tier_label("Elite") == "Elite"


def test_quintile_labels_are_canonical():
    assert DEF_TIER_LABELS == ("Elite", "Above Avg", "Avg", "Below Avg", "Weak")
    assert def_tier_from_overall_rank(1, 18) == "Elite"
    assert def_tier_from_overall_rank(18, 18) == "Weak"


def test_wnba_lookup_emits_weak_not_easy():
    info = lookup_stat_defense("BRZL", "Points")
    # Brazil (exhibition) is typically generous — Weak, never EASY
    if info.get("stat_def_tier"):
        assert info["stat_def_tier"] in DEF_TIER_LABELS
        assert info["stat_def_tier"] != "EASY"
        assert "EASY" not in str(info["stat_def_tier"]).upper() or info["stat_def_tier"] == "Weak"


def test_wnba_lookup_atl_elite_not_hard():
    info = lookup_stat_defense("ATL", "Points")
    assert info.get("stat_def_category") == "pts"
    assert info.get("stat_def_tier") in DEF_TIER_LABELS
    assert info["stat_def_tier"] != "HARD"


def test_soft_priority_uses_five_bucket():
    # Elite (stingy) hurts OVER
    assert (
        soft_priority_delta(
            sport="WNBA", prop="Rebounds", direction="OVER", stat_def_tier="Elite"
        )
        == -0.04
    )
    # Weak (generous) helps OVER
    assert (
        soft_priority_delta(
            sport="WNBA", prop="Rebounds", direction="OVER", stat_def_tier="Weak"
        )
        == 0.06
    )
    # Below Avg also helps OVER (EASY coarse)
    assert (
        soft_priority_delta(
            sport="WNBA", prop="Rebounds", direction="OVER", stat_def_tier="Below Avg"
        )
        == 0.06
    )


def test_best_props_pool_below_avg_over_d():
    from utils.best_props_pool import _def_tier, _over_d_ok

    row = {"sport": "WNBA", "stat_def_tier": "Below Avg"}
    assert _def_tier(row) == "Below Avg"
    assert _over_d_ok("WNBA", "Below Avg") is True
    # legacy still maps
    assert _def_tier({"sport": "WNBA", "stat_def_tier": "EASY_MID"}) == "Below Avg"


def test_d_aligned_over_under_avg_unknown():
    assert d_aligned("WNBA", "OVER", "Weak") is True
    assert d_aligned("WNBA", "OVER", "Below Avg") is True
    assert d_aligned("WNBA", "OVER", "Avg") is False
    assert d_aligned("WNBA", "OVER", "Elite") is False
    assert d_aligned("WNBA", "UNDER", "Elite") is True
    assert d_aligned("WNBA", "UNDER", "Above Avg") is True
    assert d_aligned("WNBA", "UNDER", "Avg") is False
    assert d_aligned("TENNIS", "OVER", "") is False
    assert d_aligned("TENNIS", "OVER", None) is False


def test_d_aligned_mlb_hitter_ks_inverts():
    assert d_aligned("MLB", "OVER", "Elite", "hitter_ks") is True
    assert d_aligned("MLB", "OVER", "Above Avg", "Hitter Strikeouts") is True
    assert d_aligned("MLB", "OVER", "Weak", "hitter_ks") is False
    assert d_aligned("MLB", "UNDER", "Weak", "hitter_ks") is True
    assert d_aligned("MLB", "OVER", "Weak", "strikeouts") is True
    assert d_aligned("MLB", "OVER", "Elite", "pitcher_ks") is False
