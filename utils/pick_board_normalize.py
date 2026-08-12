"""Normalize PrizePicks-style alt boards (Goblin / Demon / Standard).

PrizePicks / enrichment sometimes sets standard_line to a synthetic offset
(~line+1.5) per Goblin row instead of the true Standard market. We resolve the
real Standard sibling from the board when possible, then reclassify Goblins that
are harder than that market (or absurd vs season/projection) as Demons.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, MutableMapping, Optional

_EPS = 0.25
# Goblin OVER this far above season/proj baseline is not a soft Goblin.
_ABSURD_OVER_BUFFER = 8.0


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


def _group_key(row: MappingLike) -> tuple[str, str, str]:
    sport = str(row.get("sport") or "").strip().upper()
    player = str(row.get("player") or row.get("player_name") or "").strip().lower()
    prop = str(row.get("prop") or row.get("prop_type") or "").strip().lower()
    return sport, player, prop


MappingLike = MutableMapping[str, Any]


def _baseline(row: MappingLike) -> Optional[float]:
    vals = [_f(row.get("season_avg")), _f(row.get("projection")), _f(row.get("standard_projection"))]
    vals = [v for v in vals if v is not None and v > 0]
    return max(vals) if vals else None


def _looks_synthetic_std(goblin_rows: list[MappingLike]) -> bool:
    """True when each Goblin OVER's standard_line is ~1–2 pts *above* its own line.

    Fake enrichment: Goblin 34.5 → standard_line 36. Real hard Goblin: 6.5 vs std 4.0
    (std below the Goblin OVER) must not be treated as synthetic.
    """
    if len(goblin_rows) < 2:
        return False
    offsets: list[float] = []
    stds: set[float] = set()
    for r in goblin_rows:
        line = _f(r.get("line"))
        std = _f(r.get("standard_line"))
        d = str(r.get("dir") or r.get("direction") or "").strip().upper()
        if line is None or std is None:
            return False
        if d.startswith("U"):
            # Fake UNDER goblin: standard_line slightly below the goblin line.
            offsets.append(line - std)
        else:
            offsets.append(std - line)
        stds.add(round(std, 2))
    # Real Standard is shared; synthetic offsets vary with each Goblin line.
    if len(stds) < 2:
        return False
    return all(0.4 <= off <= 2.6 for off in offsets)


def resolve_true_standard_line(group_rows: Iterable[MappingLike]) -> Optional[float]:
    """Prefer an actual Standard board line; ignore synthetic per-Goblin offsets."""
    rows = [r for r in group_rows if isinstance(r, dict)]
    std_lines: list[float] = []
    for r in rows:
        if canonical_pick_type(r.get("pick_type") or r.get("pick")) != "Standard":
            continue
        v = _f(r.get("line"))
        if v is not None:
            std_lines.append(v)
    if std_lines:
        std_lines.sort()
        return std_lines[len(std_lines) // 2]

    goblins = [
        r
        for r in rows
        if canonical_pick_type(r.get("pick_type") or r.get("pick")) == "Goblin"
    ]
    if _looks_synthetic_std(goblins):
        return None

    # Shared standard_line across Goblins → treat as real reference.
    shared: list[float] = []
    for r in goblins:
        v = _f(r.get("standard_line"))
        if v is not None:
            shared.append(round(v, 2))
    if shared and len(set(shared)) == 1:
        return float(shared[0])
    return None


def should_reclassify_goblin_as_demon(
    *,
    pick_type: object,
    direction: object,
    line: object,
    standard_line: object,
    baseline: object = None,
    eps: float = _EPS,
    absurd_buffer: float = _ABSURD_OVER_BUFFER,
) -> bool:
    """True when a Goblin line is harder than Standard or absurd vs production."""
    if canonical_pick_type(pick_type) != "Goblin":
        return False
    line_f = _f(line)
    if line_f is None:
        return False
    d = str(direction or "").strip().upper()
    std_f = _f(standard_line)
    if std_f is not None:
        if d.startswith("O") and line_f > std_f + eps:
            return True
        if d.startswith("U") and line_f < std_f - eps:
            return True
    base = _f(baseline)
    if d.startswith("O") and base is not None and line_f > base + absurd_buffer:
        return True
    return False


def normalize_row_pick_type(
    row: MutableMapping[str, Any],
    *,
    true_standard_line: Optional[float] = None,
) -> MutableMapping[str, Any]:
    """
    In-place: Goblin harder than true Standard (or absurd vs avg/proj) → Demon.
    """
    if not isinstance(row, dict):
        return row
    raw = row.get("pick_type") or row.get("pick") or "Standard"
    canon = canonical_pick_type(raw)
    row["pick_type"] = canon
    if "pick" in row:
        row["pick"] = canon

    std_for_cmp = true_standard_line
    line_f = _f(row.get("line"))
    row_std = _f(row.get("standard_line"))
    direction = str(row.get("dir") or row.get("direction") or "").strip().upper()
    if std_for_cmp is None and line_f is not None and row_std is not None:
        # Synthetic fake makes Goblin look *softer* than Standard (OVER: std ≈ line+1.5).
        if direction.startswith("U"):
            fake_off = line_f - row_std
        else:
            fake_off = row_std - line_f
        if 0.4 <= fake_off <= 2.6:
            std_for_cmp = None
            base = _baseline(row)
            if base is not None:
                row["standard_line"] = round(base * 2) / 2.0
                row["standard_line_source"] = "baseline_avg_proj"
        else:
            std_for_cmp = row_std
    elif std_for_cmp is None:
        std_for_cmp = row_std

    if std_for_cmp is not None:
        row["standard_line"] = std_for_cmp
        row["standard_line_source"] = "board_standard"

    direction = row.get("dir") or row.get("direction") or ""
    if should_reclassify_goblin_as_demon(
        pick_type=canon,
        direction=direction,
        line=row.get("line"),
        standard_line=std_for_cmp,
        baseline=_baseline(row),
    ):
        row["pick_type_raw"] = str(raw)
        row["pick_type"] = "Demon"
        if "pick" in row:
            row["pick"] = "Demon"
        row["pick_reclassified"] = "goblin_harder_than_standard"
    return row


def normalize_rows_pick_types(rows: list[Any]) -> list[Any]:
    """Batch normalize: resolve true Standard per player/prop, then reclassify."""
    if not isinstance(rows, list):
        return rows
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    passthrough: list[Any] = []
    keyed: list[tuple[tuple[str, str, str], dict]] = []
    for r in rows:
        if not isinstance(r, dict):
            passthrough.append(r)
            continue
        rr = dict(r)
        key = _group_key(rr)
        groups[key].append(rr)
        keyed.append((key, rr))

    true_std: dict[tuple[str, str, str], Optional[float]] = {
        k: resolve_true_standard_line(v) for k, v in groups.items()
    }
    out: list[Any] = []
    for key, rr in keyed:
        normalize_row_pick_type(rr, true_standard_line=true_std.get(key))
        out.append(rr)
    out.extend(passthrough)
    return out
