import json
from pathlib import Path
from collections import Counter
p=Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\ui_runner\templates\slate_sport_wnba.json")
rows=json.loads(p.read_text(encoding="utf-8"))["rows"]
paige=[r for r in rows if "Paige" in str(r.get("player") or "")]
print("paige rows", len(paige))
if paige:
    print("sample keys", sorted(paige[0].keys())[:40])
    c=Counter(str(r.get("prop_type") or r.get("Prop") or r.get("prop") or "") for r in paige)
    print("prop_type counts", c.most_common(15))
    for r in paige:
        pt=str(r.get("prop_type") or r.get("Prop") or "")
        if "Point" in pt and "Combo" not in pt and "+" not in pt:
            print(r.get("player"), pt, r.get("line"), r.get("pick_type") or r.get("Pick Type"), r.get("standard_line"), r.get("game_date"))
