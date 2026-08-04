#!/usr/bin/env python3
"""Print compact top consistency leaders for deliverable."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
d = json.loads((REPO / "data" / "reports" / "consistency_leaders_tables_latest.json").read_text(encoding="utf-8"))

for sport, props in d["tables"].items():
    info = d["sports"][sport]
    print(f"==== {sport} from={info['from']} first={info['first_graded']} n_leaders={info['n_leaders']} ====")
    flat = []
    for prop, dirs in props.items():
        for direction, picks in dirs.items():
            for pick, rows in picks.items():
                for r in rows:
                    flat.append((float(r["hit_rate"]) * float(r["sample_n"]), pick, direction, prop, r))
    flat.sort(key=lambda x: -x[0])
    for _, pick, direction, prop, r in flat[:12]:
        line = r["line"]
        line_s = f"{line:.1f}" if line is not None else "?"
        demon = " [Demon-only]" if r.get("demon_only") else ""
        print(
            f"  {pick:8s} {direction:5s} {prop:22s} {r['player'][:28]:28s} "
            f"@{line_s:>5s} HR={r['hit_rate']*100:5.1f}% n={r['sample_n']}{demon}"
        )
    print()
