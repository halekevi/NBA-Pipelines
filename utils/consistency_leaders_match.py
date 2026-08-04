"""Load + match season consistency leaders for UI / ticket badges."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_CANDIDATES = (
    _REPO / "data" / "slate_consistency" / "consistency_leaders_latest.json",
    _REPO / "ui_runner" / "data" / "consistency_leaders_latest.json",
    _REPO / "mobile" / "www" / "consistency_leaders_latest.json",
)


def _norm_name(name: Any) -> str:
    s = str(name or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", " ", s)


def _norm_prop(p: Any) -> str:
    s = re.sub(r"\s+", " ", str(p or "").strip().lower().replace("_", " "))
    s = s.replace("+", " + ")
    s = re.sub(r"\s+", " ", s).strip()
    aliases = {
        "pts": "points",
        "reb": "rebounds",
        "rebs": "rebounds",
        "ast": "assists",
        "asts": "assists",
        "pra": "pts+rebs+asts",
        "pr": "pts+rebs",
        "pa": "pts+asts",
        "ra": "rebs+asts",
        "pts + rebs + asts": "pts+rebs+asts",
        "pts + rebs": "pts+rebs",
        "pts + asts": "pts+asts",
        "rebs + asts": "rebs+asts",
        "3pm": "3-pt made",
        "blocks": "blocked shots",
        "g+a": "goals+assists",
        "goals + assists": "goals+assists",
    }
    return aliases.get(s, s)


def _num(x: Any) -> float | None:
    try:
        if x in (None, ""):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def load_match_index() -> tuple[dict[tuple[str, str, str, str], dict], float]:
    """Return ({(sport, player_norm, prop_key, direction): row}, mtime)."""
    path = next((p for p in _CANDIDATES if p.is_file()), None)
    if path is None:
        return {}, 0.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mtime = path.stat().st_mtime
    except (OSError, json.JSONDecodeError):
        return {}, 0.0
    idx: dict[tuple[str, str, str, str], dict] = {}
    for row in data.get("match_index") or []:
        if not isinstance(row, dict):
            continue
        sport = str(row.get("sport") or "").upper()
        pn = str(row.get("player_norm") or _norm_name(row.get("player")))
        prop = str(row.get("prop_key") or _norm_prop(row.get("prop")))
        direction = str(row.get("direction") or "").upper()
        if not (sport and pn and prop and direction in ("OVER", "UNDER")):
            continue
        key = (sport, pn, prop, direction)
        prev = idx.get(key)
        if prev is None or float(row.get("score") or 0) > float(prev.get("score") or 0):
            idx[key] = row
    return idx, mtime


def match_leader(
    *,
    sport: Any,
    player: Any,
    prop: Any,
    direction: Any,
    line: Any = None,
    pick_type: Any = None,
) -> dict | None:
    """Match a slate/ticket leg to a consistency leader (line within band)."""
    idx, _ = load_match_index()
    if not idx:
        return None
    sport_u = str(sport or "").upper().strip()
    pn = _norm_name(player)
    prop_k = _norm_prop(prop)
    direction_u = str(direction or "").upper().strip()
    if direction_u in ("O", "MORE"):
        direction_u = "OVER"
    if direction_u in ("U", "LESS", "LOWER"):
        direction_u = "UNDER"
    if not (sport_u and pn and prop_k and direction_u in ("OVER", "UNDER")):
        return None
    row = idx.get((sport_u, pn, prop_k, direction_u))
    if row is None:
        return None
    # Optional pick_type soft filter: prefer same pick, but don't reject on mismatch
    # (match_index already keeps best pick_type per player/prop/dir).
    band = float(row.get("line_band") or 0.5)
    leader_line = _num(row.get("line"))
    slate_line = _num(line)
    if leader_line is not None and slate_line is not None:
        if abs(leader_line - slate_line) > band + 1e-9:
            return None
    return row


def cons_line_badge_html(leg: dict) -> str:
    """HTML badge for ticket/slate legs that match a consistency leader."""
    if not isinstance(leg, dict):
        return ""
    row = match_leader(
        sport=leg.get("sport"),
        player=leg.get("player"),
        prop=leg.get("prop_type") or leg.get("prop"),
        direction=leg.get("direction") or leg.get("dir"),
        line=leg.get("line"),
        pick_type=leg.get("pick_type"),
    )
    if not row:
        return ""
    hr = row.get("hit_rate")
    n = row.get("sample_n")
    line = row.get("line")
    pick = row.get("pick_type") or ""
    hr_pct = f"{100 * float(hr):.0f}%" if hr is not None else "?"
    line_s = f"{float(line):.1f}" if line is not None else "?"
    title = (
        f"Season consistent {row.get('direction')} {row.get('prop')} "
        f"@{line_s} · {hr_pct} ({n}) · {pick}"
    )
    demon = " · Demon-only" if row.get("demon_only") else ""
    label = f"CONS {hr_pct}"
    return (
        f'<span class="cons-line-badge" title="{title}{demon}">'
        f"📌 {label}</span>"
    )


def clear_cache() -> None:
    load_match_index.cache_clear()
