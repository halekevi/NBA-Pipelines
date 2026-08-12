import json
from pathlib import Path

d = json.loads(
    Path("data/reports/wnba_prop_specific_def_lift_30d.json").read_text(encoding="utf-8")
)
want = [
    "Free Throws Made",
    "Free Throws Attempted",
    "Two Pointers Made",
    "Two Pointers Attempted",
    "FG Made",
    "FG Attempted",
    "3-PT Made",
    "3-PT Attempted",
]
rows = [c for c in d["contrasts"] if c["prop"] in want]
print("n contrasts", len(rows))
print("available shooting props", sorted({c["prop"] for c in d["contrasts"] if any(t in c["prop"] for t in ("Free", "Two", "FG", "3-PT", "Pointer"))}))
for c in sorted(rows, key=lambda x: (x["prop"], x["pick"], x["direction"], x["live"])):
    print(
        f"{c['prop'][:26]:26} {c['pick'][:3]:3} {c['direction']:5} "
        f"{'LIVE' if c['live'] else 'ALL ':4} "
        f"statΔ={c['stat_aligned_delta']} ovΔ={c['overall_aligned_delta']} "
        f"H={c['stat_hard']['hr']}%/{c['stat_hard']['n']} "
        f"E={c['stat_easy']['hr']}%/{c['stat_easy']['n']} "
        f"any={c['any']['hr']}%/{c['any']['n']}"
    )

# also check if defense file has ftm/fta/fg2 ranks
import pandas as pd

df = pd.read_csv("Sports/WNBA/data/wnba_defense_by_stat.csv")
cols = [c for c in df.columns if any(x in c for x in ("ftm", "fta", "fg2", "fgm", "fga", "fg3"))]
print("defense cols", cols)
