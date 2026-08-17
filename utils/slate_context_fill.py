"""Fill slate context columns when upstream step8 left them blank."""

from __future__ import annotations

import numpy as np
import pandas as pd

_MIN_TIER_NUM_MAP = {0: "LOW", 1: "MEDIUM", 2: "HIGH", 3: "HIGH"}
_MIN_TIER_STR_MAP = {
    "0": "LOW",
    "1": "MEDIUM",
    "2": "HIGH",
    "3": "HIGH",
    "LOW": "LOW",
    "MED": "MEDIUM",
    "MEDIUM": "MEDIUM",
    "HIGH": "HIGH",
    "ELITE": "ELITE",
}


def fill_min_tier_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Restore HIGH/MEDIUM/LOW(/ELITE) from labels or 0–3 codes into min_tier."""
    out = df.copy()
    n = len(out)
    label = pd.Series([""] * n, index=out.index, dtype=object)
    for col in ("minutes_tier_label", "min_tier", "Min Tier", "minutes_tier"):
        if col not in out.columns:
            continue
        raw = out[col]
        raw_u = raw.astype(str).str.strip().str.upper().replace({"NAN": "", "NONE": "", "<NA>": ""})
        mapped = raw_u.map(_MIN_TIER_STR_MAP)
        num = pd.to_numeric(raw, errors="coerce")
        from_num = num.round().astype("Int64").map(_MIN_TIER_NUM_MAP)
        cand = mapped.where(mapped.isin(["LOW", "MEDIUM", "HIGH", "ELITE"]), from_num)
        empty = label.eq("") | label.isna()
        label = label.where(~empty, cand)
    ok = label.isin(["LOW", "MEDIUM", "HIGH", "ELITE"])
    out["min_tier"] = label.where(ok, pd.NA)
    if "minutes_tier" in out.columns:
        out["minutes_tier"] = out["min_tier"]
    return out


def fill_cv_pct_if_missing(df: pd.DataFrame, *, min_games: int = 3) -> pd.DataFrame:
    """CV% = std/mean of G1–G10 / stat_g1–g10. Only fills blank cells."""
    out = df.copy()
    gcols = [c for c in (f"stat_g{i}" for i in range(1, 11)) if c in out.columns]
    if not gcols:
        gcols = [c for c in (f"G{i}" for i in range(1, 11)) if c in out.columns]
    existing = pd.to_numeric(out["cv_pct"], errors="coerce") if "cv_pct" in out.columns else pd.Series(np.nan, index=out.index)
    if not gcols:
        out["cv_pct"] = existing
        return out
    g = out[gcols].apply(pd.to_numeric, errors="coerce")
    n = g.notna().sum(axis=1)
    mean = g.mean(axis=1)
    std = g.std(axis=1, ddof=0)
    cv = (std / mean.replace(0, np.nan)) * 100.0
    cv = cv.where(n.ge(min_games) & mean.gt(0), np.nan).round(1)
    out["cv_pct"] = existing.combine_first(cv)
    return out


def summarize_board_context_fill(df: pd.DataFrame) -> dict[str, int]:
    """Counts for daily Combined logs: L5 / CV% / Min Tier vs rows with game logs."""
    n = 0 if df is None else int(len(df))
    if df is None or n == 0:
        return {"rows": 0, "l5": 0, "cv": 0, "min_tier": 0, "g3": 0}
    l5 = pd.to_numeric(df["l5_over"], errors="coerce") if "l5_over" in df.columns else pd.Series(np.nan, index=df.index)
    cv = pd.to_numeric(df["cv_pct"], errors="coerce") if "cv_pct" in df.columns else pd.Series(np.nan, index=df.index)
    mt = df["min_tier"] if "min_tier" in df.columns else pd.Series(pd.NA, index=df.index)
    mt_txt = mt.astype(str).str.strip().str.upper()
    mt_ok = mt.notna() & ~mt_txt.isin(["", "NAN", "NONE", "<NA>"])
    gcols = [c for c in (f"stat_g{i}" for i in range(1, 6)) if c in df.columns]
    g3 = int((df[gcols].apply(pd.to_numeric, errors="coerce").notna().sum(axis=1) >= 3).sum()) if gcols else 0
    return {
        "rows": n,
        "l5": int(l5.notna().sum()),
        "cv": int(cv.notna().sum()),
        "min_tier": int(mt_ok.sum()),
        "g3": g3,
    }
