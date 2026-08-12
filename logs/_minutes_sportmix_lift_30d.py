"""Test WNBA minutes/role floors + ticket same-game / sport-mix lift (30d)."""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = date(2026, 7, 11)
END = date(2026, 8, 9)
OUT = ROOT / "data" / "reports" / "minutes_sportmix_lift_30d.json"


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
    return None


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


def norm_minutes(raw: object) -> str:
    s = str(raw or "").upper().strip()
    if s in ("HIGH", "H"):
        return "HIGH"
    if s in ("MED", "MEDIUM", "MID", "M"):
        return "MED"
    if s in ("LOW", "L"):
        return "LOW"
    if s in ("UNKNOWN", "UNK", ""):
        return "UNKNOWN"
    return s or "UNKNOWN"


def norm_role(raw: object) -> str:
    s = str(raw or "").upper().strip()
    if s in ("PRIMARY", "PRIM"):
        return "PRIMARY"
    if s in ("SECONDARY", "SEC"):
        return "SECONDARY"
    if s in ("SUPPORT", "SUP"):
        return "SUPPORT"
    return s or "UNKNOWN"


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


def slate_l5_index(slate: dict):
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
            idx[key] = {
                "l5_over": fnum(r.get("l5_over")),
                "l5_under": fnum(r.get("l5_under")),
                "l10_over": fnum(r.get("l10_over")),
                "l10_under": fnum(r.get("l10_under")),
                "l10_games_played": fnum(r.get("l10_games_played") or r.get("l10_sample")),
                "minutes_tier": norm_minutes(
                    r.get("minutes_tier") or r.get("min_tier")
                ),
                "role_tier": norm_role(r.get("role_tier") or r.get("usage_role")),
            }
    return idx


def game_key(leg: dict) -> str:
    team = norm_name(leg.get("team"))
    opp = norm_name(leg.get("opp") or leg.get("opp_team"))
    gt = str(leg.get("game_time") or leg.get("event_start_time") or "")[:16]
    sport = str(leg.get("sport") or "").upper()
    if team and opp:
        pair = "|".join(sorted([team, opp]))
        return f"{sport}:{pair}:{gt}"
    return f"{sport}:{team}:{gt}"


def main():
    wnba = defaultdict(Acc)
    tickets_acc = defaultdict(Acc)
    leg_acc = defaultdict(Acc)
    days_props = []
    days_tickets = []
    join_fail = 0
    tickets_partial = 0
    tickets_full = 0

    d = START
    while d <= END:
        gp = ROOT / f"ui_runner/templates/graded_props_{d.isoformat()}.json"
        if not gp.exists():
            d += timedelta(days=1)
            continue
        props = json.loads(gp.read_text(encoding="utf-8")).get("props") or []
        days_props.append(d.isoformat())
        slate = load_slate(d)
        sidx = slate_l5_index(slate) if slate else {}

        # Build graded lookup for ticket join
        gidx = {}
        for x in props:
            hit = res_hit(x)
            if hit is None:
                continue
            sport = str(x.get("sport") or "").upper()
            player = norm_name(x.get("player"))
            prop = norm_name(x.get("prop") or x.get("prop_type"))
            line = fnum(x.get("line"))
            direction = norm_dir(x)
            if not player or not prop or line is None or not direction:
                continue
            key = (sport, player, prop, round(line, 2), direction)
            gidx[key] = hit

            # WNBA minutes/role analysis
            if sport != "WNBA":
                continue
            pick = norm_pick(x)
            if pick not in ("GOBLIN", "STANDARD"):
                continue
            # fill L5 from slate
            sr = sidx.get(key)
            if sr:
                for fk in (
                    "l5_over",
                    "l5_under",
                    "l10_over",
                    "l10_under",
                    "l10_games_played",
                ):
                    if x.get(fk) in (None, "") and sr.get(fk) is not None:
                        x[fk] = sr.get(fk)
            minutes = norm_minutes(
                x.get("minutes_tier")
                or x.get("min_tier")
                or (sr or {}).get("minutes_tier")
            )
            role = norm_role(
                x.get("role_tier")
                or x.get("usage_role")
                or (sr or {}).get("role_tier")
            )
            l5, l10, sample = side_l5_l10(x, direction)
            is_live = live_ok(pick, direction, l5, l10, sample)

            wnba[f"ALL|{pick}|{direction}"].add(hit)
            wnba[f"MIN:{minutes}|{pick}|{direction}"].add(hit)
            wnba[f"ROLE:{role}|{pick}|{direction}"].add(hit)
            wnba[f"MIN:{minutes}|ROLE:{role}|{pick}|{direction}"].add(hit)
            if is_live:
                wnba[f"LIVE|{pick}|{direction}"].add(hit)
                wnba[f"LIVE|MIN:{minutes}|{pick}|{direction}"].add(hit)
                wnba[f"LIVE|ROLE:{role}|{pick}|{direction}"].add(hit)
                # actionable combo floors
                if minutes in ("HIGH", "MED"):
                    wnba[f"LIVE|MIN_GE_MED|{pick}|{direction}"].add(hit)
                if minutes == "HIGH":
                    wnba[f"LIVE|MIN_HIGH|{pick}|{direction}"].add(hit)
                if role == "PRIMARY":
                    wnba[f"LIVE|ROLE_PRIMARY|{pick}|{direction}"].add(hit)
                if minutes in ("HIGH", "MED") and role == "PRIMARY":
                    wnba[f"LIVE|MIN_GE_MED+PRIMARY|{pick}|{direction}"].add(hit)
                if minutes != "LOW":
                    wnba[f"LIVE|NOT_LOW|{pick}|{direction}"].add(hit)

        # Ticket reconstruction
        tp = ROOT / f"ui_runner/data/combined_slate_tickets_{d.isoformat()}.json"
        if tp.exists():
            days_tickets.append(d.isoformat())
            tdata = json.loads(tp.read_text(encoding="utf-8"))
            for g in tdata.get("groups") or []:
                gname = str(g.get("group_name") or "")
                for tk in g.get("tickets") or []:
                    legs = tk.get("legs") or []
                    if len(legs) < 2:
                        continue
                    hits = []
                    sports = set()
                    games = Counter()
                    for leg in legs:
                        sport = str(leg.get("sport") or "").upper()
                        sports.add(sport)
                        games[game_key(leg)] += 1
                        player = norm_name(leg.get("player"))
                        prop = norm_name(leg.get("prop_type") or leg.get("prop"))
                        line = fnum(leg.get("line"))
                        direction = norm_dir(leg)
                        key = (
                            sport,
                            player,
                            prop,
                            round(line, 2) if line is not None else None,
                            direction,
                        )
                        if key[3] is None or key not in gidx:
                            join_fail += 1
                            hits.append(None)
                        else:
                            hits.append(gidx[key])
                            leg_acc["ALL"].add(gidx[key])

                    if any(h is None for h in hits):
                        tickets_partial += 1
                        continue
                    tickets_full += 1
                    all_hit = 1 if all(h == 1 for h in hits) else 0
                    flex = 1 if sum(hits) >= len(hits) - 1 else 0
                    n_legs = len(hits)
                    max_sg = max(games.values()) if games else 1
                    n_sports = len(sports)
                    n_games = len(games)

                    for label, val in (
                        ("POWER", all_hit),
                        ("FLEX", flex),
                    ):
                        tickets_acc[f"{label}|ALL"].add(val)
                        tickets_acc[f"{label}|LEGS:{n_legs}"].add(val)
                        tickets_acc[f"{label}|MAXSG:{max_sg}"].add(val)
                        tickets_acc[f"{label}|MAXSG_LE:{2 if max_sg <= 2 else 'gt2'}"].add(
                            val
                        )
                        if max_sg <= 1:
                            tickets_acc[f"{label}|MAXSG_LE:1"].add(val)
                        tickets_acc[f"{label}|NSPORTS:{n_sports}"].add(val)
                        tickets_acc[f"{label}|NGAMES:{n_games}"].add(val)
                        # mix buckets
                        if n_sports >= 2:
                            tickets_acc[f"{label}|MULTI_SPORT"].add(val)
                        else:
                            tickets_acc[f"{label}|SINGLE_SPORT"].add(val)
                        if n_games >= n_legs:  # all different games
                            tickets_acc[f"{label}|ALL_DIFF_GAMES"].add(val)
                        if max_sg >= 3:
                            tickets_acc[f"{label}|STACK3PLUS"].add(val)
                        # group family
                        if "STRONG" in gname.upper():
                            tickets_acc[f"{label}|FAMILY:STRONG"].add(val)
                        if "GOBLIN" in gname.upper():
                            tickets_acc[f"{label}|FAMILY:GOBLINISH"].add(val)

        d += timedelta(days=1)

    def dump_acc(prefix: str, bag, min_n=20):
        rows = []
        for k, a in sorted(bag.items(), key=lambda kv: (-kv[1].n, kv[0])):
            if not k.startswith(prefix) and prefix != "":
                # allow exact filter via contains
                pass
            if a.n < min_n:
                continue
            rows.append({"key": k, **a.d()})
        return rows

    wnba_rows = [{"key": k, **a.d()} for k, a in sorted(wnba.items(), key=lambda kv: -kv[1].n) if a.n >= 15]
    ticket_rows = [{"key": k, **a.d()} for k, a in sorted(tickets_acc.items(), key=lambda kv: -kv[1].n) if a.n >= 10]

    def cell(bag, key):
        a = bag.get(key)
        return a.d() if a and a.n else {"hr": None, "hits": 0, "n": 0}

    # Focus contrasts
    wnba_focus = []
    for pick, direction in (("GOBLIN", "OVER"), ("STANDARD", "OVER"), ("STANDARD", "UNDER")):
        base = cell(wnba, f"ALL|{pick}|{direction}")
        live = cell(wnba, f"LIVE|{pick}|{direction}")
        for extra in (
            "LIVE|MIN:HIGH",
            "LIVE|MIN:MED",
            "LIVE|MIN:LOW",
            "LIVE|MIN_GE_MED",
            "LIVE|NOT_LOW",
            "LIVE|ROLE_PRIMARY",
            "LIVE|ROLE:PRIMARY",
            "LIVE|ROLE:SECONDARY",
            "LIVE|ROLE:SUPPORT",
            "LIVE|MIN_GE_MED+PRIMARY",
        ):
            # ROLE keys stored as LIVE|ROLE:PRIMARY|...
            pass
        contrasts = {
            "base": base,
            "live": live,
            "live_HIGH": cell(wnba, f"LIVE|MIN:HIGH|{pick}|{direction}"),
            "live_MED": cell(wnba, f"LIVE|MIN:MED|{pick}|{direction}"),
            "live_LOW": cell(wnba, f"LIVE|MIN:LOW|{pick}|{direction}"),
            "live_min_ge_med": cell(wnba, f"LIVE|MIN_GE_MED|{pick}|{direction}"),
            "live_not_low": cell(wnba, f"LIVE|NOT_LOW|{pick}|{direction}"),
            "live_primary": cell(wnba, f"LIVE|ROLE_PRIMARY|{pick}|{direction}"),
            "live_role_primary": cell(wnba, f"LIVE|ROLE:PRIMARY|{pick}|{direction}"),
            "live_role_secondary": cell(wnba, f"LIVE|ROLE:SECONDARY|{pick}|{direction}"),
            "live_role_support": cell(wnba, f"LIVE|ROLE:SUPPORT|{pick}|{direction}"),
            "live_min_ge_med_primary": cell(
                wnba, f"LIVE|MIN_GE_MED+PRIMARY|{pick}|{direction}"
            ),
        }
        # deltas vs live
        if live["hr"] is not None:
            for name in (
                "live_HIGH",
                "live_MED",
                "live_LOW",
                "live_min_ge_med",
                "live_not_low",
                "live_primary",
                "live_min_ge_med_primary",
            ):
                c = contrasts[name]
                c["delta_vs_live"] = (
                    round(c["hr"] - live["hr"], 1)
                    if c["hr"] is not None and c["n"] >= 15
                    else None
                )
        wnba_focus.append({"pool": f"{pick} {direction}", **contrasts})

    ticket_focus = {
        "power_all": cell(tickets_acc, "POWER|ALL"),
        "flex": cell(tickets_acc, "FLEX|ALL"),
        "power_maxsg_le1": cell(tickets_acc, "POWER|MAXSG_LE:1"),
        "power_maxsg_le2": cell(tickets_acc, "POWER|MAXSG_LE:2"),
        "power_maxsg_gt2": cell(tickets_acc, "POWER|MAXSG_LE:gt2"),
        "power_stack3plus": cell(tickets_acc, "POWER|STACK3PLUS"),
        "power_multi_sport": cell(tickets_acc, "POWER|MULTI_SPORT"),
        "power_single_sport": cell(tickets_acc, "POWER|SINGLE_SPORT"),
        "power_all_diff_games": cell(tickets_acc, "POWER|ALL_DIFF_GAMES"),
        "flex_maxsg_le1": cell(tickets_acc, "FLEX|MAXSG_LE:1"),
        "flex_maxsg_le2": cell(tickets_acc, "FLEX|MAXSG_LE:2"),
        "flex_maxsg_gt2": cell(tickets_acc, "FLEX|MAXSG_LE:gt2"),
        "flex_multi_sport": cell(tickets_acc, "FLEX|MULTI_SPORT"),
        "flex_single_sport": cell(tickets_acc, "FLEX|SINGLE_SPORT"),
    }
    # per legs
    for n in range(2, 7):
        ticket_focus[f"power_legs_{n}"] = cell(tickets_acc, f"POWER|LEGS:{n}")
        ticket_focus[f"flex_legs_{n}"] = cell(tickets_acc, f"FLEX|LEGS:{n}")

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": START.isoformat(), "end": END.isoformat()},
        "coverage": {
            "days_with_graded_props": days_props,
            "n_prop_days": len(days_props),
            "days_with_tickets": days_tickets,
            "n_ticket_days": len(days_tickets),
            "tickets_fully_joined": tickets_full,
            "tickets_partial_skip": tickets_partial,
            "leg_join_fails": join_fail,
        },
        "wnba_focus": wnba_focus,
        "wnba_rows_min15": wnba_rows,
        "ticket_focus": ticket_focus,
        "ticket_rows_min10": ticket_rows,
        "leg_hr_on_joined_tickets": cell(leg_acc, "ALL") if leg_acc else None,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print("prop_days", len(days_props), "ticket_days", len(days_tickets))
    print("tickets_full", tickets_full, "partial", tickets_partial)
    print("\nWNBA FOCUS")
    for block in wnba_focus:
        print(block["pool"])
        for k, v in block.items():
            if k == "pool" or not isinstance(v, dict):
                continue
            if v.get("n", 0) >= 15:
                print(f"  {k:28} {v['hr']}% n={v['n']} Δ={v.get('delta_vs_live')}")
    print("\nTICKET FOCUS")
    for k, v in ticket_focus.items():
        if v.get("n", 0) >= 10:
            print(f"  {k:28} {v['hr']}% {v['hits']}/{v['n']}")


if __name__ == "__main__":
    main()
