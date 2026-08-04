#!/usr/bin/env python3
"""
Backfill MLB Stats API game logs into:
  - Sports/MLB/mlb_stats_cache.csv
  - data/cache/proporacle_ref.db table ``mlb_gamelog``

Skips configured All-Star break dates (utils.allstar_filter) and AL/NL
exhibition squads. Designed to fill gaps from season opener through yesterday.

Example:
  py -3.14 scripts/backfill_mlb_gamelog_range.py --from 2026-03-25 --to 2026-08-03
  py -3.14 scripts/backfill_mlb_gamelog_range.py --from 2026-07-30 --to 2026-08-03 --limit-players 50
"""

from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.db_utils import ensure_mlb_schema, find_db_path, open_db, upsert_rows  # noqa: E402
from utils.allstar_filter import (  # noqa: E402
    allstar_date_exclusion_sql,
    drop_allstar_game_rows,
    is_allstar_date,
)


def _load_mlb_step4():
    path = REPO / "Sports" / "MLB" / "scripts" / "step4_attach_player_stats_mlb.py"
    spec = importlib.util.spec_from_file_location("mlb_step4_stats", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _parse_ymd(s: str) -> date:
    return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()


def _mirror_cache_to_db(con: sqlite3.Connection, cache: pd.DataFrame, season: str) -> int:
    """Upsert cache rows for ``season`` into mlb_gamelog (ASG dates already purged)."""
    if cache is None or cache.empty:
        return 0
    sub = cache.loc[cache["SEASON"].astype(str) == str(season)].copy()
    if sub.empty:
        return 0
    sub, _ = drop_allstar_game_rows(sub, sport="MLB")
    if sub.empty:
        return 0
    ts = datetime.now(timezone.utc).isoformat()
    rows = []
    for _, r in sub.iterrows():
        try:
            val = float(r.get("STAT_VALUE"))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "mlb_player_id": str(r.get("MLB_PLAYER_ID", "")).strip(),
                "season": str(r.get("SEASON", "")).strip(),
                "game_date": str(r.get("GAME_DATE", "")).strip()[:10],
                "game_id": str(r.get("GAME_ID", "")).strip(),
                "player_type": str(r.get("PLAYER_TYPE", "")).strip() or None,
                "prop_norm": str(r.get("PROP_NORM", "")).strip(),
                "stat_value": val,
                "updated_at": ts,
            }
        )
    if not rows:
        return 0
    # Chunk upserts
    n = 0
    chunk = 5000
    for i in range(0, len(rows), chunk):
        upsert_rows(con, "mlb_gamelog", rows[i : i + chunk])
        n += len(rows[i : i + chunk])
    return n


def _db_snapshot(con: sqlite3.Connection, d0: str, d1: str) -> dict:
    date_sql, date_params = allstar_date_exclusion_sql("MLB", date_col="game_date")
    cur = con.cursor()
    mn, mx, n, nd = cur.execute(
        f"""
        SELECT MIN(game_date), MAX(game_date), COUNT(*), COUNT(DISTINCT game_date)
        FROM mlb_gamelog
        WHERE game_date BETWEEN ? AND ?
          AND ({date_sql})
        """,
        (d0, d1) + tuple(date_params),
    ).fetchone()
    asg = cur.execute(
        """
        SELECT game_date, COUNT(*) FROM mlb_gamelog
        WHERE game_date BETWEEN '2026-07-13' AND '2026-07-15'
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    # calendar gaps (non-ASG) inside window
    present = {
        r[0]
        for r in cur.execute(
            f"""
            SELECT DISTINCT game_date FROM mlb_gamelog
            WHERE game_date BETWEEN ? AND ?
              AND ({date_sql})
            """,
            (d0, d1) + tuple(date_params),
        ).fetchall()
    }
    gaps = []
    cur_d = _parse_ymd(d0)
    end = _parse_ymd(d1)
    while cur_d <= end:
        ds = cur_d.isoformat()
        if not is_allstar_date(ds, "MLB") and ds not in present:
            gaps.append(ds)
        cur_d += timedelta(days=1)
    return {
        "min": mn,
        "max": mx,
        "rows": int(n or 0),
        "distinct_dates": int(nd or 0),
        "asg_rows": asg,
        "gaps": gaps,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill MLB gamelog cache + DB, skipping ASG break.")
    ap.add_argument("--from", dest="date_from", default="2026-03-25", help="Season opener / start YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", default="2026-08-03", help="End YYYY-MM-DD (inclusive)")
    ap.add_argument("--season", default="2026")
    ap.add_argument(
        "--cache",
        default=str(REPO / "Sports" / "MLB" / "mlb_stats_cache.csv"),
        help="Path to mlb_stats_cache.csv",
    )
    ap.add_argument(
        "--id-cache",
        default=str(REPO / "Sports" / "MLB" / "mlb_id_cache.csv"),
        help="Player id cache (mlb_player_id column)",
    )
    ap.add_argument("--db", default="", help="Override proporacle_ref.db path")
    ap.add_argument("--n-games", type=int, default=200, help="Max new games to pull per player refresh")
    ap.add_argument("--limit-players", type=int, default=0, help="Debug: only first N player ids")
    ap.add_argument("--sleep", type=float, default=0.15, help="Sleep between API player refreshes")
    ap.add_argument("--mirror-only", action="store_true", help="Skip API refresh; purge ASG + mirror cache→DB")
    args = ap.parse_args()

    d0 = str(args.date_from).strip()[:10]
    d1 = str(args.date_to).strip()[:10]
    season = str(args.season).strip()
    cache_path = Path(args.cache)
    id_path = Path(args.id_cache)
    db_path = Path(args.db) if args.db else find_db_path(REPO)
    mod = _load_mlb_step4()

    con = open_db(db_path)
    ensure_mlb_schema(con)
    before = _db_snapshot(con, d0, d1)
    print(f"BEFORE window {d0}..{d1}: rows={before['rows']} dates={before['distinct_dates']} "
          f"min={before['min']} max={before['max']}")
    print(f"  ASG Jul13-15 rows: {before['asg_rows']}")
    print(f"  non-ASG gaps ({len(before['gaps'])}): {before['gaps'][:20]}{'...' if len(before['gaps'])>20 else ''}")

    cache = mod.load_cache(cache_path)
    n0 = len(cache)
    cache, n_as = drop_allstar_game_rows(cache, sport="MLB")
    if n_as:
        print(f"Purged {n_as} All-Star break row(s) from cache ({n0} → {len(cache)})")
        mod.save_cache(cache, cache_path)

    # Also delete any ASG rows already in DB
    date_sql, date_params = allstar_date_exclusion_sql("MLB", date_col="game_date")
    # Invert: delete rows that fail the keep predicate → delete inside windows
    deleted = 0
    for start_s, end_s in (
        ("2025-07-14", "2025-07-17"),
        ("2026-07-13", "2026-07-15"),
    ):
        cur = con.execute(
            "DELETE FROM mlb_gamelog WHERE game_date BETWEEN ? AND ?",
            (start_s, end_s),
        )
        deleted += cur.rowcount or 0
    if deleted:
        con.commit()
        print(f"Deleted {deleted} mlb_gamelog ASG-break row(s) from DB")

    if not args.mirror_only:
        ids = pd.read_csv(id_path, low_memory=False)
        id_col = "mlb_player_id" if "mlb_player_id" in ids.columns else "MLB_PLAYER_ID"
        type_col = next((c for c in ("player_type", "PLAYER_TYPE") if c in ids.columns), None)
        pids = (
            ids[id_col]
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        if args.limit_players and args.limit_players > 0:
            pids = pids[: int(args.limit_players)]
        print(f"Refreshing game logs for {len(pids)} player(s), season={season}…")
        refreshed = 0
        added_games = 0
        for i, pid in enumerate(pids, 1):
            # Prefer hitter then pitcher so both groups land when id cache lacks type.
            types = []
            if type_col:
                t = str(ids.loc[ids[id_col].astype(str) == str(pid), type_col].iloc[0] or "").lower()
                if t in ("hitter", "pitcher"):
                    types = [t]
            if not types:
                types = ["hitter", "pitcher"]
            for ptype in types:
                try:
                    cache, added = mod.update_cache(
                        cache, str(pid), ptype, season, int(args.n_games)
                    )
                    if added:
                        added_games += int(added)
                        refreshed += 1
                except Exception as e:
                    print(f"  warn pid={pid} type={ptype}: {type(e).__name__}: {e}")
            if i % 50 == 0 or i == len(pids):
                print(f"  … {i}/{len(pids)} players (cache rows={len(cache)})")
                mod.save_cache(cache, cache_path)
            if args.sleep > 0:
                time.sleep(float(args.sleep))
        cache, n_as2 = drop_allstar_game_rows(cache, sport="MLB")
        if n_as2:
            print(f"Post-refresh ASG purge: {n_as2} row(s)")
        mod.save_cache(cache, cache_path)
        print(f"API refresh done: players_touched≈{refreshed} new_games≈{added_games}")

    print("Mirroring cache → mlb_gamelog…")
    cache, _ = drop_allstar_game_rows(cache, sport="MLB")
    sub = cache.loc[cache["SEASON"].astype(str) == str(season)].copy()
    if sub.empty:
        print("Upserted 0 row(s) into mlb_gamelog")
    else:
        sub["STAT_VALUE_NUM"] = pd.to_numeric(sub["STAT_VALUE"], errors="coerce")
        sub = sub.dropna(subset=["STAT_VALUE_NUM"])
        sub["game_date"] = sub["GAME_DATE"].astype(str).str[:10]
        sub = sub[~sub["game_date"].map(lambda x: is_allstar_date(x, "MLB"))]
        ts = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "mlb_player_id": str(r.MLB_PLAYER_ID).strip(),
                "season": str(season),
                "game_date": str(r.game_date)[:10],
                "game_id": str(r.GAME_ID).strip(),
                "player_type": (str(r.PLAYER_TYPE).strip() or None),
                "prop_norm": str(r.PROP_NORM).strip(),
                "stat_value": float(r.STAT_VALUE_NUM),
                "updated_at": ts,
            }
            for r in sub.itertuples(index=False)
        ]
        n_up = 0
        for i in range(0, len(rows), 8000):
            upsert_rows(con, "mlb_gamelog", rows[i : i + 8000])
            n_up += len(rows[i : i + 8000])
        con.commit()
        print(f"Upserted {n_up} row(s) into mlb_gamelog")

    after = _db_snapshot(con, d0, d1)
    print(f"AFTER window {d0}..{d1}: rows={after['rows']} dates={after['distinct_dates']} "
          f"min={after['min']} max={after['max']}")
    print(f"  ASG Jul13-15 rows: {after['asg_rows']}")
    print(f"  remaining non-ASG gaps ({len(after['gaps'])}): {after['gaps'][:30]}")
    con.close()


if __name__ == "__main__":
    main()
