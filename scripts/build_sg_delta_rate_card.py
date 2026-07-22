#!/usr/bin/env python3
"""
Build a complete Standard/Goblin payout rate card across mixes × Goblin-Δ signatures.

Sources (priority):
  1) live_cdp Min Guarantee floors (trusted)
  2) historical ladder log (excludes Δ≈0 junk)
  3) linear / additive extrapolation from observed cells

Writes:
  data/reports/sg_delta_payout_rate_card_<date>.json
  ui_runner/data/sg_delta_payout_rate_card_latest.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ui_runner"))

LIVE_CDP = ROOT / "ui_runner" / "data" / "payout_ladder_live_cdp.json"
LADDER_LOG = ROOT / "ui_runner" / "data" / "payout_ladder_log.csv"
OUT_DIR = ROOT / "data" / "reports"
LATEST = ROOT / "ui_runner" / "data" / "sg_delta_payout_rate_card_latest.json"

MIN_DELTA = 0.25

# (n_legs, n_standard, n_goblin)
TARGET_SG: list[tuple[int, int, int]] = [
    (2, 2, 0),
    (2, 1, 1),
    (2, 0, 2),
    (3, 3, 0),
    (3, 2, 1),
    (3, 1, 2),
    (3, 0, 3),
    (4, 4, 0),
    (4, 3, 1),
    (4, 2, 2),
    (4, 1, 3),
    (4, 0, 4),
    (5, 5, 0),
    (5, 4, 1),
    (5, 3, 2),
    (5, 2, 3),
    (5, 1, 4),
    (5, 0, 5),
    (6, 6, 0),
    (6, 5, 1),
    (6, 4, 2),
    (6, 3, 3),
    (6, 2, 4),
    (6, 1, 5),
    (6, 0, 6),
]

# Common Goblin Δ bins seen on WNBA boards.
COMMON_DELTAS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]


def _norm_sig(parts: list[float]) -> str:
    vals = sorted(float(x) for x in parts if math.isfinite(float(x)))
    return "+".join(f"{v:g}" for v in vals)


def _parse_sig(raw: object) -> list[float]:
    """Parse goblin_deltas from list, JSON list-string, or '1+1.5' / '1,1.5'."""
    out: list[float] = []
    if isinstance(raw, (list, tuple)):
        for part in raw:
            try:
                out.append(float(part))
            except (TypeError, ValueError):
                continue
        return sorted(out)
    text = str(raw or "").strip()
    if not text:
        return []
    # JSON / Python list repr: "['1', '1.5']" or '["1","1.5"]'
    if text.startswith("["):
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, list):
                return _parse_sig(parsed)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    for part in text.replace("|", ",").replace("+", ",").split(","):
        part = part.strip().strip("[]'\"")
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return sorted(out)


def _sig_ok(parts: list[float], n_g: int) -> bool:
    if n_g <= 0:
        return True
    if len(parts) != n_g:
        return False
    return all(abs(v) >= MIN_DELTA for v in parts)


def _parse_comp(comp: str) -> tuple[int, int, int]:
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


def _comp_label(n_s: int, n_g: int, n_d: int = 0) -> str:
    return f"{n_s}S+{n_g}G+{n_d}D"


def _load_evidence() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if LIVE_CDP.is_file():
        live = json.loads(LIVE_CDP.read_text(encoding="utf-8"))
        for r in live.get("rows") or []:
            if not isinstance(r, dict):
                continue
            s, g, d = _parse_comp(str(r.get("leg_composition") or ""))
            if d > 0:
                continue  # S/G card only
            parts = _parse_sig(r.get("goblin_deltas"))
            if not _sig_ok(parts, g):
                continue
            try:
                x = float(r.get("power_payout_x") or 0)
            except (TypeError, ValueError):
                continue
            if x <= 0:
                continue
            rows.append(
                {
                    "n_legs": int(r.get("n_legs") or (s + g + d)),
                    "n_s": s,
                    "n_g": g,
                    "composition": _comp_label(s, g, 0),
                    "goblin_delta_sig": _norm_sig(parts) if parts else "",
                    "power_min_x": x,
                    "source": "live_cdp",
                    "date": str(r.get("date") or ""),
                    "ticket_id": str(r.get("ticket_id") or ""),
                }
            )

    if LADDER_LOG.is_file():
        with LADDER_LOG.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                s, g, d = _parse_comp(str(r.get("leg_composition") or ""))
                if d > 0:
                    continue
                parts = _parse_sig(r.get("goblin_deltas"))
                if not _sig_ok(parts, g):
                    continue
                try:
                    x = float(r.get("power_payout_x") or 0)
                except (TypeError, ValueError):
                    continue
                if x <= 0:
                    continue
                src = str(r.get("source") or "historical").strip().lower()
                if src == "live_cdp":
                    continue
                rows.append(
                    {
                        "n_legs": int(float(r.get("n_legs") or (s + g + d))),
                        "n_s": s,
                        "n_g": g,
                        "composition": _comp_label(s, g, 0),
                        "goblin_delta_sig": _norm_sig(parts) if parts else "",
                        "power_min_x": x,
                        "source": "historical",
                        "date": str(r.get("date") or ""),
                        "ticket_id": "",
                    }
                )
    return rows


def _aggregate(evidence: list[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """Key = (n_legs, n_s, n_g, delta_sig) → cell with preferred rate."""
    buckets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for e in evidence:
        key = (e["n_legs"], e["n_s"], e["n_g"], e["goblin_delta_sig"])
        buckets[key].append(e)

    cells: dict[tuple, dict[str, Any]] = {}
    for key, items in buckets.items():
        live = [x for x in items if x["source"] == "live_cdp"]
        use = live if live else items
        # Prefer newest slate date when live samples disagree (older scrapes
        # sometimes logged first-place as Min Guarantee).
        if live:
            newest = max(str(x.get("date") or "") for x in live)
            dated = [x for x in live if str(x.get("date") or "") == newest]
            if dated:
                use = dated
            vals = [float(x["power_min_x"]) for x in use]
            # Median of newest-date live floors (min was too pessimistic when
            # earlier same-day scrapes under-clicked Goblins).
            rate = statistics.median(vals)
        else:
            vals = [float(x["power_min_x"]) for x in use]
            rate = statistics.median(vals)
        cells[key] = {
            "n_legs": key[0],
            "n_s": key[1],
            "n_g": key[2],
            "composition": _comp_label(key[1], key[2], 0),
            "goblin_delta_sig": key[3] or "—",
            "power_min_x": round(rate, 4),
            "min_x": round(min(vals), 4),
            "max_x": round(max(vals), 4),
            "n_samples": len(use),
            "n_live": len(live),
            "source": "live_cdp" if live else "historical",
            "confidence": "high" if live else ("medium" if len(use) >= 3 else "low"),
        }
    return cells


def _delta_sum(sig: str) -> float:
    if not sig or sig == "—":
        return 0.0
    return sum(_parse_sig(sig))


def _extrapolate_cell(
    n_legs: int,
    n_s: int,
    n_g: int,
    want_sig: str,
    cells: dict[tuple, dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Extrapolate missing S/G×Δ cells.

    Heuristics (PP-ish, from observed board):
      - Pure Standard floors cluster near ~3.0× for 2–3 legs (live).
      - Replacing Standard with Goblin lowers floor; larger ΣΔ tends to lower floor further
        (easier Goblins → lower payout).
      - Fit: rate ≈ a + b*(n_g/n_legs) + c*mean_delta  using nearby observed cells
        with same n_legs, else same composition family.
    """
    # Pure standard
    if n_g == 0:
        key = (n_legs, n_s, 0, "")
        if key in cells:
            return None
        # Prefer live pure-S at this n_legs
        pure = [
            c
            for k, c in cells.items()
            if k[0] == n_legs and k[2] == 0 and c["source"] == "live_cdp"
        ]
        if not pure:
            pure = [c for k, c in cells.items() if k[0] == n_legs and k[2] == 0]
        if pure:
            x = statistics.mean(c["power_min_x"] for c in pure)
            return {
                "n_legs": n_legs,
                "n_s": n_s,
                "n_g": 0,
                "composition": _comp_label(n_s, 0, 0),
                "goblin_delta_sig": "—",
                "power_min_x": round(x, 4),
                "min_x": round(x, 4),
                "max_x": round(x, 4),
                "n_samples": 0,
                "n_live": 0,
                "source": "extrapolated",
                "confidence": "medium",
                "method": "pure_standard_peer",
            }
        # Fallback table of rough PP power mins
        fallback = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 40.0}
        x = float(fallback.get(n_legs, 3.0))
        return {
            "n_legs": n_legs,
            "n_s": n_s,
            "n_g": 0,
            "composition": _comp_label(n_s, 0, 0),
            "goblin_delta_sig": "—",
            "power_min_x": x,
            "min_x": x,
            "max_x": x,
            "n_samples": 0,
            "n_live": 0,
            "source": "extrapolated",
            "confidence": "low",
            "method": "standard_fallback_table",
        }

    want_parts = _parse_sig(want_sig)
    if not _sig_ok(want_parts, n_g):
        return None
    want_sum = sum(want_parts)
    want_mean = want_sum / n_g

    # Same mix peers (any Δ)
    peers = [
        c
        for k, c in cells.items()
        if k[0] == n_legs and k[1] == n_s and k[2] == n_g and k[3]
    ]
    if peers:
        # Interpolate vs ΣΔ / mean Δ
        pts = []
        for c in peers:
            parts = _parse_sig(c["goblin_delta_sig"])
            if len(parts) != n_g:
                continue
            pts.append((sum(parts) / n_g, float(c["power_min_x"]), c["source"]))
        if pts:
            pts.sort(key=lambda t: t[0])
            # nearest-neighbor blend of 2–3 closest mean-Δ points
            pts2 = sorted(pts, key=lambda t: abs(t[0] - want_mean))[:3]
            if len(pts2) == 1:
                md0, rate0, _ = pts2[0]
                # Soft slope when only one peer: larger mean Goblin-Δ → slightly lower floor.
                x = rate0 * (1.0 - 0.045 * (want_mean - md0))
            else:
                # Prefer linear fit if we have spread; else inverse-distance weight.
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                if max(xs) - min(xs) >= 0.75 and len(pts) >= 2:
                    # Simple least-squares slope
                    n = len(pts)
                    mx = sum(xs) / n
                    my = sum(ys) / n
                    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
                    den = sum((xs[i] - mx) ** 2 for i in range(n)) or 1e-9
                    slope = num / den
                    intercept = my - slope * mx
                    x = intercept + slope * want_mean
                else:
                    wsum = 0.0
                    xsum = 0.0
                    for md, rate, _ in pts2:
                        w = 1.0 / max(0.05, abs(md - want_mean))
                        wsum += w
                        xsum += w * rate
                    x = xsum / wsum
            conf = "medium" if any(s == "live_cdp" for _, _, s in pts2) else "low"
            return {
                "n_legs": n_legs,
                "n_s": n_s,
                "n_g": n_g,
                "composition": _comp_label(n_s, n_g, 0),
                "goblin_delta_sig": _norm_sig(want_parts),
                "power_min_x": round(max(1.05, x), 4),
                "min_x": round(max(1.05, x), 4),
                "max_x": round(max(1.05, x), 4),
                "n_samples": 0,
                "n_live": 0,
                "source": "extrapolated",
                "confidence": conf,
                "method": "peer_mean_delta_fit",
                "peer_means": [round(p[0], 3) for p in pts2],
            }

    # Cross-mix: use all-goblin or similar n_g cells at this n_legs
    family = [
        c
        for k, c in cells.items()
        if k[0] == n_legs and k[2] == n_g and k[3]
    ]
    if family:
        pts = []
        for c in family:
            parts = _parse_sig(c["goblin_delta_sig"])
            if len(parts) != n_g:
                continue
            pts.append((sum(parts) / n_g, float(c["power_min_x"])))
        if pts:
            pts.sort(key=lambda t: abs(t[0] - want_mean))
            md, rate = pts[0]
            # Adjust for more Standards: each Standard tends to raise floor vs all-G
            # Observed ~ +0.5x to +1.5x when adding S into G slips (rough).
            s_boost = 0.35 * n_s
            x = rate + s_boost
            return {
                "n_legs": n_legs,
                "n_s": n_s,
                "n_g": n_g,
                "composition": _comp_label(n_s, n_g, 0),
                "goblin_delta_sig": _norm_sig(want_parts),
                "power_min_x": round(max(1.05, x), 4),
                "min_x": round(max(1.05, x), 4),
                "max_x": round(max(1.05, x), 4),
                "n_samples": 0,
                "n_live": 0,
                "source": "extrapolated",
                "confidence": "low",
                "method": f"family_n_g_plus_s_boost(base_meanΔ={md:g})",
            }

    return None


def _signatures_to_cover(n_g: int, observed: set[str], board_bins: list[float]) -> list[str]:
    """Multisets of size n_g from board bins + observed, capped for tractability."""
    if n_g <= 0:
        return [""]
    bins = sorted(set(board_bins) | {1.0, 1.5, 2.0, 2.5, 3.0})
    # Always include all-equal signatures and observed ones.
    sigs: set[str] = set(observed)
    for d in bins:
        sigs.add(_norm_sig([d] * n_g))
    # Mixed two-value signatures for n_g>=2
    if n_g >= 2:
        for i, a in enumerate(bins):
            for b in bins[i + 1 :]:
                # one of each extreme + fill with mid
                parts = [a] + [b] * (n_g - 1)
                sigs.add(_norm_sig(parts))
                parts2 = [a] * (n_g - 1) + [b]
                sigs.add(_norm_sig(parts2))
    # Cap
    ordered = sorted(sigs, key=lambda s: (_delta_sum(s), s))
    return ordered[: max(12, len(observed) + 8)]


def build_rate_card(board_bins: list[float] | None = None) -> dict[str, Any]:
    evidence = _load_evidence()
    cells = _aggregate(evidence)
    bins = board_bins or COMMON_DELTAS

    observed_by_mix: dict[tuple[int, int, int], set[str]] = defaultdict(set)
    for (n_legs, n_s, n_g, sig), _ in cells.items():
        if n_g > 0 and sig:
            observed_by_mix[(n_legs, n_s, n_g)].add(sig)

    complete: list[dict[str, Any]] = []
    for n_legs, n_s, n_g in TARGET_SG:
        if n_s + n_g != n_legs:
            continue
        if n_g == 0:
            key = (n_legs, n_s, 0, "")
            if key in cells:
                complete.append({**cells[key], "status": "observed"})
            else:
                ext = _extrapolate_cell(n_legs, n_s, 0, "", cells)
                if ext:
                    complete.append({**ext, "status": "extrapolated"})
            continue

        sigs = _signatures_to_cover(
            n_g, observed_by_mix.get((n_legs, n_s, n_g), set()), bins
        )
        for sig in sigs:
            key = (n_legs, n_s, n_g, sig)
            if key in cells:
                complete.append({**cells[key], "status": "observed"})
            else:
                ext = _extrapolate_cell(n_legs, n_s, n_g, sig, cells)
                if ext:
                    complete.append({**ext, "status": "extrapolated"})

    # Also include any observed cells not already listed (extra Δ signatures).
    listed = {
        (r["n_legs"], r["n_s"], r["n_g"], "" if r["goblin_delta_sig"] in ("", "—") else r["goblin_delta_sig"])
        for r in complete
    }
    for key, cell in cells.items():
        k2 = (key[0], key[1], key[2], key[3])
        if k2 not in listed:
            complete.append({**cell, "status": "observed"})

    complete.sort(
        key=lambda r: (
            int(r["n_legs"]),
            int(r["n_g"]),
            int(r["n_s"]),
            _delta_sum(str(r.get("goblin_delta_sig") or "")),
            str(r.get("goblin_delta_sig") or ""),
        )
    )

    n_obs = sum(1 for r in complete if r.get("status") == "observed")
    n_ext = sum(1 for r in complete if r.get("status") == "extrapolated")
    n_live = sum(1 for r in complete if r.get("source") == "live_cdp")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Standard + Goblin only (Demons excluded)",
        "notes": [
            "observed = measured Min Guarantee (prefer live_cdp over historical)",
            "extrapolated = peer/mean-Δ interpolation or family boost — not PP-official",
            "Δ≈0 signatures excluded as invalid",
        ],
        "summary": {
            "n_cells": len(complete),
            "n_observed": n_obs,
            "n_extrapolated": n_ext,
            "n_live_cdp": n_live,
            "n_evidence_rows": len(evidence),
        },
        "board_delta_bins": bins,
        "cells": complete,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument(
        "--board-bins",
        default="",
        help="Comma list of Goblin Δ bins from step1 (optional)",
    )
    args = ap.parse_args()
    bins = None
    if str(args.board_bins or "").strip():
        bins = []
        for part in str(args.board_bins).split(","):
            try:
                bins.append(float(part.strip()))
            except ValueError:
                continue
    card = build_rate_card(bins)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"sg_delta_payout_rate_card_{args.date}.json"
    out.write_text(json.dumps(card, indent=2), encoding="utf-8")
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(f"[rate_card] -> {out}")
    print(f"[rate_card] -> {LATEST}")
    print(json.dumps(card["summary"], indent=2))
    # Preview
    for r in card["cells"][:25]:
        print(
            f"  {r['composition']:10} GΔ={str(r.get('goblin_delta_sig') or '—'):12} "
            f"{r['power_min_x']:>6}×  {r['source']:12} {r.get('status')}"
        )
    if len(card["cells"]) > 25:
        print(f"  ... +{len(card['cells']) - 25} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
