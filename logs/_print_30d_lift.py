import json
from pathlib import Path

d = json.loads(
    Path("data/reports/standard_direction_lift_30d.json").read_text(encoding="utf-8")
)
print("days", d["n_days"], d["window"])
print("missing", ",".join(d["files_missing"]))
idx = {x["key"]: x for x in d["summary"]}
want = [
    "STANDARD|OVER",
    "STANDARD|UNDER",
    "GOBLIN|OVER",
    "GOBLIN|UNDER",
    "STANDARD|OVER|L5>=4",
    "STANDARD|OVER|L10>=8",
    "STANDARD|OVER|L5>=3+L10>=8",
    "STANDARD|OVER|L5>=4+L10>=8",
    "STANDARD|UNDER|L5>=4",
    "STANDARD|UNDER|L10>=8",
    "STANDARD|UNDER|L5>=4+L10>=8",
    "GOBLIN|OVER|L5>=4",
    "GOBLIN|OVER|L10>=8",
    "GOBLIN|OVER|L5>=4+L10>=8",
]
print("\nPOOL / GATE")
for k in want:
    if k in idx:
        x = idx[k]
        print(f"{k:40} {x['hr']:5}%  {x['hits']}/{x['n']}")
print("\nLIFTS VS BASE")
for x in d["lifts_vs_base"]:
    print(x)
print("\nSPORT n>=30")
rows = sorted(
    [x for x in d["sport_breakdown_min20"] if x["n"] >= 30],
    key=lambda x: (-x["n"], x["key"]),
)
for x in rows:
    print(f"{x['key']:60} {x['hr']:5}% n={x['n']}")
