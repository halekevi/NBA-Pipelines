import json
from pathlib import Path
rows=json.loads(Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\ui_runner\templates\slate_sport_wnba.json").read_text(encoding="utf-8"))["rows"]
paige=[r for r in rows if "Paige Bueckers" == str(r.get("player") or "")]
print("solo paige", len(paige))
from collections import Counter
print(Counter(repr(r.get("prop_type")) for r in paige).most_common(20))
for r in paige:
    if "Point" in str(r.get("prop_type") or ""):
        print(r.get("prop_type"), r.get("line"), r.get("pick_type"), r.get("standard_line"), r.get("game_date"), r.get("dir"))
