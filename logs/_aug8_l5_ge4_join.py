import json
from collections import Counter, defaultdict
from pathlib import Path

root = Path(__file__).resolve().parents[1]
date = "2026-08-08"

gp = json.loads((root / f"ui_runner/templates/graded_props_{date}.json").read_text(encoding="utf-8"))
props = gp.get("props") or []

slate_path = root / f"outputs/{date}/canonical/platform_ui/slate_latest.json"
if not slate_path.exists():
    slate_path = root / f"outputs/{date}/canonical/mobile_app/slate_latest.json"
slate = json.loads(slate_path.read_text(encoding="utf-8"))
sports = slate.get("sports") or {}
print("slate", slate.get("date"), "path", slate_path.name)


def fnum(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
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
    sp = norm(sport or x.get("sport"))
    return (
        sp,
        norm(x.get("player")),
        norm(x.get("prop") or x.get("stat") or x.get("market")),
        round(fnum(x.get("line"), 0) or 0, 2),
        dir_of(x),
        norm(x.get("pick_type")),
    )


# Build L5 lookup from slate
l5_map = {}
dup = 0
for sp, rows in sports.items():
    if not isinstance(rows, list):
        continue
    for r in rows:
        k = key_of(r, sp)
        lo, lu = fnum(r.get("l5_over")), fnum(r.get("l5_under"))
        l5r = fnum(r.get("l5_side_hit_rate") or r.get("hit_rate_l5"))
        if lo is None and lu is None and l5r is None:
            continue
        d = dir_of(r)
        if lo is not None or lu is not None:
            lo = lo or 0.0
            lu = lu or 0.0
            n = lo + lu
            hits = lo if d == "OVER" else lu
            rate = (hits / n) if n else None
        else:
            rate = l5r / 100.0 if l5r and l5r > 1 else l5r
            hits = (rate * 5.0) if rate is not None else None
            n = 5.0 if rate is not None else None
        payload = {"hits": hits, "n": n, "rate": rate, "l5_over": lo, "l5_under": lu}
        if k in l5_map:
            dup += 1
        l5_map[k] = payload

print("l5_map size", len(l5_map), "dups_overwritten", dup)


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
    if r in ("PENDING", "LIVE", "OPEN", ""):
        return "PENDING"
    return r or "OTHER"


def sport(x):
    return norm(x.get("sport")) or "UNK"


def ptype(x):
    return str(x.get("pick_type") or "").title() or "Unk"


def l5_info(x):
    # prefer graded native L5 if present
    lo, lu = fnum(x.get("l5_over")), fnum(x.get("l5_under"))
    d = dir_of(x)
    if lo is not None or lu is not None:
        lo = lo or 0.0
        lu = lu or 0.0
        n = lo + lu
        if n > 0:
            hits = lo if d == "OVER" else lu
            return hits, n, hits / n, "graded"
    k = key_of(x)
    m = l5_map.get(k)
    if not m:
        # try without pick_type
        k2 = (k[0], k[1], k[2], k[3], k[4], "")
        # fuzzy: any pick type
        for kk, vv in l5_map.items():
            if kk[:5] == k[:5]:
                m = vv
                break
    if not m:
        return None, None, None, None
    return m["hits"], m["n"], m["rate"], "slate"


def ge4(hits, n, rate):
    if hits is None or n is None:
        return False
    return n >= 5 and hits >= 4


joined = []
for x in props:
    hits, n, rate, src = l5_info(x)
    joined.append((x, hits, n, rate, src))

matched = [t for t in joined if t[1] is not None]
ge4_rows = [t for t in matched if ge4(t[1], t[2], t[3])]
lt4_rows = [t for t in matched if not ge4(t[1], t[2], t[3])]
print(
    f"graded={len(props)} matched_l5={len(matched)} "
    f"L5>=4={len(ge4_rows)} L5<4={len(lt4_rows)} unmatched={len(props)-len(matched)}"
)
print("match by sport:")
mb = defaultdict(lambda: Counter())
for x, hits, n, rate, src in joined:
    sp = sport(x)
    if hits is None:
        mb[sp]["unmatched"] += 1
    elif ge4(hits, n, rate):
        mb[sp]["ge4"] += 1
    else:
        mb[sp]["lt4"] += 1
for sp in sorted(mb):
    print(f"  {sp}: {dict(mb[sp])}")


def summarize(label, triples):
    rows = [t[0] for t in triples]
    c = Counter(res(x) for x in rows)
    d = c["HIT"] + c["MISS"]
    hr = round(100 * c["HIT"] / d, 1) if d else None
    print(
        f"{label}: HIT={c['HIT']} MISS={c['MISS']} PUSH={c['PUSH']} "
        f"PEND={c['PENDING']} HR={hr}% decided={d} n={len(rows)}"
    )
    return hr


print("\n=== OVERALL ===")
summarize("ALL graded", [(x, None, None, None, None) for x in props])
summarize("Matched L5", matched)
summarize("L5>=4/5", ge4_rows)
summarize("L5<4/5", lt4_rows)

print("\n=== L5>=4 BY SPORT ===")
by = defaultdict(list)
for t in ge4_rows:
    by[sport(t[0])].append(t)
for sp in sorted(by):
    summarize(sp, by[sp])

print("\n=== L5>=4 BY PICK TYPE ===")
by2 = defaultdict(list)
for t in ge4_rows:
    by2[ptype(t[0])].append(t)
for pt in sorted(by2):
    summarize(pt, by2[pt])

print("\n=== L5>=4 SPORT x PICK (decided>=20) ===")
by3 = defaultdict(list)
for t in ge4_rows:
    by3[(sport(t[0]), ptype(t[0]))].append(t)
for k in sorted(by3):
    rows = [x[0] for x in by3[k]]
    c = Counter(res(x) for x in rows)
    d = c["HIT"] + c["MISS"]
    if d < 20:
        continue
    print(f"  {k[0]} {k[1]}: {round(100*c['HIT']/d,1)}% ({c['HIT']}/{d})")

print("\n=== L5 4/5 vs 5/5 ===")
b = defaultdict(list)
for t in ge4_rows:
    hits, n = t[1], t[2]
    if n >= 5 and hits >= 5:
        b["5/5"].append(t)
    elif n >= 5 and hits >= 4:
        b["4/5"].append(t)
    else:
        b[f"{hits}/{n}"].append(t)
for k in sorted(b):
    summarize(k, b[k])

print("\n=== L5>=4 NO DEMONS ===")
no_dem = [t for t in ge4_rows if ptype(t[0]) != "Demon"]
summarize("no demon", no_dem)
by4 = defaultdict(list)
for t in no_dem:
    by4[sport(t[0])].append(t)
for sp in sorted(by4):
    summarize(sp, by4[sp])

# Ticket eval legs if we can mark from HTML? skip
# Compare lift
print("\n=== LIFT vs ALL / vs matched ===")
c_all = Counter(res(x) for x in props)
d_all = c_all["HIT"] + c_all["MISS"]
c_ge = Counter(res(t[0]) for t in ge4_rows)
d_ge = c_ge["HIT"] + c_ge["MISS"]
c_m = Counter(res(t[0]) for t in matched)
d_m = c_m["HIT"] + c_m["MISS"]
print(f"ALL {round(100*c_all['HIT']/d_all,1)}% | matched {round(100*c_m['HIT']/d_m,1)}% | L5>=4 {round(100*c_ge['HIT']/d_ge,1)}%")
