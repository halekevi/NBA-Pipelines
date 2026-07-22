#!/usr/bin/env python3
"""
Discover realistic PrizePicks payout rates from ANY available board.

Flow:
  1) CDP-scrape whatever board is open (WNBA/NBA/MLB — any sport is fine)
  2) Build real Power slips across S/G/D mixes and Goblin line-distance bins
  3) Capture live Min Guarantee (power_min_x)
  4) Upsert into payout_ladder_live_cdp.json (feeds /payout/ladder)

Optional --mix-only / --delta-only still compare against historical ladder recipes.

Usage:
  # Gentle path (HTTP prefetch + slow CDP clicks — less bot detection):
  py -3.14 scripts/validate_payout_ladder.py --run --discover --prefetch-http --gentle --max-cases 20

  pwsh -File scripts/launch_prizepicks_chrome_cdp.ps1 -OpenBoard
  py -3.14 scripts/validate_payout_ladder.py --run --discover --max-cases 30

Outputs:
  data/reports/payout_ladder_validation_<date>_discover.json
  ui_runner/data/payout_ladder_validation_tickets.json
  ui_runner/data/payout_ladder_live_cdp.json  (merged)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime, timezone
from itertools import combinations, combinations_with_replacement
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "ui_runner"))

import collect_payout_data as cpd  # noqa: E402

LADDER_LOG = ROOT / "ui_runner" / "data" / "payout_ladder_log.csv"
LADDER_LIVE = ROOT / "ui_runner" / "data" / "payout_ladder_live_cdp.json"
LIVE_TICKETS_PATH = ROOT / "ui_runner" / "data" / "payout_ladder_validation_tickets.json"
REPORTS_DIR = ROOT / "data" / "reports"

# Preferred clickable props for discovery (more reliable on PP board tabs).
_SIMPLE_PROPS = {
    "points",
    "assists",
    "rebounds",
    "strikeouts",
    "hits",
    "total bases",
    "pitcher strikeouts",
    "hits+runs+rbis",
    "hits-runs-rbis",
    "hits runs rbis",
    "earned runs allowed",
    "hits allowed",
    "walks allowed",
    "pitching outs",
}

# Fantasy / abbreviated props often fail CDP tab switch + lookup during discover.
_DISCOVER_BLOCKED_PROPS = {
    "hitter fs",
    "hitter fantasy score",
    "pitcher fs",
    "pitcher fantasy score",
    "fantasy score",
    "fantasy pts",
    "fantasy points",
}

# PrizePicks sometimes shows "Starting" / TBA placeholders before names resolve.
_DISCOVER_BLOCKED_PLAYERS = {
    "starting",
    "starter",
    "tba",
    "tbd",
    "player",
    "n/a",
    "na",
    "unknown",
}


def _usable_board_player(name: object) -> bool:
    raw = str(name or "").strip()
    if len(raw) < 3:
        return False
    key = cpd._norm(raw)
    if not key or key in _DISCOVER_BLOCKED_PLAYERS:
        return False
    # Reject pure placeholders / role labels (not real athlete names).
    if key in ("starting pitcher", "starting batting", "pitcher", "hitter"):
        return False
    return True

# S/G mixes to cover (n_standard, n_goblin). n_legs = sum, min 2.
_DISCOVER_COMPOSITIONS: list[tuple[int, int]] = [
    (0, 2),
    (0, 3),
    (0, 4),
    (0, 5),
    (0, 6),
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
    (1, 5),
    (2, 0),
    (2, 1),
    (2, 2),
    (2, 3),
    (2, 4),
    (3, 0),
    (3, 1),
    (3, 2),
    (3, 3),
    (4, 0),
    (4, 1),
    (4, 2),
    (5, 0),
    (5, 1),
    (6, 0),
]



def _round_delta(dist: float | None) -> float | None:
    if dist is None:
        return None
    try:
        d = float(dist)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    # PrizePicks distances are usually half-point steps.
    return round(d * 2) / 2



def _norm_delta_sig(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    vals: list[float] = []
    for part in text.replace("|", ",").replace("+", ",").split(","):
        part = part.strip()
        if not part or part in {"—", "-"}:
            continue
        try:
            vals.append(float(part))
        except (TypeError, ValueError):
            continue
    if not vals:
        return ""
    vals.sort()
    return "+".join(f"{v:g}" for v in vals)


def _parse_sgd(comp: str) -> tuple[int, int, int]:
    s = g = d = 0
    for part in str(comp or "").split("+"):
        part = part.strip().upper()
        if not part:
            continue
        try:
            if part.endswith("S"):
                s = int(part[:-1] or 0)
            elif part.endswith("G"):
                g = int(part[:-1] or 0)
            elif part.endswith("D"):
                d = int(part[:-1] or 0)
        except ValueError:
            continue
    return s, g, d


def load_pools_from_step1_csv(
    path: Path,
    *,
    sport: str = "WNBA",
) -> tuple[list[dict], list[dict], list[dict], dict[str, Any]]:
    """
    Build Standard / Goblin / Demon pools from a step1 CSV, with Goblin Δ =
    |goblin_line - standard_line| for the same (player, prop).
    """
    import csv as _csv

    path = Path(path)
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            if isinstance(row, dict):
                rows.append(row)

    std_map: dict[tuple[str, str], float] = {}
    for r in rows:
        pt = str(r.get("pick_type") or r.get("odds_type") or "").strip().lower()
        # Accept explicit Standard rows only.
        if "standard" not in pt and pt not in ("std",):
            continue
        try:
            line = float(r.get("line") or 0)
        except (TypeError, ValueError):
            continue
        key = (cpd._norm(r.get("player")), cpd._norm(r.get("prop_type") or r.get("prop")))
        if not key[0] or not key[1] or line < 0.5:
            continue
        prev = std_map.get(key)
        if prev is None or line > prev:
            std_map[key] = line

    standard: list[dict] = []
    goblins: list[dict] = []
    demons: list[dict] = []
    for r in rows:
        pt = str(r.get("pick_type") or r.get("odds_type") or "").strip().lower()
        try:
            line = float(r.get("line") or 0)
        except (TypeError, ValueError):
            continue
        player = str(r.get("player") or "").strip()
        prop = str(r.get("prop_type") or r.get("prop") or "").strip()
        if not player or not prop or line <= 0:
            continue
        key = (cpd._norm(player), cpd._norm(prop))
        std_line = std_map.get(key)
        card = {
            "player": player,
            "prop_type": prop,
            "line": line,
            "pick_type": (
                "goblin" if "goblin" in pt else ("demon" if "demon" in pt else "standard")
            ),
            "sport": sport,
            "league": sport,
            "standard_line": std_line,
            "line_distance": (
                abs(line - float(std_line)) if std_line is not None else None
            ),
            "source_filter": prop,
        }
        if "demon" in pt:
            if std_line is not None and line <= float(std_line):
                continue
            demons.append(card)
        elif "goblin" in pt:
            if std_line is not None and line >= float(std_line):
                continue
            # Prefer goblins that have a real Standard anchor.
            goblins.append(card)
        elif "standard" in pt or pt in ("std",):
            if line >= 1.0:
                standard.append(card)

    dist_counts = Counter(
        _round_delta(c.get("line_distance"))
        for c in goblins
        if _round_delta(c.get("line_distance")) is not None
    )
    meta = {
        "path": str(path),
        "n_rows": len(rows),
        "n_standard": len(standard),
        "n_goblin": len(goblins),
        "n_goblin_with_delta": sum(1 for c in goblins if c.get("line_distance")),
        "n_demon": len(demons),
        "std_keys": len(std_map),
        "goblin_delta_bins": {f"{k:g}": v for k, v in sorted(dist_counts.items())},
    }
    print(
        f"[discover] step1 {path.name}: S={len(standard)} G={len(goblins)} "
        f"(withΔ={meta['n_goblin_with_delta']}) D={len(demons)} "
        f"Δbins={meta['goblin_delta_bins']}"
    )
    return standard, goblins, demons, meta


def _prop_key_aliases(prop: str) -> list[str]:
    """Normalize common PP prop label variants for step1↔board matching."""
    n = cpd._norm(prop)
    aliases = [n]
    # Hits+Runs+RBIs <-> Hits-Runs-RBIs <-> HRR
    compact = (
        n.replace("runs", "r")
        .replace("rbis", "rbi")
        .replace("plus", "")
        .replace("-", "")
        .replace("+", "")
        .replace(" ", "")
    )
    if "hits" in n and ("rbi" in n or "runs" in n or "rbi" in compact):
        aliases.extend(
            [
                cpd._norm("Hits+Runs+RBIs"),
                cpd._norm("Hits-Runs-RBIs"),
                cpd._norm("Hits Runs RBIs"),
            ]
        )
    return list(dict.fromkeys(a for a in aliases if a))


def enrich_pools_with_std_map(
    standard: list[dict],
    goblins: list[dict],
    demons: list[dict],
    std_map: dict[tuple[str, str], float],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Attach standard_line / line_distance onto board pools from an external std map."""
    if not std_map:
        return standard, goblins, demons

    def _lookup_std(player: str, prop: str) -> float | None:
        pnorm = cpd._norm(player)
        for prop_alias in _prop_key_aliases(prop):
            hit = std_map.get((pnorm, prop_alias))
            if hit is not None:
                return float(hit)
        return None

    def _enrich(cards: list[dict], *, role: str) -> list[dict]:
        out: list[dict] = []
        for c in cards:
            c2 = dict(c)
            std_line = _lookup_std(str(c2.get("player") or ""), str(c2.get("prop_type") or ""))
            if std_line is None:
                out.append(c2)
                continue
            try:
                line_val = float(c2.get("line") or 0)
            except (TypeError, ValueError):
                out.append(c2)
                continue
            c2["standard_line"] = float(std_line)
            c2["line_distance"] = abs(line_val - float(std_line))
            if role == "goblin" and line_val >= float(std_line):
                continue
            if role == "demon" and line_val <= float(std_line):
                continue
            out.append(c2)
        return out

    # Also fold any missing standards from the map as synthetic cards? Skip — CDP must click.
    return (
        _enrich(standard, role="standard"),
        _enrich(goblins, role="goblin"),
        _enrich(demons, role="demon"),
    )


def _live_covered_recipe_keys() -> set[str]:
    """Composition|goblin_delta_sig keys already present in live CDP with a real floor."""
    if not LADDER_LIVE.is_file():
        return set()
    try:
        payload = json.loads(LADDER_LIVE.read_text(encoding="utf-8"))
    except Exception:
        return set()
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    covered: set[str] = set()
    if not isinstance(rows, list):
        return covered
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("source") or "").lower() not in ("", "live_cdp"):
            continue
        try:
            px = float(r.get("power_payout_x") or 0)
        except (TypeError, ValueError):
            continue
        if not (px > 0):
            continue
        comp = str(r.get("leg_composition") or "").strip()
        raw = r.get("goblin_deltas")
        if isinstance(raw, list):
            if raw and all(isinstance(x, str) and len(x) <= 1 for x in raw):
                raw = "".join(raw)
            elif all(isinstance(x, (int, float)) for x in raw):
                raw = "+".join(f"{float(x):g}" for x in raw)
            else:
                raw = ",".join(str(x) for x in raw)
        g_sig = _norm_delta_sig(str(raw or ""))
        if not g_sig and ("+0G+" in comp or comp.endswith("0G+0D") or "G" not in comp):
            g_sig = ""
        covered.add(f"{comp}|{g_sig}")
    return covered


def build_discovery_recipes_from_board(
    *,
    standard: list[dict],
    goblins: list[dict],
    demons: list[dict],
    max_cases: int = 80,
    exhaustive: bool = True,
    prefer_missing_live: bool = True,
) -> list[dict[str, Any]]:
    """
    Enumerate S/G mixes × Goblin-Δ signatures available on the board.

    exhaustive=True: all fillable (composition, Δ multiset) pairs, prioritized
    for coverage; truncated to max_cases.
    prefer_missing_live=True: recipes not yet in payout_ladder_live_cdp.json first.
    """

    def _ok_card(c: dict) -> bool:
        player = str(c.get("player") or "")
        if len(player) < 2:
            return False
        prop = str(c.get("prop_type") or "").strip().lower()
        if prop in _DISCOVER_BLOCKED_PROPS:
            return False
        return True

    def _prop_pref(c: dict) -> tuple:
        prop = str(c.get("prop_type") or "").lower()
        simple = 0 if prop in _SIMPLE_PROPS else 1
        dist = _card_distance(c) or 99.0
        return (simple, dist, str(c.get("player") or ""))

    g_pool = sorted([c for c in goblins if _ok_card(c)], key=_prop_pref)
    s_pool = sorted([c for c in standard if _ok_card(c)], key=_prop_pref)
    d_pool = sorted([c for c in demons if _ok_card(c)], key=_prop_pref)

    # Prefer goblins with a known Δ for exhaustive rate mapping.
    g_with = [c for c in g_pool if _round_delta(_card_distance(c)) is not None]
    g_use = g_with if g_with else g_pool

    by_delta: dict[float, list[dict]] = {}
    for c in g_use:
        rd = _round_delta(_card_distance(c))
        if rd is None:
            by_delta.setdefault(-1.0, []).append(c)
            continue
        by_delta.setdefault(rd, []).append(c)
    known_deltas = sorted(k for k in by_delta if k > 0)
    print(
        f"[discover] board bins G_deltas={known_deltas or '—'} "
        f"counts={{ {', '.join(f'{k:g}:{len(by_delta[k])}' for k in known_deltas[:20])} }} "
        f"S={len(s_pool)} G={len(g_use)} D={len(d_pool)}"
    )

    recipes: list[dict[str, Any]] = []

    def _add(n_s: int, n_g: int, n_d: int = 0, *, g_deltas: list[float] | None = None) -> None:
        n = n_s + n_g + n_d
        if n < 2 or n > 6:
            return
        if n_s > len(s_pool) or n_g > len(g_use) or n_d > len(d_pool):
            return
        if g_deltas:
            need = Counter(_round_delta(x) or x for x in g_deltas)
            for d, cnt in need.items():
                if d is None or len(by_delta.get(float(d), [])) < cnt:
                    return
        comp = f"{n_s}S+{n_g}G+{n_d}D"
        g_sig = _norm_delta_sig("+".join(f"{x:g}" for x in (g_deltas or [])))
        recipes.append(
            {
                "n_legs": n,
                "composition": comp,
                "n_standard": n_s,
                "n_goblin": n_g,
                "n_demon": n_d,
                "kind": "discover",
                "recipe_id": f"discover|{n}|{comp}|{g_sig}",
                "samples": 0,
                "ladder_min_x": 0.0,
                "ladder_max_x": 0.0,
                "ladder_avg_x": 0.0,
                "goblin_delta_sig": g_sig,
                "demon_delta_sig": "",
            }
        )

    # 1) Mix floors without forcing Δ (always useful baselines).
    for n_s, n_g in _DISCOVER_COMPOSITIONS:
        _add(n_s, n_g)
    if len(d_pool) >= 1 and len(g_use) >= 2:
        _add(0, 2, 1)
    if len(d_pool) >= 2 and len(g_use) >= 2:
        _add(0, 2, 2)

    # 2) Exhaustive Goblin-Δ coverage when bins exist.
    if known_deltas:
        # Uniform-Δ: all Goblin legs share one distance (clearest rate signal).
        for d in known_deltas:
            for n_s, n_g in _DISCOVER_COMPOSITIONS:
                if n_g <= 0:
                    continue
                if len(by_delta.get(d, [])) < n_g:
                    continue
                _add(n_s, n_g, g_deltas=[d] * n_g)

        # 2G: every unordered pair of bins (incl. same-same already covered).
        for a, b in combinations(known_deltas, 2):
            for n_s in (0, 1, 2, 3, 4):
                _add(n_s, 2, g_deltas=[a, b])

        if exhaustive:
            # 3G: combinations with replacement across bins (fillable only).
            for trio in combinations_with_replacement(known_deltas, 3):
                for n_s in (0, 1, 2, 3):
                    _add(n_s, 3, g_deltas=list(trio))
            # 4G: mixed quads from top bins.
            top = known_deltas[:10]
            for quad in combinations_with_replacement(top, 4):
                if len(set(quad)) == 1:
                    continue
                for n_s in (0, 1, 2):
                    _add(n_s, 4, g_deltas=list(quad))
            # 5G / 6G: uniform already covered; add mixed from top bins.
            for n_g in (5, 6):
                for combo in combinations_with_replacement(known_deltas[:6], n_g):
                    if len(set(combo)) == 1:
                        continue
                    _add(0, n_g, g_deltas=list(combo))
                    if n_g == 5:
                        _add(1, n_g, g_deltas=list(combo))

    covered = _live_covered_recipe_keys() if prefer_missing_live else set()
    if covered:
        print(f"[discover] already-live recipe keys={len(covered)} (prefer missing first)")

    # De-dupe; prefer missing-live, Δ-tagged, fewer legs, more standards.
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    recipes.sort(
        key=lambda r: (
            0
            if f"{r.get('composition')}|{r.get('goblin_delta_sig') or ''}" not in covered
            else 1,
            0 if r.get("goblin_delta_sig") else 1,
            0 if int(r.get("n_goblin") or 0) == 0 else 1,  # pure-S baselines early
            int(r.get("n_legs") or 99),
            -int(r.get("n_standard") or 0),
            str(r.get("goblin_delta_sig") or ""),
            str(r.get("composition") or ""),
        )
    )
    for r in recipes:
        key = f"{r['composition']}|{r.get('goblin_delta_sig') or ''}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    total = len(uniq)
    n_missing = sum(
        1
        for r in uniq
        if f"{r.get('composition')}|{r.get('goblin_delta_sig') or ''}" not in covered
    )
    if max_cases > 0 and len(uniq) > max_cases:
        missing = [
            r
            for r in uniq
            if f"{r.get('composition')}|{r.get('goblin_delta_sig') or ''}" not in covered
        ]
        already = [
            r
            for r in uniq
            if f"{r.get('composition')}|{r.get('goblin_delta_sig') or ''}" in covered
        ]
        # Round-robin missing first across primary Goblin Δ.
        by_bin: dict[float | str, list[dict[str, Any]]] = {}
        for r in missing:
            parts = [
                float(x)
                for x in str(r.get("goblin_delta_sig") or "").split("+")
                if x.strip()
            ]
            primary: float | str = parts[0] if parts else ("baseline" if not r.get("goblin_delta_sig") else "other")
            by_bin.setdefault(primary, []).append(r)
        ordered: list[dict[str, Any]] = []
        bins = sorted(by_bin.keys(), key=lambda x: (isinstance(x, str), x))
        idx = {b: 0 for b in bins}
        while len(ordered) < max_cases and any(idx[b] < len(by_bin[b]) for b in bins):
            progressed = False
            for b in bins:
                i = idx[b]
                if i < len(by_bin[b]):
                    ordered.append(by_bin[b][i])
                    idx[b] = i + 1
                    progressed = True
                    if len(ordered) >= max_cases:
                        break
            if not progressed:
                break
        if len(ordered) < max_cases:
            ordered.extend(already[: max_cases - len(ordered)])
        uniq = ordered[:max_cases]

    print(
        f"[discover] planned recipes={len(uniq)}/{total} "
        f"(exhaustive={exhaustive}, missing_live≈{n_missing}, "
        f"from board Δ bins + S/G mixes)"
    )
    return uniq


def _card_distance(card: dict) -> float | None:
    try:
        dist = float(card.get("line_distance") or 0.0)
        if dist > 0:
            return dist
    except (TypeError, ValueError):
        pass
    try:
        line = float(card.get("line"))
        std = float(card.get("standard_line") or card.get("std_line"))
        dist = abs(line - std)
        return dist if dist > 0 else None
    except (TypeError, ValueError):
        return None


def load_ladder_recipes(*, include_mix: bool = True, include_delta: bool = True) -> list[dict[str, Any]]:
    """Load unique recipes from ladder CSV + live CDP file."""
    rows: list[dict[str, Any]] = []
    if LADDER_LOG.is_file():
        with LADDER_LOG.open("r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if isinstance(row, dict):
                    rows.append(row)
    if LADDER_LIVE.is_file():
        try:
            live = json.loads(LADDER_LIVE.read_text(encoding="utf-8"))
            for row in live.get("rows") or []:
                if isinstance(row, dict):
                    rows.append(row)
        except (OSError, json.JSONDecodeError):
            pass

    # Aggregate expected ranges
    buckets: dict[tuple, list[float]] = {}
    meta: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        try:
            n = int(float(r.get("n_legs") or 0))
        except (TypeError, ValueError):
            continue
        comp = str(r.get("leg_composition") or "").strip()
        if n < 2 or not comp:
            continue
        try:
            px = float(r.get("power_payout_x") or 0)
        except (TypeError, ValueError):
            continue
        if not (px > 0):
            continue
        g_sig = _norm_delta_sig(r.get("goblin_deltas"))
        d_sig = _norm_delta_sig(r.get("demon_deltas"))
        s_c, g_c, d_c = _parse_sgd(comp)

        if include_mix:
            key_m = ("mix", n, comp, "", "")
            buckets.setdefault(key_m, []).append(px)
            meta[key_m] = {"n_legs": n, "composition": comp, "n_standard": s_c, "n_goblin": g_c, "n_demon": d_c}

        if include_delta and (g_c or d_c):
            if g_c and (not g_sig or len(g_sig.split("+")) != g_c):
                continue
            if d_c and (not d_sig or len(d_sig.split("+")) != d_c):
                continue
            key_d = ("delta", n, comp, g_sig, d_sig)
            buckets.setdefault(key_d, []).append(px)
            meta[key_d] = {
                "n_legs": n,
                "composition": comp,
                "n_standard": s_c,
                "n_goblin": g_c,
                "n_demon": d_c,
                "goblin_delta_sig": g_sig,
                "demon_delta_sig": d_sig,
            }

    recipes: list[dict[str, Any]] = []
    for key, vals in sorted(buckets.items(), key=lambda kv: kv[0]):
        kind, n, comp, g_sig, d_sig = key
        info = dict(meta[key])
        info.update(
            {
                "kind": kind,
                "recipe_id": f"{kind}|{n}|{comp}|{g_sig}|{d_sig}".rstrip("|"),
                "samples": len(vals),
                "ladder_min_x": round(min(vals), 4),
                "ladder_max_x": round(max(vals), 4),
                "ladder_avg_x": round(sum(vals) / len(vals), 4),
            }
        )
        recipes.append(info)
    return recipes


def _synthesize_goblin_leg(
    std_card: dict,
    want_delta: float,
    *,
    sport: str = "MLB",
) -> dict[str, Any] | None:
    """Build a Goblin leg at Standard−Δ so CDP can cycle the More control to that line."""
    if not _usable_board_player(std_card.get("player")):
        return None
    try:
        std = float(std_card.get("line") or std_card.get("standard_line") or 0)
        want = float(want_delta)
    except (TypeError, ValueError):
        return None
    if std < 1.0 or want < 0.25:
        return None
    # Goblin OVER is easier → lower line than Standard.
    want_line = round(std - want, 2)
    if want_line < 0.5:
        return None
    # Half-step lines only (PP board granularity).
    if abs(want_line * 2 - round(want_line * 2)) > 1e-6:
        want_line = round(want_line * 2) / 2.0
        if want_line < 0.5 or want_line >= std:
            return None
        want = round(std - want_line, 2)
    return {
        "player": std_card.get("player"),
        "prop_type": std_card.get("prop_type"),
        "direction": "OVER",
        "line": want_line,
        "pick_type": "Goblin",
        "sport": str(std_card.get("league") or std_card.get("sport") or sport).upper(),
        "line_distance": want,
        "standard_line": std,
        "role": "goblin",
        "has_alt_lines": True,
        "force_alt_cycle": True,
        "source_filter": std_card.get("source_filter") or std_card.get("prop_type"),
    }


def _pick_cards_for_recipe(
    recipe: dict[str, Any],
    *,
    standard: list[dict],
    goblins: list[dict],
    demons: list[dict],
    tol: float = 0.35,
    force_alt_cycle: bool = False,
) -> dict[str, Any] | None:
    """Choose unique-player board cards for a recipe. Prefer exact Goblin distances.

    force_alt_cycle=True: when the board lacks the target Δ, synthesize a Goblin leg
    from a Standard face (std−Δ) so capture can cycle the dual-arrow to that line.
    """
    n_s = int(recipe.get("n_standard") or 0)
    n_g = int(recipe.get("n_goblin") or 0)
    n_d = int(recipe.get("n_demon") or 0)
    target_g = []
    if recipe.get("goblin_delta_sig"):
        target_g = [float(x) for x in str(recipe["goblin_delta_sig"]).split("+") if x]
    target_d = []
    if recipe.get("demon_delta_sig"):
        target_d = [float(x) for x in str(recipe["demon_delta_sig"]).split("+") if x]

    used: set[str] = set()
    picked: list[dict] = []
    matched_deltas: list[float] = []
    proxy = False
    sport_hint = "MLB"

    def _prop_rank(c: dict) -> float:
        prop = str(c.get("prop_type") or "").lower()
        if prop in ("points", "assists", "rebounds", "hits+runs+rbis", "total bases", "tb", "pitcher strikeouts", "ks"):
            return 0.0
        if "+" in prop or "pts" in prop:
            return 2.0
        return 1.0

    def _std_alt_pool(want_delta: float | None = None) -> list[dict]:
        # Prefer Standards that already have a cataloged Goblin at the target Δ.
        catalog_keys: set[str] = set()
        if want_delta is not None:
            for g in goblins:
                if not g.get("cataloged_alt"):
                    continue
                dist = _card_distance(g)
                if dist is None or abs(float(dist) - float(want_delta)) > max(tol, 0.26):
                    continue
                catalog_keys.add(
                    f"{cpd._norm(g.get('player'))}|{cpd._norm(g.get('prop_type'))}"
                )
        pool = []
        for c in standard:
            if not _usable_board_player(c.get("player")):
                continue
            try:
                line = float(c.get("line") or 0)
            except (TypeError, ValueError):
                continue
            if line < 1.0:
                continue
            pool.append(c)
        pool.sort(
            key=lambda c: (
                0
                if (
                    f"{cpd._norm(c.get('player'))}|{cpd._norm(c.get('prop_type'))}"
                    in catalog_keys
                )
                else 1,
                0 if c.get("has_alt_lines") or c.get("cataloged_alt") else 1,
                -float(c.get("line") or 0),
                _prop_rank(c),
                str(c.get("player") or ""),
            )
        )
        return pool

    def take(pool: list[dict], n: int, role: str, targets: list[float] | None = None) -> bool:
        nonlocal proxy
        if n <= 0:
            return True
        remaining = list(pool)
        for i in range(n):
            want = targets[i] if targets and i < len(targets) else None
            best = None
            best_score = 1e9
            for c in remaining:
                if not _usable_board_player(c.get("player")):
                    continue
                pk = cpd._norm(c.get("player"))
                if not pk or pk in used:
                    continue
                dist = _card_distance(c)
                if want is not None:
                    if dist is None:
                        score = 100.0
                    else:
                        score = abs(float(dist) - float(want))
                        # Strongly prefer faces we already cycled to this Δ on-board.
                        if c.get("cataloged_alt") and score <= max(tol, 0.26):
                            score -= 5.0
                else:
                    # Prefer verified distances, then common board tabs (Points/Assists).
                    score = 0.0 if dist is not None else 5.0
                    prop = str(c.get("prop_type") or "").lower()
                    if "point" in prop:
                        score -= 0.5
                    elif "assist" in prop or "rebound" in prop:
                        score -= 0.2
                    src = str(c.get("source_filter") or "").lower()
                    if src in ("points", "assists", "rebounds", "popular"):
                        score -= 0.3
                    if c.get("cataloged_alt"):
                        score -= 1.0
                score += _prop_rank(c)
                if score < best_score:
                    best_score = score
                    best = c

            # Force-cycle path: synthesize Goblin @ std−Δ only from named Standards,
            # preferring faces that already showed this Δ in the alt-line catalog.
            if (
                role == "goblin"
                and force_alt_cycle
                and want is not None
                and (best is None or best_score > tol)
            ):
                synth = None
                for sc in _std_alt_pool(float(want)):
                    pk = cpd._norm(sc.get("player"))
                    if not pk or pk in used:
                        continue
                    synth = _synthesize_goblin_leg(sc, float(want), sport=sport_hint)
                    if synth is not None:
                        used.add(pk)
                        picked.append(synth)
                        matched_deltas.append(float(synth["line_distance"]))
                        proxy = True
                        break
                if synth is not None:
                    continue
            if best is None:
                return False
            if want is not None and best_score > tol:
                # Still force-cycle even when a weak goblin face exists.
                if role == "goblin" and force_alt_cycle:
                    synth = None
                    for sc in _std_alt_pool(float(want)):
                        pk = cpd._norm(sc.get("player"))
                        if not pk or pk in used:
                            continue
                        synth = _synthesize_goblin_leg(sc, float(want), sport=sport_hint)
                        if synth is not None:
                            used.add(pk)
                            picked.append(synth)
                            matched_deltas.append(float(synth["line_distance"]))
                            proxy = True
                            break
                    if synth is not None:
                        continue
                proxy = True
            used.add(cpd._norm(best.get("player")))
            remaining = [c for c in remaining if c is not best]
            dist = _card_distance(best)
            leg = {
                "player": best.get("player"),
                "prop_type": best.get("prop_type"),
                "direction": "OVER",
                "line": best.get("line"),
                "pick_type": "Goblin" if role == "goblin" else ("Demon" if role == "demon" else "Standard"),
                "sport": str(best.get("league") or best.get("sport") or "WNBA").upper(),
                "line_distance": dist,
                "standard_line": best.get("standard_line"),
                "role": role,
                "force_alt_cycle": bool(best.get("cataloged_alt") and role == "goblin"),
            }
            picked.append(leg)
            if role == "goblin" and dist is not None:
                matched_deltas.append(float(dist))
        return True

    # Prefer goblins/demons first so standards don't steal players.
    if not take(goblins, n_g, "goblin", target_g or None):
        return None
    if not take(demons, n_d, "demon", target_d or None):
        return None
    if not take(standard, n_s, "standard", None):
        return None

    return {
        "legs": picked,
        "matched_goblin_deltas": matched_deltas,
        "proxy_match": proxy,
    }


def build_force_delta_recipes(
    *,
    max_cases: int = 60,
    available_deltas: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Enumerate missing S/G×Δ cells using Δ bins actually reachable on this board."""
    priority_mixes: list[tuple[int, int]] = [
        (1, 1),
        (0, 2),
        (0, 3),
        (2, 1),
        (1, 2),
        (0, 4),
        (1, 3),
        (2, 2),
        (3, 1),
        (0, 5),
        (1, 4),
        (2, 3),
        (3, 2),
        (4, 1),
        (0, 6),
    ]
    if available_deltas:
        common_deltas = sorted(
            {
                round(float(d), 2)
                for d in available_deltas
                if 0.25 <= float(d) <= 6.5
            }
        )
    else:
        common_deltas = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    if not common_deltas:
        common_deltas = [1.0, 1.5, 2.0]
    print(f"[force-delta] using board-reachable Δ bins={common_deltas}")
    covered = _live_covered_recipe_keys()

    recipes: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(n_s: int, n_g: int, g_deltas: list[float]) -> None:
        n = n_s + n_g
        if n < 2 or n > 6:
            return
        if n_g and len(g_deltas) != n_g:
            return
        comp = f"{n_s}S+{n_g}G+0D"
        g_sig = _norm_delta_sig("+".join(f"{x:g}" for x in g_deltas)) if g_deltas else ""
        key = f"{comp}|{g_sig}"
        if key in seen:
            return
        seen.add(key)
        recipes.append(
            {
                "kind": "force_delta",
                "n_legs": n,
                "composition": comp,
                "n_standard": n_s,
                "n_goblin": n_g,
                "n_demon": 0,
                "goblin_delta_sig": g_sig,
                "demon_delta_sig": "",
                "ladder_avg_x": 0.0,
                "ladder_min_x": 0.0,
                "ladder_max_x": 0.0,
                "samples": 0,
                "force_alt_cycle": True,
                "already_live": key in covered,
            }
        )

    for n_s, n_g in priority_mixes:
        if n_g == 0:
            _add(n_s, 0, [])
            continue
        for d in common_deltas:
            _add(n_s, n_g, [d] * n_g)

    for n_s, n_g in ((0, 2), (1, 2), (0, 3), (1, 3), (2, 2)):
        for i, a in enumerate(common_deltas):
            for b in common_deltas[i + 1 :]:
                if n_g == 2:
                    _add(n_s, 2, [a, b])
                elif n_g == 3:
                    _add(n_s, 3, [a, a, b])
                    _add(n_s, 3, [a, b, b])

    recipes.sort(
        key=lambda r: (
            1 if r.get("already_live") else 0,
            {
                "1S+1G+0D": 0,
                "0S+2G+0D": 1,
                "0S+3G+0D": 2,
                "2S+1G+0D": 3,
                "1S+2G+0D": 4,
                "0S+4G+0D": 5,
                "1S+3G+0D": 6,
                "2S+2G+0D": 7,
                "3S+1G+0D": 8,
            }.get(str(r.get("composition") or ""), 20),
            float(
                sum(float(x) for x in str(r.get("goblin_delta_sig") or "").split("+") if x) or 0
            ),
            str(r.get("goblin_delta_sig") or ""),
        )
    )
    out = recipes[: max(1, int(max_cases))]
    n_missing = sum(1 for r in out if not r.get("already_live"))
    print(
        f"[force-delta] planned recipes={len(out)}/{len(recipes)} "
        f"(missing_live≈{n_missing}; from cataloged board Δ steps)"
    )
    return out


def build_live_board_tickets_payload(
    recipes: list[dict[str, Any]],
    *,
    standard: list[dict],
    goblins: list[dict],
    demons: list[dict],
    date_str: str,
    max_cases: int = 0,
    delta_tol: float = 0.35,
    force_alt_cycle: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build tickets payload from LIVE board cards matching each ladder recipe."""
    tickets: list[dict] = []
    plan_rows: list[dict[str, Any]] = []
    for i, recipe in enumerate(recipes, 1):
        if max_cases > 0 and len(tickets) >= max_cases:
            break
        # Rotate pools so one stale card does not poison every recipe.
        g_off = (i - 1) % len(goblins) if goblins else 0
        d_off = (i - 1) % len(demons) if demons else 0
        s_off = (i - 1) % len(standard) if standard else 0
        g_pool = goblins[g_off:] + goblins[:g_off] if goblins else []
        d_pool = demons[d_off:] + demons[:d_off] if demons else []
        s_pool = standard[s_off:] + standard[:s_off] if standard else []
        force = bool(force_alt_cycle) or bool(recipe.get("force_alt_cycle"))
        pick = _pick_cards_for_recipe(
            recipe,
            standard=s_pool,
            goblins=g_pool,
            demons=d_pool,
            tol=float(delta_tol),
            force_alt_cycle=force,
        )
        if not pick:
            plan_rows.append({**recipe, "status": "unbuildable", "error": "no_matching_board_cards"})
            continue
        tid = f"{date_str}|LADDER_VAL|{recipe.get('kind')}|{i}"
        ticket = {
            "ticket_id": tid,
            "strong_builder": True,
            "n_legs": int(recipe["n_legs"]),
            "legs": pick["legs"],
            "ladder_recipe": {
                "kind": recipe.get("kind"),
                "composition": recipe.get("composition"),
                "goblin_delta_sig": recipe.get("goblin_delta_sig", ""),
                "demon_delta_sig": recipe.get("demon_delta_sig", ""),
                "ladder_avg_x": recipe.get("ladder_avg_x"),
                "ladder_min_x": recipe.get("ladder_min_x"),
                "ladder_max_x": recipe.get("ladder_max_x"),
                "samples": recipe.get("samples"),
                "proxy_match": pick["proxy_match"],
                "matched_goblin_deltas": pick["matched_goblin_deltas"],
                "force_alt_cycle": force,
            },
        }
        tickets.append(ticket)
        plan_rows.append(
            {
                **recipe,
                "status": "planned",
                "ticket_id": tid,
                "proxy_match": pick["proxy_match"],
                "matched_goblin_deltas": pick["matched_goblin_deltas"],
                "legs": [
                    {
                        "player": lg.get("player"),
                        "prop": lg.get("prop_type"),
                        "line": lg.get("line"),
                        "pick_type": lg.get("pick_type"),
                        "line_distance": lg.get("line_distance"),
                        "force_alt_cycle": lg.get("force_alt_cycle"),
                    }
                    for lg in pick["legs"]
                ],
            }
        )

    payload = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "purpose": "payout_ladder_live_board_validation",
        "groups": [
            {
                "name": "LADDER VALIDATION",
                "group_name": "LADDER VALIDATION",
                "tickets": tickets,
            }
        ],
    }
    return payload, plan_rows


def _verdict(live_x: float, recipe: dict[str, Any], *, rel_tol: float = 0.15, abs_tol: float = 0.5) -> str:
    lo = float(recipe.get("ladder_min_x") or 0)
    hi = float(recipe.get("ladder_max_x") or 0)
    avg = float(recipe.get("ladder_avg_x") or 0)
    if lo > 0 and hi > 0 and lo <= live_x <= hi:
        return "in_range"
    if avg > 0 and (abs(live_x - avg) <= abs_tol or abs(live_x - avg) / avg <= rel_tol):
        return "near_avg"
    return "mismatch"


def compare_capture_to_recipes(
    captured: list[dict],
    plan_rows: list[dict],
) -> list[dict[str, Any]]:
    by_tid = {str(c.get("ticket_id") or ""): c for c in captured if isinstance(c, dict)}
    out: list[dict[str, Any]] = []
    for plan in plan_rows:
        tid = str(plan.get("ticket_id") or "")
        row = dict(plan)
        cap = by_tid.get(tid)
        if not cap:
            if row.get("status") == "unbuildable":
                row["verdict"] = "skipped"
            else:
                row["verdict"] = "missing_capture"
            out.append(row)
            continue
        row["capture_status"] = cap.get("status")
        try:
            live_x = float(cap.get("power_min_x") or cap.get("min_x") or 0)
        except (TypeError, ValueError):
            live_x = 0.0
        row["live_power_min_x"] = live_x if live_x > 0 else None
        row["live_power_first_x"] = cap.get("power_first_x")
        if live_x > 0 and str(cap.get("status") or "").lower() in ("ok", "partial"):
            row["verdict"] = _verdict(live_x, plan)
            avg = float(plan.get("ladder_avg_x") or 0)
            row["delta_vs_ladder_avg"] = round(live_x - avg, 4) if avg else None
        else:
            row["verdict"] = "capture_failed"
            row["error"] = cap.get("error")
        out.append(row)
    return out


def scrape_board_pools(
    cdp_url: str,
    *,
    light: bool = False,
    focused: bool = False,
    prefer_wnba: bool = False,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Open PP boards and return (standard, goblin, demon) card pools with distances.

    light=True: only Popular/Points once (no multi-filter expand) — gentler on DataDome.
    focused=True: a few high-yield filters only (discover) — clickable faces + Goblin Δ harvest.
    prefer_wnba=True: try WNBA Points first (wider Δ ladders for force-delta sweeps).
    """
    p, browser, context, page = cpd.connect_existing_browser(cdp_url)
    try:
        best_cards: list[dict] = []
        best_score = -1
        # WNBA Points has the widest Goblin-Δ steps; MLB next for live volume.
        league_order = (
            ((3, "WNBA"), (2, "MLB"), (7, "NBA"))
            if prefer_wnba
            else ((2, "MLB"), (3, "WNBA"), (7, "NBA"))
        )
        for league_id, label in league_order:
            try:
                url = f"https://app.prizepicks.com/board?league_id={league_id}"
                print(f"[validate] navigate {label} -> {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(3500 if light else 2500)
            except Exception as e:
                print(f"[validate] navigate {label} skipped: {e}")
                continue
            frame = cpd.find_prizepicks_frame(page)
            cpd.ensure_popular_filter(frame, page)
            cpd.dismiss_modal(frame, page)
            if light:
                # Single filter pass — avoid hammering every stat tab (bot-trigger).
                try:
                    loc = frame.get_by_text("Points", exact=True).first
                    if loc.count() == 0:
                        loc = frame.get_by_text("Hits", exact=True).first
                    if loc.count() == 0:
                        loc = frame.get_by_text("Popular", exact=True).first
                    loc.click(force=True, timeout=4000)
                    frame.wait_for_timeout(1200)
                except Exception:
                    pass
                cpd._scroll_board_for_lazy_load(page)
                cards = cpd.get_all_cards(frame)
                print(f"[validate] {label} light-scrape cards={len(cards)}")
            elif focused:
                # Discover: stay on props that stay searchable (avoid Fantasy Score sprawl).
                focus_filters = (
                    [
                        "Popular",
                        "Hits",
                        "Hits+Runs+RBIs",
                        "Total Bases",
                        "Pitcher Strikeouts",
                    ]
                    if label == "MLB"
                    else [
                        "Popular",
                        "Points",
                        "Assists",
                        "Rebounds",
                        "Pts+Reb+Ast",
                        "3-PT Made",
                    ]
                )
                cards = []
                seen: set[str] = set()
                for filter_name in focus_filters:
                    try:
                        cpd.dismiss_modal(frame, page)
                        loc = frame.get_by_text(filter_name, exact=True).first
                        if loc.count() == 0:
                            loc = frame.get_by_text(filter_name, exact=False).first
                        loc.click(force=True, timeout=4000)
                        frame.wait_for_timeout(1000)
                        cpd._scroll_board_for_lazy_load(page)
                        batch = cpd.get_all_cards(frame)
                        added = 0
                        for c in batch:
                            key = (
                                f"{cpd._norm(c.get('player'))}|"
                                f"{cpd._norm(c.get('prop_type'))}|"
                                f"{c.get('line')}|"
                                f"{str(c.get('pick_type') or '').lower()}"
                            )
                            if key in seen:
                                continue
                            seen.add(key)
                            c2 = dict(c)
                            c2["source_filter"] = filter_name
                            cards.append(c2)
                            added += 1
                        print(f"[validate] {label} focus {filter_name}: +{added} (pool={len(cards)})")
                    except Exception as e:
                        print(f"[validate] {label} focus {filter_name} skipped: {e}")
                print(f"[validate] {label} focused-scrape cards={len(cards)}")
            else:
                cards = cpd.expand_card_pool(frame, page)
            n_g = sum(1 for c in cards if str(c.get("pick_type") or "").lower() == "goblin")
            n_s = sum(1 for c in cards if str(c.get("pick_type") or "").lower() == "standard")
            n_d = sum(1 for c in cards if str(c.get("pick_type") or "").lower() == "demon")
            print(f"[validate] {label} cards={len(cards)} S={n_s} G={n_g} D={n_d}")
            score = min(n_g, 4) * 10 + min(n_s, 4) * 3 + min(n_d, 2) * 5
            if score > best_score and len(cards) >= 4:
                best_score = score
                stamped = []
                for c in cards:
                    c2 = dict(c)
                    c2["league"] = label
                    c2["sport"] = label
                    stamped.append(c2)
                best_cards = stamped
            if n_g >= 3 and n_s >= 2:
                break
            # Light mode: accept one league only when it actually has Goblins to click.
            if light and best_cards and n_g >= 1:
                break
            if focused and best_cards and (n_g >= 2 or n_s >= 4):
                break

        board_std = cpd._build_std_map_from_board_cards(best_cards)
        standard: list[dict] = []
        goblins: list[dict] = []
        demons: list[dict] = []
        n_placeholder = 0
        for c in best_cards:
            if not _usable_board_player(c.get("player")):
                n_placeholder += 1
                continue
            try:
                line_val = float(c.get("line") or 0)
            except (TypeError, ValueError):
                continue
            pt = str(c.get("pick_type") or "").lower()
            key = (cpd._norm(c.get("player")), cpd._norm(c.get("prop_type")))
            std_line = board_std.get(key)
            c2 = dict(c)
            if std_line is not None:
                c2["standard_line"] = std_line
                c2["line_distance"] = abs(line_val - float(std_line))
            if "demon" in pt:
                if std_line is not None and line_val <= float(std_line):
                    continue
                demons.append(c2)
            elif "goblin" in pt:
                if std_line is not None and line_val >= float(std_line):
                    continue
                goblins.append(c2)
            else:
                # MLB Hits standards are often 0.5; keep them so Goblin Δ can be computed.
                if line_val >= 0.5:
                    standard.append(c2)
        goblins.sort(key=lambda c: (0 if c.get("line_distance") is not None else 1, str(c.get("player") or "")))
        demons.sort(key=lambda c: (0 if c.get("line_distance") is not None else 1, str(c.get("player") or "")))
        if n_placeholder:
            print(
                f"[validate] dropped {n_placeholder} placeholder/Starting cards "
                f"(kept S={len(standard)} G={len(goblins)} D={len(demons)})"
            )

        # Catalog reachable Goblin Δ by cycling More — but bail fast on placeholder-heavy boards.
        # Full walks re-parse ~200 cards every swap and can hang for 20+ minutes.
        try:
            usable_frac = 0.0
            if best_cards:
                usable_frac = 1.0 - (n_placeholder / max(1, len(best_cards)))
            probe_pool = sorted(
                [
                    c
                    for c in standard
                    if _usable_board_player(c.get("player"))
                    and float(c.get("line") or 0) >= 1.5
                    and str(c.get("prop_type") or "").lower()
                    in (
                        "points",
                        "assists",
                        "rebounds",
                        "hits",
                        "hits+runs+rbis",
                        "total bases",
                        "tb",
                        "pitcher strikeouts",
                        "ks",
                        "3-pt made",
                    )
                ],
                key=lambda c: -float(c.get("line") or 0),
            )[:8]
            skip_catalog = usable_frac < 0.35 or len(probe_pool) < 2
            if skip_catalog:
                print(
                    f"[validate] skipping alt-line Δ catalog "
                    f"(usable_frac={usable_frac:.2f} probe_std={len(probe_pool)}; "
                    f"will use board/step1 paired Δ)"
                )
            else:
                frame = cpd.find_prizepicks_frame(page)
                cpd.dismiss_modal(frame, page)
                cataloged = 0

                def _switch_prop_tab(tab_name: str) -> None:
                    try:
                        cpd.dismiss_modal(frame, page)
                        loc = frame.get_by_text(tab_name, exact=True).first
                        if loc.count() == 0:
                            loc = frame.get_by_text(tab_name, exact=False).first
                        loc.click(force=True, timeout=4000)
                        frame.wait_for_timeout(900)
                    except Exception as e:
                        print(f"[validate] catalog tab '{tab_name}' skip: {e}")

                # Board is often left on 3PTM/Assists after focused scrape — switch to Points
                # (or the probe prop tab) so More rebind does not latch onto the wrong face.
                _switch_prop_tab("Points")
                for cand in probe_pool[:8]:
                    player = str(cand.get("player") or "")
                    prop = str(cand.get("prop_type") or "")
                    if not _usable_board_player(player):
                        continue
                    try:
                        std_line = float(cand.get("line") or cand.get("standard_line") or 0)
                    except (TypeError, ValueError):
                        continue
                    if std_line < 1.5 or not player or not prop:
                        continue
                    prop_l = prop.lower().strip()
                    tab = (
                        "Points"
                        if prop_l == "points"
                        else (
                            "Assists"
                            if prop_l == "assists"
                            else (
                                "Rebounds"
                                if prop_l == "rebounds"
                                else str(cand.get("source_filter") or "Points")
                            )
                        )
                    )
                    _switch_prop_tab(tab)
                    print(f"[validate] catalog probe: {player} {prop} std={std_line:g} tab={tab}")
                    btn, bound = cpd._rebind_more_btn(frame, player, prop)
                    if btn is None:
                        print(f"[validate] catalog miss (no More): {player} {prop}")
                        continue
                    bound_prop = str((bound or {}).get("prop_type") or "").lower()
                    if bound_prop and prop_l not in bound_prop and bound_prop not in prop_l:
                        print(
                            f"[validate] catalog miss (wrong prop bind): "
                            f"want={prop} got={bound.get('prop_type')}"
                        )
                        continue
                    cycled = cpd.cycle_card_to_pick_type(
                        frame,
                        btn,
                        player=player,
                        prop=prop,
                        want_pick="goblin",
                        want_line=None,
                        require_line=False,
                        max_clicks=8,
                    )
                    if not cycled:
                        continue
                    try:
                        g_line = float(cycled.get("line") or 0)
                    except (TypeError, ValueError):
                        continue
                    if g_line <= 0 or g_line >= std_line:
                        try:
                            btn2, _ = cpd._rebind_more_btn(frame, player, prop)
                            if btn2 is not None:
                                cpd.cycle_card_to_pick_type(
                                    frame,
                                    btn2,
                                    player=player,
                                    prop=prop,
                                    want_pick="standard",
                                    want_line=std_line,
                                    require_line=False,
                                    max_clicks=4,
                                )
                        except Exception:
                            pass
                        continue
                    delta = round(abs(std_line - g_line) * 2) / 2.0
                    # Reject impossible deltas from wrong-face binds (e.g. Points 24 → 0.5).
                    if delta > 6.5 or g_line < max(0.5, std_line - 6.5):
                        print(
                            f"[validate] catalog reject implausible Δ={delta:g} "
                            f"({std_line:g}->{g_line:g}) for {player} {prop}"
                        )
                        continue
                    if 0.25 <= delta <= 6.5:
                        goblins.append(
                            {
                                **cand,
                                "line": g_line,
                                "pick_type": "goblin",
                                "standard_line": std_line,
                                "line_distance": delta,
                                "has_alt_lines": True,
                                "cataloged_alt": True,
                                "league": cand.get("league") or cand.get("sport"),
                                "sport": cand.get("sport") or cand.get("league"),
                                "source_filter": cand.get("source_filter") or prop,
                            }
                        )
                        cataloged += 1
                        print(f"[validate] cataloged Δ={delta:g} via {player} {prop} {std_line:g}->{g_line:g}")
                    try:
                        btn3, _ = cpd._rebind_more_btn(frame, player, prop)
                        if btn3 is not None:
                            cpd.cycle_card_to_pick_type(
                                frame,
                                btn3,
                                player=player,
                                prop=prop,
                                want_pick="standard",
                                want_line=std_line,
                                require_line=False,
                                max_clicks=3,
                            )
                    except Exception:
                        pass
                    page.wait_for_timeout(250)
                # Deduplicate catalog goblins by player|prop|line.
                uniq: dict[str, dict] = {}
                for g in goblins:
                    key = (
                        f"{cpd._norm(g.get('player'))}|"
                        f"{cpd._norm(g.get('prop_type'))}|"
                        f"{g.get('line')}|"
                        f"{str(g.get('pick_type') or '').lower()}"
                    )
                    prev = uniq.get(key)
                    if prev is None or (g.get("line_distance") and not prev.get("line_distance")):
                        uniq[key] = g
                goblins = list(uniq.values())
                goblins.sort(
                    key=lambda c: (
                        0 if c.get("line_distance") is not None else 1,
                        float(c.get("line_distance") or 99),
                        str(c.get("player") or ""),
                    )
                )
                delta_bins = sorted(
                    {
                        round(float(c["line_distance"]), 2)
                        for c in goblins
                        if c.get("line_distance") and 0.25 <= float(c["line_distance"]) <= 6.5
                    }
                )
                print(
                    f"[validate] alt-line Δ catalog: +{cataloged} faces "
                    f"total_G={len(goblins)} bins={delta_bins[:16]}"
                )
        except Exception as e:
            print(f"[validate] WARN: alt-line Δ catalog failed: {e}")

        print(f"[validate] pools standard={len(standard)} goblin={len(goblins)} demon={len(demons)}")
        return standard, goblins, demons
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass



def prefetch_step1_http(
    *,
    date_str: str,
    output_path: Path,
    league: str = "WNBA",
    cdp_url: str = "",
) -> Path:
    """
    Prefetch board inventory without CDP click-storm:
      1) curl_cffi chrome131 + warmup + rotating TLS-matched headers
      2) on persistent 403 → step1 via logged-in Chrome CDP (API cookies, not UI expand)
      3) if both fail but a non-empty on-disk CSV exists → reuse it
    """
    import os
    import subprocess

    os.environ.setdefault("PROPORACLE_CURL_IMPERSONATE", "chrome131")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if league.upper() != "WNBA":
        raise ValueError(f"prefetch_step1_http: unsupported league {league}")

    script = ROOT / "Sports" / "WNBA" / "step1_fetch_prizepicks.py"
    base_cmd = [
        sys.executable,
        "-X",
        "utf8",
        str(script),
        "--date",
        date_str,
        "--output",
        str(output_path),
        "--league_id",
        "3",
        "--max_pages",
        "8",
        "--first-page-waves",
        "3",
        "--sleep",
        "2.0",
    ]

    def _csv_ok(path: Path) -> bool:
        try:
            if not path.is_file() or path.stat().st_size < 200:
                return False
            # header + at least a few data rows
            with path.open(encoding="utf-8", errors="ignore") as fh:
                lines = sum(1 for _ in fh)
            return lines >= 10
        except OSError:
            return False

    print(f"[prefetch] HTTP chrome131 + rotating headers -> {output_path}")
    print(f"[prefetch] {' '.join(base_cmd)}")
    rc = subprocess.call(base_cmd, cwd=str(script.parent))
    if rc == 0 and _csv_ok(output_path):
        print(f"[prefetch] OK (HTTP) rows file={output_path}")
        return output_path

    cdp = str(cdp_url or "").strip()
    if cdp:
        cdp_cmd = base_cmd + ["--cdp", cdp]
        # CDP path does not need first-page waves; keep args harmless.
        print(f"[prefetch] HTTP blocked — retrying via CDP session {cdp}")
        print(f"[prefetch] {' '.join(cdp_cmd)}")
        rc2 = subprocess.call(cdp_cmd, cwd=str(script.parent))
        if rc2 == 0 and _csv_ok(output_path):
            print(f"[prefetch] OK (CDP) rows file={output_path}")
            return output_path

    if _csv_ok(output_path):
        print(
            f"[prefetch] WARN: live fetch failed; reusing on-disk step1 "
            f"({output_path.stat().st_size} bytes)"
        )
        return output_path

    raise RuntimeError(
        f"HTTP/CDP prefetch failed and no usable step1 CSV at {output_path} (http_rc={rc})"
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Discover realistic PrizePicks payout rates from any board (or validate vs ladder)"
    )
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    ap.add_argument("--max-cases", type=int, default=80, help="Max slips to build/capture")
    ap.add_argument(
        "--discover",
        action="store_true",
        help="Board-agnostic rate discovery from whatever board is open (recommended)",
    )
    ap.add_argument(
        "--exhaustive",
        action="store_true",
        help="Enumerate all fillable S/G mixes × Goblin-Δ signatures (default on for --discover)",
    )
    ap.add_argument(
        "--step1-csv",
        default="",
        help="Step1 props CSV for Standard anchors + Goblin Δ (e.g. tomorrow WNBA fetch)",
    )
    ap.add_argument(
        "--slate-date",
        default="",
        help="Slate date YYYY-MM-DD for auto-locating step1 CSV / report stamp (default: --date)",
    )
    ap.add_argument("--mix-only", action="store_true", help="Compare mix-level historical ladder recipes")
    ap.add_argument("--delta-only", action="store_true", help="Compare Goblin-distance historical recipes")
    ap.add_argument(
        "--delta-tol",
        type=float,
        default=0.35,
        help="Max |board_delta - recipe_delta| when matching Goblin distances",
    )
    ap.add_argument("--dry-run", action="store_true", help="List historical recipes without CDP scrape")
    ap.add_argument("--run", action="store_true", help="Scrape board, build real slips, capture floors")
    ap.add_argument("--rel-tol", type=float, default=0.15)
    ap.add_argument("--abs-tol", type=float, default=0.5)
    ap.add_argument(
        "--prefetch-http",
        action="store_true",
        help="Prefetch step1 via curl_cffi chrome131 + warmup + rotating headers (no CDP click-storm)",
    )
    ap.add_argument(
        "--gentle",
        action="store_true",
        help="Human-paced CDP: light/skip board expand, longer delays, cooloff between slips",
    )
    ap.add_argument(
        "--delay-sec",
        type=float,
        default=0.0,
        help="CDP click delay seconds (default 0.5; with --gentle default 2.5)",
    )
    ap.add_argument(
        "--skip-cdp-scrape",
        action="store_true",
        help="Skip CDP board expand; use step1 CSV pools only (recommended with --prefetch-http)",
    )
    ap.add_argument(
        "--force-deltas",
        action="store_true",
        help=(
            "Comprehensive Δ sweep: plan missing mix×Δ cells and cycle the More control "
            "to hit target Goblin lines (std−Δ), not limited to faces already showing"
        ),
    )
    args = ap.parse_args()
    date_str = str(args.slate_date or args.date)[:10]
    gentle = bool(args.gentle) or bool(args.prefetch_http)
    delay_sec = float(args.delay_sec) if float(args.delay_sec) > 0 else (2.5 if gentle else 0.5)
    skip_cdp_scrape = bool(args.skip_cdp_scrape) or bool(args.prefetch_http)
    force_deltas = bool(args.force_deltas)

    # Discovery is the default for --run unless an explicit compare mode is chosen.
    discover = bool(args.discover) or force_deltas or (
        bool(args.run) and not args.mix_only and not args.delta_only
    )
    if args.mix_only or args.delta_only:
        discover = False

    include_mix = not bool(args.delta_only)
    include_delta = not bool(args.mix_only)
    mode = (
        "force_delta"
        if force_deltas
        else ("discover" if discover else ("delta" if args.delta_only else ("mix" if args.mix_only else "all")))
    )

    recipes: list[dict[str, Any]] = []
    if not discover:
        recipes = load_ladder_recipes(include_mix=include_mix, include_delta=include_delta)
        if args.delta_only:
            cleaned: list[dict[str, Any]] = []
            for r in recipes:
                sig = str(r.get("goblin_delta_sig") or "")
                parts = [p for p in sig.split("+") if p.strip()]
                bad_zero = False
                for part in parts:
                    try:
                        if abs(float(part)) < 1e-9:
                            bad_zero = True
                            break
                    except ValueError:
                        continue
                if not bad_zero:
                    cleaned.append(r)
            recipes = cleaned
        recipes.sort(
            key=lambda r: (
                0 if r.get("kind") == "delta" else 1,
                int(r.get("n_legs") or 99),
                int(r.get("n_demon") or 0),
                len([x for x in str(r.get("goblin_delta_sig") or "").split("+") if x]),
                str(r.get("composition") or ""),
            )
        )
        print(f"[validate] loaded {len(recipes)} ladder recipes (mix={include_mix} delta={include_delta})")
    else:
        print("[discover] board-agnostic payout rate discovery (any league board is fine)")

    if args.dry_run and not args.run:
        if discover:
            print("[discover] dry-run for discovery needs the board; use: --run --discover")
            return 2
        out = {
            "date": date_str,
            "mode": "dry_run",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_recipes": len(recipes),
            "recipes": recipes[: max(1, int(args.max_cases))] if args.max_cases else recipes,
            "note": "Re-run with --run --discover to capture live floors from any board.",
        }
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"payout_ladder_validation_{date_str}.json"
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"[validate] dry-run plan -> {path}")
        for r in out["recipes"][:25]:
            print(
                f"  {r['kind']:5} {r['n_legs']}L {r['composition']:12} "
                f"GΔ={r.get('goblin_delta_sig') or '—':12} "
                f"avg={r['ladder_avg_x']} [{r['ladder_min_x']}-{r['ladder_max_x']}] n={r['samples']}"
            )
        if len(out["recipes"]) > 25:
            print(f"  ... +{len(out['recipes']) - 25} more")
        return 0

    if not args.run and not args.dry_run:
        print("[validate] pass --run --discover   (recommended)")
        return 2

    # HTTP prefetch first (chrome131 + rotating headers) — inventory without CDP thrash.
    if args.prefetch_http and args.run:
        out_csv = (
            Path(str(args.step1_csv).strip())
            if str(args.step1_csv or "").strip()
            else ROOT / "Sports" / "WNBA" / "data" / "outputs" / f"step1_wnba_props_{date_str}.csv"
        )
        try:
            prefetch_step1_http(
                date_str=date_str,
                output_path=out_csv,
                league="WNBA",
                cdp_url=str(args.cdp_url or ""),
            )
            args.step1_csv = str(out_csv)
        except Exception as e:
            print(f"[prefetch] FAILED: {e}")
            return 1

    try:
        import urllib.request

        urllib.request.urlopen(f"{args.cdp_url.rstrip('/')}/json/version", timeout=3)
    except Exception as e:
        print(f"[validate] CDP not reachable at {args.cdp_url}: {e}")
        print("  Launch: pwsh -File scripts/launch_prizepicks_chrome_cdp.ps1 -OpenBoard")
        return 1

    standard: list[dict] = []
    goblins: list[dict] = []
    demons: list[dict] = []
    if skip_cdp_scrape:
        print("[validate] skipping CDP board expand (using step1 pools / light path)")
    else:
        # Discover: focused filters (clickable) + alt-line Δ harvest. Gentle delays still
        # apply during slip capture. Avoid full expand (Fantasy Score noise / stale faces).
        # Force-delta: prefer WNBA Points (room to cycle std−Δ across 0.5…6).
        use_focused = bool(discover)
        use_light = bool(gentle) and not bool(discover)
        prefer_wnba = bool(force_deltas) and "wnba" in str(args.step1_csv or "").lower()
        if force_deltas and prefer_wnba:
            print("[force-delta] focused scrape preferring WNBA Points for wide Δ ladders")
        elif force_deltas:
            print("[force-delta] focused scrape preferring MLB (Hits/HRR/TB/Ks) for mid-range Δ")
        elif discover:
            print("[discover] focused board scrape + alt-line Δ harvest (any board faces)")
        standard, goblins, demons = scrape_board_pools(
            args.cdp_url,
            light=use_light,
            focused=use_focused,
            prefer_wnba=prefer_wnba,
        )

    step1_meta: dict[str, Any] = {}
    step1_path = Path(str(args.step1_csv or "").strip()) if str(args.step1_csv or "").strip() else None
    if step1_path is None or not step1_path.is_file():
        # Auto-detect tomorrow/slate step1 CSVs.
        candidates = [
            ROOT / "Sports" / "WNBA" / "data" / "outputs" / f"step1_wnba_props_{date_str}.csv",
            ROOT / "Sports" / "MLB" / "data" / "outputs" / f"step1_mlb_props_{date_str}.csv",
            ROOT / "Sports" / "NBA" / "data" / "outputs" / f"step1_pp_props_{date_str}.csv",
        ]
        for cand in candidates:
            if cand.is_file():
                step1_path = cand
                break

    if discover and step1_path and step1_path.is_file():
        sport = "WNBA"
        name_l = step1_path.name.lower()
        if "mlb" in name_l:
            sport = "MLB"
        elif "wnba" in name_l:
            sport = "WNBA"
        elif "nba" in name_l:
            sport = "NBA"
        s1, g1, d1, step1_meta = load_pools_from_step1_csv(step1_path, sport=sport)
        # Prefer step1 pools (accurate Δ); CDP scrape still used for clickability enrich.
        std_map: dict[tuple[str, str], float] = {}
        for c in s1:
            if c.get("line") is None:
                continue
            player_n = cpd._norm(c.get("player"))
            for prop_alias in _prop_key_aliases(str(c.get("prop_type") or "")):
                key = (player_n, prop_alias)
                try:
                    line_f = float(c.get("line") or 0)
                except (TypeError, ValueError):
                    continue
                prev = std_map.get(key)
                if prev is None or line_f > prev:
                    std_map[key] = line_f
        for c in g1:
            if c.get("standard_line") is None:
                continue
            player_n = cpd._norm(c.get("player"))
            try:
                std_f = float(c["standard_line"])
            except (TypeError, ValueError):
                continue
            for prop_alias in _prop_key_aliases(str(c.get("prop_type") or "")):
                std_map.setdefault((player_n, prop_alias), std_f)
        if standard or goblins or demons:
            standard, goblins, demons = enrich_pools_with_std_map(standard, goblins, demons, std_map)
        g_with_delta = sum(1 for c in goblins if _card_distance(c) is not None)
        print(f"[discover] CDP pools after step1 enrich: S={len(standard)} G={len(goblins)} withΔ={g_with_delta}")

        def _simple_first(cards: list[dict]) -> list[dict]:
            return sorted(
                cards,
                key=lambda c: (
                    0 if str(c.get("prop_type") or "").lower() in _SIMPLE_PROPS else 1,
                    0 if _card_distance(c) is not None else 1,
                    _card_distance(c) or 99,
                    str(c.get("player") or ""),
                ),
            )

        # Prefer step1 when it has rich Goblin-Δ coverage (tomorrow slate). Sport must be correct
        # so CDP navigates to WNBA/MLB — not NBA (substring bug previously).
        #
        # CRITICAL: never replace CDP click pools with step1-only players when we already
        # scraped the live board — those names/lines often are not clickable → 0/N captures.
        if skip_cdp_scrape:
            print(
                f"[discover] using step1 pools (CDP scrape skipped) "
                f"(S={len(s1)} G={len(g1)} withΔ={step1_meta.get('n_goblin_with_delta')}) sport={sport}"
            )
            standard, goblins, demons = _simple_first(s1), _simple_first(g1), _simple_first(d1)
        else:
            # Keep CDP faces for clicking; step1 only enriched Δ above.
            standard = [{**c, "sport": sport, "league": sport} for c in standard]
            goblins = [{**c, "sport": sport, "league": sport} for c in goblins]
            demons = [{**c, "sport": sport, "league": sport} for c in demons]
            print(
                f"[discover] click pools from live CDP board "
                f"(S={len(standard)} G={len(goblins)} withΔ={g_with_delta} D={len(demons)}; "
                f"step1 withΔ={step1_meta.get('n_goblin_with_delta')} used for enrich only)"
            )
            if g_with_delta < 3:
                print(
                    "[discover] WARN: few Goblin-Δ faces on board — "
                    "coverage limited until alt-line cycle expands Goblins"
                )
        # Persist inventory for the slate.
        inv_path = REPORTS_DIR / f"payout_board_inventory_{date_str}.json"
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        inv_path.write_text(
            json.dumps(
                {
                    "date": date_str,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "step1": step1_meta,
                    "prefetch_http": bool(args.prefetch_http),
                    "gentle": gentle,
                    "cdp_pools": {
                        "standard": len(standard),
                        "goblin": len(goblins),
                        "goblin_with_delta": sum(1 for c in goblins if _card_distance(c)),
                        "demon": len(demons),
                    },
                    "goblin_delta_examples": [
                        {
                            "player": c.get("player"),
                            "prop": c.get("prop_type"),
                            "line": c.get("line"),
                            "standard_line": c.get("standard_line"),
                            "delta": _round_delta(_card_distance(c)),
                        }
                        for c in sorted(
                            [x for x in goblins if _card_distance(x)],
                            key=lambda x: (_card_distance(x) or 0, str(x.get("player") or "")),
                        )[:40]
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[discover] inventory -> {inv_path}")
    elif skip_cdp_scrape:
        print("[validate] FATAL: --skip-cdp-scrape / --prefetch-http needs a step1 CSV")
        return 1

    if len(standard) + len(goblins) < 4:
        print("[validate] FATAL: not enough board cards from scrape/step1")
        return 1

    if discover:
        def _clickable(c: dict) -> bool:
            prop = str(c.get("prop_type") or "").strip().lower()
            if prop in _DISCOVER_BLOCKED_PROPS:
                return False
            return _usable_board_player(c.get("player"))

        n_before = (len(standard), len(goblins), len(demons))
        standard = [c for c in standard if _clickable(c)]
        goblins = [c for c in goblins if _clickable(c)]
        demons = [c for c in demons if _clickable(c)]
        print(
            f"[discover] clickable pools (blocked fantasy/FS/placeholders): "
            f"S={len(standard)}/{n_before[0]} G={len(goblins)}/{n_before[1]} "
            f"D={len(demons)}/{n_before[2]}"
        )
        if force_deltas:
            # Prefer Δ bins proven via More cycling; fall back to any mid-range distances.
            avail = [
                float(c["line_distance"])
                for c in goblins
                if c.get("cataloged_alt")
                and c.get("line_distance") is not None
                and 0.25 <= float(c["line_distance"]) <= 6.5
            ]
            if not avail:
                avail = [
                    float(c["line_distance"])
                    for c in goblins
                    if c.get("line_distance") is not None
                    and 0.25 <= float(c["line_distance"]) <= 6.5
                ]
            # If More-catalog failed, still plan mid-range Δ recipes and synthesize
            # Goblin legs from high Standard faces (force_alt_cycle). Prefer this over
            # mix-only discover which produces GΔ=— and does not close the rate grid.
            if not avail:
                avail = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
                print(
                    "[force-delta] WARN: no board Δ catalog — "
                    f"using default mid-range bins={avail} with alt-line synthesize"
                )
            if avail:
                recipes = build_force_delta_recipes(
                    max_cases=int(args.max_cases),
                    available_deltas=avail,
                )
                delta_tol = max(float(args.delta_tol), 0.75)
            else:
                print(
                    "[force-delta] WARN: no mid-range Δ (0.5–6.5) cataloged — "
                    "falling back to board-face discover recipes"
                )
                recipes = build_discovery_recipes_from_board(
                    standard=standard,
                    goblins=goblins,
                    demons=demons,
                    max_cases=int(args.max_cases),
                    exhaustive=True,
                )
                delta_tol = max(float(args.delta_tol), 0.75)
                force_deltas = False
        else:
            recipes = build_discovery_recipes_from_board(
                standard=standard,
                goblins=goblins,
                demons=demons,
                max_cases=int(args.max_cases),
                exhaustive=True,
            )
            delta_tol = max(float(args.delta_tol), 0.75)
    else:
        delta_tol = float(args.delta_tol)

    payload, plan_rows = build_live_board_tickets_payload(
        recipes,
        standard=standard,
        goblins=goblins,
        demons=demons,
        date_str=date_str,
        max_cases=int(args.max_cases),
        delta_tol=delta_tol,
        force_alt_cycle=force_deltas,
    )
    # Stamp actual matched Goblin distances onto discover recipes for ladder sync.
    if discover:
        for t in payload.get("groups", [{}])[0].get("tickets") or []:
            lr = t.get("ladder_recipe") or {}
            matched = lr.get("matched_goblin_deltas") or []
            if matched:
                lr["goblin_delta_sig"] = _norm_delta_sig(
                    "+".join(f"{float(x):g}" for x in matched)
                )
                t["ladder_recipe"] = lr

    LIVE_TICKETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_TICKETS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    n_planned = sum(1 for row in plan_rows if row.get("status") == "planned")
    n_skip = sum(1 for row in plan_rows if row.get("status") == "unbuildable")
    print(f"[validate] live-board tickets -> {LIVE_TICKETS_PATH} planned={n_planned} unbuildable={n_skip}")

    capture_path = REPORTS_DIR / f"payout_ladder_validation_capture_{date_str}_{mode}.json"
    print(
        f"[validate] scraping live Min Guarantee for {n_planned} real slips "
        f"(gentle={gentle} delay={delay_sec:.1f}s)..."
    )
    rc = cpd.capture_tickets_from_board(
        tickets_path=LIVE_TICKETS_PATH,
        output_path=capture_path,
        fields=["power_min_x", "power_first_x", "min_guarantee"],
        cdp_url=args.cdp_url,
        entry_amount=1.0,
        max_cases=int(args.max_cases),
        delay_sec=delay_sec,
        write_back=False,
        date_override=date_str,
        strict_lines=True,
        # Force-delta synthesizes Goblin @ std−Δ; exact lines are often nearest-carousel
        # steps, so keep require_line off and stamp matched Δ after capture.
        require_line=False if (discover and force_deltas) else bool(force_deltas),
        gentle=gentle,
    )
    captured = []
    if capture_path.is_file():
        try:
            captured = json.loads(capture_path.read_text(encoding="utf-8")).get("slips") or []
        except (OSError, json.JSONDecodeError):
            captured = []

    ok_slips = [
        s
        for s in captured
        if isinstance(s, dict)
        and str(s.get("status") or "").lower() in ("ok", "partial")
        and float(s.get("power_min_x") or s.get("min_x") or 0) > 0
    ]
    if ok_slips:
        cpd.sync_captures_to_payout_ladder_live(
            ok_slips,
            date_str=date_str,
            tickets_path=LIVE_TICKETS_PATH,
            keep_same_date=True,
        )

    recipe_by_tid = {}
    for t in payload["groups"][0]["tickets"]:
        recipe_by_tid[t["ticket_id"]] = {**(t.get("ladder_recipe") or {}), "ticket_id": t["ticket_id"]}
    for row in plan_rows:
        tid = row.get("ticket_id")
        if tid and tid in recipe_by_tid:
            row.update(
                {
                    k: v
                    for k, v in recipe_by_tid[tid].items()
                    if k not in row or row.get(k) in (None, "")
                }
            )

    results = compare_capture_to_recipes(captured, plan_rows)
    for r in results:
        live = r.get("live_power_min_x")
        if discover:
            if live:
                r["verdict"] = "captured"
                matched = r.get("matched_goblin_deltas") or []
                if matched:
                    r["goblin_delta_sig"] = _norm_delta_sig(
                        "+".join(f"{float(x):g}" for x in matched)
                    )
            elif r.get("status") == "unbuildable":
                r["verdict"] = "unbuildable"
            elif r.get("verdict") not in ("skipped", "missing_capture", "capture_failed"):
                r["verdict"] = "capture_failed"
        elif live and r.get("verdict") in ("in_range", "near_avg", "mismatch"):
            r["verdict"] = _verdict(
                float(live), r, rel_tol=float(args.rel_tol), abs_tol=float(args.abs_tol)
            )

    counts: dict[str, int] = {}
    for r in results:
        v = str(r.get("verdict") or "skipped")
        counts[v] = counts.get(v, 0) + 1

    report = {
        "date": date_str,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cdp_url": args.cdp_url,
        "live_board_tickets_path": str(LIVE_TICKETS_PATH),
        "capture_path": str(capture_path),
        "capture_exit": rc,
        "summary": counts,
        "n_ok_slips": len(ok_slips),
        "n_results": len(results),
        "results": results,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"payout_ladder_validation_{date_str}_{mode}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS_DIR / f"payout_ladder_validation_{date_str}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    title = "PAYOUT RATE DISCOVERY" if discover else "LADDER LIVE-BOARD VALIDATION"
    print(f"\n=== {title} ===")
    for k, v in sorted(counts.items()):
        if v:
            print(f"  {k}: {v}")
    print(f"ok captures synced to ladder: {len(ok_slips)}")
    print(f"report -> {report_path}")
    print("\nCaptured floors:" if discover else "\nMismatches / failures:")
    shown = 0
    for r in results:
        live = r.get("live_power_min_x")
        if discover:
            if not live:
                continue
            print(
                f"  {r.get('composition')} GΔ={r.get('goblin_delta_sig') or '—'} "
                f"live={live}x"
            )
            shown += 1
        elif r.get("verdict") in ("mismatch", "capture_failed", "unbuildable"):
            print(
                f"  [{r.get('verdict')}] {r.get('composition')} "
                f"GΔ={r.get('goblin_delta_sig') or '—'} "
                f"ladder_avg={r.get('ladder_avg_x')} live={live} "
                f"err={r.get('error')}"
            )
            shown += 1
        if shown >= 40:
            break
    if shown == 0:
        print("  (none)")

    if discover:
        return 0 if ok_slips else 1
    ok_n = counts.get("in_range", 0) + counts.get("near_avg", 0)
    return 0 if ok_n > 0 else (1 if counts.get("mismatch", 0) else rc)


if __name__ == "__main__":
    raise SystemExit(main())
