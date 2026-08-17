import json
from pathlib import Path
p=Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\ui_runner\templates\slate_sport_wnba.json")
data=json.loads(p.read_text(encoding="utf-8"))
rows=data.get("rows") or data.get("props") or []
if isinstance(data, dict) and "sports" in data:
    rows=data["sports"].get("wnba") or []
print("type", type(data), "keys", list(data)[:8] if isinstance(data,dict) else "")
print("nrows", len(rows))
pts=[]
for r in rows:
    if not isinstance(r,dict): continue
    pl=str(r.get("player") or "")
    prop=str(r.get("prop_norm") or r.get("prop_type") or "").lower()
    if "Paige" in pl and prop in ("pts","points"):
        pts.append((pl, r.get("line"), r.get("pick_type"), r.get("standard_line"), r.get("game_date")))
print("Paige pts", len(pts))
for t in sorted(pts, key=lambda x: float(x[1] or 0)):
    print(t)
aja=[r for r in rows if isinstance(r,dict) and "ja Wilson" in str(r.get("player") or "")]
print("Aja any props", len(aja))
