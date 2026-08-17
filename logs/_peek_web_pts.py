import json
from pathlib import Path
rows=json.loads(Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\ui_runner\templates\slate_sport_wnba.json").read_text(encoding="utf-8"))["rows"]
for r in rows:
    if r.get("player")=="Paige Bueckers" and r.get("prop")=="Points":
        print(r.get("line"), r.get("pick_type"), r.get("standard_line"), r.get("game_date"), r.get("dir"), r.get("tier"))
