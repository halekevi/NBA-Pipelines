"""Power/flex by legs × same-game density (stratified)."""
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

root = Path(__file__).resolve().parents[1]
start = date(2026, 7, 11)
end = date(2026, 8, 9)


def fnum(x):
    try:
        if x is None or x == "":
            return None
        v = float(x)
        return None if math.isnan(v) else v
    except Exception:
        return None


def norm(s):
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", str(s or "").upper()).split())


def ndir(x):
    for k in ("direction", "dir", "over_under"):
        v = str(x.get(k) or "").upper()
        if v.startswith("O"):
            return "OVER"
        if v.startswith("U"):
            return "UNDER"
    return ""


def hit(x):
    if x.get("hit") in (True, 1, "1"):
        return 1
    if x.get("hit") in (False, 0, "0"):
        return 0
    r = str(x.get("result") or "").upper()
    if r in ("HIT", "WIN"):
        return 1
    if r in ("MISS", "LOSS"):
        return 0
    return None


def gkey(leg):
    team = norm(leg.get("team"))
    opp = norm(leg.get("opp"))
    sport = str(leg.get("sport") or "").upper()
    gt = str(leg.get("game_time") or "")[:16]
    if team and opp:
        return f"{sport}:{'|'.join(sorted([team, opp]))}:{gt}"
    return f"{sport}:{team}:{gt}"


class A:
    def __init__(self):
        self.h = 0
        self.n = 0

    def add(self, v):
        self.h += v
        self.n += 1

    def d(self):
        return {
            "hr": round(100 * self.h / self.n, 1) if self.n else None,
            "n": self.n,
            "hits": self.h,
        }


bag = defaultdict(A)
d = start
while d <= end:
    gp = root / f"ui_runner/templates/graded_props_{d.isoformat()}.json"
    tp = root / f"ui_runner/data/combined_slate_tickets_{d.isoformat()}.json"
    day = d
    d += timedelta(days=1)
    if not gp.exists() or not tp.exists():
        continue
    gidx = {}
    for x in json.loads(gp.read_text(encoding="utf-8")).get("props") or []:
        h = hit(x)
        if h is None:
            continue
        line = fnum(x.get("line"))
        if line is None:
            continue
        key = (
            str(x.get("sport") or "").upper(),
            norm(x.get("player")),
            norm(x.get("prop") or x.get("prop_type")),
            round(line, 2),
            ndir(x),
        )
        gidx[key] = h
    for g in json.loads(tp.read_text(encoding="utf-8")).get("groups") or []:
        for tk in g.get("tickets") or []:
            legs = tk.get("legs") or []
            if len(legs) < 2:
                continue
            hits = []
            games = Counter()
            ok = True
            for leg in legs:
                line = fnum(leg.get("line"))
                key = (
                    str(leg.get("sport") or "").upper(),
                    norm(leg.get("player")),
                    norm(leg.get("prop_type") or leg.get("prop")),
                    round(line, 2) if line is not None else None,
                    ndir(leg),
                )
                if key[3] is None or key not in gidx:
                    ok = False
                    break
                hits.append(gidx[key])
                games[gkey(leg)] += 1
            if not ok:
                continue
            allhit = 1 if all(h == 1 for h in hits) else 0
            flex = 1 if sum(hits) >= len(hits) - 1 else 0
            n = len(hits)
            mx = max(games.values())
            sg_bucket = 1 if mx <= 1 else 2 if mx <= 2 else 3
            for lab, val in (("P", allhit), ("F", flex)):
                bag[f"{lab}|L{n}|SGLE{sg_bucket}"].add(val)
                bag[f"{lab}|ALL|SGLE{sg_bucket}"].add(val)

print("POWER by legs x max same-game")
for n in range(2, 7):
    for sg in (1, 2, 3):
        a = bag[f"P|L{n}|SGLE{sg}"].d()
        label = f"<={sg}" if sg < 3 else "3+"
        if a["n"] >= 8:
            print(f"  {n}-leg maxSG{label}: {a['hr']}% ({a['hits']}/{a['n']})")
print("\nPOWER overall by SG")
for sg in (1, 2, 3):
    a = bag[f"P|ALL|SGLE{sg}"].d()
    label = f"<={sg}" if sg < 3 else "3+"
    print(f"  maxSG{label}: {a['hr']}% ({a['hits']}/{a['n']})")
print("\nFLEX overall by SG")
for sg in (1, 2, 3):
    a = bag[f"F|ALL|SGLE{sg}"].d()
    label = f"<={sg}" if sg < 3 else "3+"
    print(f"  maxSG{label}: {a['hr']}% ({a['hits']}/{a['n']})")
