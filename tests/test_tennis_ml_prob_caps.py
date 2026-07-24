"""Tests for tennis serve-junk ml_prob caps."""
from __future__ import annotations

import pandas as pd

from utils.tennis_ml_prob_caps import apply_tennis_ml_prob_caps, tennis_prop_family


def test_tennis_prop_family_serve_junk():
    assert tennis_prop_family("Aces") == "serve_junk"
    assert tennis_prop_family("Double Faults") == "serve_junk"
    assert tennis_prop_family("Total Games") == "totals"


def test_serve_junk_capped():
    df = pd.DataFrame(
        [
            {"prop_type": "Aces", "direction": "OVER", "ml_prob": 0.72, "composite_hit_rate": 0.5},
        ]
    )
    out = apply_tennis_ml_prob_caps(df)
    assert float(out["ml_prob"].iloc[0]) <= 0.08


def test_totals_over_floor():
    df = pd.DataFrame(
        [
            {"prop_type": "Total Games", "direction": "OVER", "ml_prob": 0.40, "composite_hit_rate": 0.7},
        ]
    )
    out = apply_tennis_ml_prob_caps(df)
    assert float(out["ml_prob"].iloc[0]) >= 0.58
