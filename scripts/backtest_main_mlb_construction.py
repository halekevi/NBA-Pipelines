#!/usr/bin/env python3
"""
Backtest MAIN MLB construction filters on historical graded ticket boards.

Two lenses:
  1) Filter-replay on archived combined_slate_tickets_*.json (graded_main) + long_parlay
  2) Filter-replay on ticket_eval_*.html cards (full MAIN eval board with outcomes)

Compares policy ablations (baseline → narrow ban → full current → stricter) on
hit rate and flat-$10 power ROI among fully graded tickets.

Writes data/reports/main_mlb_construction_backtest_latest.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
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
from backtest_strong_standard import (  # noqa: E402
    _grade_index_from_props,
    _graded_props_path,
)

_PWR = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 40.0}

# Narrow ban: Jul-18 stress props only (Hits / TB / H+R+RBI / hitter Ks)
_NARROW_HITTER_OVER = frozenset(
    {
        "hits",
        "totalbases",
        "hitsrunsrbis",
        "hitsrunsrebis",
        "hitrbis",
        "hitterstrikeouts",
        "batterstrikeouts",
    }
)


def _norm_prop(prop: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(prop or "").strip().lower())


def _pick(leg: dict) -> str:
    return str(leg.get("pick_type") or "").strip().lower()


def _dir(leg: dict) -> str:
    return str(
        leg.get("direction") or leg.get("over_under") or leg.get("bet_direction") or ""
    ).strip().upper()


def _sport(leg: dict) -> str:
    return str(leg.get("sport") or "").strip().upper()


def _prop(leg: dict) -> str:
    return _norm_prop(leg.get("prop_type") or leg.get("prop") or "")


def _is_mlb_hitter_core(prop_n: str) -> bool:
    if not prop_n:
        return False
    if prop_n in cst.MAIN_MLB_GOBLIN_OVER_ALLOW_NORMS:
        return False
    return prop_n in cst.MAIN_BANNED_GOBLIN_PROP_NORMS.get("MLB", frozenset())


def ticket_flags(legs: list[dict]) -> dict[str, bool]:
    """Boolean attributes used by policy ablations."""
    has_banned_gob_over = False
    has_narrow_gob_over = False
    has_mlb_std_over = False
    has_unknown_mlb_gob_over = False
    mlb_hitter_legs: list[dict] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        if _sport(leg) != "MLB":
            continue
        pt = _pick(leg)
        d = _dir(leg)
        pn = _prop(leg)
        if "goblin" in pt and d == "OVER":
            if pn in cst.MAIN_MLB_GOBLIN_OVER_ALLOW_NORMS:
                pass
            elif pn in cst.MAIN_BANNED_GOBLIN_PROP_NORMS.get("MLB", frozenset()):
                has_banned_gob_over = True
                if pn in _NARROW_HITTER_OVER:
                    has_narrow_gob_over = True
            else:
                has_unknown_mlb_gob_over = True
                has_banned_gob_over = True
        if "standard" in pt and "goblin" not in pt and d == "OVER":
            has_mlb_std_over = True
        if _is_mlb_hitter_core(pn):
            mlb_hitter_legs.append(leg)

    sg_hitter_stack = False
    if len(mlb_hitter_legs) >= 2:
        by_game: dict[str, int] = {}
        by_team: dict[str, int] = {}
        for leg in mlb_hitter_legs:
            team = str(leg.get("team") or "").strip().upper()
            opp = str(leg.get("opp") or leg.get("opp_team") or "").strip().upper()
            if team and opp:
                gk = "|".join(sorted([team, opp]))
                by_game[gk] = by_game.get(gk, 0) + 1
            if team:
                by_team[team] = by_team.get(team, 0) + 1
        sg_hitter_stack = any(n >= 2 for n in by_game.values()) or any(
            n >= 2 for n in by_team.values()
        )

    return {
        "has_banned_gob_over": has_banned_gob_over,
        "has_narrow_gob_over": has_narrow_gob_over,
        "has_mlb_std_over": has_mlb_std_over,
        "has_unknown_mlb_gob_over": has_unknown_mlb_gob_over,
        "sg_hitter_stack": sg_hitter_stack,
        "has_any_mlb_hitter": bool(mlb_hitter_legs),
    }


# Policy keep predicates (True = keep ticket)
POLICIES: dict[str, Any] = {
    "baseline": lambda f: True,
    "narrow_hitter_gob_over_ban": lambda f: not f["has_narrow_gob_over"],
    "full_hitter_gob_over_ban": lambda f: not f["has_banned_gob_over"],
    "plus_mlb_std_over_ban": lambda f: (not f["has_banned_gob_over"])
    and (not f["has_mlb_std_over"]),
    # Production after backtest: prop bans only (stack reject demoted to audit).
    "current_shipped": lambda f: (not f["has_banned_gob_over"])
    and (not f["has_mlb_std_over"]),
    "with_stack_reject": lambda f: (not f["has_banned_gob_over"])
    and (not f["has_mlb_std_over"])
    and (not f["sg_hitter_stack"]),
    "pitcher_only_mlb_legs": lambda f: (not f["has_any_mlb_hitter"])
    and (not f["has_mlb_std_over"]),
}


def _roi_flat10(
    results: list[str], n_legs: list[int], *, fixed_mult: float | None = None
) -> dict[str, Any]:
    """Flat $10 power ROI. fixed_mult=3.0 ignores leg-count payout variance."""
    staked = 0.0
    pnl = 0.0
    n = 0
    for res, nl in zip(results, n_legs):
        if res not in ("WIN", "LOSS"):
            continue
        mult = float(fixed_mult) if fixed_mult is not None else float(_PWR.get(int(nl), 3.0))
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
        "fixed_mult": fixed_mult,
    }


def _score_subset(
    rows: list[dict[str, Any]], keep_fn
) -> dict[str, Any]:
    kept = [r for r in rows if keep_fn(r["flags"])]
    dropped = [r for r in rows if not keep_fn(r["flags"])]
    res_k = [r["result"] for r in kept]
    nl_k = [r["n_legs"] for r in kept]
    res_d = [r["result"] for r in dropped]
    nl_d = [r["n_legs"] for r in dropped]
    sk = summarize(res_k)
    sd = summarize(res_d)
    # Short-board view (2–3 legs) — closest to current MAIN_GRADED_MAX_LEGS=3.
    kept_short = [r for r in kept if int(r["n_legs"]) <= 3]
    return {
        "kept": {
            **sk,
            "roi_flat10": _roi_flat10(res_k, nl_k),
            "roi_flat10_3x": _roi_flat10(res_k, nl_k, fixed_mult=3.0),
            "n_raw": len(kept),
            "short_le3": {
                **summarize([r["result"] for r in kept_short]),
                "roi_flat10_3x": _roi_flat10(
                    [r["result"] for r in kept_short],
                    [r["n_legs"] for r in kept_short],
                    fixed_mult=3.0,
                ),
                "n_raw": len(kept_short),
            },
        },
        "dropped": {
            **sd,
            "roi_flat10": _roi_flat10(res_d, nl_d),
            "roi_flat10_3x": _roi_flat10(res_d, nl_d, fixed_mult=3.0),
            "n_raw": len(dropped),
        },
    }


def _iter_payload_tickets(payload: dict) -> list[dict]:
    out: list[dict] = []
    for g in payload.get("groups") or []:
        if not isinstance(g, dict):
            continue
        for t in g.get("tickets") or []:
            if isinstance(t, dict):
                out.append(t)
    return out


def _load_graded_idx(date: str) -> dict:
    idx = load_graded(date)
    if idx:
        return idx
    path = _graded_props_path(date)
    if path is None:
        # try templates
        for root in (
            _REPO / "mobile" / "www",
            _REPO / "ui_runner" / "templates",
        ):
            p = root / f"graded_props_{date}.json"
            if p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8"))
                props = raw.get("props") if isinstance(raw, dict) else raw
                if isinstance(props, list):
                    return _grade_index_from_props(props)
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    props = raw.get("props") if isinstance(raw, dict) else raw
    if isinstance(props, list):
        return _grade_index_from_props(props)
    return {}


def collect_json_board(
    date: str, path: Path, graded_idx: dict
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for t in _iter_payload_tickets(payload):
        legs = [leg for leg in (t.get("legs") or t.get("rows") or []) if isinstance(leg, dict)]
        if not legs:
            continue
        result = grade_ticket_legs(legs, graded_idx)
        rows.append(
            {
                "date": date,
                "n_legs": int(t.get("n_legs") or len(legs)),
                "result": result,
                "flags": ticket_flags(legs),
                "sports": sorted(
                    {
                        _sport(leg)
                        for leg in legs
                        if _sport(leg)
                    }
                ),
            }
        )
    return rows


_LEG_RE = re.compile(
    r'<div class="legrow leg-(hit|miss|pending|void)[^"]*".*?'
    r'<span class="pill[^"]*">([A-Z0-9]+)</span>.*?'
    r'<div class="pl-(?:hit|miss|line|pending|void)[^"]*">(?:<span class="pl-name">)?([^<]+).*?'
    r'<div class="leg-prop-col[^"]*"><div>([^<]+)</div><div class="meta-muted">([^<]*)</div>.*?'
    r'(?:<div class="leg-extra[^"]*">\s*([\d.]+)\s*<span class="dir-(over|under)">)?'
    r'.*?(?:Goblin|Standard|Demon|goblin|standard|demon)',
    re.DOTALL | re.IGNORECASE,
)

# More reliable: parse pick type from nearby text
_PICK_RE = re.compile(r"\b(Goblin|Standard|Demon)\b", re.IGNORECASE)
_DIR_RE = re.compile(r'class="dir-(over|under)"', re.IGNORECASE)
_LINE_RE = re.compile(r'<div class="leg-extra[^"]*">\s*([\d.]+)', re.IGNORECASE)
_TEAM_RE = re.compile(
    r'<div class="meta-muted">\s*([A-Za-z0-9]+)\s*(?:@|vs\.?|v)\s*([A-Za-z0-9]+)',
    re.IGNORECASE,
)


def _parse_eval_legs(card_html: str) -> list[dict]:
    legs: list[dict] = []
    chunks = re.split(r'<div class="legrow leg-', card_html)[1:]
    for chunk in chunks:
        result_m = re.match(r"(hit|miss|pending|void)", chunk, re.I)
        leg_result = result_m.group(1).lower() if result_m else "pending"
        sport_m = re.search(r'<span class="pill[^"]*">([A-Z0-9]+)</span>', chunk)
        sport = sport_m.group(1).upper() if sport_m else ""
        prop_m = re.search(
            r'<div class="leg-prop-col[^"]*"><div>([^<]+)</div>', chunk
        )
        prop = prop_m.group(1).strip() if prop_m else ""
        # Ticket-eval uses G/S/D tier pills; fall back to Goblin/Standard text.
        tier_m = re.search(
            r'<div class="tier[^"]*">\s*([GSD])\s*</div>', chunk, re.IGNORECASE
        )
        pick = ""
        if tier_m:
            pick = {"G": "Goblin", "S": "Standard", "D": "Demon"}.get(
                tier_m.group(1).upper(), ""
            )
        if not pick:
            pick_m = _PICK_RE.search(chunk)
            pick = pick_m.group(1) if pick_m else ""
        dir_m = _DIR_RE.search(chunk)
        direction = dir_m.group(1).upper() if dir_m else ""
        line_m = _LINE_RE.search(chunk)
        line = line_m.group(1) if line_m else ""
        team = opp = ""
        tm = _TEAM_RE.search(chunk)
        if tm:
            team, opp = tm.group(1).upper(), tm.group(2).upper()
        # also try "NYY vs BOS" in meta
        if not team:
            meta_m = re.search(
                r'<div class="meta-muted">([^<]+)</div>', chunk
            )
            if meta_m:
                meta = meta_m.group(1)
                parts = re.split(r"\s+(?:@|vs\.?|v)\s+", meta, flags=re.I)
                if len(parts) == 2:
                    team, opp = parts[0].strip().upper(), parts[1].strip().upper()
        legs.append(
            {
                "sport": sport,
                "prop_type": prop,
                "pick_type": pick,
                "direction": direction,
                "line": line,
                "team": team,
                "opp": opp,
                "_leg_result": leg_result,
            }
        )
    return legs


def collect_eval_html(date: str, path: Path) -> list[dict[str, Any]]:
    html = path.read_text(encoding="utf-8", errors="ignore")
    cards = re.split(r'<article class="ticket-card ', html)[1:]
    rows: list[dict[str, Any]] = []
    for i, raw in enumerate(cards):
        cls = raw.split(">", 1)[0]
        if "all-hit" in cls or "card-sweep" in cls:
            result = "WIN"
        elif "card-missed" in cls or "card-loss" in cls:
            result = "LOSS"
        elif "card-void" in cls:
            result = "VOID"
        else:
            # Infer from legs if class ambiguous
            legs_tmp = _parse_eval_legs(raw)
            decided = [l for l in legs_tmp if l.get("_leg_result") in ("hit", "miss")]
            if not decided:
                result = "UNGRADED"
            elif all(l["_leg_result"] == "hit" for l in decided) and len(decided) == len(
                legs_tmp
            ):
                result = "WIN"
            elif any(l["_leg_result"] == "miss" for l in decided):
                result = "LOSS"
            else:
                result = "UNGRADED"
        legs = _parse_eval_legs(raw)
        if not legs:
            continue
        # Prefer power win = all legs hit among decided; skip all-void
        if result == "VOID":
            continue
        rows.append(
            {
                "date": date,
                "n_legs": len(legs),
                "result": result,
                "flags": ticket_flags(legs),
                "sports": sorted({str(l.get("sport") or "") for l in legs if l.get("sport")}),
                "source": "ticket_eval_html",
                "card_i": i,
            }
        )
    return rows


def _list_dates(from_date: str, to_date: str) -> list[str]:
    dates: set[str] = set()
    data = _REPO / "ui_runner" / "data"
    for p in data.glob("combined_slate_tickets_2026-*.json"):
        # skip mode-suffixed
        name = p.name
        if name.count("_") > 3:
            # combined_slate_tickets_long_parlay_DATE has extra tokens
            continue
        m = re.match(r"combined_slate_tickets_(\d{4}-\d{2}-\d{2})\.json$", name)
        if not m:
            continue
        ds = m.group(1)
        if from_date <= ds <= to_date:
            dates.add(ds)
    tmpl = _REPO / "ui_runner" / "templates"
    for p in tmpl.glob("ticket_eval_2026-*.html"):
        if "long_parlay" in p.name or "winrate" in p.name or "strong" in p.name:
            continue
        m = re.match(r"ticket_eval_(\d{4}-\d{2}-\d{2})\.html$", p.name)
        if not m:
            continue
        ds = m.group(1)
        if from_date <= ds <= to_date:
            dates.add(ds)
    return sorted(dates)


def run_board(
    label: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    empty = {
        "label": label,
        "n_tickets": 0,
        "n_mlb_touching": 0,
        "baseline_all": summarize([]),
        "baseline_mlb": summarize([]),
        "flag_rates": {},
        "policies_all": {},
        "policies_mlb": {},
    }
    if not rows:
        return empty
    # MLB-touching subset for focused view
    mlb_rows = [r for r in rows if "MLB" in (r.get("sports") or [])]
    out: dict[str, Any] = {
        "label": label,
        "n_tickets": len(rows),
        "n_mlb_touching": len(mlb_rows),
        "baseline_all": summarize([r["result"] for r in rows]),
        "baseline_mlb": summarize([r["result"] for r in mlb_rows]),
        "flag_rates": {},
        "policies_all": {},
        "policies_mlb": {},
    }
    # flag prevalence among graded
    graded = [r for r in rows if r["result"] in ("WIN", "LOSS")]
    if graded:
        for key in (
            "has_narrow_gob_over",
            "has_banned_gob_over",
            "has_mlb_std_over",
            "sg_hitter_stack",
            "has_any_mlb_hitter",
        ):
            hit = [r for r in graded if r["flags"].get(key)]
            out["flag_rates"][key] = {
                "n": len(hit),
                "pct": round(100.0 * len(hit) / len(graded), 1),
                "win_pct": summarize([r["result"] for r in hit]).get("win_pct"),
                "roi_flat10": _roi_flat10(
                    [r["result"] for r in hit], [r["n_legs"] for r in hit]
                ),
                "roi_flat10_3x": _roi_flat10(
                    [r["result"] for r in hit],
                    [r["n_legs"] for r in hit],
                    fixed_mult=3.0,
                ),
            }
    for name, fn in POLICIES.items():
        out["policies_all"][name] = _score_subset(rows, fn)
        out["policies_mlb"][name] = _score_subset(mlb_rows, fn)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_date", default="2026-07-01")
    ap.add_argument("--to", dest="to_date", default="2026-07-18")
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO / "data" / "reports" / "main_mlb_construction_backtest_latest.json",
    )
    args = ap.parse_args()

    dates = _list_dates(args.from_date, args.to_date)
    print(f"MAIN MLB construction backtest {args.from_date} → {args.to_date} ({len(dates)} days)")

    json_main_rows: list[dict] = []
    json_long_rows: list[dict] = []
    html_rows: list[dict] = []
    by_day: list[dict] = []

    for d in dates:
        day: dict[str, Any] = {"date": d}
        graded_idx = _load_graded_idx(d)

        main_path = _REPO / "ui_runner" / "data" / f"combined_slate_tickets_{d}.json"
        if main_path.is_file() and graded_idx:
            rows = collect_json_board(d, main_path, graded_idx)
            json_main_rows.extend(rows)
            day["json_main_n"] = len(rows)
            day["json_main"] = run_board("json_main", rows)
            print(
                f"  {d} json_main n={len(rows)} "
                f"WR={day['json_main']['baseline_all'].get('win_pct')}%"
            )
        else:
            day["json_main_n"] = 0

        long_path = (
            _REPO / "ui_runner" / "data" / f"combined_slate_tickets_long_parlay_{d}.json"
        )
        if long_path.is_file() and graded_idx:
            rows = collect_json_board(d, long_path, graded_idx)
            json_long_rows.extend(rows)
            day["json_long_n"] = len(rows)
            day["json_long"] = run_board("json_long", rows)
            print(
                f"  {d} json_long n={len(rows)} "
                f"WR={day['json_long']['baseline_all'].get('win_pct')}%"
            )
        else:
            day["json_long_n"] = 0

        html_path = _REPO / "ui_runner" / "templates" / f"ticket_eval_{d}.html"
        if html_path.is_file():
            rows = collect_eval_html(d, html_path)
            html_rows.extend(rows)
            day["html_n"] = len(rows)
            day["html"] = run_board("ticket_eval_html", rows)
            print(
                f"  {d} html_eval n={len(rows)} "
                f"WR={day['html']['baseline_all'].get('win_pct')}%"
            )
        else:
            day["html_n"] = 0

        by_day.append(day)

    report = {
        "from_date": args.from_date,
        "to_date": args.to_date,
        "dates": dates,
        "policy_names": list(POLICIES.keys()),
        "policy_notes": {
            "baseline": "Keep all historical tickets",
            "narrow_hitter_gob_over_ban": "Drop tickets with Hits/TB/HRRBI/hitterK Goblin OVER",
            "full_hitter_gob_over_ban": "Drop tickets with any non-pitcher MLB Goblin OVER",
            "plus_mlb_std_over_ban": "Full hitter Goblin OVER ban + MLB Standard OVER ban",
            "current_shipped": "Production: prop bans only (stack reject is audit-only)",
            "with_stack_reject": "Prop bans + same-game hitter stack reject (ablation; no rebuild lift)",
            "pitcher_only_mlb_legs": "Stricter: no MLB hitter props at all + no MLB Standard OVER",
        },
        "aggregate": {
            "json_main": run_board("json_main", json_main_rows),
            "json_long": run_board("json_long", json_long_rows),
            "ticket_eval_html": run_board("ticket_eval_html", html_rows),
        },
        "by_day": by_day,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {args.out}")

    # Console leaderboard for html + json_main MLB subsets
    for board_key in ("ticket_eval_html", "json_main", "json_long"):
        board = report["aggregate"][board_key]
        print(f"\n=== {board_key} (MLB-touching) n={board.get('n_mlb_touching')} ===")
        pols = board.get("policies_mlb") or {}
        rows_print = []
        for name, block in pols.items():
            k = block.get("kept") or {}
            roi = (k.get("roi_flat10") or {}).get("roi_pct")
            rows_print.append(
                (
                    name,
                    k.get("n_graded"),
                    k.get("win_pct"),
                    roi,
                    (block.get("dropped") or {}).get("n_graded"),
                    (block.get("dropped") or {}).get("win_pct"),
                )
            )
        print(
            f"{'policy':28} {'n':>5} {'WR%':>6} {'ROI_var':>8} {'ROI_3x':>7} "
            f"{'drop_n':>6} {'dropWR':>6} {'n<=3':>5} {'WR<=3':>6}"
        )
        for name, block in pols.items():
            k = block.get("kept") or {}
            d = block.get("dropped") or {}
            short = k.get("short_le3") or {}
            print(
                f"{name:28} {k.get('n_graded') or 0:5} "
                f"{k.get('win_pct') if k.get('win_pct') is not None else '-':>6} "
                f"{(k.get('roi_flat10') or {}).get('roi_pct') if (k.get('roi_flat10') or {}).get('roi_pct') is not None else '-':>8} "
                f"{(k.get('roi_flat10_3x') or {}).get('roi_pct') if (k.get('roi_flat10_3x') or {}).get('roi_pct') is not None else '-':>7} "
                f"{d.get('n_graded') or 0:6} "
                f"{d.get('win_pct') if d.get('win_pct') is not None else '-':>6} "
                f"{short.get('n_graded') or 0:5} "
                f"{short.get('win_pct') if short.get('win_pct') is not None else '-':>6}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
