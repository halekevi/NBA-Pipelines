"""Tennis prop-family ml_prob caps — serve stats grade ~2-4%; totals Goblin ~71%."""
from __future__ import annotations

import numpy as np
import pandas as pd

SERVE_JUNK_PROP_FRAGMENTS = (
    "ace",
    "aces",
    "double fault",
    "double_fault",
    "double faults",
)

TOTALS_PROP_FRAGMENTS = (
    "total games",
    "total games won",
    "games won",
    "match total",
    "games played",
)

# Graded ~2-4% hit; cap so ladder/tickets never treat as high-prob.
# Jul-22/23 Ace/DF Goblin OVER: 0% — keep severely capped.
SERVE_JUNK_ML_CAP = 0.08

# Ticket-eligible Goblin totals OVER — prefer these lanes when L5 clears.
TOTALS_ML_FLOOR = 0.58
TOTALS_ML_CAP = 0.82


def _norm_prop_label(row: dict | pd.Series) -> str:
    if isinstance(row, dict):
        raw = row.get("prop_type") or row.get("prop") or row.get("prop_norm") or ""
    else:
        raw = row.get("prop_type", row.get("prop", row.get("prop_norm", "")))
    return str(raw or "").strip().lower()


def tennis_prop_family(prop_label: str) -> str:
    p = str(prop_label or "").strip().lower()
    if any(frag in p for frag in SERVE_JUNK_PROP_FRAGMENTS):
        return "serve_junk"
    if any(frag in p for frag in TOTALS_PROP_FRAGMENTS):
        return "totals"
    return "other"


def tennis_serve_junk_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    labels = df.apply(_norm_prop_label, axis=1)
    return labels.map(lambda x: tennis_prop_family(x) == "serve_junk").fillna(False)


def tennis_totals_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    labels = df.apply(_norm_prop_label, axis=1)
    return labels.map(lambda x: tennis_prop_family(x) == "totals").fillna(False)


def apply_tennis_ml_prob_caps(
    df: pd.DataFrame,
    *,
    ml_prob_col: str = "ml_prob",
    in_place: bool = False,
) -> pd.DataFrame:
    """Cap serve-junk ml_prob; gently floor totals (Goblin OVER ticket pool)."""
    if df is None or df.empty or ml_prob_col not in df.columns:
        return df
    out = df if in_place else df.copy()
    mp = pd.to_numeric(out[ml_prob_col], errors="coerce")
    junk = tennis_serve_junk_mask(out)
    if junk.any():
        mp = mp.where(~junk, mp.clip(upper=SERVE_JUNK_ML_CAP))
    totals = tennis_totals_mask(out)
    if totals.any():
        direction = out.get("direction", out.get("bet_direction", out.get("final_bet_direction", "")))
        if direction is not None and hasattr(direction, "astype"):
            over = direction.astype(str).str.upper().str.strip().eq("OVER")
            boost = totals & over
            if boost.any():
                mp = mp.where(~boost, mp.clip(lower=TOTALS_ML_FLOOR, upper=TOTALS_ML_CAP))
    out[ml_prob_col] = mp
    if "blended_score" in out.columns:
        comp = pd.to_numeric(
            out.get("composite_hit_rate", out.get("line_hit_rate", np.nan)),
            errors="coerce",
        )
        out["blended_score"] = (0.3 * pd.to_numeric(out[ml_prob_col], errors="coerce") + 0.7 * comp).round(4)
    return out
