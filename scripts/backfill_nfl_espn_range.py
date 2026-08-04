#!/usr/bin/env python3
"""
Backfill NFL player boxscores from ESPN into:
  Sports/NFL/data/cache/nfl_boxscore_cache.csv

Uses the shared CFB/NFL football boxscore engine (step5b --league nfl).

Examples:
  python scripts/backfill_nfl_espn_range.py --preset full-2025 --season 2025
  python scripts/backfill_nfl_espn_range.py --preset full-2024 --season 2024
  python scripts/backfill_nfl_espn_range.py --from 2025-09-04 --to 2026-02-09 --season 2025
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Tuple

import pandas as pd

REPO = Path(__file__).resolve().parent.parent

PRESETS: dict[str, Tuple[str, str]] = {
    # Regular + playoffs windows (inclusive)
    "full-2024": ("2024-09-05", "2025-02-09"),
    "full-2025": ("2025-09-04", "2026-02-09"),
    "regular-2025": ("2025-09-04", "2026-01-05"),
    "playoffs-2025": ("2026-01-10", "2026-02-09"),
}

DEFAULT_CACHE = REPO / "Sports" / "NFL" / "data" / "cache" / "nfl_boxscore_cache.csv"


def _load_boxscore_engine():
    path = REPO / "Sports" / "CFB" / "scripts" / "pipeline" / "step5b_attach_boxscore_stats.py"
    spec = importlib.util.spec_from_file_location("nfl_box_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _expand_dates(d0: date, d1: date) -> list[date]:
    out: list[date] = []
    cur = d0
    while cur <= d1:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _fmt_game_date(ds: str) -> str:
    s = str(ds or "").strip().replace("-", "")[:8]
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(ds)[:10]


def _attach_opponent(rows: list[dict], t1: str, t2: str) -> None:
    for row in rows:
        tid = str(row.get("team_id", "")).strip()
        if tid and t1 and t2:
            row["opp_team_id"] = t2 if tid == t1 else (t1 if tid == t2 else "")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill NFL ESPN games into nfl_boxscore_cache.csv")
    ap.add_argument("--preset", choices=sorted(PRESETS.keys()), default="")
    ap.add_argument("--from", dest="date_from", default="")
    ap.add_argument("--to", dest="date_to", default="")
    ap.add_argument("--season", required=True, help="SEASON label stored on cache rows (e.g. 2025)")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--sleep", type=float, default=0.12)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.preset:
        d0s, d1s = PRESETS[args.preset]
        d0 = date.fromisoformat(d0s)
        d1 = date.fromisoformat(d1s)
        print(f"[backfill-nfl] preset {args.preset}: {d0} .. {d1}")
    else:
        if not str(args.date_from).strip() or not str(args.date_to).strip():
            raise SystemExit("Provide --preset or both --from and --to (YYYY-MM-DD).")
        d0 = date.fromisoformat(args.date_from.strip())
        d1 = date.fromisoformat(args.date_to.strip())
    if d1 < d0:
        raise SystemExit("--to must be on or after --from")

    mod = _load_boxscore_engine()
    mod.ESPN_LEAGUE = "nfl"

    cache_path = Path(args.cache)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        cache = pd.read_csv(cache_path, dtype=str, encoding="utf-8-sig").fillna("")
    else:
        cache = pd.DataFrame()

    existing_events: set[str] = set()
    if not cache.empty and "event_id" in cache.columns:
        existing_events = set(cache["event_id"].astype(str).unique())

    pending: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    dates = _expand_dates(d0, d1)
    print(f"[backfill-nfl] Scanning {len(dates)} calendar days...")
    for i, d in enumerate(dates):
        yyyymmdd = d.strftime("%Y%m%d")
        sb = mod.pull_scoreboard(yyyymmdd)
        for eid, t1, t2, ds in mod.extract_events(sb):
            if eid in seen:
                continue
            seen.add(eid)
            if eid not in existing_events:
                pending.append((eid, t1, t2, ds))
        if (i + 1) % 30 == 0:
            print(f"  ... {i + 1}/{len(dates)} days, {len(pending)} events pending")

    print(
        f"[backfill-nfl] {len(seen)} events in range | "
        f"{len(existing_events)} already cached | {len(pending)} to fetch"
    )

    new_rows: list[dict] = []
    if pending:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _one(item: tuple[str, str, str, str]) -> list[dict]:
            eid, t1, t2, ds = item
            time.sleep(args.sleep)
            summ = mod.pull_summary(eid)
            rows = mod.parse_players(summ, game_date=_fmt_game_date(ds), event_id=eid)
            _attach_opponent(rows, t1, t2)
            for r in rows:
                r["SEASON"] = str(args.season)
            return rows

        with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
            futures = {pool.submit(_one, item): item[0] for item in pending}
            done = 0
            for fut in as_completed(futures):
                done += 1
                try:
                    rows = fut.result()
                    if rows:
                        new_rows.extend(rows)
                        existing_events.add(futures[fut])
                except Exception as exc:
                    print(f"  [warn] event {futures[fut]}: {exc}")
                if done % 25 == 0 or done == len(futures):
                    print(f"  ... fetched {done}/{len(futures)} events, rows={len(new_rows)}")

    if new_rows:
        add = pd.DataFrame(new_rows).fillna("")
        cache = pd.concat([cache, add], ignore_index=True) if not cache.empty else add
        # Deduplicate on event+athlete when possible
        subset = [c for c in ("event_id", "espn_athlete_id") if c in cache.columns]
        if subset:
            cache = cache.drop_duplicates(subset=subset, keep="last")
        cache.to_csv(cache_path, index=False, encoding="utf-8")
        print(f"[backfill-nfl] wrote +{len(new_rows)} rows -> {cache_path} (total {len(cache)})")
    else:
        print("[backfill-nfl] nothing new to write")


if __name__ == "__main__":
    main()
