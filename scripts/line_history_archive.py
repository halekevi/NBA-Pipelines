#!/usr/bin/env python3
"""Append PrizePicks slate rows to data/line_history.db (cross-sport).

Keeps per-row fetched_at / pp_updated_at. After each pull, diffs the prior
snapshot and writes line_events: appeared, moved, cut, disappeared.

  py -3.14 scripts/line_history_archive.py --backfill-events --since 2026-08-17
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from utils.pp_fetch_stamp import stamp_fetched_at  # noqa: E402

ARCHIVE_DB = _REPO_ROOT / "data" / "line_history.db"

_ALIASES: dict[str, tuple[str, ...]] = {
    "projection_id": ("projection_id", "pp_projection_id", "proj_id"),
    "pp_projection_id": ("pp_projection_id", "projection_id", "proj_id"),
    "player": ("player", "player_name"),
    "prop_type": ("prop_type", "stat_type"),
    "pick_type": ("pick_type", "odds_type"),
    "line": ("line", "line_score"),
    "start_time": ("start_time", "game_start"),
    "opp_team": ("opp_team", "pp_opp_team"),
    "team": ("team", "pp_team"),
    "pp_game_id": ("pp_game_id", "game_id"),
}

_EXTRA_COLS = ("pp_updated_at",)

_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS line_events (
  sport TEXT NOT NULL,
  game_date TEXT,
  player TEXT,
  prop_type TEXT,
  projection_id TEXT,
  event TEXT NOT NULL,
  prev_pick TEXT,
  new_pick TEXT,
  prev_line REAL,
  new_line REAL,
  prev_fetched_at TEXT,
  fetched_at TEXT NOT NULL,
  start_time TEXT,
  team TEXT,
  opp_team TEXT,
  still_on_slate INTEGER
)
"""


def _first_col(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def _apply_aliases(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for dest, sources in _ALIASES.items():
        if dest in out.columns and not out[dest].isna().all():
            continue
        src = _first_col(out, sources)
        if src is None:
            continue
        if dest not in out.columns:
            out[dest] = out[src]
        else:
            blank = out[dest].isna() | (out[dest].astype(str).str.strip() == "")
            out.loc[blank, dest] = out.loc[blank, src]
    return out


def _ensure_columns(conn: sqlite3.Connection, cols: tuple[str, ...]) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(line_history)").fetchall()}
    if not existing:
        return
    for col in cols:
        if col in existing:
            continue
        conn.execute(f"ALTER TABLE line_history ADD COLUMN {col} TEXT")


def _ensure_events(conn: sqlite3.Connection) -> None:
    conn.execute(_EVENTS_DDL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_line_events_fetch "
        "ON line_events (sport, fetched_at, event)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_line_events_player "
        "ON line_events (sport, player, game_date)"
    )


def _fold(raw: object) -> str:
    return " ".join(str(raw or "").strip().lower().split())


def _pick(raw: object) -> str:
    t = str(raw or "").strip().lower()
    if "dem" in t:
        return "Demon"
    if "gob" in t:
        return "Goblin"
    if "std" in t or t == "standard":
        return "Standard"
    return str(raw or "").strip()


def _num(raw: object) -> float | None:
    try:
        if raw is None or str(raw).strip() == "":
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _gd(raw: object) -> str:
    return str(raw or "").strip()[:10]


def _rec_from_mapping(row: dict, sport: str) -> dict | None:
    player = str(row.get("player") or row.get("player_name") or "").strip()
    prop = str(row.get("prop_type") or row.get("stat_type") or "").strip()
    if not player or not prop:
        return None
    return {
        "sport": sport,
        "player": player,
        "prop_type": prop,
        "pick_type": _pick(row.get("pick_type") or row.get("odds_type")),
        "line": _num(row.get("line") if row.get("line") not in (None, "") else row.get("line_score")),
        "game_date": _gd(row.get("game_date")),
        "projection_id": str(row.get("projection_id") or row.get("proj_id") or "").strip(),
        "fetched_at": str(row.get("fetched_at") or "").strip(),
        "start_time": str(row.get("start_time") or row.get("game_start") or "").strip(),
        "team": str(row.get("team") or "").strip(),
        "opp_team": str(row.get("opp_team") or "").strip(),
    }


def records_from_df(df: pd.DataFrame, sport: str) -> list[dict]:
    out: list[dict] = []
    for row in df.to_dict("records"):
        rec = _rec_from_mapping(row, sport)
        if rec:
            out.append(rec)
    return out


def _pick_key(r: dict) -> tuple[str, str, str, str]:
    return (_fold(r["player"]), _fold(r["prop_type"]), r["pick_type"], r["game_date"])


def _mkt_key(r: dict) -> tuple[str, str, str]:
    return (_fold(r["player"]), _fold(r["prop_type"]), r["game_date"])


def diff_snapshots(prev: list[dict], curr: list[dict]) -> list[dict]:
    """appeared / moved / cut / disappeared between two pulls of the same sport."""
    if not prev:
        return []
    prev_ts = prev[0].get("fetched_at") or ""
    curr_ts = curr[0].get("fetched_at") or "" if curr else ""
    sport = (curr or prev)[0]["sport"]
    curr_dates = {r["game_date"] for r in curr if r.get("game_date")}

    prev_pick = {_pick_key(r): r for r in prev}
    curr_pick = {_pick_key(r): r for r in curr}
    curr_mkt: dict[tuple, list[dict]] = defaultdict(list)
    for r in curr:
        curr_mkt[_mkt_key(r)].append(r)

    events: list[dict] = []
    seen_curr: set[tuple] = set()
    seen_prev: set[tuple] = set()

    def emit(kind: str, before: dict | None, after: dict | None) -> None:
        src = after or before or {}
        gd = src.get("game_date") or ""
        events.append(
            {
                "sport": sport,
                "game_date": gd,
                "player": src.get("player") or "",
                "prop_type": src.get("prop_type") or "",
                "projection_id": (after or {}).get("projection_id")
                or (before or {}).get("projection_id")
                or "",
                "event": kind,
                "prev_pick": (before or {}).get("pick_type") or "",
                "new_pick": (after or {}).get("pick_type") or "",
                "prev_line": None if before is None else before.get("line"),
                "new_line": None if after is None else after.get("line"),
                "prev_fetched_at": (before or {}).get("fetched_at") or prev_ts,
                "fetched_at": curr_ts,
                "start_time": src.get("start_time") or "",
                "team": src.get("team") or "",
                "opp_team": src.get("opp_team") or "",
                "still_on_slate": 1 if gd and gd in curr_dates else 0,
            }
        )

    for key, now in curr_pick.items():
        then = prev_pick.get(key)
        if then is None:
            continue
        seen_curr.add(key)
        seen_prev.add(key)
        if then.get("line") != now.get("line"):
            emit("moved", then, now)

    for key, then in prev_pick.items():
        if key in seen_prev:
            continue
        alts = [
            r
            for r in curr_mkt.get(_mkt_key(then), [])
            if r.get("pick_type") != then.get("pick_type")
            and _pick_key(r) not in prev_pick
        ]
        if alts:
            now = alts[0]
            emit("cut", then, now)
            seen_curr.add(_pick_key(now))
            seen_prev.add(key)
        else:
            emit("disappeared", then, None)
            seen_prev.add(key)

    for key, now in curr_pick.items():
        if key in seen_curr:
            continue
        emit("appeared", None, now)

    return events


def _prev_clock(conn: sqlite3.Connection, sport: str, current_ts: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(fetched_at) FROM line_history WHERE sport = ? AND fetched_at < ?",
        (sport, current_ts),
    ).fetchone()
    ts = (row[0] if row else None) or ""
    return ts or None


def load_snapshot(conn: sqlite3.Connection, sport: str, fetched_at: str) -> list[dict]:
    cur = conn.execute(
        """
        SELECT projection_id, player, prop_type, pick_type, line, game_date,
               start_time, team, opp_team, fetched_at
        FROM line_history
        WHERE sport = ? AND fetched_at = ?
        """,
        (sport, fetched_at),
    )
    cols = (
        "projection_id",
        "player",
        "prop_type",
        "pick_type",
        "line",
        "game_date",
        "start_time",
        "team",
        "opp_team",
        "fetched_at",
    )
    out: list[dict] = []
    for tup in cur:
        rec = _rec_from_mapping(dict(zip(cols, tup)), sport)
        if rec:
            out.append(rec)
    return out


def write_events(
    conn: sqlite3.Connection,
    sport: str,
    fetched_at: str,
    events: list[dict],
) -> dict[str, int]:
    _ensure_events(conn)
    conn.execute(
        "DELETE FROM line_events WHERE sport = ? AND fetched_at = ?",
        (sport, fetched_at),
    )
    if events:
        conn.executemany(
            """
            INSERT INTO line_events (
              sport, game_date, player, prop_type, projection_id, event,
              prev_pick, new_pick, prev_line, new_line, prev_fetched_at,
              fetched_at, start_time, team, opp_team, still_on_slate
            ) VALUES (
              :sport, :game_date, :player, :prop_type, :projection_id, :event,
              :prev_pick, :new_pick, :prev_line, :new_line, :prev_fetched_at,
              :fetched_at, :start_time, :team, :opp_team, :still_on_slate
            )
            """,
            events,
        )
    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        counts[ev["event"]] += 1
    return dict(counts)


def record_events_for_pull(
    conn: sqlite3.Connection,
    sport: str,
    current: list[dict],
    pull_ts: str,
) -> dict[str, int]:
    prev_ts = _prev_clock(conn, sport, pull_ts)
    if not prev_ts or not current:
        return {}
    prev = load_snapshot(conn, sport, prev_ts)
    if not prev:
        return {}
    events = diff_snapshots(prev, current)
    return write_events(conn, sport, pull_ts, events)


def archive_lines(
    df: pd.DataFrame,
    sport: str,
    *,
    fetched_at: str | None = None,
    only_fetched_at: str | None = None,
) -> dict[str, int]:
    """Append one fetch snapshot and diff vs the previous pull. Returns event counts."""
    if df is None or df.empty:
        return {}
    out = _apply_aliases(df)
    if fetched_at:
        out = stamp_fetched_at(out, when=fetched_at, overwrite=True)
    else:
        out = stamp_fetched_at(out, overwrite=False)
    clock = (only_fetched_at or "").strip()
    if clock:
        out = out[out["fetched_at"].astype(str) == clock].copy()
        if out.empty:
            return {}
    if "pp_updated_at" not in out.columns:
        out["pp_updated_at"] = ""
    sport_u = str(sport).strip().upper()
    out["sport"] = sport_u
    pull_ts = str(out["fetched_at"].iloc[0])
    current = records_from_df(out, sport_u)
    ARCHIVE_DB.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with sqlite3.connect(ARCHIVE_DB) as conn:
        _ensure_columns(conn, _EXTRA_COLS)
        table_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(line_history)").fetchall()
        }
        if table_cols:
            keep = [c for c in out.columns if c in table_cols]
            insert_df = out[keep].copy() if keep else out.copy()
        else:
            insert_df = out.copy()
        insert_df.to_sql("line_history", conn, if_exists="append", index=False)
        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_line_history_player_sport "
            "ON line_history (player, sport, fetched_at)",
            "CREATE INDEX IF NOT EXISTS idx_line_history_proj_fetch "
            "ON line_history (sport, projection_id, fetched_at)",
            "CREATE INDEX IF NOT EXISTS idx_line_history_sport_fetch "
            "ON line_history (sport, fetched_at)",
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        counts = record_events_for_pull(conn, sport_u, current, pull_ts)
        conn.commit()
    return counts


def try_archive_lines(
    df: pd.DataFrame,
    sport: str,
    *,
    fetched_at: str | None = None,
    only_fetched_at: str | None = None,
) -> None:
    try:
        counts = archive_lines(
            df,
            sport=sport,
            fetched_at=fetched_at,
            only_fetched_at=only_fetched_at,
        )
        if counts:
            bits = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print(f"  [line_events] {str(sport).upper()} {bits}")
    except Exception as exc:
        print(f"  [WARN] line_history archive skipped: {exc}")
        return
    try:
        from utils.bet_windows import rebuild_bet_windows

        rebuild_bet_windows()
    except Exception as exc:
        print(f"  [WARN] bet-windows rebuild skipped: {exc}")


def backfill_events(*, since: str = "", sports: list[str] | None = None) -> None:
    """Rebuild line_events from consecutive line_history pulls."""
    if not ARCHIVE_DB.is_file():
        raise SystemExit(f"missing {ARCHIVE_DB}")
    with sqlite3.connect(ARCHIVE_DB) as conn:
        _ensure_events(conn)
        sport_rows = conn.execute(
            "SELECT DISTINCT sport FROM line_history WHERE sport IS NOT NULL ORDER BY 1"
        ).fetchall()
        want = {s.strip().upper() for s in (sports or []) if s}
        n_pairs = 0
        n_events = 0
        for (sport,) in sport_rows:
            if want and str(sport).upper() not in want:
                continue
            clocks = [
                r[0]
                for r in conn.execute(
                    """
                    SELECT DISTINCT fetched_at FROM line_history
                    WHERE sport = ? AND fetched_at IS NOT NULL AND fetched_at != ''
                    ORDER BY fetched_at
                    """,
                    (sport,),
                )
                if r[0] and (not since or str(r[0]) >= since)
            ]
            for prev_ts, curr_ts in zip(clocks, clocks[1:]):
                prev = load_snapshot(conn, sport, prev_ts)
                curr = load_snapshot(conn, sport, curr_ts)
                events = diff_snapshots(prev, curr)
                write_events(conn, sport, curr_ts, events)
                n_pairs += 1
                n_events += len(events)
            print(f"  {sport}: {max(0, len(clocks) - 1)} pull pairs")
        conn.commit()
    print(f"backfill pairs={n_pairs} events={n_events}")


def main() -> None:
    ap = argparse.ArgumentParser(description="PrizePicks line_history / line_events")
    ap.add_argument("--backfill-events", action="store_true")
    ap.add_argument("--since", default="", help="ISO timestamp or YYYY-MM-DD lower bound")
    ap.add_argument("--sport", action="append", default=[], help="Repeatable. Default: all.")
    args = ap.parse_args()
    if args.backfill_events:
        backfill_events(since=str(args.since or "").strip(), sports=args.sport)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
