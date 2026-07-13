"""Efficiency / correctness tests for unified edge ML helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from edge_feature_engineering import _minutes_cv_series  # noqa: E402
from edge_predict_utils import load_unified_edge_model  # noqa: E402


def _minutes_cv_series_legacy(df: pd.DataFrame, sport: str) -> pd.Series:
    """Reference loop implementation (mirrors pre-vectorization behavior)."""
    from edge_feature_engineering import _collect_last_minutes, _first_col, _to_num

    last3 = _collect_last_minutes(df, sport)
    avg_l5 = _to_num(_first_col(df, ("avg_L5", "stat_last5_avg")))
    avg_l10 = _to_num(_first_col(df, ("avg_L10", "stat_last10_avg")))
    idx = df.index
    cv_vals = []
    for i in range(len(df)):
        vals = []
        for s in last3:
            v = s.iloc[i] if i < len(s) else np.nan
            if pd.notna(v):
                vals.append(float(v))
        for s in (avg_l5, avg_l10):
            v = s.iloc[i] if i < len(s) else np.nan
            if pd.notna(v):
                vals.append(float(v))
        if len(vals) < 3:
            cv_vals.append(np.nan)
            continue
        arr = np.array(vals, dtype=float)
        mu = float(np.mean(arr))
        if mu == 0 or np.isnan(mu):
            cv_vals.append(np.nan)
        else:
            cv_vals.append(float(np.std(arr, ddof=0) / mu))
    return pd.Series(cv_vals, index=idx)


def test_minutes_cv_matches_legacy_loop():
    df = pd.DataFrame(
        {
            "avg_L5": [30.0, 20.0, np.nan, 10.0],
            "avg_L10": [28.0, 22.0, 18.0, 0.0],
            "min_g1": [32.0, 21.0, 17.0, np.nan],
            "min_g2": [29.0, 19.0, np.nan, np.nan],
            "min_g3": [31.0, 23.0, np.nan, np.nan],
        }
    )
    # Ensure column aliases used by _collect_last_minutes for NBA-like sports exist.
    for i, col in enumerate(("min_g1", "min_g2", "min_g3"), start=1):
        df[f"minutes_g{i}"] = df[col]
    got = _minutes_cv_series(df, "NBA")
    exp = _minutes_cv_series_legacy(df, "NBA")
    np.testing.assert_allclose(got.to_numpy(dtype=float), exp.to_numpy(dtype=float), equal_nan=True, rtol=1e-9)


def test_load_unified_edge_model_caches_when_present():
    mdir = ROOT / "models"
    first = load_unified_edge_model(mdir)
    second = load_unified_edge_model(mdir)
    if first is None:
        # Artifact missing in this checkout — skip assertion.
        return
    assert second is not None
    assert first[0] is second[0]
    assert first[1] == second[1]


def test_skip_prop_model_default_on():
    import os

    from prop_model_runtime import skip_prop_model_inference

    prev = os.environ.pop("PROPORACLE_STEP7_SKIP_PROP_MODEL", None)
    try:
        assert skip_prop_model_inference() is True
        os.environ["PROPORACLE_STEP7_SKIP_PROP_MODEL"] = "0"
        assert skip_prop_model_inference() is False
        os.environ["PROPORACLE_STEP7_SKIP_PROP_MODEL"] = "1"
        assert skip_prop_model_inference() is True
    finally:
        if prev is None:
            os.environ.pop("PROPORACLE_STEP7_SKIP_PROP_MODEL", None)
        else:
            os.environ["PROPORACLE_STEP7_SKIP_PROP_MODEL"] = prev
