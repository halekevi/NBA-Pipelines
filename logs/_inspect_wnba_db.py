import sqlite3
from pathlib import Path

db = Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\data\cache\proporacle_ref.db")
con = sqlite3.connect(db)
tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables", [t for t in tabs if "wnba" in t.lower()][:40])
cols = [c[1] for c in con.execute("PRAGMA table_info(wnba)").fetchall()]
print("wnba cols", cols)
print("n", con.execute("SELECT COUNT(*) FROM wnba").fetchone())
print("teams", con.execute("SELECT DISTINCT team FROM wnba ORDER BY 1").fetchall())
print("dates", con.execute("SELECT MIN(game_date), MAX(game_date) FROM wnba").fetchone())
print("opp cols", [c for c in cols if "opp" in c.lower()])
row = con.execute("SELECT * FROM wnba LIMIT 1").fetchone()
print(dict(zip(cols, row)))
