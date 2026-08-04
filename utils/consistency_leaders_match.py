"""Load + match season consistency leaders for UI / ticket badges.

Leaders are keyed by sport × player × prop × pick_class:
  goblin_over      → badge GOB xx%
  standard_over    → badge STD xx%
  standard_under   → badge UND xx%
  goblin_under     → badge UND xx%  (only when material sample exists)

Demon is never mixed into Goblin/Standard rates.
"""

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
    _REPO / "ui_runner" / "templates" / "consistency_leaders_latest.json",
    _REPO / "mobile" / "www" / "consistency_leaders_latest.json",
)

PICK_CLASS_BADGE = {
    "goblin_over": "GOB",
    "standard_over": "STD",
    "standard_under": "UND",
    "goblin_under": "UND",
}


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


def _norm_pick(pt: Any) -> str:
    s = str(pt or "").lower()
    if "goblin" in s:
        return "Goblin"
    if "demon" in s:
        return "Demon"
    if "standard" in s:
        return "Standard"
    return "Other"


def _norm_direction(direction: Any) -> str:
    d = str(direction or "").upper().strip()
    if d in ("O", "MORE"):
        return "OVER"
    if d in ("U", "LESS", "LOWER"):
        return "UNDER"
    return d


def pick_class_for(pick_type: Any, direction: Any) -> str | None:
    """Map slate pick_type + direction → leader pick_class (None = no badge)."""
    pick = _norm_pick(pick_type)
    direction_u = _norm_direction(direction)
    if pick == "Goblin" and direction_u == "OVER":
        return "goblin_over"
    if pick == "Standard" and direction_u == "OVER":
        return "standard_over"
    if pick == "Standard" and direction_u == "UNDER":
        return "standard_under"
    if pick == "Goblin" and direction_u == "UNDER":
        return "goblin_under"
    return None


def badge_prefix_for(pick_class: Any) -> str:
    return PICK_CLASS_BADGE.get(str(pick_class or ""), "CONS")


def badge_label(row: dict) -> str:
    """Return display label like 'GOB 84%' from a leader row."""
    hr = row.get("hit_rate")
    hr_pct = f"{100 * float(hr):.0f}%" if hr is not None else "?"
    prefix = row.get("badge_prefix") or badge_prefix_for(row.get("pick_class"))
    return f"{prefix} {hr_pct}"


@lru_cache(maxsize=1)
def load_match_index() -> tuple[dict[tuple[str, str, str, str], dict], float]:
    """Return ({(sport, player_norm, prop_key, pick_class): row}, mtime)."""
    path = next((p for p in _CANDIDATES if p.is_file()), None)
    if path is None:
        return {}, 0.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mtime = path.stat().st_mtime
    except (OSError, json.JSONDecodeError):
        return {}, 0.0
    idx: dict[tuple[str, str, str, str], dict] = {}
    rows = data.get("match_index") or data.get("leaders") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sport = str(row.get("sport") or "").upper()
        pn = str(row.get("player_norm") or _norm_name(row.get("player")))
        prop = str(row.get("prop_key") or _norm_prop(row.get("prop")))
        pc = str(row.get("pick_class") or "").strip().lower()
        if not pc:
            # Backward compat with older CONS artifact (best pick per dir).
            pc = pick_class_for(row.get("pick_type"), row.get("direction")) or ""
        if not (sport and pn and prop and pc in PICK_CLASS_BADGE):
            continue
        key = (sport, pn, prop, pc)
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
    """Match a slate/ticket leg to a consistency leader (class + line within band)."""
    idx, _ = load_match_index()
    if not idx:
        return None
    sport_u = str(sport or "").upper().strip()
    pn = _norm_name(player)
    prop_k = _norm_prop(prop)
    direction_u = _norm_direction(direction)
    pc = pick_class_for(pick_type, direction_u)
    if not (sport_u and pn and prop_k and pc):
        return None
    row = idx.get((sport_u, pn, prop_k, pc))
    if row is None:
        return None
    band = float(row.get("line_band") or 0.5)
    leader_line = _num(row.get("reference_line") if row.get("reference_line") is not None else row.get("line"))
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
    line = row.get("reference_line") if row.get("reference_line") is not None else row.get("line")
    pick = row.get("pick_type") or ""
    pc = row.get("pick_class") or ""
    hr_pct = f"{100 * float(hr):.0f}%" if hr is not None else "?"
    line_s = f"{float(line):.1f}" if line is not None else "?"
    label = badge_label(row)
    title = (
        f"Season {pc or pick} {row.get('direction')} {row.get('prop')} "
        f"@{line_s} · {hr_pct} (n={n})"
    )
    cls = f"cons-line-badge cons-{badge_prefix_for(pc).lower()}"
    return (
        f'<span class="{cls}" title="{title}">'
        f"📌 {label}</span>"
    )


def clear_cache() -> None:
    load_match_index.cache_clear()
