"""Cross-reference graded prop hit rates with opponent defense difficulty (30d).

Joins same-day slate def_tier / opponent_def_rank onto graded props.
HARD/EASY from OVER perspective: Elite+Above Avg = HARD, Below Avg+Weak = EASY.
"""
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
OUT = ROOT / "data" / "reports" / "opp_def_lift_30d.json"

HARD = {"Elite", "Above Avg"}
EASY = {"Below Avg", "Weak"}
MID = {"Avg"}


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


def norm_prop(s: object) -> str:
    return norm_name(s)


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
        "above average": "Above Avg",
        "solid": "Above Avg",
        "avg": "Avg",
        "average": "Avg",
        "below avg": "Below Avg",
        "below average": "Below Avg",
        "weak": "Weak",
    }
    return legacy.get(key, s if s in HARD | EASY | MID else "")


def opp_bucket(tier: str) -> str:
    if tier in HARD:
        return "HARD"  # stingy D — hard for OVER, easy for UNDER
    if tier in EASY:
        return "EASY"  # soft D — easy for OVER, hard for UNDER
    if tier in MID:
        return "MID"
    return "UNK"


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
    elif direction == "UNDER":
        l5 = fnum(x.get("l5_under"))
        l10 = fnum(x.get("l10_under"))
    else:
        l5 = l10 = None
    if l5 is None:
        # fraction hit_rate_l5 * 5
        hr5 = fnum(x.get("hit_rate_l5"))
        if hr5 is not None:
            l5 = hr5 * 5 if hr5 <= 1.0 else hr5
    if l10 is None:
        hr10 = fnum(x.get("hit_rate_l10"))
        if hr10 is not None:
            l10 = hr10 * 10 if hr10 <= 1.0 else hr10
    sample = fnum(x.get("l10_games_played"), 10.0) or 10.0
    return l5, l10, sample


def load_props(day: date):
    p = ROOT / f"ui_runner/templates/graded_props_{day.isoformat()}.json"
    if not p.exists():
        return None, "missing_graded"
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("props") or [], None


def load_slate(day: date):
    s = day.isoformat()
    for p in (
        ROOT / f"outputs/{s}/canonical/platform_ui/slate_latest.json",
        ROOT / f"outputs/{s}/canonical/mobile_app/slate_latest.json",
    ):
        if not p.exists() or p.stat().st_size < 50:
            continue
        try:
            return json.loads(p.read_text(encoding="utf-8")), p
        except json.JSONDecodeError:
            continue
    return None, None


def slate_index(slate: dict):
    """Key: sport|player|prop|line|dir -> best row with def info."""
    sports = slate.get("sports") or {}
    idx = {}
    for sp, rows in sports.items():
        if not isinstance(rows, list):
            continue
        spu = str(sp).upper()
        for r in rows:
            player = norm_name(r.get("player") or r.get("name"))
            prop = norm_prop(r.get("prop") or r.get("prop_type") or r.get("stat"))
            line = fnum(r.get("line"))
            direction = norm_dir(r)
            if not player or not prop or line is None or not direction:
                continue
            key = (spu, player, prop, round(line, 2), direction)
            tier = norm_tier(r.get("def_tier") or r.get("Def Tier"))
            rank = fnum(r.get("opponent_def_rank") or r.get("def_rank") or r.get("OVERALL_DEF_RANK"))
            if key not in idx or (tier and not idx[key].get("def_tier")):
                idx[key] = {
                    "def_tier": tier,
                    "opponent_def_rank": rank,
                    "def_matchup_signal": fnum(r.get("def_matchup_signal")),
                }
    return idx


def rank_bucket(rank):
    if rank is None:
        return "UNK"
    # 1 = best D. MLB ~30 teams: 1-10 hard, 11-20 mid, 21-30 easy for OVER
    if rank <= 10:
        return "HARD"
    if rank <= 20:
        return "MID"
    return "EASY"


class Acc:
    __slots__ = ("h", "n")

    def __init__(self):
        self.h = 0
        self.n = 0

    def add(self, hit: int):
        self.h += hit
        self.n += 1

    def as_dict(self):
        return {
            "hr": round(100.0 * self.h / self.n, 1) if self.n else None,
            "hits": self.h,
            "n": self.n,
        }


def main():
    bags = defaultdict(Acc)
    files_used = []
    files_missing_graded = []
    files_missing_slate = []
    join_stats = Acc()
    join_with_tier = Acc()

    d = START
    while d <= END:
        props, err = load_props(d)
        if err:
            files_missing_graded.append(d.isoformat())
            d += timedelta(days=1)
            continue
        slate, slate_path = load_slate(d)
        if slate is None:
            files_missing_slate.append(d.isoformat())
            sidx = {}
        else:
            sidx = slate_index(slate)
            files_used.append(d.isoformat())

        for x in props:
            hit = res_hit(x)
            if hit is None:
                continue
            sport = str(x.get("sport") or "").upper()
            if sport not in ("MLB", "WNBA", "SOCCER", "TENNIS"):
                continue
            direction = norm_dir(x)
            if direction not in ("OVER", "UNDER"):
                continue
            pick = norm_pick(x)
            if pick not in ("GOBLIN", "STANDARD"):
                continue

            player = norm_name(x.get("player"))
            prop = norm_prop(x.get("prop") or x.get("prop_type"))
            line = fnum(x.get("line"))
            tier = norm_tier(x.get("def_tier"))
            rank = fnum(x.get("opponent_def_rank") or x.get("def_rank"))

            key = (sport, player, prop, round(line, 2) if line is not None else None, direction)
            if key[3] is not None and key in sidx:
                join_stats.add(1)
                sr = sidx[key]
                if not tier:
                    tier = sr.get("def_tier") or ""
                if rank is None:
                    rank = sr.get("opponent_def_rank")
            elif slate is not None:
                join_stats.add(0)

            if tier:
                join_with_tier.add(1)
            else:
                join_with_tier.add(0)

            bucket = opp_bucket(tier) if tier else rank_bucket(rank)
            l5, l10, sample = side_l5_l10(x, direction)

            gates = ["ALL"]
            if pick == "GOBLIN" and direction == "OVER":
                if l5 is not None and l5 >= 4:
                    gates.append("L5>=4")
                if l10 is not None and sample >= 8 and l10 >= 8:
                    gates.append("L10>=8")
                if l5 is not None and l5 >= 4 and l10 is not None and sample >= 8 and l10 >= 8:
                    gates.append("LIVE")
            if pick == "STANDARD" and direction == "OVER":
                if l10 is not None and sample >= 8 and l10 >= 8:
                    gates.append("L10>=8")
                if (
                    l5 is not None
                    and l5 >= 3
                    and l10 is not None
                    and sample >= 8
                    and l10 >= 8
                ):
                    gates.append("LIVE")
            if pick == "STANDARD" and direction == "UNDER":
                if l10 is not None and sample >= 8 and l10 >= 8:
                    gates.append("LIVE")
                    gates.append("L10>=8")

            for g in gates:
                bags[f"{pick}|{direction}|{g}|{bucket}"].add(hit)
                bags[f"{pick}|{direction}|{g}|ANY"].add(hit)
                bags[f"{sport}|{pick}|{direction}|{g}|{bucket}"].add(hit)
                bags[f"DIR|{direction}|{g}|{bucket}"].add(hit)

        d += timedelta(days=1)

    # Build summary tables focused on meaningful cells
    summary = []
    for k, acc in sorted(bags.items(), key=lambda kv: (-kv[1].n, kv[0])):
        if acc.n < 20:
            continue
        summary.append({"key": k, **acc.as_dict()})

    def cell(key):
        a = bags.get(key)
        return a.as_dict() if a and a.n else {"hr": None, "hits": 0, "n": 0}

    contrasts = []
    for pick, direction, gate in [
        ("GOBLIN", "OVER", "ALL"),
        ("GOBLIN", "OVER", "LIVE"),
        ("GOBLIN", "OVER", "L5>=4"),
        ("STANDARD", "OVER", "ALL"),
        ("STANDARD", "OVER", "LIVE"),
        ("STANDARD", "UNDER", "ALL"),
        ("STANDARD", "UNDER", "LIVE"),
    ]:
        hard = cell(f"{pick}|{direction}|{gate}|HARD")
        easy = cell(f"{pick}|{direction}|{gate}|EASY")
        mid = cell(f"{pick}|{direction}|{gate}|MID")
        any_ = cell(f"{pick}|{direction}|{gate}|ANY")
        # Expected: OVER easy > hard; UNDER hard(stingy) > easy(soft)
        if direction == "OVER" and hard["n"] and easy["n"] and hard["hr"] is not None and easy["hr"] is not None:
            delta = round(easy["hr"] - hard["hr"], 1)
            expected = "EASY−HARD (want +)"
        elif direction == "UNDER" and hard["n"] and easy["n"] and hard["hr"] is not None and easy["hr"] is not None:
            delta = round(hard["hr"] - easy["hr"], 1)
            expected = "HARD−EASY (want +; HARD=stingy D favors UNDER)"
        else:
            delta = None
            expected = ""
        contrasts.append(
            {
                "pool": f"{pick} {direction} {gate}",
                "any": any_,
                "hard": hard,
                "mid": mid,
                "easy": easy,
                "aligned_delta_pts": delta,
                "aligned_delta_meaning": expected,
            }
        )

    sport_contrasts = []
    for sport in ("MLB", "WNBA", "SOCCER"):
        for pick, direction, gate in [
            ("GOBLIN", "OVER", "ALL"),
            ("GOBLIN", "OVER", "LIVE"),
            ("STANDARD", "OVER", "ALL"),
            ("STANDARD", "UNDER", "ALL"),
            ("STANDARD", "UNDER", "LIVE"),
        ]:
            hard = cell(f"{sport}|{pick}|{direction}|{gate}|HARD")
            easy = cell(f"{sport}|{pick}|{direction}|{gate}|EASY")
            if (hard["n"] or 0) + (easy["n"] or 0) < 40:
                continue
            if direction == "OVER" and hard["hr"] is not None and easy["hr"] is not None:
                delta = round(easy["hr"] - hard["hr"], 1)
            elif direction == "UNDER" and hard["hr"] is not None and easy["hr"] is not None:
                delta = round(hard["hr"] - easy["hr"], 1)
            else:
                delta = None
            sport_contrasts.append(
                {
                    "sport": sport,
                    "pool": f"{pick} {direction} {gate}",
                    "hard": hard,
                    "easy": easy,
                    "aligned_delta_pts": delta,
                }
            )

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": START.isoformat(), "end": END.isoformat()},
        "method": {
            "opp_buckets": {
                "HARD": "Elite + Above Avg (or def_rank 1-10) — stingy D",
                "MID": "Avg (or def_rank 11-20)",
                "EASY": "Below Avg + Weak (or def_rank 21+) — soft D",
            },
            "aligned_delta": {
                "OVER": "EASY HR − HARD HR (soft D should help overs)",
                "UNDER": "HARD HR − EASY HR (stingy D should help unders)",
            },
            "join": "Same-day slate def_tier/opponent_def_rank keyed by sport|player|prop|line|direction; graded def_tier used when present",
            "sports": ["MLB", "WNBA", "SOCCER", "TENNIS"],
            "pick_types": ["GOBLIN", "STANDARD"],
        },
        "coverage": {
            "days_with_slate_join": files_used,
            "n_days_with_slate": len(files_used),
            "graded_missing": files_missing_graded,
            "slate_missing_but_graded": files_missing_slate,
            "slate_row_join_rate": join_stats.as_dict(),
            "rows_with_opp_tier_or_rank_bucket": join_with_tier.as_dict(),
        },
        "contrasts": contrasts,
        "sport_contrasts": sport_contrasts,
        "summary_min20": summary,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print("days_with_slate", len(files_used), "slate_missing", len(files_missing_slate))
    print("join", join_stats.as_dict(), "with_tier_flag", join_with_tier.as_dict())
    print("\nCONTRASTS")
    for c in contrasts:
        print(
            f"{c['pool']:28} ANY={c['any']['hr']}%/{c['any']['n']}  "
            f"HARD={c['hard']['hr']}%/{c['hard']['n']}  "
            f"MID={c['mid']['hr']}%/{c['mid']['n']}  "
            f"EASY={c['easy']['hr']}%/{c['easy']['n']}  "
            f"Δ={c['aligned_delta_pts']}"
        )
    print("\nSPORT")
    for c in sport_contrasts:
        print(
            f"{c['sport']:6} {c['pool']:28} HARD={c['hard']['hr']}%/{c['hard']['n']}  "
            f"EASY={c['easy']['hr']}%/{c['easy']['n']}  Δ={c['aligned_delta_pts']}"
        )


if __name__ == "__main__":
    main()
