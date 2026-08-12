"""Inventory defense / box-log sources for prop-specific opp ranks."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "cache" / "proporacle_ref.db"

print("DB exists:", DB.is_file(), DB)
if DB.is_file():
    con = sqlite3.connect(str(DB))
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
    print("tables:", tables)
    for t in tables:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            cols = [r[1] for r in con.execute(f"PRAGMA table_info([{t}])").fetchall()]
            print(f"  {t}: n={n} cols={cols[:25]}{'...' if len(cols)>25 else ''}")
        except Exception as e:
            print(f"  {t}: ERR {e}")
    con.close()

for rel in [
    "Sports/NFL/data/defense_rankings.csv",
    "Sports/MLB/mlb_defense_summary.csv",
    "Sports/WNBA/data/wnba_defense_by_stat.csv",
    "Sports/NBA/data/nba_opp_defense_by_position.json",
    "Sports/Soccer/step3_soccer_with_defense.csv",
    "Sports/NHL/step3_nhl_with_defense.csv",
]:
    p = ROOT / rel
    print(f"FILE {rel}: exists={p.is_file()} size={p.stat().st_size if p.is_file() else 0}")

cfb = ROOT / "Sports" / "CFB"
print("CFB dir:", cfb.is_dir())
if cfb.is_dir():
    for p in sorted(cfb.rglob("*"))[:40]:
        if p.is_file() and p.suffix.lower() in {".csv", ".json", ".py"}:
            print(" ", p.relative_to(ROOT), p.stat().st_size)
