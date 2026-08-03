"""Shared slate row slimming for Flask API + mobile offline bundles."""

from __future__ import annotations

import math
from typing import Any

_HISTORY_KEYS = frozenset(
    {
        "actual_series",
        "line_series",
        *(f"g{i}" for i in range(1, 11)),
        *(f"stat_g{i}" for i in range(1, 11)),
        *(f"line_g{i}" for i in range(1, 11)),
    }
)

_LIST_KEYS = frozenset(
    {
        "tier",
        "rank_score",
        "player",
        "team",
        "opp",
        "prop",
        "pick_type",
        "line",
        "dir",
        "edge",
        "abs_edge",
        "projection",
        "hit_rate",
        "l5_avg",
        "l5_over",
        "l5_under",
        "l5_games_played",
        "l10_over",
        "l10_under",
        "l10_games_played",
        "season_avg",
        "ml_prob",
        "def_tier",
        "def_matchup_signal",
        "standard_line",
        "standard_projection",
        "opponent_def_rank",
        "image_url",
        "game_date",
        "game_time",
        "sport",
        "pick_platform",
        "line_underdog",
        "line_draftkings",
        "cross_edge_vs_pp",
        "best_cross_book",
    }
)

_ALL_UI_KEYS = _LIST_KEYS | _HISTORY_KEYS


def history_keys() -> frozenset[str]:
    return _HISTORY_KEYS


def list_keys() -> frozenset[str]:
    return _LIST_KEYS


def all_ui_keys() -> frozenset[str]:
    return _ALL_UI_KEYS


def slim_cell(key: str, v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if key == "pick_platform":
            return s.lower().replace(" ", "") if s else None
        return s if s else None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        if key in ("edge", "rank_score", "abs_edge", "ml_prob", "def_matchup_signal"):
            return round(float(v), 4)
        if key == "hit_rate":
            return round(float(v), 6)
        if key == "opponent_def_rank":
            fv = float(v)
            return int(fv) if fv.is_integer() else round(fv, 4)
        if key in (
            "line",
            "l5_over",
            "l5_under",
            "l10_over",
            "l10_under",
            "projection",
            "standard_line",
            "season_avg",
        ):
            fv = float(v)
            return int(fv) if fv.is_integer() else round(fv, 3)
        return v
    if isinstance(v, list) and key in ("actual_series", "line_series"):
        out = []
        for item in v[:12]:
            try:
                fv = float(item)
                if math.isnan(fv) or math.isinf(fv):
                    continue
                out.append(int(fv) if fv.is_integer() else round(fv, 3))
            except (TypeError, ValueError):
                continue
        return out or None
    return v


def slim_row(r: dict, *, include_history: bool = False) -> dict:
    keys = _ALL_UI_KEYS if include_history else _LIST_KEYS
    slim: dict[str, Any] = {}
    for kk in keys:
        if kk not in r:
            continue
        cv = slim_cell(kk, r[kk])
        if cv is None:
            continue
        slim[kk] = cv
    return slim


def history_only(r: dict) -> dict:
    slim: dict[str, Any] = {}
    for kk in _HISTORY_KEYS:
        if kk not in r:
            continue
        cv = slim_cell(kk, r[kk])
        if cv is None:
            continue
        slim[kk] = cv
    return slim


def card_score(r: dict) -> float:
    """Rank rows for the home-card payload (edges + streaks)."""
    try:
        edge = abs(float(r.get("edge") or 0.0))
    except (TypeError, ValueError):
        edge = 0.0
    try:
        l5 = float(r.get("l5_over") or 0.0)
    except (TypeError, ValueError):
        l5 = 0.0
    try:
        l10 = float(r.get("l10_over") or 0.0)
    except (TypeError, ValueError):
        l10 = 0.0
    try:
        rank = float(r.get("rank_score") or 0.0)
    except (TypeError, ValueError):
        rank = 0.0
    return edge * 2.0 + l5 * 1.5 + l10 * 0.8 + max(rank, 0.0) * 0.15
