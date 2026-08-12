"""30-day sport × prop-type cross-ref: base / live gate / opp HARD-EASY."""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = date(2026, 7, 11)
END = date(2026, 8, 9)
OUT = ROOT / "data" / "reports" / "sport_prop_lift_30d.json"
MIN_N = 30
MIN_N_SPORT = 20

HARD = {"Elite", "Above Avg"}
EASY = {"Below Avg", "Weak"}
MID = {"Avg"}
SPORTS = {"MLB", "WNBA", "SOCCER", "TENNIS"}


def fnum(x, default=None):
    try:
        if x is None or x == "":
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def norm_name(s: object) -> str:
    s = re.sub(r"[^A-Z0-9 ]+", " ", str(s or "").upper())
    return " ".join(s.split())


def norm_prop_label(s: object) -> str:
    raw = str(s or "").strip()
    if not raw:
        return "UNKNOWN"
    # Collapse obvious variants
    key = re.sub(r"\s+", " ", raw)
    aliases = {
        "Points (Combo)": "Points",
        "Pts+Rebs+Asts": "Pts+Rebs+Asts",
        "PRA": "Pts+Rebs+Asts",
    }
    return aliases.get(key, key)


def norm_dir(x: dict) -> str:
    for k in ("direction", "dir", "over_under", "ou"):
        v = str(x.get(k) or "").upper().strip()
        if v.startswith("O"):
            return "OVER"
        if v.startswith("U"):
            return "UNDER"
    return ""


def norm_pick(x: dict) -> str:
    v = str(x.get("pick_type") or x.get("pick") or "").upper().strip()
    if "GOB" in v:
        return "GOBLIN"
    if "DEM" in v:
        return "DEMON"
    if "STD" in v or "STAND" in v or v == "STANDARD":
        return "STANDARD"
    return v or "OTHER"


def norm_tier(raw: object) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    key = s.lower().replace("average", "avg")
    legacy = {
        "elite": "Elite",
        "above avg": "Above Avg",
        "solid": "Above Avg",
        "avg": "Avg",
        "below avg": "Below Avg",
        "weak": "Weak",
    }
    return legacy.get(key, s if s in HARD | EASY | MID else "")


def opp_bucket(tier: str, rank) -> str:
    if tier in HARD:
        return "HARD"
    if tier in EASY:
        return "EASY"
    if tier in MID:
        return "MID"
    if rank is None:
        return "UNK"
    if rank <= 10:
        return "HARD"
    if rank <= 20:
        return "MID"
    return "EASY"


def res_hit(x: dict):
    if "hit" in x and x["hit"] is not None:
        h = x["hit"]
        if h is True or h == 1 or str(h).lower() in ("true", "hit", "win"):
            return 1
        if h is False or h == 0 or str(h).lower() in ("false", "miss", "loss"):
            return 0
    r = str(x.get("result") or x.get("grade") or "").upper().strip()
    if r in ("HIT", "WIN", "W"):
        return 1
    if r in ("MISS", "LOSS", "L"):
        return 0
    return None


def side_l5_l10(x: dict, direction: str):
    if direction == "OVER":
        l5 = fnum(x.get("l5_over"))
        l10 = fnum(x.get("l10_over"))
    else:
        l5 = fnum(x.get("l5_under"))
        l10 = fnum(x.get("l10_under"))
    if l5 is None:
        hr5 = fnum(x.get("hit_rate_l5"))
        if hr5 is not None:
            l5 = hr5 * 5 if hr5 <= 1.0 else hr5
    if l10 is None:
        hr10 = fnum(x.get("hit_rate_l10"))
        if hr10 is not None:
            l10 = hr10 * 10 if hr10 <= 1.0 else hr10
    sample = fnum(x.get("l10_games_played"), 10.0) or 10.0
    return l5, l10, sample


def live_ok(pick: str, direction: str, l5, l10, sample) -> bool:
    if pick == "GOBLIN" and direction == "OVER":
        return (
            l5 is not None
            and l5 >= 4
            and l10 is not None
            and sample >= 8
            and l10 >= 8
        )
    if pick == "STANDARD" and direction == "OVER":
        return (
            l5 is not None
            and l5 >= 3
            and l10 is not None
            and sample >= 8
            and l10 >= 8
        )
    if pick == "STANDARD" and direction == "UNDER":
        return l10 is not None and sample >= 8 and l10 >= 8
    return False


def load_props(day: date):
    p = ROOT / f"ui_runner/templates/graded_props_{day.isoformat()}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("props") or []


def load_slate(day: date):
    s = day.isoformat()
    for p in (
        ROOT / f"outputs/{s}/canonical/platform_ui/slate_latest.json",
        ROOT / f"outputs/{s}/canonical/mobile_app/slate_latest.json",
    ):
        if not p.exists() or p.stat().st_size < 50:
            continue
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return None


def slate_index(slate: dict):
    sports = slate.get("sports") or {}
    idx = {}
    for sp, rows in sports.items():
        if not isinstance(rows, list):
            continue
        spu = str(sp).upper()
        for r in rows:
            player = norm_name(r.get("player") or r.get("name"))
            prop = norm_name(r.get("prop") or r.get("prop_type") or r.get("stat"))
            line = fnum(r.get("line"))
            direction = norm_dir(r)
            if not player or not prop or line is None or not direction:
                continue
            key = (spu, player, prop, round(line, 2), direction)
            tier = norm_tier(r.get("def_tier"))
            rank = fnum(
                r.get("opponent_def_rank") or r.get("def_rank") or r.get("OVERALL_DEF_RANK")
            )
            row = {
                "def_tier": tier,
                "opponent_def_rank": rank,
                "l5_over": fnum(r.get("l5_over")),
                "l5_under": fnum(r.get("l5_under")),
                "l10_over": fnum(r.get("l10_over")),
                "l10_under": fnum(r.get("l10_under")),
                "l10_games_played": fnum(r.get("l10_games_played") or r.get("l10_sample")),
                "hit_rate_l5": fnum(r.get("hit_rate_l5") or r.get("l5_hit_rate")),
                "hit_rate_l10": fnum(r.get("hit_rate_l10") or r.get("l10_hit_rate")),
            }
            if key not in idx or (tier and not idx[key].get("def_tier")):
                idx[key] = row
            else:
                for fk, fv in row.items():
                    if fv is not None and idx[key].get(fk) is None:
                        idx[key][fk] = fv
    return idx


class Acc:
    __slots__ = ("h", "n")

    def __init__(self):
        self.h = 0
        self.n = 0

    def add(self, hit: int):
        self.h += int(hit)
        self.n += 1

    def d(self):
        return {
            "hr": round(100.0 * self.h / self.n, 1) if self.n else None,
            "hits": self.h,
            "n": self.n,
        }


def main():
    bags = defaultdict(Acc)
    days_used = []
    days_missing = []
    days_with_slate = []

    d = START
    while d <= END:
        props = load_props(d)
        if props is None:
            days_missing.append(d.isoformat())
            d += timedelta(days=1)
            continue
        days_used.append(d.isoformat())
        slate = load_slate(d)
        sidx = slate_index(slate) if slate else {}
        if slate:
            days_with_slate.append(d.isoformat())

        for x in props:
            hit = res_hit(x)
            if hit is None:
                continue
            sport = str(x.get("sport") or "").upper()
            if sport not in SPORTS:
                continue
            direction = norm_dir(x)
            if direction not in ("OVER", "UNDER"):
                continue
            pick = norm_pick(x)
            if pick not in ("GOBLIN", "STANDARD"):
                continue
            prop = norm_prop_label(x.get("prop") or x.get("prop_type"))

            player = norm_name(x.get("player"))
            prop_key = norm_name(prop)
            line = fnum(x.get("line"))
            tier = norm_tier(x.get("def_tier"))
            rank = fnum(x.get("opponent_def_rank") or x.get("def_rank"))
            key = (
                sport,
                player,
                prop_key,
                round(line, 2) if line is not None else None,
                direction,
            )
            sr = sidx.get(key) if key[3] is not None else None
            if sr:
                tier = tier or sr.get("def_tier") or ""
                if rank is None:
                    rank = sr.get("opponent_def_rank")
                # Fill missing side L5/L10 from same-day slate (MLB often blank in graded JSON)
                for fk in (
                    "l5_over",
                    "l5_under",
                    "l10_over",
                    "l10_under",
                    "l10_games_played",
                    "hit_rate_l5",
                    "hit_rate_l10",
                ):
                    if x.get(fk) in (None, "") and sr.get(fk) is not None:
                        x[fk] = sr.get(fk)
            bucket = opp_bucket(tier, rank)

            l5, l10, sample = side_l5_l10(x, direction)
            is_live = live_ok(pick, direction, l5, l10, sample)

            base_k = f"{sport}|{prop}|{pick}|{direction}"
            bags[base_k].add(hit)
            bags[f"{sport}|{prop}|{pick}|{direction}|{bucket}"].add(hit)
            if is_live:
                bags[f"{sport}|{prop}|{pick}|{direction}|LIVE"].add(hit)
                bags[f"{sport}|{prop}|{pick}|{direction}|LIVE|{bucket}"].add(hit)

            # sport rollups
            bags[f"{sport}|ALL|{pick}|{direction}"].add(hit)
            if is_live:
                bags[f"{sport}|ALL|{pick}|{direction}|LIVE"].add(hit)

        d += timedelta(days=1)

    # Build per-prop table rows
    prop_rows = []
    # discover prop keys from base cells
    base_keys = [k for k in bags if k.count("|") == 3]
    for k in sorted(base_keys):
        sport, prop, pick, direction = k.split("|")
        if prop == "ALL":
            continue
        base = bags[k].d()
        if base["n"] < MIN_N:
            continue
        live = bags[f"{k}|LIVE"].d()
        hard = bags[f"{k}|HARD"].d()
        easy = bags[f"{k}|EASY"].d()
        live_hard = bags[f"{k}|LIVE|HARD"].d()
        live_easy = bags[f"{k}|LIVE|EASY"].d()

        lift = None
        if live["n"] >= 15 and base["hr"] is not None and live["hr"] is not None:
            lift = round(live["hr"] - base["hr"], 1)

        if direction == "OVER" and hard["hr"] is not None and easy["hr"] is not None:
            opp_delta = round(easy["hr"] - hard["hr"], 1)
        elif direction == "UNDER" and hard["hr"] is not None and easy["hr"] is not None:
            opp_delta = round(hard["hr"] - easy["hr"], 1)
        else:
            opp_delta = None

        prop_rows.append(
            {
                "sport": sport,
                "prop": prop,
                "pick": pick,
                "direction": direction,
                "base": base,
                "live": live,
                "live_lift_pts": lift,
                "hard": hard,
                "easy": easy,
                "opp_aligned_delta_pts": opp_delta,
                "live_hard": live_hard,
                "live_easy": live_easy,
            }
        )

    # Rank best / worst live lifts and opp deltas within sport
    by_sport = defaultdict(list)
    for r in prop_rows:
        by_sport[r["sport"]].append(r)

    highlights = {}
    for sport, rows in by_sport.items():
        with_live = [r for r in rows if r["live_lift_pts"] is not None and r["live"]["n"] >= 20]
        with_opp = [
            r
            for r in rows
            if r["opp_aligned_delta_pts"] is not None
            and (r["hard"]["n"] or 0) >= 25
            and (r["easy"]["n"] or 0) >= 25
        ]
        highlights[sport] = {
            "best_live_lift": sorted(with_live, key=lambda r: -r["live_lift_pts"])[:8],
            "worst_live_lift": sorted(with_live, key=lambda r: r["live_lift_pts"])[:5],
            "best_opp_aligned": sorted(
                with_opp, key=lambda r: -(r["opp_aligned_delta_pts"] or -999)
            )[:5],
            "worst_opp_aligned": sorted(
                with_opp, key=lambda r: (r["opp_aligned_delta_pts"] if r["opp_aligned_delta_pts"] is not None else 999)
            )[:5],
            "n_prop_cells": len(rows),
        }

    # Compact printable leaders
    leaders = []
    for r in sorted(
        [x for x in prop_rows if x["live"]["n"] >= 20 and x["live_lift_pts"] is not None],
        key=lambda x: (-x["live_lift_pts"], -x["live"]["n"]),
    )[:25]:
        leaders.append(
            {
                "sport": r["sport"],
                "prop": r["prop"],
                "pick": r["pick"],
                "direction": r["direction"],
                "base_hr": r["base"]["hr"],
                "live_hr": r["live"]["hr"],
                "lift": r["live_lift_pts"],
                "live_n": r["live"]["n"],
                "base_n": r["base"]["n"],
                "opp_delta": r["opp_aligned_delta_pts"],
            }
        )

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": START.isoformat(), "end": END.isoformat()},
        "coverage": {
            "days_used": days_used,
            "n_days": len(days_used),
            "days_missing": days_missing,
            "days_with_slate": days_with_slate,
            "n_days_with_slate": len(days_with_slate),
            "min_n_prop_cell": MIN_N,
        },
        "method": {
            "live_gates": {
                "GOBLIN_OVER": "L5>=4 + L10>=8 (sample>=8)",
                "STANDARD_OVER": "L5>=3 + L10>=8",
                "STANDARD_UNDER": "L10>=8",
            },
            "opp": "HARD=Elite/AboveAvg or rank1-10; EASY=BelowAvg/Weak or rank21+; OVER Δ=EASY-HARD; UNDER Δ=HARD-EASY",
        },
        "prop_rows": prop_rows,
        "highlights_by_sport": {
            sp: {
                "n_prop_cells": h["n_prop_cells"],
                "best_live_lift": [
                    {
                        "prop": r["prop"],
                        "pick": r["pick"],
                        "direction": r["direction"],
                        "base": r["base"],
                        "live": r["live"],
                        "lift": r["live_lift_pts"],
                        "opp_delta": r["opp_aligned_delta_pts"],
                    }
                    for r in h["best_live_lift"]
                ],
                "worst_live_lift": [
                    {
                        "prop": r["prop"],
                        "pick": r["pick"],
                        "direction": r["direction"],
                        "base": r["base"],
                        "live": r["live"],
                        "lift": r["live_lift_pts"],
                    }
                    for r in h["worst_live_lift"]
                ],
                "best_opp_aligned": [
                    {
                        "prop": r["prop"],
                        "pick": r["pick"],
                        "direction": r["direction"],
                        "hard": r["hard"],
                        "easy": r["easy"],
                        "opp_delta": r["opp_aligned_delta_pts"],
                        "base": r["base"],
                    }
                    for r in h["best_opp_aligned"]
                ],
                "worst_opp_aligned": [
                    {
                        "prop": r["prop"],
                        "pick": r["pick"],
                        "direction": r["direction"],
                        "hard": r["hard"],
                        "easy": r["easy"],
                        "opp_delta": r["opp_aligned_delta_pts"],
                    }
                    for r in h["worst_opp_aligned"]
                ],
            }
            for sp, h in highlights.items()
        },
        "top_live_lifts_overall": leaders,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print("days", len(days_used), "slate", len(days_with_slate), "prop_cells", len(prop_rows))
    print("\nTOP LIVE LIFTS")
    for r in leaders[:20]:
        print(
            f"{r['sport']:6} {r['prop'][:28]:28} {r['pick'][:3]:3} {r['direction']:5} "
            f"base={r['base_hr']}%/{r['base_n']} live={r['live_hr']}%/{r['live_n']} "
            f"lift={r['lift']:+} oppΔ={r['opp_delta']}"
        )
    print("\nBY SPORT BEST LIVE")
    for sp, h in sorted(highlights.items()):
        print(f"=== {sp} ({h['n_prop_cells']} cells) ===")
        for r in h["best_live_lift"][:5]:
            print(
                f"  {r['prop'][:26]:26} {r['pick'][:3]:3} {r['direction']:5} "
                f"{r['base']['hr']}% -> {r['live']['hr']}% ({r['live_lift_pts']:+}) n={r['live']['n']}"
            )
        print("  opp best:")
        for r in h["best_opp_aligned"][:3]:
            print(
                f"    {r['prop'][:24]:24} {r['pick'][:3]:3} {r['direction']:5} "
                f"H={r['hard']['hr']}%/{r['hard']['n']} E={r['easy']['hr']}%/{r['easy']['n']} Δ={r['opp_aligned_delta_pts']}"
            )


if __name__ == "__main__":
    main()
