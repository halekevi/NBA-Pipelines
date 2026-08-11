"""Normalize PrizePicks-style alt boards (Goblin / Demon / Standard).

PrizePicks occasionally labels harder-than-Standard alts as Goblin. True Goblin
OVERs are softer (lower line than Standard); true Goblin UNDERs are softer
(higher line than Standard). Harder alts belong on Demon (or should be hidden).
"""
from __future__ import annotations

from typing import Any, MutableMapping, Optional

_EPS = 0.25


def _f(x: object) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


def canonical_pick_type(pick: object) -> str:
    s = str(pick or "").strip().lower()
    if "gob" in s:
        return "Goblin"
    if "dem" in s:
        return "Demon"
    if "stan" in s or s in ("", "none", "nan"):
        return "Standard"
    return str(pick or "Standard").strip() or "Standard"


def should_reclassify_goblin_as_demon(
    *,
    pick_type: object,
    direction: object,
    line: object,
    standard_line: object,
    eps: float = _EPS,
) -> bool:
    """True when a Goblin line is harder than its Standard sibling."""
    if canonical_pick_type(pick_type) != "Goblin":
        return False
    line_f = _f(line)
    std_f = _f(standard_line)
    if line_f is None or std_f is None:
        return False
    d = str(direction or "").strip().upper()
    if d.startswith("O"):
        # Harder OVER = higher line than Standard
        return line_f > std_f + eps
    if d.startswith("U"):
        # Harder UNDER = lower line than Standard
        return line_f < std_f - eps
    return False


def normalize_row_pick_type(row: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """
    In-place: Goblin harder than Standard → Demon.
    Sets pick_type_raw / pick_reclassified when changed.
    """
    if not isinstance(row, dict):
        return row
    raw = row.get("pick_type") or row.get("pick") or "Standard"
    canon = canonical_pick_type(raw)
    row["pick_type"] = canon
    if "pick" in row:
        row["pick"] = canon
    direction = row.get("dir") or row.get("direction") or ""
    if should_reclassify_goblin_as_demon(
        pick_type=canon,
        direction=direction,
        line=row.get("line"),
        standard_line=row.get("standard_line"),
    ):
        row["pick_type_raw"] = str(raw)
        row["pick_type"] = "Demon"
        if "pick" in row:
            row["pick"] = "Demon"
        row["pick_reclassified"] = "goblin_harder_than_standard"
    return row
