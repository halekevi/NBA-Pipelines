import json
from pathlib import Path

d = json.loads(
    Path("data/reports/sport_prop_lift_30d.json").read_text(encoding="utf-8")
)
rows = d["prop_rows"]


def show(sport, min_n=30):
    xs = sorted(
        [r for r in rows if r["sport"] == sport],
        key=lambda r: (-(r["live"]["n"] or 0), -(r["base"]["n"] or 0)),
    )
    print(f"\n=== {sport} ===")
    for r in xs:
        if r["base"]["n"] < min_n and (r["live"]["n"] or 0) < 15:
            continue
        live = r["live"]
        lh = f"{live['hr']}%" if live["hr"] is not None else "—"
        print(
            f"{r['prop'][:28]:28} {r['pick'][:3]:3} {r['direction']:5} "
            f"base={r['base']['hr']:5}%/{r['base']['n']:<5} "
            f"live={lh:>6}/{live['n']:<4} "
            f"lift={str(r['live_lift_pts']):>5} "
            f"oppΔ={r['opp_aligned_delta_pts']} "
            f"H={r['hard']['hr']}%/{r['hard']['n']} E={r['easy']['hr']}%/{r['easy']['n']}"
        )


for sp in ["MLB", "WNBA", "SOCCER", "TENNIS"]:
    show(sp)
