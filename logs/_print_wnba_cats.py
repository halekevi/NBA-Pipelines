import json
from pathlib import Path

d = json.loads(
    Path("data/reports/sport_prop_category_coverage_30d.json").read_text(encoding="utf-8")
)
rows = d["by_sport"]["WNBA"]["rows"]
for r in rows:
    g = r["goblin_over"]
    gl = r["goblin_over_live"]
    s = r["standard_over"]
    su = r["standard_under"]
    print(
        f"{r['prop']}|{r['status']}|{g['hr']}|{g['n']}|{gl['hr']}|{gl['n']}|{r['goblin_live_lift']}|{s['hr']}|{s['n']}|{su['hr']}|{su['n']}|{r['rows']}"
    )
