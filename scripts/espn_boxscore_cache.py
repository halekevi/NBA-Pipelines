"""ESPN boxscore row cache in proporacle_ref.db.

Same process as WNBA/MLB step4: SQLite is the operational store. CSV is
backfill only. Payload is JSON so CFB / NFL / CBB column sets can differ.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.db_utils import open_db

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS espn_boxscore_rows (
    sport       TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    player_key  TEXT NOT NULL,
    game_date   TEXT,
    payload     TEXT NOT NULL,
    PRIMARY KEY (sport, event_id, player_key)
);
"""


def sport_key_from_espn_league(league: str) -> str:
    s = str(league or "").strip().lower()
    if s == "nfl":
        return "nfl"
    if "wocollege-basketball" in s or "womens-college-basketball" in s:
        return "wcbb"
    if "basketball" in s:
        return "cbb"
    return "cfb"


def _player_key(row: dict[str, Any]) -> str:
    aid = str(row.get("espn_athlete_id") or "").strip()
    if aid:
        return aid
    return str(row.get("player_norm") or "").strip()


def ensure_schema(con) -> None:
    con.execute(CREATE_SQL)
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_espn_box_sport_date "
        "ON espn_boxscore_rows (sport, game_date)"
    )
    con.commit()


def rowcount(con, sport: str) -> int:
    try:
        return int(
            con.execute(
                "SELECT COUNT(*) FROM espn_boxscore_rows WHERE sport = ?",
                (sport,),
            ).fetchone()[0]
        )
    except Exception:
        return 0


def upsert_rows(con, sport: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    ensure_schema(con)
    data = []
    for rec in rows:
        pk = _player_key(rec)
        eid = str(rec.get("event_id") or "").strip()
        if not pk or not eid:
            continue
        data.append(
            (
                sport,
                eid,
                pk,
                str(rec.get("game_date") or "").strip(),
                json.dumps(rec, default=str),
            )
        )
    if not data:
        return 0
    with con:
        con.executemany(
            "INSERT OR REPLACE INTO espn_boxscore_rows "
            "(sport, event_id, player_key, game_date, payload) VALUES (?,?,?,?,?)",
            data,
        )
    return len(data)


def load_rows(con, sport: str, *, since_date: str | None = None) -> list[dict[str, Any]]:
    ensure_schema(con)
    if since_date:
        cur = con.execute(
            "SELECT payload FROM espn_boxscore_rows WHERE sport = ? AND game_date >= ?",
            (sport, str(since_date).strip()),
        )
        rows = [json.loads(r[0]) for r in cur.fetchall() if r and r[0]]
        if rows:
            return rows
    cur = con.execute(
        "SELECT payload FROM espn_boxscore_rows WHERE sport = ?",
        (sport,),
    )
    return [json.loads(r[0]) for r in cur.fetchall() if r and r[0]]


def load_boxscore_cache(
    sport: str,
    cache_path: str,
    *,
    since_date: str | None = None,
    min_db_rows: int = 200,
) -> tuple[list[dict[str, Any]], str]:
    """Return (rows, source) where source is 'db' | 'csv' | 'empty'."""
    con = open_db()
    ensure_schema(con)
    n = rowcount(con, sport)
    if n >= min_db_rows:
        rows = load_rows(con, sport, since_date=since_date)
        if rows:
            print(f"  [CACHE] {len(rows)} rows from proporacle_ref.db espn_boxscore_rows sport={sport}")
            return rows, "db"

    path = Path(cache_path) if cache_path else None
    if path and path.is_file():
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
            rows = df.to_dict("records")
            print(f"  [CACHE] {len(rows)} rows from {path.name}")
            if rows:
                upsert_rows(con, sport, rows)
            return rows, "csv"
        except Exception as exc:
            print(f"  [CACHE] CSV load failed ({exc})")
    return [], "empty"


def save_boxscore_cache(
    sport: str,
    all_rows: list[dict[str, Any]],
    cache_path: str,
    source: str,
    *,
    new_rows: list[dict[str, Any]] | None = None,
) -> None:
    con = open_db()
    n = upsert_rows(con, sport, all_rows)
    if n:
        print(f"  [CACHE] Upserted {n} rows → espn_boxscore_rows sport={sport}")
    if source == "db":
        return
    if cache_path and all_rows:
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(all_rows).to_csv(cache_path, index=False)
            print(f"  [CACHE] Saved {len(all_rows)} rows -> {cache_path}")
        except Exception as exc:
            print(f"  [CACHE] CSV save failed: {exc}")
