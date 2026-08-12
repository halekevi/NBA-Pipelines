#!/usr/bin/env python3
"""
Pre-publish slate history / L5 integrity gate.

Fails (exit 1) when published sport rows show process bugs that caused today's
Tennis/WNBA bad boards:
  - L5 counts disagree with actual_series / stat_g*
  - Projection≈0 fingerprint (edge ≈ -line) with no season avg
  - Goblin line >= standard_line
  - Format smell: Total Games L5 median >> line (BO5 mixed into BO3)

Usage:
  py -3 scripts/validate_slate_history_gate.py
  py -3 scripts/validate_slate_history_gate.py --slate ui_runner/templates/slate_latest.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _num(x):
    try:
        if x is None or x == "":
            return None
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def _series5(row: dict) -> list[float]:
    vals: list[float] = []
    if isinstance(row.get("actual_series"), list):
        for x in row["actual_series"][:5]:
            v = _num(x)
            if v is not None:
                vals.append(v)
        if vals:
            return vals
    for i in range(1, 6):
        v = _num(row.get(f"stat_g{i}") or row.get(f"g{i}"))
        if v is not None:
            vals.append(v)
    return vals


def _check_row(sport: str, row: dict) -> list[str]:
    issues: list[str] = []
    pt = str(row.get("pick_type") or row.get("pick") or "").strip().lower()
    if pt == "demon":
        return issues
    player = str(row.get("player") or "").strip()
    prop = str(row.get("prop") or "").strip()
    line = _num(row.get("line"))
    direc = str(row.get("dir") or row.get("direction") or "").strip().upper()
    edge = _num(row.get("edge"))
    proj = _num(row.get("projection"))
    sea = _num(row.get("season_avg"))
    std = _num(row.get("standard_line"))
    vals = _series5(row)

    if pt == "goblin" and std is not None and line is not None and line >= std - 0.01:
        issues.append(f"goblin_ge_standard:{player}|{prop}|{line}>={std}")

    # proj≈0 fingerprint
    if line is not None and line >= 3 and edge is not None and abs(abs(edge) - abs(line)) < 0.05:
        if sea is None and (proj is None or abs(proj) < 0.05):
            issues.append(f"proj_zero_edge:{player}|{prop}|edge={edge}")

    if len(vals) >= 3 and line is not None and direc in ("OVER", "UNDER"):
        overs = sum(1 for v in vals if v > line)
        unders = sum(1 for v in vals if v < line)
        stored = _num(row.get("l5_over") if direc == "OVER" else row.get("l5_under"))
        true_hit = overs if direc == "OVER" else unders
        if stored is not None and abs(stored - true_hit) >= 1:
            issues.append(
                f"l5_mismatch:{player}|{prop}|stored={stored}|true={true_hit}|vals={vals}"
            )
        # BO5 smell: Slam totals often >=40; long BO3 can hit mid-30s so don't use median vs line.
        prop_l = prop.lower()
        if "total games" in prop_l and "won" not in prop_l:
            mx = max(vals)
            if mx >= 40:
                issues.append(f"bo5_smell:{player}|{prop}|max={mx}|line={line}|vals={vals}")

    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--slate",
        default=str(_REPO / "ui_runner" / "templates" / "slate_latest.json"),
    )
    ap.add_argument("--max-issues", type=int, default=40)
    ap.add_argument("--fail-threshold", type=int, default=1)
    args = ap.parse_args()

    path = Path(args.slate)
    if not path.is_file():
        print(f"[gate] missing slate: {path}")
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    sports = payload.get("sports") or {}
    all_issues: list[str] = []
    for sport, rows in sports.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for iss in _check_row(str(sport), row):
                all_issues.append(f"{sport}:{iss}")

    print(f"[gate] slate={path.name} date={payload.get('date')} issues={len(all_issues)}")
    for iss in all_issues[: max(0, int(args.max_issues))]:
        print(" ", iss)
    if len(all_issues) > int(args.max_issues):
        print(f"  ... +{len(all_issues) - int(args.max_issues)} more")

    if len(all_issues) >= int(args.fail_threshold):
        print("[gate] FAIL")
        return 1
    print("[gate] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
