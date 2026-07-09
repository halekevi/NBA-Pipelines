"""Drop PrizePicks fantasy-score markets from pipeline slates."""

from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

# Columns that may carry a human-readable prop label (checked in order).
_PROP_LABEL_COLUMNS: tuple[str, ...] = (
    "prop_type",
    "prop",
    "prop_name",
    "prop_type_norm",
    "Prop",
    "Prop Type",
    "stat_type",
    "prop_norm",
)


def _norm_label(text: object) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def is_fantasy_prop_label(text: object) -> bool:
    """True when the prop label is a fantasy-score market (not a real stat)."""
    s = _norm_label(text)
    if not s:
        return False
    return "fantasy" in s


def fantasy_prop_mask(df: pd.DataFrame) -> pd.Series:
    """Row mask: True where any known prop column is a fantasy market."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    mask = pd.Series(False, index=df.index)
    for col in _PROP_LABEL_COLUMNS:
        if col in df.columns:
            mask |= df[col].map(is_fantasy_prop_label)
    return mask


def drop_fantasy_props(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Return (filtered_df, dropped_count)."""
    if df is None or df.empty:
        return df, 0
    mask = fantasy_prop_mask(df)
    dropped = int(mask.sum())
    if dropped == 0:
        return df, 0
    return df.loc[~mask].copy(), dropped


def drop_fantasy_rows(rows: Iterable[dict]) -> tuple[list[dict], int]:
    """Filter list-of-dict step rows (NHL step2 style)."""
    kept: list[dict] = []
    dropped = 0
    for row in rows:
        label = ""
        for key in ("stat_type", "prop_type", "prop", "prop_name"):
            if key in row and str(row.get(key) or "").strip():
                label = row[key]
                break
        if is_fantasy_prop_label(label):
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped
