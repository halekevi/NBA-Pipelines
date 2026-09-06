#!/usr/bin/env python3
"""Stamp this scheduled fetch window into line_history + last_fetch_window.json.

Every 1AM / 8AM / 9AM / 9:45 / 10:30 / 1PM / 4:30 pull must write a fetched_at
clock even when lines did not move (n_moved=0) or step1 fell back to an older CSV.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.line_history_archive import try_archive_lines  # noqa: E402
from utils.bet_windows import (  # noqa: E402
    job_window_label,
    rebuild_bet_windows,
    summarize_fetch_window,
    write_fetch_window_stamp,
)
from utils.pp_fetch_stamp import now_et_iso, stamp_fetched_at  # noqa: E402

STEP1_FILES: tuple[tuple[str, str], ...] = (
    ("WNBA", "wnba/step1_wnba_props.csv"),
    ("MLB", "mlb/step1_mlb_props.csv"),
    ("SOCCER", "soccer/step1_soccer_props.csv"),
    ("TENNIS", "tennis/step1_tennis_props.csv"),
    ("NFL", "nfl/step1_pp_props_today.csv"),
    ("NBA", "nba/step1_pp_props_today.csv"),
    ("NHL", "nhl/step1_nhl_props.csv"),
    ("CFB", "cfb/step1_cfb_props.csv"),
    ("CBB", "cbb/step1_cbb_props.csv"),
)


def restamp_dated_step1s(date: str, *, when: str, window: str) -> int:
    n_ok = 0
    day = ROOT / "outputs" / date
    for sport, rel in STEP1_FILES:
        path = day / rel.replace("/", os.sep)
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            print(f"  [stamp] skip {sport}: {exc}")
            continue
        if df is None or df.empty:
            continue
        df = stamp_fetched_at(df, when=when, overwrite=True)
        df.to_csv(path, index=False)
        try_archive_lines(df, sport, fetched_at=when)
        n_ok += 1
        print(f"  [stamp] {sport} rows={len(df)} fetched_at={when} window={window}")
    return n_ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--window", default="")
    ap.add_argument("--write-stamp", action="store_true")
    ap.add_argument("--restamp-csvs", action="store_true")
    args = ap.parse_args()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    date_s = str(args.date or datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d"))[:10]
    win = str(args.window or "").strip()
    if win:
        os.environ["PROPORACLE_BET_WINDOW"] = win
    when = now_et_iso()
    if args.restamp_csvs:
        restamp_dated_step1s(date_s, when=when, window=job_window_label(when, explicit=win))
        rebuild_bet_windows(date_s)
    summary = summarize_fetch_window(date_s, win or None)
    if args.write_stamp:
        write_fetch_window_stamp(summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
