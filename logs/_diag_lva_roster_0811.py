#!/usr/bin/env python3
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
c = pd.read_csv(ROOT / "Sports/WNBA/wnba_espn_cache.csv", encoding="utf-8-sig")
print("date col present", [x for x in c.columns if "date" in x.lower()])
c["game_date"] = pd.to_datetime(c["game_date"], errors="coerce")

names = ["Jackie Young", "NaLyssa Smith", "Jewell Loyd", "Stephanie Talbot", "Chelsea Gray"]
for n in names:
    sub = c[c["PLAYER_NAME"].astype(str) == n].sort_values("game_date")
    print("====", n, "n=", len(sub), "====")
    print(sub.tail(6)[["game_date", "TEAM", "PTS", "event_id"]].to_string(index=False))
    print("teams", dict(sub["TEAM"].astype(str).str.upper().value_counts()))

slate = json.loads((ROOT / "ui_runner/templates/slate_sport_wnba.json").read_text(encoding="utf-8"))
rows = slate if isinstance(slate, list) else (slate.get("rows") or slate.get("props") or slate.get("picks") or [])
if isinstance(slate, dict) and not rows:
    # try sports.wnba
    rows = (slate.get("sports") or {}).get("wnba") or slate.get("data") or []
print("slate type", type(slate), "rows", len(rows) if hasattr(rows, "__len__") else rows)
# sample keys
if isinstance(rows, list) and rows:
    print("sample keys", list(rows[0].keys())[:20] if isinstance(rows[0], dict) else type(rows[0]))
for n in names:
    hits = [r for r in rows if isinstance(r, dict) and n.lower() in str(r.get("player") or "").lower()]
    teams = sorted({str(r.get("team")) for r in hits})
    print("slate", n, "n=", len(hits), "teams", teams)
