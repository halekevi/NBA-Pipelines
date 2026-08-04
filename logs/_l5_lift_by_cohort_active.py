"""L5 lift by sport × cohort (Std OVER / Std UNDER / Goblin) for active sports.

Uses graded_props_*.json (ui_runner/templates, then mobile/www).
Directional L5: l5_over for OVER, l5_under for UNDER; fallback hit_rate_l5*5.
MLB: exclude All-Star weekend via utils.allstar_filter; season from opener.

  py -3.14 logs/_l5_lift_by_cohort_active.py
  py -3.14 logs/_l5_lift_by_cohort_active.py --to 2026-08-03
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utils.allstar_filter import is_allstar_date  # noqa: E402
from utils.sport_season_windows import (  # noqa: E402
    ACTIVE_SPORTS,
    MLB_ASG_HARD,
    SPORT_FROM_DATES,
    SPORT_FROM_NOTES,
    from_dates_payload,
    sport_from_date,
)

SPORTS = ACTIVE_SPORTS
MLB_OPENER = SPORT_FROM_DATES["MLB"]
BASES = [REPO / "ui_runner" / "templates", REPO / "mobile" / "www"]


def _num(x):
    try:
        if x in (None, ""):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _is_hit(r: dict) -> bool | None:
    h = r.get("hit")
    if h in (True, 1, "1", "true", "True", "HIT", "hit", "W", "w"):
        return True
    if h in (False, 0, "0", "false", "False", "MISS", "miss", "L", "l"):
        return False
    res = str(r.get("result") or "").upper()
    if res in ("HIT", "W", "WIN"):
        return True
    if res in ("MISS", "L", "LOSS"):
        return False
    return None


def _norm_pick(pt: str) -> str:
    s = str(pt or "").lower()
    if "goblin" in s:
        return "Goblin"
    if "demon" in s:
        return "Demon"
    if "standard" in s:
        return "Standard"
    return "Other"


def _norm_prop(p: str) -> str:
    s = re.sub(r"\s+", " ", str(p or "").strip().lower().replace("_", " "))
    s = s.replace("+", " + ")
    s = re.sub(r"\s+", " ", s).strip()
    aliases = {
        "pts": "points",
        "reb": "rebounds",
        "rebs": "rebounds",
        "ast": "assists",
        "asts": "assists",
        "stl": "steals",
        "blk": "blocked shots",
        "blocks": "blocked shots",
        "3pm": "3-pt made",
        "3 pointers made": "3-pt made",
        "three pointers made": "3-pt made",
        "pra": "pts+rebs+asts",
        "pr": "pts+rebs",
        "pa": "pts+asts",
        "ra": "rebs+asts",
        "pts + rebs + asts": "pts+rebs+asts",
        "pts + rebs": "pts+rebs",
        "pts + asts": "pts+asts",
        "rebs + asts": "rebs+asts",
        "goal + assist": "goals+assists",
        "goals + assists": "goals+assists",
        "g+a": "goals+assists",
        "shots on target": "shots on target",
        "sot": "shots on target",
        "games won": "games won",
        "total games": "total games",
        "aces": "aces",
        "double faults": "double faults",
        "break points won": "break points won",
    }
    return aliases.get(s, s)


def _dir_l5(r: dict, direction: str) -> float | None:
    lo, lu = _num(r.get("l5_over")), _num(r.get("l5_under"))
    if direction == "OVER" and lo is not None:
        return lo
    if direction == "UNDER" and lu is not None:
        return lu
    # Some boards store only the side-aligned count in one field
    if direction == "OVER" and lu is not None and lo is None:
        # If only under present, don't invent over
        pass
    hr5 = _num(r.get("hit_rate_l5"))
    if hr5 is not None:
        # hit_rate_l5 is usually 0..1 fraction of last-5 in the picked direction
        if 0.0 <= hr5 <= 1.0:
            return round(hr5 * 5.0, 4)
        if 0.0 <= hr5 <= 5.0:
            return hr5
    return None


def _hr(xs: list[dict]) -> float | None:
    if not xs:
        return None
    return sum(1 for x in xs if x["hit"]) / len(xs)


def _stats(xs: list[dict]) -> dict:
    n = len(xs)
    base = _hr(xs)
    with_l5 = [x for x in xs if x["l5_side"] is not None]
    nol5 = [x for x in xs if x["l5_side"] is None]
    ge4 = [x for x in with_l5 if x["l5_side"] >= 4.0]
    lt4 = [x for x in with_l5 if x["l5_side"] < 4.0]
    eq5 = [x for x in with_l5 if abs(x["l5_side"] - 5.0) < 1e-9]
    hr_ge4, hr_lt4, hr_eq5, hr_nol5 = _hr(ge4), _hr(lt4), _hr(eq5), _hr(nol5)

    def lift(a, b):
        if a is None or b is None:
            return None
        return a - b

    # Prefer lift vs L5<4 when both sides have sample; also report vs all
    ref_lt4 = hr_lt4 if len(lt4) >= 20 else None
    return {
        "n": n,
        "hr": base,
        "n_with_l5": len(with_l5),
        "n_nol5": len(nol5),
        "hr_nol5": hr_nol5,
        "n_ge4": len(ge4),
        "hr_ge4": hr_ge4,
        "lift_ge4_vs_all": lift(hr_ge4, base),
        "lift_ge4_vs_lt4": lift(hr_ge4, ref_lt4) if ref_lt4 is not None else lift(hr_ge4, hr_lt4),
        "n_lt4": len(lt4),
        "hr_lt4": hr_lt4,
        "n_eq5": len(eq5),
        "hr_eq5": hr_eq5,
        "lift_eq5_vs_all": lift(hr_eq5, base),
        "lift_eq5_vs_lt4": lift(hr_eq5, ref_lt4) if ref_lt4 is not None else lift(hr_eq5, hr_lt4),
    }


def _pct(x: float | None) -> str:
    if x is None:
        return "  n/a"
    return f"{100 * x:5.1f}%"


def _pp(x: float | None) -> str:
    if x is None:
        return "  n/a"
    return f"{100 * x:+5.1f}"


def _fmt_row(label: str, s: dict) -> str:
    return (
        f"{label:28s} n={s['n']:6d} HR={_pct(s['hr'])} | "
        f"L5≥4 n={s['n_ge4']:5d} {_pct(s['hr_ge4'])} "
        f"Δall{_pp(s['lift_ge4_vs_all'])} Δ<4{_pp(s['lift_ge4_vs_lt4'])} | "
        f"L5=5 n={s['n_eq5']:4d} {_pct(s['hr_eq5'])} "
        f"Δall{_pp(s['lift_eq5_vs_all'])}"
        + (f" | nol5={s['n_nol5']}" if s["n_nol5"] >= 50 else "")
    )


def _iter_dates(d0: str, d1: str) -> list[str]:
    out = []
    cur = datetime.strptime(d0, "%Y-%m-%d").date()
    end = datetime.strptime(d1, "%Y-%m-%d").date()
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _find_graded(day: str) -> Path | None:
    for base in BASES:
        p = base / f"graded_props_{day}.json"
        if p.exists():
            return p
    return None


def _discover_range(date_to: str) -> tuple[str, str]:
    days = []
    for base in BASES:
        for p in base.glob("graded_props_*.json"):
            m = re.match(r"graded_props_(\d{4}-\d{2}-\d{2})\.json$", p.name)
            if m and m.group(1) <= date_to:
                days.append(m.group(1))
    if not days:
        return date_to, date_to
    return min(days), date_to


def load_rows(date_from: str, date_to: str) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    meta = {
        "days_used": [],
        "mlb_asg_skipped": [],
        "by_sport_days": defaultdict(set),
        "sport_from": from_dates_payload(),
    }
    for d in _iter_dates(date_from, date_to):
        path = _find_graded(d)
        if not path:
            continue
        # Day-level MLB ASG skip (belt + suspenders with is_allstar_date)
        mlb_asg_day = d in MLB_ASG_HARD or is_allstar_date(d, sport="MLB")
        if mlb_asg_day and d not in meta["mlb_asg_skipped"]:
            meta["mlb_asg_skipped"].append(d)
        props = json.loads(path.read_text(encoding="utf-8")).get("props") or []
        n_day = 0
        for r in props:
            sport = str(r.get("sport") or "").upper()
            if sport not in SPORTS:
                continue
            sport_from = sport_from_date(sport)
            if d < sport_from:
                continue
            if sport == "MLB" and mlb_asg_day:
                continue
            hit = _is_hit(r)
            if hit is None:
                continue
            direction = str(r.get("direction") or r.get("over_under") or "").upper()
            if direction not in ("OVER", "UNDER"):
                continue
            pick = _norm_pick(r.get("pick_type"))
            prop = _norm_prop(r.get("prop") or r.get("prop_type") or "")
            side = _dir_l5(r, direction)
            rows.append(
                {
                    "date": d,
                    "sport": sport,
                    "pick": pick,
                    "dir": direction,
                    "prop": prop,
                    "l5_side": side,
                    "hit": hit,
                }
            )
            meta["by_sport_days"][sport].add(d)
            n_day += 1
        if n_day:
            meta["days_used"].append(d)
    meta["by_sport_days"] = {k: sorted(v) for k, v in meta["by_sport_days"].items()}
    return rows, meta


def _fmt_prop_row(label: str, s: dict, caveat: str = "") -> str:
    cave = f"  [{caveat}]" if caveat else ""
    eq5 = ""
    if (s.get("n_eq5") or 0) >= 10:
        eq5 = f" | L5=5 n={s['n_eq5']:4d} {_pct(s['hr_eq5'])} Δall{_pp(s['lift_eq5_vs_all'])}"
    elif (s.get("n_eq5") or 0) > 0:
        eq5 = f" | L5=5 n={s['n_eq5']:4d} {_pct(s['hr_eq5'])} (thin)"
    nol5 = f" | nol5={s['n_nol5']}" if (s.get("n_nol5") or 0) >= 50 else ""
    return (
        f"{label:32s} n={s['n']:6d} HR={_pct(s['hr'])} | "
        f"L5≥4 n={s['n_ge4']:5d} {_pct(s['hr_ge4'])} Δ<4{_pp(s['lift_ge4_vs_lt4'])} "
        f"Δall{_pp(s['lift_ge4_vs_all'])}"
        f"{eq5}{nol5}{cave}"
    )


def _emit_prop_tables(
    sport: str,
    srows: list[dict],
    *,
    min_prop_n: int,
    split_n: int,
    show_all_min: int,
) -> list[dict]:
    """Full prop-category table + optional Std O/U / Goblin splits."""
    by_prop: dict[str, list] = defaultdict(list)
    for r in srows:
        if r["prop"]:
            by_prop[r["prop"]].append(r)

    ranked = sorted(by_prop.items(), key=lambda kv: -len(kv[1]))
    print(f"\n----- {sport} PROP CATEGORIES (all pick types, sorted by n) -----")
    print(
        f"{'prop':32s} {'n':>6} {'HR':>6} | {'n≥4':>5} {'HR≥4':>6} {'Δ<4':>6} {'Δall':>6} | "
        f"{'n=5':>4} {'HR=5':>6}"
    )

    prop_block: list[dict] = []
    splits = [
        ("Std OVER", lambda r: r["pick"] == "Standard" and r["dir"] == "OVER"),
        ("Std UNDER", lambda r: r["pick"] == "Standard" and r["dir"] == "UNDER"),
        ("Goblin", lambda r: r["pick"] == "Goblin"),
        ("Demon", lambda r: r["pick"] == "Demon"),
    ]

    for prop, xs in ranked:
        if len(xs) < show_all_min:
            continue
        s = _stats(xs)
        caveat = ""
        if len(xs) < min_prop_n:
            caveat = f"small-n (<{min_prop_n})"
        elif (s["n_ge4"] or 0) < 15:
            caveat = "thin L5≥4"
        print(_fmt_prop_row(prop, s, caveat))
        entry: dict = {"prop": prop, **s, "splits": []}
        # Cohort splits when cell n is meaningful
        for slabel, spred in splits:
            sub = [r for r in xs if spred(r)]
            if len(sub) < split_n:
                continue
            ss = _stats(sub)
            print(f"    · {slabel:26s} n={ss['n']:5d} HR={_pct(ss['hr'])} | "
                  f"L5≥4 n={ss['n_ge4']:4d} {_pct(ss['hr_ge4'])} Δ<4{_pp(ss['lift_ge4_vs_lt4'])}"
                  + (f" | L5=5 n={ss['n_eq5']:3d} {_pct(ss['hr_eq5'])}" if (ss['n_eq5'] or 0) >= 10 else ""))
            entry["splits"].append({"label": slabel, **ss})
        prop_block.append(entry)

    skipped = sum(1 for _, xs in ranked if len(xs) < show_all_min)
    if skipped:
        print(f"  … omitted {skipped} props with n<{show_all_min}")
    return prop_block


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default="2026-08-03")
    ap.add_argument(
        "--out",
        default=str(REPO / "data" / "reports" / "l5_lift_by_cohort_active_latest.json"),
    )
    ap.add_argument("--min-n", type=int, default=30, help="Min n for cohort summary rows")
    ap.add_argument("--min-prop-n", type=int, default=40, help="Comfortable prop n (else caveat)")
    ap.add_argument("--show-prop-min", type=int, default=15, help="Show prop if n>= this")
    ap.add_argument("--split-n", type=int, default=30, help="Min n for prop×cohort split cell")
    args = ap.parse_args()

    # Global scan floor: earliest sport from-date (Jan 1 for year-round sports).
    auto_from, _ = _discover_range(args.date_to)
    earliest_sport = min(SPORT_FROM_DATES.values())
    date_from = args.date_from or min(auto_from, earliest_sport)

    rows, meta = load_rows(date_from, args.date_to)
    print(
        f"Active-sport L5 cohort + prop lift | scan {date_from} → {args.date_to} | "
        f"decided={len(rows)} | MLB ASG skipped={meta['mlb_asg_skipped']}"
    )
    print("Per-sport from-dates:")
    for sp, info in from_dates_payload().items():
        print(f"  {sp}: {info['from']}  ({info['note']})")
    print(
        "\nL5 source: stored l5_over/l5_under (directional); fallback hit_rate_l5×5. "
        "Lift Δall = vs group overall; Δ<4 = vs L5<4 within group.\n"
    )

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "from": date_from,
        "to": args.date_to,
        "sport_from_dates": from_dates_payload(),
        "mlb_opener": MLB_OPENER,
        "mlb_asg_skipped": meta["mlb_asg_skipped"],
        "n_decided": len(rows),
        "note": (
            "Directional L5 from graded_props (l5_over/OVER, l5_under/UNDER); "
            "fallback hit_rate_l5*5. Per-sport from-dates: season opener or "
            "2026-01-01 when unclear. MLB ASG 2026-07-13..15 excluded. "
            "Prop tables include all pick types; splits shown when cell n≥split_n."
        ),
        "sports": {},
    }

    for sport in SPORTS:
        srows = [r for r in rows if r["sport"] == sport]
        days = meta["by_sport_days"].get(sport) or []
        sf = sport_from_date(sport)
        print("=" * 110)
        print(
            f"{sport}  from={sf}  days={len(days)}  first={days[0] if days else '-'}  "
            f"last={days[-1] if days else '-'}  decided={len(srows)}"
        )
        print(f"  note: {SPORT_FROM_NOTES.get(sport, '')}")
        sport_block: dict = {
            "from": sf,
            "from_note": SPORT_FROM_NOTES.get(sport, ""),
            "days": len(days),
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "n_decided": len(srows),
            "cohorts": [],
            "props": [],
        }

        cohorts = [
            ("Std OVER", lambda r: r["pick"] == "Standard" and r["dir"] == "OVER"),
            ("Std UNDER", lambda r: r["pick"] == "Standard" and r["dir"] == "UNDER"),
            ("Goblin OVER", lambda r: r["pick"] == "Goblin" and r["dir"] == "OVER"),
            ("Goblin UNDER", lambda r: r["pick"] == "Goblin" and r["dir"] == "UNDER"),
            ("Goblin (all dir)", lambda r: r["pick"] == "Goblin"),
        ]
        demon = [r for r in srows if r["pick"] == "Demon"]
        if len(demon) >= 500:
            cohorts.append(("Demon OVER", lambda r: r["pick"] == "Demon" and r["dir"] == "OVER"))
            cohorts.append(("Demon UNDER", lambda r: r["pick"] == "Demon" and r["dir"] == "UNDER"))
            cohorts.append(("Demon (all dir)", lambda r: r["pick"] == "Demon"))

        print("----- COHORT SUMMARY -----")
        for label, pred in cohorts:
            xs = [r for r in srows if pred(r)]
            if len(xs) < args.min_n:
                if xs:
                    print(f"{label:28s} n={len(xs):6d} (skip detail, n<{args.min_n})")
                continue
            s = _stats(xs)
            print(_fmt_row(label, s))
            sport_block["cohorts"].append({"label": label, **s})

        sport_block["props"] = _emit_prop_tables(
            sport,
            srows,
            min_prop_n=args.min_prop_n,
            split_n=args.split_n,
            show_all_min=args.show_prop_min,
        )
        report["sports"][sport] = sport_block
        print()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out}")

    mlb_ref = REPO / "data" / "reports" / "mlb_l5_lift_opener_latest.json"
    if mlb_ref.exists():
        ref = json.loads(mlb_ref.read_text(encoding="utf-8"))
        print(
            f"\nNote: MLB as-of rebuild reference: {mlb_ref.name} "
            f"({ref.get('from')}→{ref.get('to')}, n={ref.get('n_decided')}). "
            "Stored-L5 MLB has high nol5; as-of rebuild fills L5 and is preferred for MLB lifts."
        )


if __name__ == "__main__":
    main()
