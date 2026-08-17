import sqlite3
from pathlib import Path

p = Path("data/cache/proporacle_ref.db")
con = sqlite3.connect(str(p))
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("tables", tables)
n = con.execute("select count(*) from soccer").fetchone()[0]
d = con.execute(
    "select min(game_date), max(game_date), count(distinct game_date) from soccer"
).fetchone()
print("soccer_rows", n, "date_span", d)
print("teams", [r[0] for r in con.execute("select distinct team from soccer where team is not null limit 12")])
