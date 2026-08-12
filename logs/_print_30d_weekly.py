"""Weekly aggregates for 30d canvas."""
import json
from collections import defaultdict
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
# ISO week label by first day of week in window
weeks = defaultdict(lambda: {k: {"h": 0, "n": 0} for k in keys})
for day in d["daily"]:
    # group by week starting Sat-ish — use date prefix YYYY-Www via monday
    from datetime import date

    dt = date.fromisoformat(day["date"])
    week_start = (dt.toordinal() - (dt.weekday()))  # Monday
    label = date.fromordinal(week_start).isoformat()
    for k in keys:
        cell = day.get(k)
        if not cell:
            continue
        weeks[label][k]["h"] += int(round(cell["hr"] * cell["n"] / 100.0))
        weeks[label][k]["n"] += cell["n"]

print("week," + ",".join(keys) + "," + ",".join(k + "_n" for k in keys))
for w in sorted(weeks):
    row = [w]
    ns = []
    for k in keys:
        h, n = weeks[w][k]["h"], weeks[w][k]["n"]
        row.append(f"{100*h/n:.1f}" if n else "")
        ns.append(str(n))
    print(",".join(row + ns))
