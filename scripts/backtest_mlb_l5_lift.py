#!/usr/bin/env python3
"""
MLB L5 lift backtest from season opener with All-Star break dates excluded.

Reads graded_props_YYYY-MM-DD.json, rebuilds directional L5 from mlb_stats_cache
(as-of slate date), and reports overall + prop×pick HR for L5>=4 / L5=5.

Example:
  py -3.14 scripts/backtest_mlb_l5_lift.py
  py -3.14 scripts/backtest_mlb_l5_lift.py --from 2026-03-30 --to 2026-08-03
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "Sports" / "MLB" / "scripts"))

from scripts.step4_db_reader import calc_hit_context  # noqa: E402
from step2_attach_picktypes_mlb import norm_prop as mlb_norm_prop  # noqa: E402
from utils.allstar_filter import is_allstar_date  # noqa: E402

DEFAULT_OPENER = "2026-03-30"  # first graded_props day with MLB
DEFAULT_BOX_OPENER = "2026-03-25"  # first mlb_gamelog / cache games


def _num(x):
    try:
        if x in (None, ""):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _is_hit(r: dict) -> bool | None:
    h = r.get("hit")
    if h in (True, 1, "1", "true", "True", "HIT", "hit"):
        return True
    if h in (False, 0, "0", "false", "False", "MISS", "miss"):
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


def _player_norm(name: str) -> str:
    s = str(name or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", " ", s)


def hr(xs: list[dict]) -> float | None:
    if not xs:
        return None
    return sum(1 for x in xs if x["hit"]) / len(xs)


class MlbL5:
    def __init__(self, cache_path: Path, id_path: Path) -> None:
        cache = pd.read_csv(cache_path, low_memory=False)
        cache["GAME_DATE"] = pd.to_datetime(cache["GAME_DATE"], errors="coerce")
        # Drop All-Star break rows from L5 history.
        keep = ~cache["GAME_DATE"].map(lambda x: is_allstar_date(x, sport="MLB"))
        self.cache = cache.loc[keep].copy()
        self.cache["PROP_NORM"] = self.cache["PROP_NORM"].astype(str)
        self.cache["MLB_PLAYER_ID"] = self.cache["MLB_PLAYER_ID"].astype(str)
        self.cache["STAT_VALUE"] = pd.to_numeric(self.cache["STAT_VALUE"], errors="coerce")
        ids = pd.read_csv(id_path)
        col = "player_norm" if "player_norm" in ids.columns else "PLAYER_NORM"
        idc = "mlb_player_id" if "mlb_player_id" in ids.columns else "MLB_PLAYER_ID"
        self.name_to_id = {
            str(getattr(r, col)).strip().lower(): str(getattr(r, idc))
            for r in ids.itertuples(index=False)
            if str(getattr(r, col, "") or "").strip()
        }
        self._idx: dict[tuple[str, str], pd.DataFrame] = {}

    def vals(self, player: str, prop: str, before: str, n: int = 5) -> list[float]:
        pid = self.name_to_id.get(_player_norm(player))
        if not pid:
            pn = _player_norm(player)
            for k, v in self.name_to_id.items():
                if k == pn or k.endswith(pn) or pn.endswith(k):
                    pid = v
                    break
        if not pid:
            return []
        prop_n = mlb_norm_prop(prop)
        key = (pid, prop_n)
        if key not in self._idx:
            sub = self.cache[
                (self.cache["MLB_PLAYER_ID"] == pid) & (self.cache["PROP_NORM"] == prop_n)
            ]
            self._idx[key] = sub.sort_values("GAME_DATE", ascending=False)
        sub = self._idx[key]
        if sub.empty:
            return []
        cut = sub[sub["GAME_DATE"] < pd.Timestamp(before)]
        return cut["STAT_VALUE"].dropna().head(n).tolist()


def _iter_dates(d0: str, d1: str) -> list[str]:
    out = []
    cur = datetime.strptime(d0, "%Y-%m-%d").date()
    end = datetime.strptime(d1, "%Y-%m-%d").date()
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _find_graded(day: str) -> Path | None:
    for base in (REPO / "ui_runner" / "templates", REPO / "mobile" / "www"):
        p = base / f"graded_props_{day}.json"
        if p.exists():
            return p
    return None


def row_stats(xs: list[dict], thr: float | None = None, exact: float | None = None):
    if thr is not None:
        xs = [x for x in xs if x.get("l5_side") is not None and x["l5_side"] >= thr]
    if exact is not None:
        xs = [x for x in xs if x.get("l5_side") == exact]
    return len(xs), hr(xs)


def emit(label: str, xs: list[dict], min_n: int = 25) -> dict | None:
    base_n, base_hr = len(xs), hr(xs)
    ge4_n, ge4_hr = row_stats(xs, thr=4.0)
    eq5_n, eq5_hr = row_stats(xs, exact=5.0)
    if base_n < min_n and ge4_n < 15 and eq5_n < 10:
        return None
    d4 = ((ge4_hr or 0) - (base_hr or 0)) if ge4_hr is not None and base_hr is not None else None
    d5 = ((eq5_hr or 0) - (base_hr or 0)) if eq5_hr is not None and base_hr is not None else None
    print(
        f"{label:40s} all n={base_n:6d} {100 * (base_hr or 0):5.1f}% | "
        f"L5>=4 n={ge4_n:5d} {100 * (ge4_hr or 0):5.1f}% Δ{100 * (d4 or 0):+5.1f} | "
        f"L5=5 n={eq5_n:4d} {100 * (eq5_hr or 0):5.1f}% Δ{100 * (d5 or 0):+5.1f}"
    )
    return {
        "label": label,
        "n": base_n,
        "hr": base_hr,
        "n_ge4": ge4_n,
        "hr_ge4": ge4_hr,
        "lift_ge4": d4,
        "n_eq5": eq5_n,
        "hr_eq5": eq5_hr,
        "lift_eq5": d5,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", default=DEFAULT_OPENER)
    ap.add_argument("--to", dest="date_to", default="2026-08-03")
    ap.add_argument(
        "--cache",
        default=str(REPO / "Sports" / "MLB" / "mlb_stats_cache.csv"),
    )
    ap.add_argument(
        "--id-cache",
        default=str(REPO / "Sports" / "MLB" / "mlb_id_cache.csv"),
    )
    ap.add_argument(
        "--include-asg",
        action="store_true",
        help="Do NOT exclude All-Star break slate dates (comparison mode)",
    )
    ap.add_argument(
        "--out",
        default=str(REPO / "data" / "reports" / "mlb_l5_lift_opener_latest.json"),
    )
    args = ap.parse_args()

    mlb = MlbL5(Path(args.cache), Path(args.id_cache))
    rows: list[dict] = []
    days_used = []
    days_skipped_asg = []
    days_missing = []

    for d in _iter_dates(args.date_from, args.date_to):
        if not args.include_asg and is_allstar_date(d, sport="MLB"):
            days_skipped_asg.append(d)
            continue
        path = _find_graded(d)
        if not path:
            days_missing.append(d)
            continue
        props = json.loads(path.read_text(encoding="utf-8")).get("props") or []
        n_day = 0
        for r in props:
            if str(r.get("sport") or "").upper() != "MLB":
                continue
            hit = _is_hit(r)
            if hit is None:
                continue
            direction = str(r.get("direction") or r.get("over_under") or "").upper()
            if direction not in ("OVER", "UNDER"):
                continue
            line = _num(r.get("line"))
            if line is None:
                continue
            player = str(r.get("player") or "")
            prop = str(r.get("prop") or r.get("prop_type") or "")
            pick = _norm_pick(r.get("pick_type"))
            lo, lu = _num(r.get("l5_over")), _num(r.get("l5_under"))
            if lo is None and lu is None:
                vals = mlb.vals(player, prop, d)
                if vals:
                    over, under, *_ = calc_hit_context(vals, line, k=5)
                    lo, lu = float(over), float(under)
            side = lo if direction == "OVER" else lu
            rows.append(
                {
                    "date": d,
                    "pick": pick,
                    "dir": direction,
                    "prop": mlb_norm_prop(prop) if prop else "",
                    "l5_side": side,
                    "hit": hit,
                }
            )
            n_day += 1
        if n_day:
            days_used.append(d)

    print(
        f"MLB L5 lift | opener≥{args.date_from} → {args.date_to} | "
        f"ASG excluded={not args.include_asg} ({days_skipped_asg}) | "
        f"days={len(days_used)} decided={len(rows)}"
    )
    print(f"  with L5: {sum(1 for r in rows if r['l5_side'] is not None)}")

    report: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "from": args.date_from,
        "to": args.date_to,
        "asg_excluded": not args.include_asg,
        "asg_dates_skipped": days_skipped_asg,
        "days_used": days_used,
        "n_decided": len(rows),
        "groups": [],
    }

    print("\n========== OVERALL ==========")
    for label, xs in [
        ("MLB all", rows),
        ("MLB Standard OVER", [r for r in rows if r["pick"] == "Standard" and r["dir"] == "OVER"]),
        ("MLB Standard UNDER", [r for r in rows if r["pick"] == "Standard" and r["dir"] == "UNDER"]),
        ("MLB Goblin OVER", [r for r in rows if r["pick"] == "Goblin" and r["dir"] == "OVER"]),
        ("MLB Goblin UNDER", [r for r in rows if r["pick"] == "Goblin" and r["dir"] == "UNDER"]),
    ]:
        rec = emit(label, xs, min_n=20)
        if rec:
            report["groups"].append(rec)

    print("\n========== PICK × DIR ==========")
    for pick in ("Standard", "Goblin", "Demon"):
        for direction in ("OVER", "UNDER"):
            xs = [r for r in rows if r["pick"] == pick and r["dir"] == direction]
            rec = emit(f"{pick} {direction}", xs, min_n=40)
            if rec:
                report["groups"].append(rec)

    print("\n========== PROP × Standard OVER (key) ==========")
    by_prop: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["pick"] == "Standard" and r["dir"] == "OVER" and r["prop"]:
            by_prop[r["prop"]].append(r)
    for prop, xs in sorted(by_prop.items(), key=lambda kv: -len(kv[1]))[:20]:
        rec = emit(f"Std OVER {prop}", xs, min_n=30)
        if rec:
            report["groups"].append(rec)

    print("\n========== PROP × Goblin OVER (key) ==========")
    by_prop_g: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["pick"] == "Goblin" and r["dir"] == "OVER" and r["prop"]:
            by_prop_g[r["prop"]].append(r)
    for prop, xs in sorted(by_prop_g.items(), key=lambda kv: -len(kv[1]))[:15]:
        rec = emit(f"Gob OVER {prop}", xs, min_n=30)
        if rec:
            report["groups"].append(rec)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
