#!/usr/bin/env python3
"""Show PrizePicks line points: appeared, moved, cut, disappeared.

Reads data/line_history.db line_events (written on every step1 archive).

  py -3.14 scripts/report_line_events.py --date 2026-08-24
  py -3.14 scripts/report_line_events.py --date 2026-08-24 --sport WNBA --event disappeared
  py -3.14 scripts/line_history_archive.py --backfill-events --since 2026-08-17
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.line_history_archive import ARCHIVE_DB  # noqa: E402
from utils.pp_fetch_stamp import now_et_iso  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = _REPO / "data" / "reports" / "line_events_latest.json"


def _today() -> str:
    return datetime.now(ET).date().isoformat()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="game_date YYYY-MM-DD (default: today ET)")
    ap.add_argument("--sport", default="", help="WNBA / MLB / SOCCER / TENNIS / …")
    ap.add_argument(
        "--event",
        default="",
        help="appeared | moved | cut | disappeared (default: all)",
    )
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json-out", default=str(OUT))
    args = ap.parse_args()
    if not ARCHIVE_DB.is_file():
        raise SystemExit(f"missing {ARCHIVE_DB}")
    game_date = str(args.date or "").strip()[:10] or _today()
    sport = str(args.sport or "").strip().upper()
    kind = str(args.event or "").strip().lower()

    sql = """
        SELECT sport, game_date, player, prop_type, event, prev_pick, new_pick,
               prev_line, new_line, prev_fetched_at, fetched_at, still_on_slate
        FROM line_events
        WHERE game_date = ?
    """
    params: list[object] = [game_date]
    if sport:
        sql += " AND sport = ?"
        params.append(sport)
    if kind:
        sql += " AND lower(event) = ?"
        params.append(kind)
    sql += " ORDER BY fetched_at, sport, event, player"

    with sqlite3.connect(f"file:{ARCHIVE_DB}?mode=ro", uri=True) as conn:
        try:
            rows = list(conn.execute(sql, params))
        except sqlite3.OperationalError as exc:
            raise SystemExit(
                f"line_events missing — run a step1 fetch or "
                f"py -3.14 scripts/line_history_archive.py --backfill-events --since {game_date}\n{exc}"
            ) from exc

    counts: dict[str, int] = defaultdict(int)
    by_sport: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    payload_rows = []
    for r in rows:
        rec = {
            "sport": r[0],
            "game_date": r[1],
            "player": r[2],
            "prop": r[3],
            "event": r[4],
            "prev_pick": r[5],
            "new_pick": r[6],
            "prev_line": r[7],
            "new_line": r[8],
            "prev_fetched_at": r[9],
            "fetched_at": r[10],
            "still_on_slate": r[11],
        }
        payload_rows.append(rec)
        counts[rec["event"]] += 1
        by_sport[rec["sport"]][rec["event"]] += 1

    print(f"line_events game_date={game_date} n={len(payload_rows)}")
    print("  totals", dict(counts) or {"(none)": 0})
    for sp, c in sorted(by_sport.items()):
        print(f"  {sp}: {dict(c)}")

    live_gone = [
        r
        for r in payload_rows
        if r["event"] == "disappeared" and r["still_on_slate"] == 1
    ]
    print(f"  disappeared while slate still up: {len(live_gone)}")

    show = payload_rows[: max(0, int(args.limit))]
    if show:
        print("\nfirst rows")
        for r in show:
            prev = r["prev_line"] if r["prev_line"] is not None else "-"
            new = r["new_line"] if r["new_line"] is not None else "-"
            print(
                f"  {r['fetched_at'][:19]:19} {r['sport']:7} {r['event']:12} "
                f"{r['player'][:22]:22} {r['prop'][:18]:18} "
                f"{r['prev_pick'] or '-':8} {prev} -> {r['new_pick'] or '-':8} {new}"
            )

    out = {
        "generated_at": now_et_iso(),
        "game_date": game_date,
        "sport": sport or None,
        "event": kind or None,
        "counts": dict(counts),
        "by_sport": {k: dict(v) for k, v in by_sport.items()},
        "disappeared_still_on_slate": len(live_gone),
        "n": len(payload_rows),
        "rows": payload_rows,
    }
    path = Path(args.json_out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
