import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp")
date = "2026-08-08"

gp = json.loads((ROOT / f"ui_runner/templates/graded_props_{date}.json").read_text(encoding="utf-8"))
props = gp.get("props") or []
slate = json.loads((ROOT / f"outputs/{date}/canonical/platform_ui/slate_latest.json").read_text(encoding="utf-8"))
sports = slate.get("sports") or {}


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


def norm(s):
    return " ".join(str(s or "").upper().split())


def dir_of(x):
    d = str(x.get("direction") or x.get("dir") or x.get("over_under") or "").upper()
    if d in ("OVER", "O", "MORE"):
        return "OVER"
    if d in ("UNDER", "U", "LESS"):
        return "UNDER"
    return d


def key_of(x, sport=None):
    return (
        norm(sport or x.get("sport")),
        norm(x.get("player")),
        norm(x.get("prop") or x.get("stat") or x.get("market")),
        round(fnum(x.get("line"), 0) or 0, 2),
        dir_of(x),
        norm(x.get("pick_type")),
    )


def res(x):
    if "hit" in x and x["hit"] is not None:
        h = x["hit"]
        if h is True or h == 1 or str(h).lower() in ("true", "hit", "win"):
            return "HIT"
        if h is False or h == 0 or str(h).lower() in ("false", "miss", "loss"):
            return "MISS"
    r = str(x.get("result") or "").upper()
    if r in ("HIT", "WIN"):
        return "HIT"
    if r in ("MISS", "LOSS"):
        return "MISS"
    if r in ("PUSH", "VOID"):
        return "PUSH"
    return "PENDING" if r in ("PENDING", "LIVE", "OPEN", "") else (r or "OTHER")


def ptype(x):
    return str(x.get("pick_type") or "").title() or "Unk"


def sport(x):
    return norm(x.get("sport")) or "UNK"


# L5 map from slate
l5_map = {}
for sp, rows in sports.items():
    if not isinstance(rows, list):
        continue
    for r in rows:
        lo, lu = fnum(r.get("l5_over")), fnum(r.get("l5_under"))
        if lo is None and lu is None:
            continue
        d = dir_of(r)
        lo = lo or 0.0
        lu = lu or 0.0
        n = lo + lu
        hits = lo if d == "OVER" else lu
        l10o, l10u = fnum(r.get("l10_over"), 0) or 0, fnum(r.get("l10_under"), 0) or 0
        n10 = l10o + l10u
        h10 = l10o if d == "OVER" else l10u
        l5_map[key_of(r, sp)] = {
            "l5_hits": hits,
            "l5_n": n,
            "l5_rate": (hits / n) if n else None,
            "l10_hits": h10,
            "l10_n": n10,
            "l10_rate": (h10 / n10) if n10 else None,
        }


def l5_info(x):
    lo, lu = fnum(x.get("l5_over")), fnum(x.get("l5_under"))
    d = dir_of(x)
    if lo is not None or lu is not None:
        lo = lo or 0.0
        lu = lu or 0.0
        n = lo + lu
        hits = lo if d == "OVER" else lu
        l10o, l10u = fnum(x.get("l10_over"), 0) or 0, fnum(x.get("l10_under"), 0) or 0
        n10 = l10o + l10u
        h10 = l10o if d == "OVER" else l10u
        return hits, n, (hits / n if n else None), h10, n10, (h10 / n10 if n10 else None)
    m = l5_map.get(key_of(x))
    if not m:
        for kk, vv in l5_map.items():
            if kk[:5] == key_of(x)[:5]:
                m = vv
                break
    if not m:
        return None, None, None, None, None, None
    return m["l5_hits"], m["l5_n"], m["l5_rate"], m["l10_hits"], m["l10_n"], m["l10_rate"]


rows = []
for x in props:
    h5, n5, r5, h10, n10, r10 = l5_info(x)
    rows.append(
        {
            "x": x,
            "res": res(x),
            "sport": sport(x),
            "pt": ptype(x),
            "l5_hits": h5,
            "l5_n": n5,
            "l5_rate": r5,
            "l10_hits": h10,
            "l10_n": n10,
            "l10_rate": r10,
        }
    )


def hr(subset):
    c = Counter(r["res"] for r in subset)
    d = c["HIT"] + c["MISS"]
    rate = (100.0 * c["HIT"] / d) if d else None
    return {
        "hit": c["HIT"],
        "miss": c["MISS"],
        "push": c["PUSH"],
        "pend": c.get("PENDING", 0),
        "decided": d,
        "n": len(subset),
        "hr": None if rate is None else round(rate, 1),
    }


def lift(a, b):
    if a is None or b is None:
        return None
    return round(b - a, 1)


matched = [r for r in rows if r["l5_hits"] is not None]
goblin = [r for r in matched if r["pt"] == "Goblin"]
standard = [r for r in matched if r["pt"] == "Standard"]

filters = {}

filters["all_graded"] = hr(rows)
filters["matched_l5"] = hr(matched)
filters["l5_ge4"] = hr([r for r in matched if r["l5_n"] and r["l5_n"] >= 5 and r["l5_hits"] >= 4])
filters["l5_lt4"] = hr([r for r in matched if not (r["l5_n"] and r["l5_n"] >= 5 and r["l5_hits"] >= 4)])
filters["l5_5of5"] = hr([r for r in matched if r["l5_n"] and r["l5_n"] >= 5 and r["l5_hits"] >= 5])
filters["l5_ge4_l10_ge7"] = hr(
    [
        r
        for r in matched
        if r["l5_n"]
        and r["l5_n"] >= 5
        and r["l5_hits"] >= 4
        and r["l10_n"]
        and r["l10_n"] >= 8
        and r["l10_hits"] >= 7
    ]
)
filters["l5_ge4_l10_ge8"] = hr(
    [
        r
        for r in matched
        if r["l5_n"]
        and r["l5_n"] >= 5
        and r["l5_hits"] >= 4
        and r["l10_n"]
        and r["l10_n"] >= 8
        and r["l10_hits"] >= 8
    ]
)
filters["goblin_all"] = hr(goblin)
filters["goblin_l5_ge4"] = hr([r for r in goblin if r["l5_n"] and r["l5_n"] >= 5 and r["l5_hits"] >= 4])
filters["goblin_l5_5"] = hr([r for r in goblin if r["l5_n"] and r["l5_n"] >= 5 and r["l5_hits"] >= 5])
filters["goblin_l5_ge4_l10_ge8"] = hr(
    [
        r
        for r in goblin
        if r["l5_n"]
        and r["l5_n"] >= 5
        and r["l5_hits"] >= 4
        and r["l10_n"]
        and r["l10_n"] >= 8
        and r["l10_hits"] >= 8
    ]
)
filters["std_all"] = hr(standard)
filters["std_l5_ge4"] = hr([r for r in standard if r["l5_n"] and r["l5_n"] >= 5 and r["l5_hits"] >= 4])

# by sport for goblin L5>=4
by_sport = {}
for sp in sorted({r["sport"] for r in matched}):
    base = [r for r in matched if r["sport"] == sp]
    g4 = [r for r in base if r["pt"] == "Goblin" and r["l5_n"] and r["l5_n"] >= 5 and r["l5_hits"] >= 4]
    by_sport[sp] = {
        "all": hr(base),
        "goblin_l5_ge4": hr(g4),
    }

# ticket-leg simulation: product of independent leg HR for 2/3/4/5/6 legs
base_hr = (filters["matched_l5"]["hr"] or 0) / 100
g4_hr = (filters["goblin_l5_ge4"]["hr"] or 0) / 100
g5_hr = (filters["goblin_l5_5"]["hr"] or 0) / 100
agree_hr = (filters["goblin_l5_ge4_l10_ge8"]["hr"] or 0) / 100

ticket_sim = []
for n in (2, 3, 4, 5, 6):
    ticket_sim.append(
        {
            "legs": n,
            "matched_board": round(100 * (base_hr**n), 1),
            "goblin_l5_ge4": round(100 * (g4_hr**n), 1),
            "goblin_l5_5": round(100 * (g5_hr**n), 1),
            "goblin_l5_l10_agree": round(100 * (agree_hr**n), 1),
            "lift_vs_board_ge4": round(100 * ((g4_hr**n) - (base_hr**n)), 1),
        }
    )

# coverage / pool shrink
cov = {
    "graded_n": len(rows),
    "matched_n": len(matched),
    "l5_ge4_n": filters["l5_ge4"]["n"],
    "goblin_l5_ge4_n": filters["goblin_l5_ge4"]["n"],
    "goblin_l5_5_n": filters["goblin_l5_5"]["n"],
    "goblin_agree_n": filters["goblin_l5_ge4_l10_ge8"]["n"],
    "matched_pct_kept_ge4": round(100 * filters["l5_ge4"]["n"] / max(len(matched), 1), 1),
    "goblin_pct_kept_ge4": round(100 * filters["goblin_l5_ge4"]["n"] / max(len(goblin), 1), 1),
}

out = {
    "date": date,
    "note": "Aug 8 graded props joined to that day's slate L5/L10. Ticket sims assume independent legs (upper bound).",
    "filters": filters,
    "by_sport": by_sport,
    "ticket_sim": ticket_sim,
    "coverage": cov,
    "lifts": {
        "board_to_l5_ge4": lift(filters["all_graded"]["hr"], filters["l5_ge4"]["hr"]),
        "matched_to_l5_ge4": lift(filters["matched_l5"]["hr"], filters["l5_ge4"]["hr"]),
        "goblin_to_l5_ge4": lift(filters["goblin_all"]["hr"], filters["goblin_l5_ge4"]["hr"]),
        "goblin_to_l5_5": lift(filters["goblin_all"]["hr"], filters["goblin_l5_5"]["hr"]),
        "goblin_ge4_to_agree": lift(filters["goblin_l5_ge4"]["hr"], filters["goblin_l5_ge4_l10_ge8"]["hr"]),
        "std_to_l5_ge4": lift(filters["std_all"]["hr"], filters["std_l5_ge4"]["hr"]),
    },
}

Path(r"C:\Temp\lift_aug8.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(out, indent=2))
