import json
from pathlib import Path
rows=json.loads(Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\ui_runner\templates\slate_sport_wnba.json").read_text(encoding="utf-8"))["rows"]
for r in rows:
    if str(r.get("player"))=="Paige Bueckers" and str(r.get("prop_type"))=="Points":
        print({k:r.get(k) for k in ["player","prop_type","line","pick_type","Pick Type","standard_line","game_date","dir","tier"]})
