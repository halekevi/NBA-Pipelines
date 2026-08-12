"""Stamp Matchup Edge league/team/opp-category ranks onto slate explorer rows."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.matchup_edge.slate_io import norm_player_name, norm_prop

_REPO = Path(__file__).resolve().parents[2]

_PROP_TO_CAT: dict[str, str] = {
    "points": "pts",
    "rebounds": "reb",
    "assists": "ast",
    "steals": "stl",
    "blocks": "blk",
    "3-pointers made": "fg3m",
    "3-pt made": "fg3m",
    "pts+rebs+asts": "pra",
    "pts+reb+ast": "pra",
    "stocks": "stocks",
    "goals": "goals",
    "shots": "shots",
    "hits": "hits",
    "total bases": "total_bases",
    "home runs": "home_runs",
    "rbi": "rbi",
}


def _matchup_edge_paths(sport: str, repo: Path) -> list[Path]:
    sk = str(sport or "").strip().lower()
    name = f"{sk}_matchup_edge.json"
    return [
        repo / "ui_runner" / "templates" / name,
        repo / "Sports" / sk.upper() / "data" / name,
        repo / "mobile" / "www" / "data" / name,
    ]


@lru_cache(maxsize=32)
def _load_rank_lookup(sport: str, mtime_key: float) -> dict[tuple[str, str], dict[str, Any]]:
    del mtime_key
    sk = str(sport or "").strip().lower()
    path = next((p for p in _matchup_edge_paths(sk, _REPO) if p.is_file()), None)
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    blocks = payload.get("players_by_team_cat") or {}
    if not isinstance(blocks, dict):
        return out
    for key, block in blocks.items():
        if not isinstance(block, dict):
            continue
        cid = str(block.get("category") or (str(key).split("|")[-1] if "|" in str(key) else "")).lower()
        opp = block.get("opponent") if isinstance(block.get("opponent"), dict) else {}
        for p in block.get("players") or []:
            if not isinstance(p, dict):
                continue
            pn = norm_player_name(p.get("player_norm") or p.get("player"))
            if not pn or not cid:
                continue
            out[(pn, cid)] = {
                "league_rank": p.get("league_rank"),
                "league_n": p.get("league_n"),
                "rank_on_team": p.get("rank_on_team"),
                "category_rank_label": p.get("category_rank_label"),
                "stat_def_rank": opp.get("stat_def_rank") or p.get("opp_def_rank"),
                "stat_def_tier": opp.get("stat_def_tier") or "",
                "stat_def_category": opp.get("stat_def_category") or cid,
            }
    return out


def enrich_slate_rows_with_category_ranks(
    rows: list[dict[str, Any]],
    sport: str,
    *,
    repo: Path | None = None,
) -> list[dict[str, Any]]:
    root = repo or _REPO
    sk = str(sport or "").strip().lower()
    path = next((p for p in _matchup_edge_paths(sk, root) if p.is_file()), None)
    if path is None:
        return rows
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    # Cache key uses absolute path via sport+mtime; reload when JSON rebuilds.
    lookup = _load_rank_lookup(sk, mtime)
    if not lookup:
        return rows
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("league_rank") is not None and row.get("category_rank_label"):
            continue
        pn = norm_player_name(row.get("player") or row.get("player_name"))
        prop = row.get("prop") or row.get("prop_type") or row.get("prop_norm")
        cid = norm_prop(prop) or _PROP_TO_CAT.get(str(prop or "").strip().lower(), "")
        hit = lookup.get((pn, cid))
        if not hit:
            continue
        for k, v in hit.items():
            if v is None or v == "":
                continue
            if row.get(k) is None or row.get(k) == "":
                row[k] = v
    return rows
