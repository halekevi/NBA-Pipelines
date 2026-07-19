#!/usr/bin/env python3
"""Rebuild MAIN win-rate tickets from graded_props under alternate MLB policies.

Compares:
  - baseline_legacy: no MLB hitter Goblin OVER ban, allow MLB Standard OVER, no SG stack reject
  - current_shipped: production rules (as coded)
  - no_stack_reject: current bans without same-game hitter stack reject
  - pitcher_only: only pitcher allowlist Goblin OVER + no MLB Standard OVER

Writes data/reports/main_mlb_construction_rebuild_latest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import combined_slate_tickets as cst  # noqa: E402
from backtest_strong_standard import (  # noqa: E402
    _grade_index_from_props,
    _graded_props_path,
    _list_graded_dates,
    _props_to_df,
    _tickets_to_gradeable,
)
from grade_strong_builder_tickets import grade_ticket_legs, load_graded, summarize  # noqa: E402

_PWR = {2: 3.0, 3: 5.0, 4: 10.0}


def _roi(results: list[str], n_legs: list[int], *, fixed_mult: float | None = None) -> dict:
    staked = pnl = 0.0
    n = 0
    for res, nl in zip(results, n_legs):
        if res not in ("WIN", "LOSS"):
            continue
        mult = float(fixed_mult) if fixed_mult is not None else float(_PWR.get(int(nl), 3.0))
        staked += 10.0
        n += 1
        pnl += (mult - 1.0) * 10.0 if res == "WIN" else -10.0
    return {
        "n": n,
        "staked": round(staked, 2),
        "pnl": round(pnl, 2),
        "roi_pct": round(100.0 * pnl / staked, 1) if staked else None,
    }


def _frames_from_df(df: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    frames: list[tuple[str, pd.DataFrame]] = []
    if df.empty or "sport" not in df.columns:
        return frames
    for sport, g in df.groupby(df["sport"].astype(str).str.upper(), sort=True):
        frames.append((str(sport), g.copy()))
    return frames


def _install_policy(name: str) -> tuple:
    """Monkeypatch cst helpers; return restore tuple."""
    orig = (
        cst._main_leg_prop_banned,
        cst._row_win_rate_eligible,
        cst._winrate_ticket_construction_reject,
        cst._winrate_ticket_mlb_same_game_hitter_stack,
    )

    if name == "current_shipped":
        return orig  # no patch

    if name == "baseline_legacy":
        def _never_ban_mlb_goblin(row_d: dict) -> bool:
            sport = str(row_d.get("sport") or "").strip().upper()
            pick = str(row_d.get("pick_type") or "").strip().lower()
            if sport == "MLB" and "goblin" in pick:
                return False
            return orig[0](row_d)

        def legacy_eligible(row, **kwargs):
            if isinstance(row, pd.Series):
                row_d = row.to_dict()
            else:
                row_d = dict(row)
            graded_ctx = kwargs.get("graded_ctx")
            if graded_ctx and cst._row_in_avoid_slice(row_d, graded_ctx):
                return False
            sport = str(row_d.get("sport") or "").strip().upper()
            if sport != "MLB":
                if cst._main_leg_prop_banned(row_d):
                    return False
            pt = str(row_d.get("pick_type") or "").strip().lower()
            tier = str(row_d.get("tier") or "").strip().upper()
            if not cst.goblin_direction_ok(row_d):
                return False
            goblin_only = kwargs.get("goblin_only", False)
            standard_only = kwargs.get("standard_only", False)
            goblin_tier_a_only = kwargs.get("goblin_tier_a_only", False)
            qualify_standard = kwargs.get("qualify_standard", True)
            min_leg_prob = float(kwargs["min_leg_prob"])
            min_composite_hr = float(kwargs["min_composite_hr"])
            if goblin_only and standard_only:
                return False
            if goblin_only:
                if pt != "goblin":
                    return False
                if goblin_tier_a_only and tier != "A":
                    return False
            elif standard_only:
                if "standard" not in pt or "goblin" in pt:
                    return False
                if tier not in ("A", "B"):
                    return False
            elif pt == "goblin":
                if goblin_tier_a_only and tier != "A":
                    return False
            elif pt == "standard" and tier in ("A", "B"):
                pass
            else:
                return False
            comp = row_d.get("composite_hit_rate")
            if comp is None or comp == "":
                comp = row_d.get("hit_rate")
            try:
                comp_f = float(comp) if comp is not None and comp != "" else 0.0
            except (TypeError, ValueError):
                comp_f = 0.0
            if comp_f < min_composite_hr:
                return False
            leg_prob = cst._leg_prob_for_p_win_from_mapping(row_d)
            if leg_prob < min_leg_prob:
                return False
            direction = str(
                row_d.get("direction")
                or row_d.get("over_under")
                or row_d.get("bet_direction")
                or ""
            ).strip().upper()
            # Legacy: MLB Goblin OVER stress floors only (no hard hitter ban, no Std OVER ban)
            if sport == "MLB" and pt == "goblin" and direction == "OVER":
                prop_n = cst._norm_main_prop_key(
                    row_d.get("prop_type") or row_d.get("prop") or ""
                )
                mlb_floor = float(cst.MAIN_MLB_GOBLIN_MIN_LEG_PROB)
                if prop_n in cst.MAIN_MLB_GOBLIN_STRESS_PROP_NORMS:
                    mlb_floor = max(
                        mlb_floor, float(cst.MAIN_MLB_GOBLIN_STRESS_MIN_LEG_PROB)
                    )
                if leg_prob < mlb_floor:
                    return False
            mlp = pd.to_numeric(row_d.get("ml_prob"), errors="coerce")
            if pd.notna(mlp) and 0.0 < float(mlp) < float(cst.MAIN_MIN_ML_PROB_LEG):
                if comp_f < min_leg_prob and leg_prob < min_leg_prob:
                    return False
            if not cst._win_rate_sport_allowed(sport, leg_prob):
                return False
            if cst._winrate_leg_bench_risk(row_d):
                return False
            if qualify_standard and ("standard" in pt) and ("goblin" not in pt):
                if not cst._standard_high_prob_leg_allowed(row_d):
                    return False
                std_floor = cst._standard_direction_floor(row_d)
                if leg_prob < float(std_floor):
                    return False
                if direction == "OVER" and not cst._standard_over_elite_ok(row_d):
                    return False
            return True

        def construction_bench_only(ticket: dict) -> bool:
            return cst._winrate_ticket_same_game_bench_stack(ticket)

        cst._main_leg_prop_banned = _never_ban_mlb_goblin  # type: ignore
        cst._row_win_rate_eligible = legacy_eligible  # type: ignore
        cst._winrate_ticket_construction_reject = construction_bench_only  # type: ignore
        return orig

    if name == "no_stack_reject":
        def construction_no_stack(ticket: dict) -> bool:
            return cst._winrate_ticket_same_game_bench_stack(ticket)

        cst._winrate_ticket_construction_reject = construction_no_stack  # type: ignore
        return orig

    if name == "pitcher_only":
        # Already fail-closed on unknown Goblin OVER; also ban any MLB hitter residual
        # via construction reject on any hitter prop.
        def construction_pitcher(ticket: dict) -> bool:
            if cst._winrate_ticket_same_game_bench_stack(ticket):
                return True
            legs = [
                leg
                for leg in (ticket.get("legs") or ticket.get("rows") or [])
                if isinstance(leg, dict)
            ]
            for leg in legs:
                if str(leg.get("sport") or "").upper() != "MLB":
                    continue
                pn = cst._norm_main_prop_key(leg.get("prop_type") or leg.get("prop") or "")
                if cst._main_mlb_prop_is_hitter_core(pn):
                    return True
            return False

        cst._winrate_ticket_construction_reject = construction_pitcher  # type: ignore
        return orig

    return orig


def _restore(orig: tuple) -> None:
    (
        cst._main_leg_prop_banned,
        cst._row_win_rate_eligible,
        cst._winrate_ticket_construction_reject,
        cst._winrate_ticket_mlb_same_game_hitter_stack,
    ) = orig


def _run_policy(
    frames: list[tuple[str, pd.DataFrame]],
    graded_idx: dict,
    date_str: str,
    policy: str,
) -> dict[str, Any]:
    orig = _install_policy(policy)
    try:
        groups = cst.build_win_rate_ticket_groups(
            frames,
            min_leg_prob=float(cst.MAIN_MIN_LEG_PROB),
            min_composite_hr=0.55,
            max_legs=int(cst.MAIN_GRADED_MAX_LEGS),
            max_tickets=int(cst.MAIN_MAX_SLIPS),
            goblin_only=False,
            goblin_only_3leg=False,
        )
        tickets: list[dict] = []
        for _gn, ts, _meta in groups or []:
            tickets.extend(ts)
        gradeable = _tickets_to_gradeable(tickets)
        results = [grade_ticket_legs(t.get("legs") or [], graded_idx) for t in gradeable]
        n_legs = [int(t.get("n_legs") or len(t.get("legs") or [])) for t in gradeable]
        mlb_idx = [
            i
            for i, t in enumerate(gradeable)
            if any(str(l.get("sport") or "").upper() == "MLB" for l in (t.get("legs") or []))
        ]
        mlb_res = [results[i] for i in mlb_idx]
        mlb_nl = [n_legs[i] for i in mlb_idx]
        return {
            "policy": policy,
            "built": len(tickets),
            "summary": summarize(results),
            "roi_flat10": _roi(results, n_legs),
            "roi_flat10_3x": _roi(results, n_legs, fixed_mult=3.0),
            "mlb_touching": {
                "n": len(mlb_idx),
                "summary": summarize(mlb_res),
                "roi_flat10_3x": _roi(mlb_res, mlb_nl, fixed_mult=3.0),
            },
        }
    finally:
        _restore(orig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_date", default="2026-07-14")
    ap.add_argument("--to", dest="to_date", default="2026-07-18")
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO / "data" / "reports" / "main_mlb_construction_rebuild_latest.json",
    )
    args = ap.parse_args()

    dates = _list_graded_dates(args.from_date, args.to_date)
    policies = (
        "baseline_legacy",
        "current_shipped",
        "no_stack_reject",
        "pitcher_only",
    )
    days: list[dict] = []
    print(f"MAIN MLB rebuild backtest {args.from_date}→{args.to_date} ({len(dates)} days)")

    for d in dates:
        path = _graded_props_path(d)
        if path is None:
            print(f"  {d}: no graded props")
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        props = raw.get("props") if isinstance(raw, dict) else raw
        if not isinstance(props, list) or not props:
            continue
        df = _props_to_df(props)
        # Prefer props that look ticketable: goblin/standard A/B
        frames = _frames_from_df(df)
        graded_idx = load_graded(d) or _grade_index_from_props(props)
        day: dict[str, Any] = {"date": d, "policies": {}}
        for pol in policies:
            rec = _run_policy(frames, graded_idx, d, pol)
            day["policies"][pol] = rec
            s = rec["summary"]
            print(
                f"  {d} {pol:18} built={rec['built']} "
                f"WR={s.get('win_pct')} n={s.get('n_graded')} "
                f"ROI3x={rec['roi_flat10_3x'].get('roi_pct')} "
                f"MLB_n={rec['mlb_touching']['n']} "
                f"MLB_WR={rec['mlb_touching']['summary'].get('win_pct')}"
            )
        days.append(day)

    # Aggregate
    agg: dict[str, Any] = {}
    for pol in policies:
        all_res: list[str] = []
        all_nl: list[int] = []
        mlb_res: list[str] = []
        mlb_nl: list[int] = []
        built = 0
        for day in days:
            rec = day["policies"].get(pol) or {}
            built += int(rec.get("built") or 0)
            # reconstruct not stored — store per-day only; re-summarize from day summaries
        # Aggregate from day summaries approximately via wins/losses
        wins = losses = ungraded = 0
        mlb_w = mlb_l = 0
        pnl3 = stake3 = 0.0
        for day in days:
            rec = day["policies"].get(pol) or {}
            s = rec.get("summary") or {}
            wins += int(s.get("wins") or 0)
            losses += int(s.get("losses") or 0)
            ungraded += int(s.get("ungraded") or 0)
            ms = (rec.get("mlb_touching") or {}).get("summary") or {}
            mlb_w += int(ms.get("wins") or 0)
            mlb_l += int(ms.get("losses") or 0)
            r3 = rec.get("roi_flat10_3x") or {}
            if r3.get("staked"):
                stake3 += float(r3["staked"])
                pnl3 += float(r3["pnl"])
        n = wins + losses
        mlb_n = mlb_w + mlb_l
        agg[pol] = {
            "built": built,
            "n_graded": n,
            "wins": wins,
            "losses": losses,
            "ungraded": ungraded,
            "win_pct": round(100.0 * wins / n, 1) if n else None,
            "roi_flat10_3x": {
                "staked": round(stake3, 2),
                "pnl": round(pnl3, 2),
                "roi_pct": round(100.0 * pnl3 / stake3, 1) if stake3 else None,
            },
            "mlb_touching": {
                "n_graded": mlb_n,
                "wins": mlb_w,
                "losses": mlb_l,
                "win_pct": round(100.0 * mlb_w / mlb_n, 1) if mlb_n else None,
            },
        }

    out = {
        "from_date": args.from_date,
        "to_date": args.to_date,
        "policies": list(policies),
        "aggregate": agg,
        "by_day": days,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nWrote {args.out}")
    print("\n=== AGGREGATE ===")
    for pol, a in agg.items():
        print(
            f"{pol:18} built={a['built']} WR={a['win_pct']} "
            f"ROI3x={a['roi_flat10_3x'].get('roi_pct')} "
            f"MLB_WR={a['mlb_touching'].get('win_pct')} "
            f"MLB_n={a['mlb_touching'].get('n_graded')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
