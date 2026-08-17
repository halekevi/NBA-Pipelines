import json
from pathlib import Path
rows=json.loads(Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\ui_runner\templates\slate_sport_wnba.json").read_text(encoding="utf-8"))["rows"]
paige=[r for r in rows if "Paige" in str(r.get("player") or "")]
print(repr(paige[0].get("player")))
pts=[r for r in paige if "Points" == str(r.get("prop_type"))]
print("exact Points", len(pts))
pts2=[r for r in paige if "point" in str(r.get("prop_type") or "").lower()]
print("any point", len(pts2))
for r in pts2[:12]:
    print(repr(r.get("prop_type")), r.get("line"), r.get("pick_type"), r.get("standard_line"), r.get("game_date"))
# show all keys containing pick
print([k for k in paige[0] if "pick" in k.lower() or "type" in k.lower() or "line" in k.lower()])
