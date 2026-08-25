"""Per-prop PrizePicks fetch clocks.

fetched_at     — when this process pulled the board (America/New_York ISO).
pp_updated_at  — PrizePicks projection updated/created time when the API sends it.

Every step1 row should carry both so line-history compares prints, not a
board-level overwrite.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")

PP_UPDATED_KEYS = (
    "updated_at",
    "updatedAt",
    "odds_updated_at",
    "line_updated_at",
    "last_updated_at",
    "last_updated",
    "created_at",
    "createdAt",
)


def now_et_iso() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def extract_pp_updated_at(attrs: object) -> str:
    """First non-empty PrizePicks timestamp on a projection attributes dict."""
    if not isinstance(attrs, dict):
        return ""
    blob = attrs.get("attributes") if isinstance(attrs.get("attributes"), dict) else attrs
    if not isinstance(blob, dict):
        return ""
    for key in PP_UPDATED_KEYS:
        raw = blob.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text and text.lower() not in {"nan", "none", "nat"}:
            return text
    return ""


def _blank_mask(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    return series.isna() | text.eq("") | text.str.lower().isin({"nan", "none", "nat"})


def stamp_fetched_at(
    df: pd.DataFrame,
    *,
    when: str | None = None,
    overwrite: bool = True,
) -> pd.DataFrame:
    """Write fetched_at on every row. overwrite=True for a fresh API pull."""
    if df is None or df.empty:
        if df is not None and "fetched_at" not in df.columns:
            out = df.copy()
            out["fetched_at"] = ""
            return out
        return df
    out = df.copy()
    ts = (when or now_et_iso()).strip()
    if overwrite or "fetched_at" not in out.columns:
        out["fetched_at"] = ts
        return out
    miss = _blank_mask(out["fetched_at"])
    out.loc[miss, "fetched_at"] = ts
    return out


def clock_fields(attrs: object, *, fetched_at: str | None = None) -> dict[str, str]:
    return {
        "fetched_at": (fetched_at or "").strip() or now_et_iso(),
        "pp_updated_at": extract_pp_updated_at(attrs),
    }
