"""Historical PrizePicks category hit-rate prior for ticket ranking.

Loads data/reports/pp_prop_hit_rates_by_sport.json (sport × prop × Std/Goblin × O/U).
Fantasy-score markets are never indexed or returned.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

import numpy as np
import pandas as pd

from utils.fantasy_prop_filter import is_fantasy_prop_label

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CATEGORY_HR_PATH = os.path.join(
    REPO_ROOT, "data", "reports", "pp_prop_hit_rates_by_sport.json"
)

# Soft floors for win-rate ticket pools (HIT/(HIT+MISS)).
CATEGORY_HR_MIN_GOBLIN = float(os.getenv("PROPORACLE_CATEGORY_HR_MIN_GOBLIN", "0.58"))
CATEGORY_HR_MIN_STANDARD = float(os.getenv("PROPORACLE_CATEGORY_HR_MIN_STANDARD", "0.55"))
CATEGORY_HR_MIN_N = int(os.getenv("PROPORACLE_CATEGORY_HR_MIN_N", "50"))
# When True, drop legs below floor when category_hr is known (n>=MIN_N).
CATEGORY_HR_HARD_FILTER = os.getenv(
    "PROPORACLE_CATEGORY_HR_HARD_FILTER", "1"
).strip().lower() not in ("0", "false", "no", "off")


def _norm_prop(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").strip().lower())


def _norm_sport(text: object) -> str:
    s = str(text or "").strip().upper()
    if s == "SOC":
        return "SOCCER"
    return s


def _norm_pick(text: object) -> str:
    s = str(text or "").strip().lower()
    if "goblin" in s:
        return "Goblin"
    if "standard" in s:
        return "Standard"
    return ""


def _norm_dir(text: object) -> str:
    s = str(text or "").strip().upper()
    return s if s in ("OVER", "UNDER") else ""


@lru_cache(maxsize=2)
def load_category_hr_index(
    path: str = DEFAULT_CATEGORY_HR_PATH,
) -> dict[tuple[str, str, str, str], dict[str, float]]:
    """
    Key: (sport, prop_norm, pick_type, direction) -> {hr, n, hit, miss}
    hr is 0..1. Fantasy props are skipped.
    """
    out: dict[tuple[str, str, str, str], dict[str, float]] = {}
    if not path or not os.path.isfile(path):
        return out
    try:
        raw = json.loads(open(path, encoding="utf-8").read())
    except Exception:
        return out
    sports = raw.get("sports") or {}
    if not isinstance(sports, dict):
        return out
    for sport, sv in sports.items():
        sp = _norm_sport(sport)
        for prop_block in (sv or {}).get("props") or []:
            if not isinstance(prop_block, dict):
                continue
            label = str(prop_block.get("prop") or "")
            if is_fantasy_prop_label(label):
                continue
            pn = _norm_prop(prop_block.get("prop_norm") or label)
            if not pn or "fantasy" in pn:
                continue
            for cell in prop_block.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                pick = _norm_pick(cell.get("pick_type"))
                direction = _norm_dir(cell.get("direction"))
                if not pick or not direction:
                    continue
                if is_fantasy_prop_label(cell.get("prop") or label):
                    continue
                decided = int(cell.get("decided") or 0)
                hr_pct = cell.get("hit_rate_pct")
                if hr_pct is None or decided <= 0:
                    continue
                try:
                    hr = float(hr_pct) / 100.0
                except (TypeError, ValueError):
                    continue
                out[(sp, pn, pick, direction)] = {
                    "hr": hr,
                    "n": float(decided),
                    "hit": float(cell.get("hit") or 0),
                    "miss": float(cell.get("miss") or 0),
                }
    return out


def lookup_category_hr(
    index: dict[tuple[str, str, str, str], dict[str, float]],
    *,
    sport: object,
    prop: object,
    pick_type: object,
    direction: object,
) -> dict[str, float] | None:
    if is_fantasy_prop_label(prop):
        return None
    sp = _norm_sport(sport)
    pn = _norm_prop(prop)
    pick = _norm_pick(pick_type)
    direction_u = _norm_dir(direction)
    if not (sp and pn and pick and direction_u):
        return None
    return index.get((sp, pn, pick, direction_u))


def attach_category_hr_columns(
    df: pd.DataFrame,
    index: dict[tuple[str, str, str, str], dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Add category_hr (0..1) and category_hr_n columns. Fantasy rows get NaN."""
    if df is None or df.empty:
        return df
    out = df.copy()
    idx = index if index is not None else load_category_hr_index()
    hrs: list[float] = []
    ns: list[float] = []
    prop_col = "prop_type" if "prop_type" in out.columns else ("prop" if "prop" in out.columns else None)
    for i in range(len(out)):
        row = out.iloc[i]
        prop = row.get(prop_col) if prop_col else ""
        if is_fantasy_prop_label(prop):
            hrs.append(float("nan"))
            ns.append(float("nan"))
            continue
        hit = lookup_category_hr(
            idx,
            sport=row.get("sport"),
            prop=prop,
            pick_type=row.get("pick_type"),
            direction=row.get("direction") or row.get("over_under") or row.get("bet_direction"),
        )
        if not hit:
            hrs.append(float("nan"))
            ns.append(float("nan"))
        else:
            hrs.append(float(hit["hr"]))
            ns.append(float(hit["n"]))
    out["category_hr"] = hrs
    out["category_hr_n"] = ns
    return out


def category_hr_boost_series(df: pd.DataFrame) -> pd.Series:
    """
    Additive boost for rank_score from category prior.
    ~±0.12 centered at 55% HR; requires n>=MIN_N.
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    if "category_hr" not in df.columns:
        return pd.Series(0.0, index=df.index)
    hr = pd.to_numeric(df["category_hr"], errors="coerce")
    n = pd.to_numeric(df.get("category_hr_n"), errors="coerce")
    conf = np.clip((n.fillna(0.0) / float(max(CATEGORY_HR_MIN_N, 1))), 0.0, 1.0)
    raw = ((hr - 0.55) * 0.8).clip(lower=-0.12, upper=0.18)
    return (raw.fillna(0.0) * (0.25 + 0.75 * conf)).astype(float)


def category_hr_fail_mask(df: pd.DataFrame) -> pd.Series:
    """
    True = drop this leg (known weak category with enough sample).
    Fantasy always fails. Unknown category_hr never fails (soft).
    """
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    if not CATEGORY_HR_HARD_FILTER:
        return pd.Series(False, index=df.index)

    prop_col = "prop_type" if "prop_type" in df.columns else ("prop" if "prop" in df.columns else None)
    fantasy = (
        df[prop_col].map(is_fantasy_prop_label)
        if prop_col
        else pd.Series(False, index=df.index)
    )

    if "category_hr" not in df.columns:
        return fantasy

    hr = pd.to_numeric(df["category_hr"], errors="coerce")
    n = pd.to_numeric(df.get("category_hr_n"), errors="coerce").fillna(0.0)
    pick = df.get("pick_type", pd.Series("", index=df.index)).astype(str).str.lower()
    floor = np.where(pick.str.contains("goblin"), CATEGORY_HR_MIN_GOBLIN, CATEGORY_HR_MIN_STANDARD)
    known = hr.notna() & (n >= CATEGORY_HR_MIN_N)
    weak = known & (hr < floor)
    return (fantasy | weak).astype(bool)


def winrate_priority_series(df: pd.DataFrame) -> pd.Series:
    """
    Composite used for ticket leg ordering (winrate sort mode).
    0.35 category + 0.25 recent + 0.20 model + 0.10 matchup + 0.10 HOT/consistency.
    Fantasy rows get -9.
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)

    prop_col = "prop_type" if "prop_type" in df.columns else ("prop" if "prop" in df.columns else None)
    fantasy = (
        df[prop_col].map(is_fantasy_prop_label)
        if prop_col
        else pd.Series(False, index=df.index)
    )

    nan_s = pd.Series(np.nan, index=df.index)
    cat = (
        pd.to_numeric(df["category_hr"], errors="coerce")
        if "category_hr" in df.columns
        else nan_s.copy()
    )
    ml = (
        pd.to_numeric(df["ml_prob"], errors="coerce")
        if "ml_prob" in df.columns
        else nan_s.copy()
    )
    pq = (
        pd.to_numeric(df["prop_quality_score"], errors="coerce")
        if "prop_quality_score" in df.columns
        else nan_s.copy()
    )
    rs = (
        pd.to_numeric(df["rank_score"], errors="coerce")
        if "rank_score" in df.columns
        else nan_s.copy()
    )

    direction = df.get("direction", pd.Series("", index=df.index)).astype(str).str.upper().str.strip()
    l5_o = pd.to_numeric(df.get("l5_over", nan_s), errors="coerce")
    l5_u = pd.to_numeric(df.get("l5_under", nan_s), errors="coerce")
    l10_o = pd.to_numeric(df.get("l10_over", nan_s), errors="coerce")
    l10_u = pd.to_numeric(df.get("l10_under", nan_s), errors="coerce")
    if not isinstance(l5_o, pd.Series):
        l5_o = pd.Series(l5_o, index=df.index)
    if not isinstance(l5_u, pd.Series):
        l5_u = pd.Series(l5_u, index=df.index)
    if not isinstance(l10_o, pd.Series):
        l10_o = pd.Series(l10_o, index=df.index)
    if not isinstance(l10_u, pd.Series):
        l10_u = pd.Series(l10_u, index=df.index)
    side_l5 = np.where(direction.eq("UNDER"), l5_u, l5_o)
    side_l10 = np.where(direction.eq("UNDER"), l10_u, l10_o)
    # Map counts to ~0..1 recent HR proxies (L5 /5, L10 /10).
    recent = np.where(
        ~pd.isna(side_l10),
        np.clip(np.asarray(side_l10, dtype=float) / 10.0, 0.0, 1.0),
        np.where(~pd.isna(side_l5), np.clip(np.asarray(side_l5, dtype=float) / 5.0, 0.0, 1.0), np.nan),
    )
    recent_s = pd.Series(recent, index=df.index)

    model = ml.where(ml.notna(), pq)
    if "rank_score" in df.columns:
        # crude sigmoid of rank for missing ml
        rs_p = 1.0 / (1.0 + np.exp(-pd.to_numeric(rs, errors="coerce").fillna(0.0) / 3.0))
        model = model.where(model.notna(), rs_p)

    def_tier = (
        df.get("def_tier", pd.Series("", index=df.index))
        .astype(str)
        .str.upper()
        .str.strip()
    )
    matchup = pd.Series(0.50, index=df.index)
    matchup = matchup + np.where(direction.eq("OVER") & def_tier.str.contains("WEAK"), 0.08, 0.0)
    matchup = matchup + np.where(
        direction.eq("OVER") & def_tier.str.contains("ABOVE"), 0.04, 0.0
    )
    matchup = matchup - np.where(direction.eq("OVER") & def_tier.str.contains("ELITE"), 0.06, 0.0)
    matchup = matchup + np.where(
        direction.eq("UNDER") & def_tier.str.contains("ELITE"), 0.08, 0.0
    )
    matchup = matchup + np.where(
        direction.eq("UNDER") & def_tier.str.contains("ABOVE"), 0.05, 0.0
    )
    matchup = matchup - np.where(direction.eq("UNDER") & def_tier.str.contains("WEAK"), 0.06, 0.0)

    streak = df.get("l10_streak", pd.Series("", index=df.index)).astype(str).str.upper().str.strip()
    consistency = pd.Series(0.50, index=df.index)
    consistency = consistency + np.where(streak.eq("HOT"), 0.10, 0.0)
    consistency = consistency - np.where(streak.eq("COLD"), 0.10, 0.0)
    grade = df.get("consistency_grade", pd.Series("", index=df.index)).astype(str).str.upper().str.strip()
    consistency = consistency + np.where(grade.eq("S"), 0.05, np.where(grade.eq("A"), 0.03, 0.0))

    cat_f = cat.fillna(0.52)
    recent_f = recent_s.fillna(0.50)
    model_f = model.fillna(0.50)
    match_f = matchup.clip(0.0, 1.0)
    cons_f = consistency.clip(0.0, 1.0)

    pri = (
        0.35 * cat_f
        + 0.25 * recent_f
        + 0.20 * model_f
        + 0.10 * match_f
        + 0.10 * cons_f
    )
    pri = pd.to_numeric(pri, errors="coerce").fillna(0.0)
    pri = pri.where(~fantasy, -9.0)
    return pri
