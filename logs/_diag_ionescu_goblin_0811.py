#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
s = json.loads((ROOT / "ui_runner/templates/slate_latest.json").read_text(encoding="utf-8"))
rows = s.get("sports", {}).get("wnba") or []
hits = [
    r
    for r in rows
    if "ionescu" in str(r.get("player") or "").lower() and str(r.get("prop")) == "Pts+Rebs+Asts"
]
print("Ionescu PRA lines:")
for r in sorted(hits, key=lambda x: (str(x.get("pick_type")), float(x.get("line") or 0))):
    print(
        f"  {r.get('pick_type'):8} {r.get('dir'):5} {r.get('line')}  "
        f"std={r.get('standard_line')} edge={r.get('edge')} "
        f"stat={r.get('stat_def_tier')}/{r.get('stat_def_rank')} "
        f"overall={r.get('def_tier')}/{r.get('opponent_def_rank')}"
    )

# Goblins harder than standard (bug / junk alts)
junk = []
for r in rows:
    if str(r.get("pick_type")) != "Goblin":
        continue
    if str(r.get("dir") or "").upper()[:1] != "O":
        continue
    try:
        line = float(r.get("line"))
        std = float(r.get("standard_line"))
    except (TypeError, ValueError):
        continue
    if line > std + 0.25:
        junk.append((r.get("player"), r.get("prop"), line, std, r.get("edge")))
junk.sort(key=lambda x: -(x[2] - x[3]))
print(f"\nWNBA Goblin OVER lines ABOVE standard: {len(junk)}")
for row in junk[:15]:
    print(f"  {row[0]} | {row[1]} Gob O {row[2]} (std {row[3]}) edge={row[4]}")
