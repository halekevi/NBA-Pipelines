"""Jul-22 seeded + rolling category HR priority for MAIN / big-slate ranking.

Soft-boosts direction×prop×pick cells that hit ≥60% (n≥10) on 2026-07-22 graded
non-Demon props, and/or rolling category_hr ≥60% with meaningful n.

Soft-downranks known weak lanes (Soccer OVER Shots Goblin, Tennis Ace/DF Goblin, …).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

import numpy as np
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_JUL22_PATH = os.path.join(
    REPO_ROOT, "data", "reports", "jul22_priority_hr_cells.json"
)

# Soft additive rank_score deltas (same units as category_hr_boost / graded_history).
PRIORITY_BOOST = float(os.getenv("PROPORACLE_CELL_HR_PRIORITY_BOOST", "0.10"))
WEAK_PENALTY = float(os.getenv("PROPORACLE_CELL_HR_WEAK_PENALTY", "0.14"))
ROLLING_HR_FLOOR = float(os.getenv("PROPORACLE_CELL_HR_ROLLING_FLOOR", "0.60"))
ROLLING_HR_MIN_N = int(os.getenv("PROPORACLE_CELL_HR_ROLLING_MIN_N", "10"))


def _norm_prop(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").strip().lower())


def _norm_sport(text: object) -> str:
    s = str(text or "").strip().upper()
    if s in ("SOC", "SOCCER"):
        return "SOCCER"
    return s


def _norm_pick(text: object) -> str:
    s = str(text or "").strip().lower()
    if "goblin" in s:
        return "Goblin"
    if "demon" in s:
        return "Demon"
    if "standard" in s or s in ("", "std", "normal"):
        return "Standard"
    return ""


def _norm_dir(text: object) -> str:
    s = str(text or "").strip().upper()
    if s in ("O", "OVER", "MORE"):
        return "OVER"
    if s in ("U", "UNDER", "LESS", "LOWER"):
        return "UNDER"
    return ""


def _cell_key(
    sport: object, prop: object, pick_type: object, direction: object
) -> tuple[str, str, str, str] | None:
    sp = _norm_sport(sport)
    pn = _norm_prop(prop)
    pick = _norm_pick(pick_type)
    direction_u = _norm_dir(direction)
    if not (sp and pn and pick and direction_u):
        return None
    if pick == "Demon":
        return None
    return (sp, pn, pick, direction_u)


@lru_cache(maxsize=2)
def load_jul22_cell_sets(
    path: str = DEFAULT_JUL22_PATH,
) -> tuple[frozenset[tuple[str, str, str, str]], frozenset[tuple[str, str, str, str]]]:
    """Return (priority_keys, weak_keys) as (sport, prop_norm, pick, direction)."""
    priority: set[tuple[str, str, str, str]] = set()
    weak: set[tuple[str, str, str, str]] = set()
    if not path or not os.path.isfile(path):
        return frozenset(), frozenset()
    try:
        raw = json.loads(open(path, encoding="utf-8").read())
    except Exception:
        return frozenset(), frozenset()
    for row in raw.get("priority_cells") or []:
        if not isinstance(row, dict):
            continue
        key = _cell_key(
            row.get("sport_key") or row.get("sport"),
            row.get("prop"),
            row.get("pick_type"),
            row.get("direction"),
        )
        if key:
            priority.add(key)
    for row in raw.get("weak_cells") or []:
        if not isinstance(row, dict):
            continue
        key = _cell_key(
            row.get("sport_key") or row.get("sport"),
            row.get("prop"),
            row.get("pick_type"),
            row.get("direction"),
        )
        if key:
            weak.add(key)
    # Hardcoded fallbacks if JSON missing weak seeds (user callouts).
    if not weak:
        weak.update(
            {
                ("SOCCER", "shots", "Goblin", "OVER"),
                ("SOCCER", "goalassist", "Goblin", "OVER"),
                ("TENNIS", "aces", "Goblin", "OVER"),
                ("TENNIS", "doublefaults", "Goblin", "OVER"),
            }
        )
    return frozenset(priority), frozenset(weak)


def cell_hr_priority_boost_series(
    df: pd.DataFrame,
    *,
    path: str = DEFAULT_JUL22_PATH,
) -> pd.Series:
    """
    Additive rank_score boost/penalty for MAIN / combined slate ranking.

    +PRIORITY_BOOST when Jul-22 allowlist match OR category_hr>=60% with n>=10
    -WEAK_PENALTY when weak-cell match (overrides priority for that leg)
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)

    priority, weak = load_jul22_cell_sets(path)
    prop_col = (
        "prop_type"
        if "prop_type" in df.columns
        else ("prop" if "prop" in df.columns else None)
    )
    boost = pd.Series(0.0, index=df.index, dtype=float)
    cat_hr = pd.to_numeric(df.get("category_hr"), errors="coerce")
    cat_n = pd.to_numeric(df.get("category_hr_n"), errors="coerce")

    for i in df.index:
        row = df.loc[i]
        prop = row.get(prop_col) if prop_col else ""
        key = _cell_key(
            row.get("sport"),
            prop,
            row.get("pick_type"),
            row.get("direction")
            or row.get("over_under")
            or row.get("bet_direction"),
        )
        if key is None:
            continue
        if key in weak:
            boost.at[i] -= WEAK_PENALTY
            continue
        if key in priority:
            boost.at[i] += PRIORITY_BOOST
            continue
        # Rolling / long-run category prior (≥60%, meaningful n).
        try:
            hr_v = float(cat_hr.at[i]) if cat_hr is not None else float("nan")
            n_v = float(cat_n.at[i]) if cat_n is not None else float("nan")
        except (TypeError, ValueError, KeyError):
            continue
        if np.isfinite(hr_v) and np.isfinite(n_v) and n_v >= ROLLING_HR_MIN_N and hr_v >= ROLLING_HR_FLOOR:
            boost.at[i] += PRIORITY_BOOST * 0.85

    return boost.astype(float)


def summarize_cell_hr_priority(df: pd.DataFrame, boost: pd.Series) -> dict[str, int]:
    """Counts for logging."""
    if df is None or df.empty or boost is None or boost.empty:
        return {"boosted": 0, "penalized": 0}
    b = pd.to_numeric(boost, errors="coerce").fillna(0.0)
    return {
        "boosted": int((b > 0).sum()),
        "penalized": int((b < 0).sum()),
    }
