import json
from pathlib import Path
from collections import Counter

def load_rows(name):
    p=Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\ui_runner\templates")/name
    print(name, "mtime", p.stat().st_mtime)
    return json.loads(p.read_text(encoding="utf-8")).get("rows") or []

wnba=load_rows("slate_sport_wnba.json")
pts=[r for r in wnba if r.get("player")=="Paige Bueckers" and r.get("prop")=="Points"]
print("WNBA Paige Points:")
for r in sorted(pts, key=lambda x: float(x.get("line") or 0)):
    print(r.get("line"), r.get("pick_type"), "std", r.get("standard_line"), r.get("game_date"))

ten=load_rows("slate_sport_tennis.json")
print("tennis rows", len(ten))
print("game_date counts", Counter(str(r.get("game_date"))[:10] for r in ten).most_common(8))
# sample players
print("sample players", sorted({r.get("player") for r in ten})[:20])
# Pablo?
pablo=[r for r in ten if r.get("player") and "Pablo" in str(r.get("player"))]
print("Pablo rows", len(pablo), [r.get("player") for r in pablo[:5]])
jodar=[r for r in ten if r.get("player") and "Jodar" in str(r.get("player"))]
print("Jodar", [(r.get("prop"), r.get("line"), r.get("pick_type"), r.get("l5_over"), r.get("game_date")) for r in jodar[:12]])
