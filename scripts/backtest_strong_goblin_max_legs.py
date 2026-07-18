#!/usr/bin/env python3
"""Backtest production Goblin STRONG: max_legs=3 (new default) vs max_legs=6 (legacy).

Rebuilds tickets from graded_props history and grades power wins (all legs HIT).
Writes data/reports/strong_goblin_max_legs_backtest_latest.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from analyze_graded_history import _norm_dir, _norm_pick, _norm_sport, _parse_hit  # noqa: E402
from backtest_strong_standard import (  # noqa: E402
    _grade_index_from_props,
    _graded_props_path,
    _list_graded_dates,
    _props_to_df,
    _tickets_to_gradeable,
)
from combined_slate_tickets import build_strong_tickets  # noqa: E402
from grade_strong_builder_tickets import grade_ticket_legs, load_graded, summarize  # noqa: E402
import combined_slate_tickets as cst  # noqa: E402
import utils.ticket_ev_tiers as tet  # noqa: E402

_DATE_RE = re.compile(r"^graded_props_(\d{4}-\d{2}-\d{2})\.json$")

# Approximate PrizePicks power multipliers for flat-$10 ROI (display only).
_PWR = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 40.0}


def _norm(s: object) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _roi_flat10(results: list[str], n_legs_list: list[int]) -> dict[str, Any]:
    """$10 flat power: win pays (mult-1)*10, loss -10. Skip UNGRADED."""
    staked = 0.0
    pnl = 0.0
    n = 0
    for res, nl in zip(results, n_legs_list):
        if res not in ("WIN", "LOSS"):
            continue
        mult = float(_PWR.get(int(nl), 3.0))
        staked += 10.0
        n += 1
        if res == "WIN":
            pnl += (mult - 1.0) * 10.0
        else:
            pnl -= 10.0
    return {
        "n": n,
        "staked": round(staked, 2),
        "pnl": round(pnl, 2),
        "roi_pct": round(100.0 * pnl / staked, 1) if staked else None,
    }


def _run_variant(
    df: pd.DataFrame,
    graded_idx: dict,
    *,
    max_legs: int,
    date_str: str,
) -> dict[str, Any]:
    old_tet = tet.STRONG_MAX_LEGS
    old_cst = cst.STRONG_MAX_LEGS
    try:
        tet.STRONG_MAX_LEGS = int(max_legs)
        cst.STRONG_MAX_LEGS = int(max_legs)
        tickets = build_strong_tickets(
            df,
            max_legs=int(max_legs),
            max_tickets=40,
            exhaust_pool=False,
            pick_mode="goblin",
            date_str=date_str,
        )
    finally:
        tet.STRONG_MAX_LEGS = old_tet
        cst.STRONG_MAX_LEGS = old_cst

    gradeable = _tickets_to_gradeable(tickets)
    results = [grade_ticket_legs(t.get("legs") or [], graded_idx) for t in gradeable]
    n_legs = [int(t.get("n_legs") or len(t.get("legs") or [])) for t in gradeable]
    summ = summarize(results)
    by_n: dict[str, dict[str, Any]] = {}
    for nl in sorted(set(n_legs)):
        idxs = [i for i, n in enumerate(n_legs) if n == nl]
        sub = [results[i] for i in idxs]
        by_n[str(nl)] = summarize(sub)
    p_wins = [float(t.get("est_win_prob") or 0.0) for t in gradeable]
    return {
        "max_legs": int(max_legs),
        "built": len(tickets),
        "summary": summ,
        "by_n_legs": by_n,
        "avg_est_win_prob": round(sum(p_wins) / len(p_wins), 4) if p_wins else None,
        "roi_flat10": _roi_flat10(results, n_legs),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_date", default="2026-07-01")
    ap.add_argument("--to", dest="to_date", default="2026-07-17")
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO / "data" / "reports" / "strong_goblin_max_legs_backtest_latest.json",
    )
    args = ap.parse_args()

    dates = _list_graded_dates(args.from_date, args.to_date)
    if not dates:
        print("No graded dates in range.")
        return 1

    days: list[dict[str, Any]] = []
    agg = {
        "3": {"wins": 0, "losses": 0, "built": 0, "pnl": 0.0, "staked": 0.0},
        "6": {"wins": 0, "losses": 0, "built": 0, "pnl": 0.0, "staked": 0.0},
    }

    print(f"STRONG Goblin max-legs backtest {args.from_date} → {args.to_date} ({len(dates)} days)")
    for d in dates:
        path = _graded_props_path(d)
        if path is None:
            print(f"  {d}: no graded file — skip")
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        props = raw.get("props") if isinstance(raw, dict) else raw
        if not isinstance(props, list) or not props:
            print(f"  {d}: empty props — skip")
            continue
        df = _props_to_df(props)
        graded_idx = load_graded(d) or _grade_index_from_props(props)
        v3 = _run_variant(df, graded_idx, max_legs=3, date_str=d)
        v6 = _run_variant(df, graded_idx, max_legs=6, date_str=d)
        day = {"date": d, "max3": v3, "max6": v6}
        days.append(day)

        for key, var in (("3", v3), ("6", v6)):
            s = var["summary"]
            r = var["roi_flat10"]
            agg[key]["wins"] += int(s.get("wins") or 0)
            agg[key]["losses"] += int(s.get("losses") or 0)
            agg[key]["built"] += int(var.get("built") or 0)
            agg[key]["pnl"] += float(r.get("pnl") or 0)
            agg[key]["staked"] += float(r.get("staked") or 0)

        w3, l3 = v3["summary"].get("wins"), v3["summary"].get("losses")
        w6, l6 = v6["summary"].get("wins"), v6["summary"].get("losses")
        print(
            f"  {d}: max3 {w3}W/{l3}L ({v3['summary'].get('win_pct')}%) "
            f"n={v3['summary'].get('n_graded')} | "
            f"max6 {w6}W/{l6}L ({v6['summary'].get('win_pct')}%) "
            f"n={v6['summary'].get('n_graded')}"
        )

    def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
        n = int(bucket["wins"]) + int(bucket["losses"])
        staked = float(bucket["staked"])
        pnl = float(bucket["pnl"])
        return {
            "built": bucket["built"],
            "wins": bucket["wins"],
            "losses": bucket["losses"],
            "n_graded": n,
            "win_pct": round(100.0 * bucket["wins"] / n, 1) if n else None,
            "pnl_flat10": round(pnl, 2),
            "staked_flat10": round(staked, 2),
            "roi_pct": round(100.0 * pnl / staked, 1) if staked else None,
        }

    summary = {
        "max_legs_3": _finalize(agg["3"]),
        "max_legs_6": _finalize(agg["6"]),
    }
    out = {
        "generated_at": "2026-07-18",
        "from": args.from_date,
        "to": args.to_date,
        "pick_mode": "goblin",
        "comparison": "STRONG max_legs=3 (new default) vs max_legs=6 (legacy)",
        "summary": summary,
        "days": days,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    for label, block in summary.items():
        print(
            f"  {label}: {block['wins']}W/{block['losses']}L = {block['win_pct']}% "
            f"(n={block['n_graded']}) ROI@$10={block['roi_pct']}% pnl={block['pnl_flat10']}"
        )
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
