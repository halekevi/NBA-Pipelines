import json
from pathlib import Path
rows=json.loads(Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\ui_runner\templates\slate_sport_wnba.json").read_text(encoding="utf-8"))["rows"]
paige=[r for r in rows if str(r.get("player") or "")=="Paige Bueckers"][0]
for k,v in sorted(paige.items()):
    if v not in (None,"",[],{}):
        print(f"{k}={v!r}"[:120])
