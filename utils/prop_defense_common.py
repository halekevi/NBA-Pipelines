"""Shared helpers for prop-specific opponent defense ranks."""
from __future__ import annotations

from typing import Optional

import pandas as pd


def coarse_bucket_from_rank(rank: object, n_teams: int) -> str:
    """1 = stingiest. Top two quintiles HARD, bottom two EASY."""
    try:
        r = float(rank)
        n = max(int(n_teams), 1)
    except (TypeError, ValueError):
        return "UNK"
    if r != r:  # NaN
        return "UNK"
    q = max(n / 5.0, 1.0)
    if r <= 2 * q:
        return "HARD"
    if r <= 3 * q:
        return "MID"
    return "EASY"


def coarse_bucket_from_tier(tier: object) -> str:
    t = str(tier or "").strip().upper().replace(" ", "_")
    if t in ("HARD", "HARD_MID", "ELITE", "ABOVE_AVG", "ABOVEAVG"):
        return "HARD" if t in ("HARD", "HARD_MID", "ELITE") else "HARD"
    if t in ("EASY", "EASY_MID", "WEAK", "BELOW_AVG", "BELOWAVG"):
        return "EASY"
    if t in ("MID", "AVG", "AVERAGE"):
        return "MID"
    if t in ("ELITE",):
        return "HARD"
    # PrizePicks-style
    if t in ("ABOVE AVG", "ABOVEAVG"):
        return "HARD"
    if t in ("BELOW AVG", "BELOWAVG"):
        return "EASY"
    if t in ("HARD", "HARD_MID"):
        return "HARD"
    if t in ("EASY", "EASY_MID"):
        return "EASY"
    return "UNK"


def empty_stat_def(category: str = "") -> dict:
    return {
        "stat_def_category": category or "",
        "stat_def_rank": None,
        "stat_def_tier": "",
        "stat_def_coarse": "UNK",
    }


def attach_lookup_columns(
    df: pd.DataFrame,
    *,
    sport: str,
    lookup_fn,
    sport_col_candidates: tuple[str, ...] = ("sport", "Sport"),
) -> pd.DataFrame:
    """Apply lookup_fn(opp, prop) -> dict for matching sport rows."""
    if df is None or len(df) == 0:
        return df
    out = df.copy()
    sport_col = next((c for c in sport_col_candidates if c in out.columns), None)
    if sport_col is None:
        is_sport = pd.Series(True, index=out.index)
    else:
        is_sport = out[sport_col].astype(str).str.upper().str.strip().eq(sport.upper())

    opp_col = next((c for c in ("opp", "opp_team", "opponent", "Opp") if c in out.columns), None)
    prop_col = next(
        (c for c in ("prop_type", "prop", "Prop", "prop_norm", "stat_type") if c in out.columns),
        None,
    )
    if not opp_col or not prop_col:
        return out

    cats: list[str] = []
    ranks: list[Optional[int]] = []
    tiers: list[str] = []
    for i, row in out.iterrows():
        if not bool(is_sport.loc[i]):
            cats.append(str(out.at[i, "stat_def_category"]) if "stat_def_category" in out.columns else "")
            ranks.append(out.at[i, "stat_def_rank"] if "stat_def_rank" in out.columns else None)
            tiers.append(str(out.at[i, "stat_def_tier"]) if "stat_def_tier" in out.columns else "")
            continue
        info = lookup_fn(row.get(opp_col), row.get(prop_col)) or empty_stat_def()
        cats.append(info.get("stat_def_category") or "")
        ranks.append(info.get("stat_def_rank"))
        tiers.append(info.get("stat_def_tier") or "")

    out["stat_def_category"] = cats
    out["stat_def_rank"] = ranks
    out["stat_def_tier"] = tiers
    return out
