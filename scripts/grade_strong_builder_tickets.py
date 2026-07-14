#!/usr/bin/env python3
"""Grade strong_builder tickets vs full win-rate ticket load for given slate dates."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from analyze_graded_history import _norm_dir, _norm_pick, _norm_sport, _parse_hit  # noqa: E402


def _norm(s: object) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _norm_line(v: object) -> str:
    try:
        return str(round(float(v or 0), 2))
    except (TypeError, ValueError):
        return "0.0"


def _parse_row_hit(row: dict) -> int | None:
    h = _parse_hit(row.get("result"))
    if h is not None:
        return h
    raw = row.get("hit")
    if raw in (0, 1, "0", "1"):
        return int(raw)
    return None


def load_graded(date: str) -> dict[tuple, int | None]:
    p = _REPO / "mobile" / "www" / f"graded_props_{date}.json"
    if not p.is_file():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8")).get("props") or []
    out: dict[tuple, int | None] = {}
    for r in rows:
        key = (
            _norm_sport(r.get("sport")),
            _norm(r.get("player")),
            _norm(r.get("prop") or r.get("prop_type")),
            _norm_dir(r.get("direction")),
            _norm_pick(r.get("pick_type")).title(),
            _norm_line(r.get("line")),
        )
        out[key] = _parse_row_hit(r)
    return out


def leg_key(leg: dict) -> tuple:
    return (
        _norm_sport(leg.get("sport")),
        _norm(leg.get("player")),
        _norm(leg.get("prop_type") or leg.get("prop")),
        _norm_dir(leg.get("direction") or leg.get("dir")),
        _norm_pick(leg.get("pick_type")).title(),
        _norm_line(leg.get("line")),
    )


def grade_ticket_legs(legs: list[dict], graded: dict[tuple, int | None]) -> str:
    """Return WIN, LOSS, UNGRADED, or VOID."""
    if not legs:
        return "UNGRADED"
    hits: list[int | None] = []
    for leg in legs:
        h = graded.get(leg_key(leg))
        if h is None:
            return "UNGRADED"
        hits.append(h)
    if all(h == 1 for h in hits):
        return "WIN"
    return "LOSS"


def iter_tickets(payload: dict):
    for g in payload.get("groups") or []:
        gname = str(g.get("group_name") or "")
        for t in g.get("tickets") or []:
            yield gname, t


def summarize(results: list[str]) -> dict[str, int | float]:
    graded = [r for r in results if r in ("WIN", "LOSS")]
    wins = sum(1 for r in graded if r == "WIN")
    n = len(graded)
    return {
        "n_graded": n,
        "wins": wins,
        "losses": n - wins,
        "ungraded": sum(1 for r in results if r == "UNGRADED"),
        "win_pct": round(100 * wins / n, 1) if n else None,
    }


def analyze_date(date: str, *, verbose: bool) -> None:
    graded = load_graded(date)
    if not graded:
        print(f"{date}: no graded_props — skip")
        return

    paths = {
        "combined": _REPO / "ui_runner" / "data" / f"combined_slate_tickets_{date}.json",
        "winrate": _REPO / "ui_runner" / "data" / f"combined_slate_tickets_winrate_goblin_opt3_{date}.json",
        "strong_standard": _REPO
        / "ui_runner"
        / "data"
        / f"combined_slate_tickets_strong_standard_{date}.json",
        "strong_mix": _REPO
        / "ui_runner"
        / "data"
        / f"combined_slate_tickets_strong_mix_{date}.json",
    }

    print(f"\n{'='*60}")
    print(f"  {date}")
    print(f"{'='*60}")

    for label, path in paths.items():
        if not path.is_file():
            print(f"\n[{label}] file not found")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        all_results: list[str] = []
        strong_results: list[str] = []
        strong_rows: list[dict] = []

        for gname, t in iter_tickets(payload):
            legs = t.get("legs") or []
            res = grade_ticket_legs(legs, graded)
            all_results.append(res)
            if t.get("strong_builder"):
                strong_results.append(res)
                rec = str(
                    (t.get("payout") or {}).get("recommendation")
                    or t.get("empirical_recommendation")
                    or ""
                ).upper()
                strong_rows.append(
                    {
                        "group": gname,
                        "ticket_no": t.get("ticket_no"),
                        "result": res,
                        "rec": rec,
                        "n_legs": len(legs),
                        "legs": [
                            f"{leg.get('player')} {leg.get('prop_type')} {leg.get('direction')} {leg.get('line')}"
                            for leg in legs
                        ],
                    }
                )

        all_s = summarize(all_results)
        sb_s = summarize(strong_results)

        print(f"\n[{label}] {path.name}")
        print(
            f"  ALL tickets:     {all_s['win_pct']}%  "
            f"({all_s['wins']}/{all_s['n_graded']})  ungraded={all_s['ungraded']}"
        )
        print(
            f"  strong_builder:  {sb_s['win_pct']}%  "
            f"({sb_s['wins']}/{sb_s['n_graded']})  ungraded={sb_s['ungraded']}  "
            f"built={len(strong_results)}"
        )
        if all_s["n_graded"] and sb_s["n_graded"]:
            lift = sb_s["win_pct"] - all_s["win_pct"]
            print(f"  strong_builder lift vs ALL: {lift:+.1f}pp")

        if verbose and strong_rows:
            print(f"\n  strong_builder detail ({len(strong_rows)} tickets):")
            for row in strong_rows:
                mark = "✅" if row["result"] == "WIN" else ("❌" if row["result"] == "LOSS" else "⏳")
                legs_s = " | ".join(row["legs"])
                print(
                    f"    {mark} #{row['ticket_no']} [{row['rec']}] {row['group']} "
                    f"({row['n_legs']}leg): {legs_s}"
                )


def main() -> int:
    ap = argparse.ArgumentParser(description="Grade strong_builder vs full ticket load.")
    ap.add_argument("--date", action="append", dest="dates", help="Slate date YYYY-MM-DD (repeatable)")
    ap.add_argument("--from", dest="from_date", default="2026-06-20")
    ap.add_argument("--to", dest="to_date", default="2026-06-21")
    ap.add_argument("-v", "--verbose", action="store_true", help="Print each strong_builder ticket")
    args = ap.parse_args()

    if args.dates:
        dates = sorted(args.dates)
    else:
        dates = [args.from_date, args.to_date]
        if args.from_date == args.to_date:
            dates = [args.from_date]

    # 2-day rollup accumulators
    rollup: dict[str, dict[str, int]] = defaultdict(lambda: {"w": 0, "n": 0, "built": 0})

    for d in dates:
        analyze_date(d, verbose=args.verbose)
        graded = load_graded(d)
        path_by_label = {
            "combined": _REPO / "ui_runner" / "data" / f"combined_slate_tickets_{d}.json",
            "winrate": _REPO
            / "ui_runner"
            / "data"
            / f"combined_slate_tickets_winrate_goblin_opt3_{d}.json",
            "strong_standard": _REPO
            / "ui_runner"
            / "data"
            / f"combined_slate_tickets_strong_standard_{d}.json",
            "strong_mix": _REPO
            / "ui_runner"
            / "data"
            / f"combined_slate_tickets_strong_mix_{d}.json",
        }
        for label, p in path_by_label.items():
            if not p.is_file():
                continue
            payload = json.loads(p.read_text(encoding="utf-8"))
            for _, t in iter_tickets(payload):
                res = grade_ticket_legs(t.get("legs") or [], graded)
                if res in ("WIN", "LOSS"):
                    rollup[f"{label}_all"]["n"] += 1
                    rollup[f"{label}_all"]["w"] += 1 if res == "WIN" else 0
                if t.get("strong_builder") or label in ("strong_standard", "strong_mix"):
                    rollup[f"{label}_sb"]["built"] += 1
                    if res in ("WIN", "LOSS"):
                        rollup[f"{label}_sb"]["n"] += 1
                        rollup[f"{label}_sb"]["w"] += 1 if res == "WIN" else 0

    if len(dates) > 1:
        print(f"\n{'='*60}")
        print(f"  ROLLUP {dates[0]} → {dates[-1]}")
        print(f"{'='*60}")
        for key, title in [
            ("combined_all", "combined ALL"),
            ("combined_sb", "combined strong_builder"),
            ("winrate_all", "winrate ALL"),
            ("winrate_sb", "winrate strong_builder"),
            ("strong_standard_all", "std HOT shadow ALL"),
            ("strong_standard_sb", "std HOT shadow strong"),
            ("strong_mix_all", "mix shadow ALL"),
            ("strong_mix_sb", "mix shadow strong"),
        ]:
            r = rollup[key]
            if r["n"]:
                print(f"  {title:28s} {100*r['w']/r['n']:5.1f}%  ({r['w']}/{r['n']})  built={r.get('built', r['n'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
