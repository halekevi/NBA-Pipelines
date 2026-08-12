"""Extract daily series for 30d lift canvas."""
import json
from pathlib import Path

d = json.loads(Path("data/reports/standard_direction_lift_30d.json").read_text(encoding="utf-8"))
keys = [
    "GOBLIN|OVER",
    "GOBLIN|OVER|L5>=4+L10>=8",
    "STANDARD|OVER",
    "STANDARD|OVER|L5>=3+L10>=8",
    "STANDARD|UNDER",
    "STANDARD|UNDER|L10>=8",
]
print("date," + ",".join(keys))
for day in d["daily"]:
    row = [day["date"]]
    for k in keys:
        cell = day.get(k)
        if not cell or cell.get("n", 0) < 5:
            row.append("")
        else:
            row.append(str(cell["hr"]))
    print(",".join(row))
