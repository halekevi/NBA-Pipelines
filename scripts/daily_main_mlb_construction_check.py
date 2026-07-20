#!/usr/bin/env python3
"""One-screen MAIN / long-parlay hit rate vs expected construction target.

Grades archived ticket boards against graded_props and reports:
  - raw board WR
  - WR after MLB construction hygiene (hitter Goblin OVER + MLB Standard OVER bans)
  - gap vs expected MAIN rebuild target (~57%)

Writes data/reports/main_mlb_construction_daily_latest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import combined_slate_tickets as cst  # noqa: E402
from grade_strong_builder_tickets import (  # noqa: E402
    grade_ticket_legs,
    load_graded,
    summarize,
)

EXPORT_DIR = _REPO / "ui_runner" / "data"
REPORTS = _REPO / "data" / "reports"
REBUILD_REPORT = REPORTS / "main_mlb_construction_rebuild_latest.json"

# From Jul 14–18 rebuild under shipped prop bans.
EXPECTED_MAIN_WR_PCT = 57.1
EXPECTED_MAIN_NOTE = "MAIN rebuild Jul 14–18 under hitter Goblin OVER + MLB Std OVER bans"
MIN_DECIDED_BAR = 10


def _load_expected() -> tuple[float, str]:
    if not REBUILD_REPORT.is_file():
        return EXPECTED_MAIN_WR_PCT, EXPECTED_MAIN_NOTE
    try:
        rep = json.loads(REBUILD_REPORT.read_text(encoding="utf-8"))
        agg = (rep.get("aggregate") or {}).get("current_shipped") or {}
        wr = agg.get("win_pct")
        if wr is not None:
            return float(wr), (
                f"MAIN rebuild {rep.get('from_date')}→{rep.get('to_date')} "
                f"(current_shipped)"
            )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return EXPECTED_MAIN_WR_PCT, EXPECTED_MAIN_NOTE


def _iter_tickets(payload: dict) -> list[dict]:
    out: list[dict] = []
    for g in payload.get("groups") or []:
        if not isinstance(g, dict):
            continue
        for t in g.get("tickets") or []:
            if isinstance(t, dict):
                out.append(t)
    return out


def _ticket_legs(t: dict) -> list[dict]:
    return [leg for leg in (t.get("legs") or t.get("rows") or []) if isinstance(leg, dict)]


def _mlb_touching(legs: list[dict]) -> bool:
    return any(str(leg.get("sport") or "").strip().upper() == "MLB" for leg in legs)


def _grade_board(path: Path, date_str: str) -> dict[str, Any]:
    empty = {
        "path": str(path.relative_to(_REPO)) if path.is_file() else None,
        "n_tickets": 0,
        "raw": summarize([]),
        "hygiene": summarize([]),
        "mlb_raw": summarize([]),
        "mlb_hygiene": summarize([]),
        "n_hygiene_kept": 0,
        "n_mlb_raw": 0,
        "n_mlb_hygiene": 0,
    }
    if not path.is_file():
        return empty
    graded = load_graded(date_str)
    if not graded:
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty

    raw_res: list[str] = []
    hyg_res: list[str] = []
    mlb_raw_res: list[str] = []
    mlb_hyg_res: list[str] = []
    n_tickets = 0
    n_hyg = 0
    n_mlb = 0
    n_mlb_hyg = 0

    for t in _iter_tickets(payload):
        legs = _ticket_legs(t)
        if not legs:
            continue
        n_tickets += 1
        res = grade_ticket_legs(legs, graded)
        raw_res.append(res)
        is_mlb = _mlb_touching(legs)
        if is_mlb:
            n_mlb += 1
            mlb_raw_res.append(res)
        banned = cst._ticket_rows_mlb_construction_banned(legs)
        if banned:
            continue
        n_hyg += 1
        hyg_res.append(res)
        if is_mlb:
            n_mlb_hyg += 1
            mlb_hyg_res.append(res)

    return {
        "path": str(path.relative_to(_REPO)),
        "n_tickets": n_tickets,
        "raw": summarize(raw_res),
        "hygiene": summarize(hyg_res),
        "mlb_raw": summarize(mlb_raw_res),
        "mlb_hygiene": summarize(mlb_hyg_res),
        "n_hygiene_kept": n_hyg,
        "n_mlb_raw": n_mlb,
        "n_mlb_hygiene": n_mlb_hyg,
    }


def _gap(actual: float | None, expected: float) -> float | None:
    if actual is None:
        return None
    return round(float(actual) - float(expected), 1)


def _fmt_wr(block: dict) -> str:
    wr = block.get("win_pct")
    n = block.get("n_graded") or 0
    if wr is None:
        return f"— (n={n})"
    return f"{wr}% (n={n})"


def run_range(from_date: str, to_date: str) -> dict[str, Any]:
    expected_wr, expected_note = _load_expected()
    days: list[dict[str, Any]] = []
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    d = start
    while d <= end:
        ds = d.isoformat()
        main_path = EXPORT_DIR / f"combined_slate_tickets_{ds}.json"
        long_path = EXPORT_DIR / f"combined_slate_tickets_long_parlay_{ds}.json"
        day = {
            "date": ds,
            "main": _grade_board(main_path, ds),
            "long_parlay": _grade_board(long_path, ds),
        }
        days.append(day)
        d += timedelta(days=1)

    # Aggregate MAIN hygiene (primary KPI)
    main_w = main_l = main_u = 0
    hyg_w = hyg_l = hyg_u = 0
    for day in days:
        r = day["main"]["raw"]
        h = day["main"]["hygiene"]
        main_w += int(r.get("wins") or 0)
        main_l += int(r.get("losses") or 0)
        main_u += int(r.get("ungraded") or 0)
        hyg_w += int(h.get("wins") or 0)
        hyg_l += int(h.get("losses") or 0)
        hyg_u += int(h.get("ungraded") or 0)

    main_n = main_w + main_l
    hyg_n = hyg_w + hyg_l
    main_wr = round(100.0 * main_w / main_n, 1) if main_n else None
    hyg_wr = round(100.0 * hyg_w / hyg_n, 1) if hyg_n else None

    return {
        "from_date": from_date,
        "to_date": to_date,
        "expected_main_wr_pct": expected_wr,
        "expected_note": expected_note,
        "aggregate_main": {
            "raw": {
                "wins": main_w,
                "losses": main_l,
                "ungraded": main_u,
                "n_graded": main_n,
                "win_pct": main_wr,
            },
            "hygiene": {
                "wins": hyg_w,
                "losses": hyg_l,
                "ungraded": hyg_u,
                "n_graded": hyg_n,
                "win_pct": hyg_wr,
            },
            "gap_vs_expected_pp": _gap(hyg_wr, expected_wr),
            "enough_sample": bool(hyg_n >= MIN_DECIDED_BAR),
        },
        "by_day": days,
    }


def _print_report(rep: dict[str, Any]) -> None:
    exp = rep["expected_main_wr_pct"]
    print("=" * 64)
    print("MAIN MLB construction — expected vs actual")
    print(f"  Window: {rep['from_date']} → {rep['to_date']}")
    print(f"  Expected MAIN WR: {exp}%  ({rep['expected_note']})")
    print("=" * 64)
    agg = rep["aggregate_main"]
    print(f"  MAIN raw board:      {_fmt_wr(agg['raw'])}")
    print(f"  MAIN after hygiene:  {_fmt_wr(agg['hygiene'])}")
    gap = agg.get("gap_vs_expected_pp")
    if gap is None:
        print("  Gap vs expected:     — (not enough graded slips)")
    else:
        sign = "+" if gap >= 0 else ""
        bar = "OK sample" if agg.get("enough_sample") else f"thin sample (<{MIN_DECIDED_BAR})"
        print(f"  Gap vs expected:     {sign}{gap} pp  [{bar}]")
    print()
    print(f"{'date':12} {'main_raw':>12} {'main_hyg':>12} {'long_raw':>12} {'long_hyg':>12}")
    for day in rep["by_day"]:
        m = day["main"]
        lp = day["long_parlay"]
        print(
            f"{day['date']:12} "
            f"{_fmt_wr(m['raw']):>12} "
            f"{_fmt_wr(m['hygiene']):>12} "
            f"{_fmt_wr(lp['raw']):>12} "
            f"{_fmt_wr(lp['hygiene']):>12}"
        )
    print()
    print("  Hygiene = drop MLB hitter Goblin OVER + MLB Standard OVER legs.")
    print(f"  Report → {REPORTS / 'main_mlb_construction_daily_latest.json'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--from",
        dest="from_date",
        default=(date.today() - timedelta(days=7)).isoformat(),
    )
    ap.add_argument("--to", dest="to_date", default=date.today().isoformat())
    ap.add_argument(
        "--out",
        type=Path,
        default=REPORTS / "main_mlb_construction_daily_latest.json",
    )
    args = ap.parse_args()

    rep = run_range(args.from_date, args.to_date)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    _print_report(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
