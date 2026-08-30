#!/usr/bin/env python3
"""Shared PGA round actuals for fetch_golf_actuals + golf_grader."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_GOLF_SCRIPTS = Path(__file__).resolve().parent
_REPO = _GOLF_SCRIPTS.parents[2]
if str(_GOLF_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_GOLF_SCRIPTS))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from step4_attach_player_stats_golf import (  # noqa: E402
    CACHE_COLUMNS,
    ensure_round_cache,
    load_round_cache,
    prop_stat_key,
    _player_key,
)

STAT_TO_PROP = {
    "strokes": "Strokes",
    "birdies_or_better": "Birdies Or Better",
    "pars": "Pars",
    "bogeys_or_worse": "Bogeys Or Worse",
}

DEFAULT_CACHE = _REPO / "Sports" / "Golf" / "cache" / "golf_round_cache.csv"


def round_calendar_date(tournament_date: str, round_n: object) -> str:
    """Map ESPN event start + round number to the round's calendar day (Thu=R1)."""
    raw = str(tournament_date or "").strip()[:10]
    try:
        d0 = date.fromisoformat(raw)
        rn = int(float(round_n))
    except (TypeError, ValueError):
        return raw
    if rn < 1:
        rn = 1
    return (d0 + timedelta(days=rn - 1)).isoformat()


def load_golf_round_cache(cache_path: Path | None = None, *, force_refresh: bool = False) -> pd.DataFrame:
    path = Path(cache_path) if cache_path else DEFAULT_CACHE
    if not path.is_absolute():
        path = _REPO / path
    if force_refresh or not path.is_file():
        return ensure_round_cache(path, weeks_back=12, force_refresh=True)
    return load_round_cache(path)


def actuals_rows_for_date(cache: pd.DataFrame, target: str) -> list[dict[str, object]]:
    """One row per player × prop for rounds whose calendar day equals ``target``."""
    if cache is None or cache.empty:
        return []
    want = str(target).strip()[:10]
    rows: list[dict[str, object]] = []
    work = cache.copy()
    if "player_key" not in work.columns:
        work["player_key"] = work.get("player_name", "").map(_player_key)
    work["_round_date"] = [
        round_calendar_date(td, rn)
        for td, rn in zip(work.get("tournament_date", ""), work.get("round", 1))
    ]
    day = work[work["_round_date"] == want]
    if day.empty:
        return []
    # Playoff / weather: keep the last round of that calendar day.
    day = day.sort_values(["player_key", "round"], kind="mergesort")
    day = day.drop_duplicates(subset=["player_key"], keep="last")
    for _, rec in day.iterrows():
        player = str(rec.get("player_name") or "").strip()
        if not player:
            continue
        team = str(rec.get("tournament_name") or "PGA").strip() or "PGA"
        for stat, prop in STAT_TO_PROP.items():
            raw = rec.get(stat)
            try:
                actual = float(raw)
            except (TypeError, ValueError):
                continue
            if actual != actual:
                continue
            rows.append(
                {
                    "player": player,
                    "team": team,
                    "prop_type": prop,
                    "actual": actual,
                    "round": rec.get("round"),
                    "round_date": want,
                }
            )
    return rows


def actuals_lookup(cache: pd.DataFrame, target: str) -> dict[tuple[str, str], float]:
    """(player_key, stat_col) → actual for that calendar day."""
    if cache is None or cache.empty:
        return {}
    want = str(target).strip()[:10]
    work = cache.copy()
    if "player_key" not in work.columns:
        work["player_key"] = work.get("player_name", "").map(_player_key)
    work["_round_date"] = [
        round_calendar_date(td, rn)
        for td, rn in zip(work.get("tournament_date", ""), work.get("round", 1))
    ]
    day = work[work["_round_date"] == want]
    if day.empty:
        return {}
    day = day.sort_values(["player_key", "round"], kind="mergesort")
    day = day.drop_duplicates(subset=["player_key"], keep="last")
    out: dict[tuple[str, str], float] = {}
    for _, rec in day.iterrows():
        pk = str(rec.get("player_key") or "").strip()
        if not pk:
            continue
        for stat in STAT_TO_PROP:
            try:
                actual = float(rec.get(stat))
            except (TypeError, ValueError):
                continue
            if actual != actual:
                continue
            out[(pk, stat)] = actual
    return out


__all__ = [
    "CACHE_COLUMNS",
    "DEFAULT_CACHE",
    "STAT_TO_PROP",
    "actuals_lookup",
    "actuals_rows_for_date",
    "load_golf_round_cache",
    "prop_stat_key",
    "round_calendar_date",
    "_player_key",
]
