#!/usr/bin/env python3
"""Verify tickets_latest meets Jul-25 guidelines: floor >=1.9x, prefer 2L, starve 5-6L."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOTS = [
    Path(r"H:/halek/ProfileFromC/Desktop/PropORACLE"),
    Path(r"H:/halek/ProfileFromC/Desktop/PropORACLE_main_cp"),
]
DATE = "2026-07-26"
FLOOR = 1.9


def audit(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    slips = []
    for g in d.get("groups") or []:
        gname = g.get("group_name") or ""
        for t in g.get("tickets") or []:
            px = float(
                t.get("power_payout")
                or t.get("display_min_x")
                or (t.get("payout") or {}).get("display_min_x")
                or (t.get("payout") or {}).get("min_payout_x")
                or g.get("power_payout")
                or 0
            )
            n = int(t.get("n_legs") or g.get("n_legs") or 0)
            slips.append({"group": gname, "n_legs": n, "power_payout": px})
    below = [s for s in slips if s["power_payout"] > 0 and s["power_payout"] < FLOOR]
    unknown = [s for s in slips if s["power_payout"] <= 0]
    by_legs = Counter(s["n_legs"] for s in slips)
    ge19 = [s for s in slips if s["power_payout"] >= FLOOR]
    return {
        "path": str(path),
        "date": d.get("date"),
        "generated_at": d.get("generated_at"),
        "preferred_min_payout_x": d.get("preferred_min_payout_x"),
        "short_floor_hard_x": d.get("short_floor_hard_x"),
        "n_groups": len(d.get("groups") or []),
        "n_slips": len(slips),
        "n_ge_1_9": len(ge19),
        "n_below_1_9": len(below),
        "n_unknown_payout": len(unknown),
        "by_legs": dict(sorted(by_legs.items())),
        "below_sample": below[:10],
        "payout_sample": sorted({round(s["power_payout"], 2) for s in slips if s["power_payout"] > 0})[:20],
        "ok_date": d.get("date") == DATE,
        "ok_floor_meta": float(d.get("preferred_min_payout_x") or 0) >= FLOOR
        and float(d.get("short_floor_hard_x") or 0) >= FLOOR,
        "ok_no_subfloor": len(below) == 0,
        "ok_few_long": by_legs.get(6, 0) == 0 and by_legs.get(5, 0) <= max(2, len(slips) // 10),
    }


def main() -> int:
    reports = []
    for root in ROOTS:
        p = root / "ui_runner/templates/tickets_latest.json"
        if p.exists():
            reports.append(audit(p))
    print(json.dumps(reports, indent=2))
    if not reports:
        print("NO tickets_latest found", file=sys.stderr)
        return 2
    # Prefer feature repo report
    r = reports[0]
    fails = []
    if not r["ok_date"]:
        fails.append(f"date={r['date']} want {DATE}")
    if not r["ok_floor_meta"]:
        fails.append(
            f"meta floors preferred={r['preferred_min_payout_x']} hard={r['short_floor_hard_x']}"
        )
    if not r["ok_no_subfloor"]:
        fails.append(f"{r['n_below_1_9']} slips below {FLOOR}x")
    if not r["ok_few_long"]:
        fails.append(f"too many long legs: {r['by_legs']}")
    if fails:
        print("FAIL:", "; ".join(fails), file=sys.stderr)
        return 1
    print("PASS guidelines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
