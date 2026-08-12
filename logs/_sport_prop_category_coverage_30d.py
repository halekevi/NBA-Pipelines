"""Full PP category coverage vs 30d graded — include Demon for inventory; exclude Fantasy/1st Inn."""
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
OUT = ROOT / "data" / "reports" / "sport_prop_category_coverage_30d.json"

PP_CATALOG = {
    "WNBA": [
        "Pts+Rebs+Asts",
        "Points",
        "Rebounds",
        "Assists",
        "3-PT Made",
        "3-PT Attempted",
        "Rebs+Asts",
        "FG Made",
        "FG Attempted",
        "Pts+Rebs",
        "Two Pointers Made",
        "Pts+Asts",
        "Two Pointers Attempted",
        "Free Throws Made",
        "Free Throws Attempted",
        "Defensive Rebounds",
        "Turnovers",
        "Offensive Rebounds",
        "Blks+Stls",
        "Blocked Shots",
        "Steals",
        "Points (Combo)",
        "Rebounds (Combo)",
        "Assists (Combo)",
    ],
    "MLB": [
        "Pitcher Strikeouts",
        "Total Bases",
        "Hits+Runs+RBIs",
        "Pitching Outs",
        "Hits Allowed",
        "Hits",
        "Runs",
        "RBIs",
        "Home Runs",
        "Plate Appearances",
        "Walks",
        "Stolen Bases",
        "Pitches Thrown",
        "Earned Runs Allowed",
        "Walks Allowed",
        "Hitter Strikeouts",
        "Singles",
        "Doubles",
        "Pitcher Strikeouts (Combo)",
        "Batters Faced",
        "Pitches Seen",
        "Triples",
    ],
    "TENNIS": [
        "Total Games",
        "Total Games Won",
        "Total Sets",
        "Aces",
        "Break Points Won",
        "Total Tie Breaks",
        "Double Faults",
    ],
    "SOCCER": [
        "Passes Attempted",
        "Shots",
        "Shots On Target",
        "Goalie Saves",
        "Clearances",
        "Goals",
        "Assists",
        "Attempted Dribbles",
        "Goal + Assist",
        "Shots Assisted",
        "Tackles",
        "Fouls",
    ],
}

EXCLUDE_RE = [
    re.compile(r"fantasy", re.I),
    re.compile(r"1st\s*inn", re.I),
    re.compile(r"first\s*inn", re.I),
]


def excluded(prop: str) -> bool:
    return any(p.search(prop or "") for p in EXCLUDE_RE)


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
    s = re.sub(r"[^A-Z0-9+ ]+", " ", str(s or "").upper())
    return " ".join(s.split())


def canon_prop(raw: object) -> str:
    s = str(raw or "").strip()
    aliases = {
        "HITS-RUNS-RBIS": "Hits+Runs+RBIs",
        "HITS RUNS RBIS": "Hits+Runs+RBIs",
        "HITS+RUNS+RBIS": "Hits+Runs+RBIs",
        "PRA": "Pts+Rebs+Asts",
        "PTS+REBS+ASTS": "Pts+Rebs+Asts",
        "POINTS COMBO": "Points (Combo)",
        "REBOUNDS COMBO": "Rebounds (Combo)",
        "ASSISTS COMBO": "Assists (Combo)",
        "PITCHER STRIKEOUTS COMBO": "Pitcher Strikeouts (Combo)",
        "3 PT MADE": "3-PT Made",
        "3PT MADE": "3-PT Made",
        "3 PT ATTEMPTED": "3-PT Attempted",
        "3PT ATTEMPTED": "3-PT Attempted",
        "SHOTS ON TARGET": "Shots On Target",
        "GOAL ASSIST": "Goal + Assist",
        "GOAL+ASSIST": "Goal + Assist",
    }
    key = norm_name(s)
    return aliases.get(key, s)


def match_catalog(sport: str, prop: str) -> str | None:
    c = canon_prop(prop)
    if c in PP_CATALOG.get(sport, []):
        return c
    cn = norm_name(c)
    for cat in PP_CATALOG.get(sport, []):
        if norm_name(cat) == cn:
            return cat
    return None


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
    return None  # VOID/PENDING/etc


def side_l5_l10(x: dict, direction: str):
    if direction == "OVER":
        l5, l10 = fnum(x.get("l5_over")), fnum(x.get("l10_over"))
    else:
        l5, l10 = fnum(x.get("l5_under")), fnum(x.get("l10_under"))
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
        return l5 is not None and l5 >= 4 and l10 is not None and sample >= 8 and l10 >= 8
    if pick == "STANDARD" and direction == "OVER":
        return l5 is not None and l5 >= 3 and l10 is not None and sample >= 8 and l10 >= 8
    if pick == "STANDARD" and direction == "UNDER":
        return l10 is not None and sample >= 8 and l10 >= 8
    return False


def load_props(day: date):
    p = ROOT / f"ui_runner/templates/graded_props_{day.isoformat()}.json"
    if not p.exists():
        return None
    return (json.loads(p.read_text(encoding="utf-8")).get("props") or [])


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
    idx = {}
    for sp, rows in (slate.get("sports") or {}).items():
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
            row = {
                k: fnum(r.get(k))
                for k in (
                    "l5_over",
                    "l5_under",
                    "l10_over",
                    "l10_under",
                    "l10_games_played",
                    "hit_rate_l5",
                    "hit_rate_l10",
                )
            }
            row["l10_games_played"] = fnum(
                r.get("l10_games_played") or r.get("l10_sample")
            )
            if key not in idx:
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
    # bags: sport|prop|pick|direction[+|LIVE]
    bags = defaultdict(Acc)
    counts = defaultdict(lambda: {"rows": 0, "decided": 0, "pending_void": 0, "by_pick": defaultdict(int)})
    days_used = []

    d = START
    while d <= END:
        props = load_props(d)
        if props is None:
            d += timedelta(days=1)
            continue
        days_used.append(d.isoformat())
        slate = load_slate(d)
        sidx = slate_index(slate) if slate else {}

        for x in props:
            sport = str(x.get("sport") or "").upper()
            if sport not in PP_CATALOG:
                continue
            raw = str(x.get("prop") or x.get("prop_type") or "").strip()
            if not raw or excluded(raw):
                continue
            prop = match_catalog(sport, raw) or canon_prop(raw)
            if excluded(prop):
                continue
            # Only catalog + known extras tracked in counts for catalog props
            cat = match_catalog(sport, raw)
            if not cat:
                continue
            prop = cat

            pick = norm_pick(x)
            direction = norm_dir(x) or "UNK"
            counts[f"{sport}|{prop}"]["rows"] += 1
            counts[f"{sport}|{prop}"]["by_pick"][pick] += 1

            hit = res_hit(x)
            if hit is None:
                counts[f"{sport}|{prop}"]["pending_void"] += 1
                continue
            counts[f"{sport}|{prop}"]["decided"] += 1

            if pick not in ("GOBLIN", "STANDARD", "DEMON") or direction not in (
                "OVER",
                "UNDER",
            ):
                continue

            player = norm_name(x.get("player"))
            line = fnum(x.get("line"))
            key = (
                sport,
                player,
                norm_name(prop),
                round(line, 2) if line is not None else None,
                direction,
            )
            sr = sidx.get(key) if key[3] is not None else None
            if sr:
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

            l5, l10, sample = side_l5_l10(x, direction)
            is_live = live_ok(pick, direction, l5, l10, sample)
            base = f"{sport}|{prop}|{pick}|{direction}"
            bags[base].add(hit)
            if is_live:
                bags[f"{base}|LIVE"].add(hit)

        d += timedelta(days=1)

    by_sport = {}
    for sport, cats in PP_CATALOG.items():
        rows = []
        for prop in cats:
            meta = counts[f"{sport}|{prop}"]
            by_pick = dict(meta["by_pick"])
            gob = bags[f"{sport}|{prop}|GOBLIN|OVER"].d()
            gob_live = bags[f"{sport}|{prop}|GOBLIN|OVER|LIVE"].d()
            std_u = bags[f"{sport}|{prop}|STANDARD|UNDER"].d()
            std_u_live = bags[f"{sport}|{prop}|STANDARD|UNDER|LIVE"].d()
            std_o = bags[f"{sport}|{prop}|STANDARD|OVER"].d()
            dem = bags[f"{sport}|{prop}|DEMON|OVER"].d()
            ticket_n = gob["n"] + std_u["n"] + std_o["n"]
            demon_n = by_pick.get("DEMON", 0)
            rows_n = meta["rows"]
            decided = meta["decided"]

            if rows_n == 0:
                status = "MISSING_FROM_GRADED"
                note = "Not in graded archive this window"
            elif decided == 0:
                status = "UNDECIDED_ONLY"
                note = "Only PENDING/VOID — no HIT/MISS yet"
            elif ticket_n == 0 and demon_n > 0:
                status = "DEMON_ONLY"
                note = "On board as Demon; not in Goblin/Standard ticket pool"
            elif ticket_n < 30:
                status = "THIN_TICKET"
                note = "Few Goblin/Standard decided grades"
            else:
                status = "TICKET_READY"
                note = "Has Goblin/Standard decided grades"

            lift = None
            if gob_live["n"] >= 10 and gob["hr"] is not None and gob_live["hr"] is not None:
                lift = round(gob_live["hr"] - gob["hr"], 1)

            rows.append(
                {
                    "prop": prop,
                    "status": status,
                    "note": note,
                    "rows": rows_n,
                    "decided": decided,
                    "pending_void": meta["pending_void"],
                    "by_pick": by_pick,
                    "goblin_over": gob,
                    "goblin_over_live": gob_live,
                    "goblin_live_lift": lift,
                    "standard_under": std_u,
                    "standard_under_live": std_u_live,
                    "standard_over": std_o,
                    "demon_over": dem,
                }
            )

        status_counts = defaultdict(int)
        for r in rows:
            status_counts[r["status"]] += 1

        by_sport[sport] = {
            "catalog_n": len(cats),
            "status_counts": dict(status_counts),
            "rows": rows,
            "ticket_ready": [r for r in rows if r["status"] == "TICKET_READY"],
            "demon_only": [r["prop"] for r in rows if r["status"] == "DEMON_ONLY"],
            "missing": [r["prop"] for r in rows if r["status"] == "MISSING_FROM_GRADED"],
            "undecided": [r["prop"] for r in rows if r["status"] == "UNDECIDED_ONLY"],
            "thin": [r["prop"] for r in rows if r["status"] == "THIN_TICKET"],
            "top_goblin_live": sorted(
                [r for r in rows if r["goblin_live_lift"] is not None],
                key=lambda r: -r["goblin_live_lift"],
            )[:10],
        }

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": START.isoformat(), "end": END.isoformat()},
        "exclusions": ["Fantasy*", "1st Inning*"],
        "excluded_note": "Fantasy Score / Hitter-Pitcher-Outfield Fantasy / 1st Inning Runs|Walks Allowed omitted per request",
        "pp_catalog_source": "user PrizePicks screenshots 2026-08-10",
        "days_used": days_used,
        "n_days": len(days_used),
        "by_sport": by_sport,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote", OUT)
    for sport, b in by_sport.items():
        print(f"\n=== {sport} {b['status_counts']} ===")
        print("  missing:", b["missing"] or "-")
        print("  demon_only:", b["demon_only"] or "-")
        print("  undecided:", b["undecided"] or "-")
        print("  thin:", b["thin"] or "-")
        for r in b["top_goblin_live"][:6]:
            print(
                f"  lift {r['prop'][:26]:26} {r['goblin_over']['hr']}%->"
                f"{r['goblin_over_live']['hr']}% ({r['goblin_live_lift']:+}) n={r['goblin_over_live']['n']}"
            )
        for r in b["rows"]:
            if r["status"] == "TICKET_READY":
                continue
            print(
                f"  [{r['status']}] {r['prop']}: rows={r['rows']} decided={r['decided']} "
                f"picks={r['by_pick']} demHR={r['demon_over']}"
            )


if __name__ == "__main__":
    main()
