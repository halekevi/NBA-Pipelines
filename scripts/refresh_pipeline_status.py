#!/usr/bin/env python3
"""
Refresh ui_runner/templates/pipeline_status.json (+ mobile copy) from real board / slate mtimes.

Usage:
  py -3 scripts/refresh_pipeline_status.py
  py -3 scripts/refresh_pipeline_status.py --date 2026-08-12
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = timezone.utc


def _today_et() -> str:
    return datetime.now(tz=_ET).date().isoformat()


def _mtime_str(path: Path | None) -> str:
    if not path or not path.is_file():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=_ET).strftime("%Y-%m-%d %H:%M:%S")


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def build_status(date: str) -> dict:
    out = _REPO / "outputs" / date
    sports_root = _REPO / "Sports"
    slate = _REPO / "ui_runner" / "templates" / "slate_latest.json"
    slate_payload: dict = {}
    if slate.is_file():
        try:
            slate_payload = json.loads(slate.read_text(encoding="utf-8"))
        except Exception:
            slate_payload = {}
    sports_rows = slate_payload.get("sports") or {}
    slate_mod = _mtime_str(slate)

    artifacts = {
        "nba": _first_existing(
            [out / f"step8_nba_direction_clean_{date}.xlsx", out / "nba" / "step8_nba_direction_clean.xlsx"]
        ),
        "nba1h": _first_existing([sports_root / "NBA" / "step8_nba1h_direction_clean.xlsx"]),
        "nba1q": _first_existing([sports_root / "NBA" / "step8_nba1q_direction_clean.xlsx"]),
        "cbb": _first_existing(
            [sports_root / "CBB" / "step6_ranked_cbb.xlsx", sports_root / "CBB" / "outputs" / date / "step6_ranked_cbb.xlsx"]
        ),
        "cfb": _first_existing([out / "cfb" / "step8_cfb_direction_clean.xlsx"]),
        "nhl": _first_existing(
            [out / "nhl" / "step8_nhl_direction_clean.xlsx", sports_root / "NHL" / "outputs" / "step8_nhl_direction_clean.xlsx"]
        ),
        "soccer": _first_existing(
            [
                out / "soccer" / "step8_soccer_direction_clean.xlsx",
                sports_root / "Soccer" / "outputs" / "step8_soccer_direction_clean.xlsx",
            ]
        ),
        "mlb": _first_existing(
            [
                out / "mlb" / "step8_mlb_direction_clean.xlsx",
                sports_root / "MLB" / "outputs" / "step8_mlb_direction_clean.xlsx",
                sports_root / "MLB" / "step8_mlb_direction_clean.xlsx",
            ]
        ),
        "nfl": _first_existing(
            [out / "nfl" / "step8_nfl_direction_clean.xlsx", sports_root / "NFL" / "outputs" / "step8_nfl_direction_clean.xlsx"]
        ),
        "tennis": _first_existing(
            [
                out / "tennis" / f"step8_tennis_direction_clean_{date}.xlsx",
                out / "tennis" / "step8_tennis_direction_clean.xlsx",
                out / f"step8_tennis_direction_clean_{date}.xlsx",
                sports_root / "Tennis" / "outputs" / "step8_tennis_direction_clean.xlsx",
            ]
        ),
        "golf": _first_existing(
            [out / "golf" / "step8_golf_direction_clean.xlsx", sports_root / "Golf" / "outputs" / "step8_golf_direction_clean.xlsx"]
        ),
        "wnba": _first_existing(
            [
                out / "wnba" / "step8_wnba_direction_clean.xlsx",
                out / f"step8_wnba_direction_clean_{date}.xlsx",
                sports_root / "WNBA" / "step8_wnba_direction_clean.xlsx",
            ]
        ),
        "wcbb": _first_existing([sports_root / "CBB" / "step6_ranked_wcbb.xlsx"]),
        "combined": slate if slate.is_file() else None,
    }

    status: dict = {}
    for sport, art in artifacts.items():
        rows = sports_rows.get(sport) if isinstance(sports_rows, dict) else None
        has_rows = isinstance(rows, list) and len(rows) > 0
        has_art = bool(art and art.is_file())
        exists = bool(has_rows or has_art or (sport == "combined" and slate.is_file()))
        if sport == "combined" and slate_mod:
            mod = slate_mod
        elif has_art:
            mod = _mtime_str(art)
        elif has_rows and slate_mod:
            mod = slate_mod
        else:
            mod = ""
        status[sport] = {"slate": {"exists": exists, "modified": mod}}
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=_today_et())
    args = ap.parse_args()
    date = str(args.date).strip()[:10]
    payload = build_status(date)
    targets = [
        _REPO / "ui_runner" / "templates" / "pipeline_status.json",
        _REPO / "mobile" / "www" / "pipeline_status.json",
    ]
    text = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
        print(f"[pipeline_status] wrote {t}")
    # quick digest
    alive = [k for k, v in payload.items() if (v.get("slate") or {}).get("exists")]
    print(f"[pipeline_status] date={date} sports_with_signal={alive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
