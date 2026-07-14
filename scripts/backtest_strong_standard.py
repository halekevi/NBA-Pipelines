#!/usr/bin/env python3
"""Backtest STRONG Standard pools reconstructed from graded_props history.

Modes:
  - standard (legacy): Standard + Tier A/B + HOT, mirrored Goblin STRONG stacking
  - standard_prob (default): probability-first Standard OVER/UNDER with direction floors
    (no HOT requirement). Reports gate pass, avg p_win/EV, and ticket outcomes —
    not comparisons against Goblin hit rate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from analyze_graded_history import _norm_dir, _norm_pick, _norm_sport, _parse_hit  # noqa: E402
from combined_slate_tickets import (  # noqa: E402
    _leg_prob_for_p_win_from_mapping,
    _prepare_strong_builder_pool,
    _standard_direction_floor,
    _strong_candidate_legs,
    build_strong_tickets,
)
from grade_strong_builder_tickets import (  # noqa: E402
    grade_ticket_legs,
    iter_tickets,
    load_graded,
    summarize,
)

_GRADED_DIRS = (
    _REPO / "ui_runner" / "templates",
    _REPO / "mobile" / "www",
)
_DATE_RE = re.compile(r"^graded_props_(\d{4}-\d{2}-\d{2})\.json$")


def _norm(s: object) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _parse_row_hit(row: dict) -> int | None:
    h = _parse_hit(row.get("result"))
    if h is not None:
        return h
    raw = row.get("hit")
    if raw in (0, 1, "0", "1"):
        return int(raw)
    return None


def _graded_props_path(d: str) -> Path | None:
    for root in _GRADED_DIRS:
        p = root / f"graded_props_{d}.json"
        if p.is_file():
            return p
    return None


def _list_graded_dates(from_date: str, to_date: str) -> list[str]:
    found: set[str] = set()
    for root in _GRADED_DIRS:
        if not root.is_dir():
            continue
        for p in root.glob("graded_props_*.json"):
            m = _DATE_RE.match(p.name)
            if not m:
                continue
            ds = m.group(1)
            if from_date <= ds <= to_date:
                found.add(ds)
    return sorted(found)


def _props_to_df(props: list[dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for r in props:
        if not isinstance(r, dict):
            continue
        prop = r.get("prop_type") or r.get("prop") or ""
        direction = r.get("direction") or r.get("over_under") or ""
        hit_rate = r.get("hit_rate")
        if hit_rate in (None, ""):
            hit_rate = r.get("hit_rate_l10")
        ml_prob = r.get("ml_prob")
        if ml_prob in (None, ""):
            ml_prob = hit_rate
        rows.append(
            {
                "sport": str(r.get("sport") or "").strip().upper(),
                "player": r.get("player"),
                "team": r.get("team") or r.get("player_team") or "",
                "opp": r.get("opp") or r.get("opp_team") or "",
                "prop_type": prop,
                "prop": prop,
                "pick_type": str(r.get("pick_type") or "Standard").strip().title(),
                "tier": str(r.get("tier") or "").strip().upper(),
                "direction": str(direction or "").strip().upper(),
                "line": r.get("line"),
                "hit_rate": float(hit_rate or 0.5),
                "composite_hit_rate": r.get("composite_hit_rate"),
                "rank_score": float(r.get("rank_score") or r.get("confidence_score") or 0.0),
                "ml_prob": float(ml_prob or 0.5),
                "l10_over": r.get("l10_over"),
                "l10_under": r.get("l10_under"),
                "l10_streak": str(r.get("l10_streak") or "").strip().upper(),
                "prop_quality_score": r.get("prop_quality_score"),
                "hit": _parse_row_hit(r),
                "result": r.get("result"),
            }
        )
    return pd.DataFrame(rows)


def _tickets_to_gradeable(tickets: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, t in enumerate(tickets, start=1):
        legs = []
        for row in t.get("rows") or []:
            legs.append(
                {
                    "sport": row.get("sport"),
                    "player": row.get("player"),
                    "prop_type": row.get("prop_type") or row.get("prop"),
                    "direction": row.get("direction"),
                    "pick_type": row.get("pick_type"),
                    "line": row.get("line"),
                }
            )
        out.append(
            {
                "ticket_no": i,
                "n_legs": int(t.get("n_legs") or len(legs)),
                "strong_builder": True,
                "strong_builder_pick": t.get("strong_builder_pick") or "Standard",
                "pool_policy": t.get("pool_policy"),
                "est_win_prob": t.get("est_win_prob"),
                "ev_power": t.get("ev_power"),
                "legs": legs,
            }
        )
    return out


def _line_key(v: object) -> str:
    try:
        return str(round(float(v or 0), 2))
    except (TypeError, ValueError):
        return "0.0"


def _grade_index_from_props(props: list[dict]) -> dict[tuple, int | None]:
    out: dict[tuple, int | None] = {}
    for r in props:
        key = (
            _norm_sport(r.get("sport")),
            _norm(r.get("player")),
            _norm(r.get("prop") or r.get("prop_type")),
            _norm_dir(r.get("direction") or r.get("over_under")),
            _norm_pick(r.get("pick_type")).title(),
            _line_key(r.get("line")),
        )
        out[key] = _parse_row_hit(r)
    return out


def _leg_decided_hr(props: list[dict], *, pick: str, hot_only: bool = True) -> dict[str, Any]:
    want = str(pick).strip().title()
    hits = misses = 0
    for r in props:
        pt = str(r.get("pick_type") or "").strip().title()
        st = str(r.get("l10_streak") or "").upper().strip()
        tier = str(r.get("tier") or "").upper().strip()
        sp = str(r.get("sport") or "").upper().strip()
        if pt != want or tier not in ("A", "B"):
            continue
        if hot_only and st != "HOT":
            continue
        if sp not in ("NBA", "NBA1Q", "WNBA", "MLB"):
            continue
        h = _parse_row_hit(r)
        if h is None:
            continue
        if h == 1:
            hits += 1
        else:
            misses += 1
    n = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "n": n,
        "hr_pct": round(100.0 * hits / n, 1) if n else None,
    }


def _gate_pass_stats(df: pd.DataFrame, *, pick_mode: str) -> dict[str, Any]:
    """Count Standard rows that clear probability-first / HOT candidate gates."""
    prepared = _prepare_strong_builder_pool(df)
    if prepared is None or prepared.empty:
        return {
            "pool_rows": 0,
            "standard_ab": 0,
            "gate_pass": 0,
            "gate_pass_pct": None,
            "avg_leg_prob": None,
            "by_direction": {},
        }
    pick = prepared.get("pick_type", pd.Series("", index=prepared.index)).astype(str).str.lower()
    tier = prepared.get("tier", pd.Series("", index=prepared.index)).astype(str).str.upper()
    std_ab = prepared[
        pick.str.contains("standard", na=False)
        & ~pick.str.contains("goblin", na=False)
        & tier.isin(["A", "B"])
    ]
    cands = _strong_candidate_legs(prepared, pick_mode=pick_mode)
    probs: list[float] = []
    by_dir: dict[str, dict[str, Any]] = {}
    for _, row in cands.iterrows() if not cands.empty else []:
        row_d = row.to_dict()
        p = float(_leg_prob_for_p_win_from_mapping(row_d))
        probs.append(p)
        d = str(row_d.get("direction") or "").strip().upper() or "UNK"
        slot = by_dir.setdefault(d, {"n": 0, "prob_sum": 0.0, "hits": 0, "misses": 0})
        slot["n"] += 1
        slot["prob_sum"] += p
        h = _parse_row_hit(row_d)
        if h == 1:
            slot["hits"] += 1
        elif h == 0:
            slot["misses"] += 1
    by_dir_out: dict[str, Any] = {}
    for d, slot in by_dir.items():
        n = int(slot["n"])
        hn = int(slot["hits"]) + int(slot["misses"])
        by_dir_out[d] = {
            "n": n,
            "avg_leg_prob": round(slot["prob_sum"] / n, 4) if n else None,
            "hits": int(slot["hits"]),
            "misses": int(slot["misses"]),
            "hr_pct": round(100.0 * int(slot["hits"]) / hn, 1) if hn else None,
            "min_floor_example": _standard_direction_floor({"direction": d, "sport": "WNBA"})
            if d in ("OVER", "UNDER")
            else None,
        }
    n_std = int(len(std_ab))
    n_pass = int(len(cands))
    return {
        "pool_rows": int(len(prepared)),
        "standard_ab": n_std,
        "gate_pass": n_pass,
        "gate_pass_pct": round(100.0 * n_pass / n_std, 1) if n_std else None,
        "avg_leg_prob": round(sum(probs) / len(probs), 4) if probs else None,
        "by_direction": by_dir_out,
    }


def _ticket_quality(tickets: list[dict]) -> dict[str, Any]:
    if not tickets:
        return {
            "n": 0,
            "avg_est_win_prob": None,
            "avg_ev_power": None,
            "by_n_legs": {},
        }
    p_wins = [float(t.get("est_win_prob") or 0.0) for t in tickets]
    evs = [float(t.get("ev_power") or 0.0) for t in tickets]
    by_n: dict[str, int] = {}
    for t in tickets:
        k = str(int(t.get("n_legs") or 0))
        by_n[k] = by_n.get(k, 0) + 1
    return {
        "n": len(tickets),
        "avg_est_win_prob": round(sum(p_wins) / len(p_wins), 4),
        "avg_ev_power": round(sum(evs) / len(evs), 4),
        "by_n_legs": by_n,
    }


def _grade_saved_goblin_strong(date_str: str, graded: dict[tuple, int | None]) -> dict[str, Any]:
    path = _REPO / "ui_runner" / "data" / f"combined_slate_tickets_{date_str}.json"
    if not path.is_file():
        return {"file": None, "built": 0, **summarize([])}
    payload = json.loads(path.read_text(encoding="utf-8"))
    results: list[str] = []
    for _, t in iter_tickets(payload):
        if not t.get("strong_builder"):
            continue
        if str(t.get("strong_builder_pick") or "").lower() == "standard":
            continue
        results.append(grade_ticket_legs(t.get("legs") or [], graded))
    s = summarize(results)
    return {"file": str(path.name), "built": len(results), **s}


def analyze_date(
    date_str: str,
    *,
    pick_mode: str,
    max_tickets: int,
    max_legs: int,
    exhaust_pool: bool,
    quiet: bool,
    include_goblin_cmp: bool,
) -> dict[str, Any] | None:
    path = _graded_props_path(date_str)
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    props = raw.get("props") if isinstance(raw, dict) else raw
    if not isinstance(props, list) or not props:
        return None

    mode = str(pick_mode or "standard_prob").strip().lower()
    df = _props_to_df(props)
    gates = _gate_pass_stats(df, pick_mode=mode)

    if mode in ("standard", "std"):
        hot_streaks = sum(1 for r in props if str(r.get("l10_streak") or "").upper().strip() == "HOT")
        if hot_streaks <= 0:
            return {
                "date": date_str,
                "skipped": "no_hot_streaks",
                "pick_mode": mode,
                "gates": gates,
                "std_leg": _leg_decided_hr(props, pick="Standard", hot_only=True),
            }

    if not quiet:
        print(f"\n... building {date_str} mode={mode} (props={len(df)})", flush=True)
    std_tickets = build_strong_tickets(
        df,
        date_str=date_str,
        pick_mode=mode,
        max_tickets=max_tickets,
        max_legs=max_legs,
        exhaust_pool=exhaust_pool,
    )
    gradeable = _tickets_to_gradeable(std_tickets)
    graded_idx = _grade_index_from_props(props)
    shared = load_graded(date_str)
    if shared:
        graded_idx = shared

    results = [grade_ticket_legs(t.get("legs") or [], graded_idx) for t in gradeable]
    std_s = summarize(results)
    quality = _ticket_quality(std_tickets)

    # Candidate-leg realized HR (gate-pass legs only).
    cand_df = _strong_candidate_legs(_prepare_strong_builder_pool(df), pick_mode=mode)
    cand_hits = cand_misses = 0
    for _, row in cand_df.iterrows() if not cand_df.empty else []:
        h = _parse_row_hit(row.to_dict())
        if h == 1:
            cand_hits += 1
        elif h == 0:
            cand_misses += 1
    cand_n = cand_hits + cand_misses
    cand_leg = {
        "hits": cand_hits,
        "misses": cand_misses,
        "n": cand_n,
        "hr_pct": round(100.0 * cand_hits / cand_n, 1) if cand_n else None,
    }

    row: dict[str, Any] = {
        "date": date_str,
        "pick_mode": mode,
        "graded_file": str(path.relative_to(_REPO)).replace("\\", "/"),
        "gates": gates,
        "std_candidates_built": len(std_tickets),
        "std_ticket": {"built": len(gradeable), **std_s},
        "ticket_quality": quality,
        "std_leg_gate_pass": cand_leg,
        "std_leg_hot_ab": _leg_decided_hr(props, pick="Standard", hot_only=True),
    }
    if include_goblin_cmp:
        row["goblin_strong_saved"] = _grade_saved_goblin_strong(date_str, graded_idx)
        row["goblin_leg"] = _leg_decided_hr(props, pick="Goblin", hot_only=True)

    if not quiet:
        print(f"\n{'=' * 60}")
        print(f"  {date_str}  [{mode}]")
        print(f"{'=' * 60}")
        g = gates
        print(
            f"  Gate pass: {g.get('gate_pass')}/{g.get('standard_ab')} Standard A/B "
            f"({g.get('gate_pass_pct')}%)  avg_leg_p={g.get('avg_leg_prob')}"
        )
        print(
            f"  Tickets: {std_s.get('win_pct')}%  "
            f"({std_s.get('wins')}/{std_s.get('n_graded')})  "
            f"built={len(gradeable)} ungraded={std_s.get('ungraded')}  "
            f"avg_p_win={quality.get('avg_est_win_prob')} avg_EV={quality.get('avg_ev_power')}"
        )
        print(
            f"  Gate-pass legs HR: {cand_leg.get('hr_pct')}%  "
            f"({cand_leg.get('hits')}/{cand_leg.get('n')})"
        )
    return row


def _rollup(days: list[dict[str, Any]], *, include_goblin_cmp: bool) -> dict[str, Any]:
    def acc(path_keys: tuple[str, ...], win_key: str = "wins", n_key: str = "n_graded"):
        w = n = built = 0
        for d in days:
            node: Any = d
            for k in path_keys:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(k)
            if not isinstance(node, dict):
                continue
            built += int(node.get("built") or 0)
            n += int(node.get(n_key) or 0)
            w += int(node.get(win_key) or 0)
        return {
            "built": built,
            "wins": w,
            "n_graded": n,
            "win_pct": round(100.0 * w / n, 1) if n else None,
        }

    def acc_leg(key: str):
        hits = misses = 0
        for d in days:
            node = d.get(key) if isinstance(d, dict) else None
            if not isinstance(node, dict):
                continue
            hits += int(node.get("hits") or 0)
            misses += int(node.get("misses") or 0)
        n = hits + misses
        return {
            "hits": hits,
            "misses": misses,
            "n": n,
            "hr_pct": round(100.0 * hits / n, 1) if n else None,
        }

    usable = [d for d in days if not d.get("skipped")]
    gate_pass = std_ab = 0
    prob_sum = 0.0
    prob_n = 0
    p_win_sum = 0.0
    ev_sum = 0.0
    q_n = 0
    for d in usable:
        g = d.get("gates") if isinstance(d, dict) else None
        if isinstance(g, dict):
            gate_pass += int(g.get("gate_pass") or 0)
            std_ab += int(g.get("standard_ab") or 0)
            ap = g.get("avg_leg_prob")
            if ap is not None and int(g.get("gate_pass") or 0) > 0:
                # weight by gate_pass count
                n_gp = int(g.get("gate_pass") or 0)
                prob_sum += float(ap) * n_gp
                prob_n += n_gp
        q = d.get("ticket_quality") if isinstance(d, dict) else None
        if isinstance(q, dict) and int(q.get("n") or 0) > 0:
            nn = int(q["n"])
            if q.get("avg_est_win_prob") is not None:
                p_win_sum += float(q["avg_est_win_prob"]) * nn
            if q.get("avg_ev_power") is not None:
                ev_sum += float(q["avg_ev_power"]) * nn
            q_n += nn

    out: dict[str, Any] = {
        "days_scanned": len(days),
        "days_built": len(usable),
        "days_skipped_no_hot": sum(1 for d in days if d.get("skipped") == "no_hot_streaks"),
        "gates": {
            "standard_ab": std_ab,
            "gate_pass": gate_pass,
            "gate_pass_pct": round(100.0 * gate_pass / std_ab, 1) if std_ab else None,
            "avg_leg_prob": round(prob_sum / prob_n, 4) if prob_n else None,
        },
        "standard_strong_tickets": acc(("std_ticket",)),
        "ticket_quality": {
            "n": q_n,
            "avg_est_win_prob": round(p_win_sum / q_n, 4) if q_n else None,
            "avg_ev_power": round(ev_sum / q_n, 4) if q_n else None,
        },
        "standard_gate_pass_legs": acc_leg("std_leg_gate_pass"),
        "standard_hot_ab_legs": acc_leg("std_leg_hot_ab"),
    }
    if include_goblin_cmp:
        out["goblin_strong_saved_tickets"] = acc(("goblin_strong_saved",))
        out["goblin_hot_ab_legs"] = acc_leg("goblin_leg")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Backtest STRONG Standard (HOT or probability-first) from graded_props."
    )
    ap.add_argument("--from", dest="from_date", default="2026-06-26")
    ap.add_argument("--to", dest="to_date", default="")
    ap.add_argument(
        "--mode",
        choices=("standard_prob", "standard"),
        default="standard_prob",
        help="standard_prob = O/U probability floors (default); standard = HOT mirror",
    )
    ap.add_argument("--max-tickets", type=int, default=25, help="Board cap when not exhausting.")
    ap.add_argument("--max-legs", type=int, default=3, help="Max legs per reconstructed STRONG slip.")
    ap.add_argument(
        "--exhaust",
        action="store_true",
        help="Exhaust combo pool (slower; uses STRONG hard max).",
    )
    ap.add_argument(
        "--compare-goblin",
        action="store_true",
        help="Also grade saved Goblin STRONG tickets (reference only).",
    )
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--out",
        default="",
        help="Output JSON path (default depends on --mode).",
    )
    args = ap.parse_args()
    to_date = (args.to_date or "").strip() or date.today().isoformat()
    from_date = args.from_date.strip()
    mode = str(args.mode).strip().lower()
    include_goblin = bool(args.compare_goblin) or mode == "standard"
    dates = _list_graded_dates(from_date, to_date)
    if not dates:
        print(f"No graded_props files between {from_date} and {to_date}")
        return 1

    default_out = (
        _REPO / "data" / "reports" / "strong_standard_prob_backtest_latest.json"
        if mode == "standard_prob"
        else _REPO / "data" / "reports" / "strong_standard_backtest_latest.json"
    )
    out_path = Path(args.out.strip() or str(default_out))

    print(
        f"STRONG Standard backtest mode={mode} {from_date} → {to_date} "
        f"({len(dates)} graded days, exhaust={bool(args.exhaust)}, max_legs={int(args.max_legs)})"
    )
    days: list[dict[str, Any]] = []
    for ds in dates:
        row = analyze_date(
            ds,
            pick_mode=mode,
            max_tickets=max(5, int(args.max_tickets)),
            max_legs=max(2, min(6, int(args.max_legs))),
            exhaust_pool=bool(args.exhaust),
            quiet=bool(args.quiet),
            include_goblin_cmp=include_goblin,
        )
        if row:
            days.append(row)

    summary = _rollup(days, include_goblin_cmp=include_goblin)
    out = {
        "generated_at": date.today().isoformat(),
        "from": from_date,
        "to": to_date,
        "pick_mode": mode,
        "params": {
            "max_tickets": int(args.max_tickets),
            "max_legs": int(args.max_legs),
            "exhaust": bool(args.exhaust),
            "compare_goblin": include_goblin,
        },
        "summary": summary,
        "days": days,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print("  ROLLUP")
    print(f"{'=' * 60}")
    g = summary["gates"]
    st = summary["standard_strong_tickets"]
    tq = summary["ticket_quality"]
    gl = summary["standard_gate_pass_legs"]
    print(
        f"  Gate pass: {g.get('gate_pass')}/{g.get('standard_ab')} Standard A/B "
        f"({g.get('gate_pass_pct')}%)  avg_leg_p={g.get('avg_leg_prob')}"
    )
    print(
        f"  Standard tickets: {st.get('win_pct')}%  "
        f"({st.get('wins')}/{st.get('n_graded')})  built={st.get('built')}  "
        f"avg_p_win={tq.get('avg_est_win_prob')} avg_EV={tq.get('avg_ev_power')}"
    )
    print(
        f"  Gate-pass legs:   {gl.get('hr_pct')}%  "
        f"({gl.get('hits')}/{gl.get('n')})"
    )
    if include_goblin and "goblin_strong_saved_tickets" in summary:
        gb = summary["goblin_strong_saved_tickets"]
        print(
            f"  Goblin STRONG (ref): {gb.get('win_pct')}%  "
            f"({gb.get('wins')}/{gb.get('n_graded')})  built={gb.get('built')}"
        )
    print(f"  Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
