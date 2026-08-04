#!/usr/bin/env python3
"""Print compact top line-class consistency leaders for deliverable."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
d = json.loads((REPO / "data" / "reports" / "consistency_leaders_tables_latest.json").read_text(encoding="utf-8"))

for sport, props in d["tables"].items():
    info = d["sports"][sport]
    by_pc = info.get("by_pick_class") or {}
    print(
        f"==== {sport} from={info['from']} first={info['first_graded']} "
        f"n_leaders={info['n_leaders']} classes={by_pc} ===="
    )
    flat = []
    for prop, classes in props.items():
        for pick_class, cell in classes.items():
            badge = cell.get("badge") or pick_class
            for r in cell.get("rows") or []:
                flat.append((float(r["hit_rate"]) * float(r["sample_n"]), badge, pick_class, prop, r))
    flat.sort(key=lambda x: -x[0])
    for _, badge, pick_class, prop, r in flat[:12]:
        line = r.get("reference_line", r.get("line"))
        line_s = f"{line:.1f}" if line is not None else "?"
        print(
            f"  {badge:3s} {pick_class:15s} {prop:22s} {r['player'][:28]:28s} "
            f"@{line_s:>5s} HR={r['hit_rate']*100:5.1f}% n={r['sample_n']}"
        )
    print()
