#!/usr/bin/env python3
"""Backtest STRONG Standard HOT slips reconstructed from graded_props history.

No historical STRONG Standard tickets exist (production STRONG is Goblin-only),
so this rebuilds candidates from graded_props_{date}.json and grades in-file.
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
from combined_slate_tickets import build_strong_tickets  # noqa: E402
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
                "est_win_prob": t.get("est_win_prob"),
                "legs": legs,
            }
        )
    return out


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


def _line_key(v: object) -> str:
    try:
        return str(round(float(v or 0), 2))
    except (TypeError, ValueError):
        return "0.0"


def _leg_decided_hr(props: list[dict], *, pick: str) -> dict[str, Any]:
    want = str(pick).strip().title()
    hits = misses = 0
    for r in props:
        pt = str(r.get("pick_type") or "").strip().title()
        st = str(r.get("l10_streak") or "").upper().strip()
        tier = str(r.get("tier") or "").upper().strip()
        sp = str(r.get("sport") or "").upper().strip()
        if pt != want or st != "HOT" or tier not in ("A", "B"):
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


def _grade_saved_goblin_strong(date_str: str, graded: dict[tuple, int | None]) -> dict[str, Any]:
    path = _REPO / "ui_runner" / "data" / f"combined_slate_tickets_{date_str}.json"
    if not path.is_file():
        return {"file": None, "built": 0, **summarize([])}
    payload = json.loads(path.read_text(encoding="utf-8"))
    results: list[str] = []
    for _, t in iter_tickets(payload):
        if not t.get("strong_builder"):
            continue
        # Historical strong_builder is Goblin-only; still filter if pick tagged Standard.
        if str(t.get("strong_builder_pick") or "").lower() == "standard":
            continue
        results.append(grade_ticket_legs(t.get("legs") or [], graded))
    s = summarize(results)
    return {"file": str(path.name), "built": len(results), **s}


def analyze_date(
    date_str: str,
    *,
    max_tickets: int,
    max_legs: int,
    exhaust_pool: bool,
    quiet: bool,
) -> dict[str, Any] | None:
    path = _graded_props_path(date_str)
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    props = raw.get("props") if isinstance(raw, dict) else raw
    if not isinstance(props, list) or not props:
        return None

    hot_streaks = sum(1 for r in props if str(r.get("l10_streak") or "").upper().strip() == "HOT")
    if hot_streaks <= 0:
        return {
            "date": date_str,
            "skipped": "no_hot_streaks",
            "std_leg": _leg_decided_hr(props, pick="Standard"),
            "goblin_leg": _leg_decided_hr(props, pick="Goblin"),
        }

    df = _props_to_df(props)
    if not quiet:
        print(f"\n... building {date_str} (props={len(df)})", flush=True)
    std_tickets = build_strong_tickets(
        df,
        date_str=date_str,
        pick_mode="standard",
        max_tickets=max_tickets,
        max_legs=max_legs,
        exhaust_pool=exhaust_pool,
    )
    gradeable = _tickets_to_gradeable(std_tickets)
    graded_idx = _grade_index_from_props(props)
    # Prefer shared load_graded for www/templates parity when available.
    shared = load_graded(date_str)
    if shared:
        graded_idx = shared

    results = [grade_ticket_legs(t.get("legs") or [], graded_idx) for t in gradeable]
    std_s = summarize(results)
    goblin_s = _grade_saved_goblin_strong(date_str, graded_idx)

    row = {
        "date": date_str,
        "graded_file": str(path.relative_to(_REPO)).replace("\\", "/"),
        "std_candidates_built": len(std_tickets),
        "std_ticket": {"built": len(gradeable), **std_s},
        "std_leg": _leg_decided_hr(props, pick="Standard"),
        "goblin_strong_saved": goblin_s,
        "goblin_leg": _leg_decided_hr(props, pick="Goblin"),
    }
    if not quiet:
        print(f"\n{'=' * 60}")
        print(f"  {date_str}")
        print(f"{'=' * 60}")
        print(
            f"  Standard STRONG tickets: {std_s.get('win_pct')}%  "
            f"({std_s.get('wins')}/{std_s.get('n_graded')})  "
            f"built={len(gradeable)} ungraded={std_s.get('ungraded')}"
        )
        print(
            f"  Standard HOT A/B legs:   {row['std_leg'].get('hr_pct')}%  "
            f"({row['std_leg'].get('hits')}/{row['std_leg'].get('n')})"
        )
        gs = goblin_s
        print(
            f"  Goblin STRONG (saved):   {gs.get('win_pct')}%  "
            f"({gs.get('wins')}/{gs.get('n_graded')})  built={gs.get('built')}"
        )
    return row


def _rollup(days: list[dict[str, Any]]) -> dict[str, Any]:
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
    return {
        "days_scanned": len(days),
        "days_built": len(usable),
        "days_skipped_no_hot": sum(1 for d in days if d.get("skipped") == "no_hot_streaks"),
        "standard_strong_tickets": acc(("std_ticket",)),
        "goblin_strong_saved_tickets": acc(("goblin_strong_saved",)),
        "standard_hot_ab_legs": acc_leg("std_leg"),
        "goblin_hot_ab_legs": acc_leg("goblin_leg"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest STRONG Standard HOT from graded_props.")
    ap.add_argument("--from", dest="from_date", default="2026-06-26")
    ap.add_argument("--to", dest="to_date", default="")
    ap.add_argument("--max-tickets", type=int, default=25, help="Board cap when not exhausting.")
    ap.add_argument("--max-legs", type=int, default=3, help="Max legs per reconstructed STRONG slip.")
    ap.add_argument(
        "--exhaust",
        action="store_true",
        help="Exhaust combo pool (slower; uses STRONG hard max).",
    )
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--out",
        default=str(_REPO / "data" / "reports" / "strong_standard_backtest_latest.json"),
    )
    args = ap.parse_args()
    to_date = (args.to_date or "").strip() or date.today().isoformat()
    from_date = args.from_date.strip()
    dates = _list_graded_dates(from_date, to_date)
    if not dates:
        print(f"No graded_props files between {from_date} and {to_date}")
        return 1

    print(
        f"STRONG Standard HOT backtest {from_date} → {to_date} "
        f"({len(dates)} graded days, exhaust={bool(args.exhaust)}, max_legs={int(args.max_legs)})"
    )
    days: list[dict[str, Any]] = []
    for ds in dates:
        row = analyze_date(
            ds,
            max_tickets=max(5, int(args.max_tickets)),
            max_legs=max(2, min(6, int(args.max_legs))),
            exhaust_pool=bool(args.exhaust),
            quiet=bool(args.quiet),
        )
        if row:
            days.append(row)

    summary = _rollup(days)
    out = {
        "generated_at": date.today().isoformat(),
        "from": from_date,
        "to": to_date,
        "params": {
            "max_tickets": int(args.max_tickets),
            "max_legs": int(args.max_legs),
            "exhaust": bool(args.exhaust),
        },
        "summary": summary,
        "days": days,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print("  ROLLUP")
    print(f"{'=' * 60}")
    st = summary["standard_strong_tickets"]
    gb = summary["goblin_strong_saved_tickets"]
    sl = summary["standard_hot_ab_legs"]
    gl = summary["goblin_hot_ab_legs"]
    print(
        f"  Standard STRONG tickets: {st.get('win_pct')}%  "
        f"({st.get('wins')}/{st.get('n_graded')})  built={st.get('built')}"
    )
    print(
        f"  Goblin STRONG (saved):   {gb.get('win_pct')}%  "
        f"({gb.get('wins')}/{gb.get('n_graded')})  built={gb.get('built')}"
    )
    print(
        f"  Standard HOT A/B legs:   {sl.get('hr_pct')}%  "
        f"({sl.get('hits')}/{sl.get('n')})"
    )
    print(
        f"  Goblin HOT A/B legs:     {gl.get('hr_pct')}%  "
        f"({gl.get('hits')}/{gl.get('n')})"
    )
    print(f"  Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
