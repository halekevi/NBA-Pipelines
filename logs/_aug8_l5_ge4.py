import json
from collections import Counter, defaultdict
from pathlib import Path

root = Path(__file__).resolve().parents[1]
date = "2026-08-08"
gp = json.loads((root / f"ui_runner/templates/graded_props_{date}.json").read_text(encoding="utf-8"))
props = gp.get("props") or gp.get("rows") or []


def fnum(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def res(x):
    if "hit" in x and x["hit"] is not None:
        h = x["hit"]
        if h is True or h == 1 or str(h).lower() in ("true", "hit", "win"):
            return "HIT"
        if h is False or h == 0 or str(h).lower() in ("false", "miss", "loss"):
            return "MISS"
    r = str(x.get("result") or x.get("grade") or "").upper().strip()
    if r in ("HIT", "WIN", "W"):
        return "HIT"
    if r in ("MISS", "LOSS", "L"):
        return "MISS"
    if r in ("PUSH", "VOID"):
        return "PUSH"
    if r in ("PENDING", "LIVE", "OPEN", ""):
        return "PENDING"
    return r or "OTHER"


def sport(x):
    return str(x.get("sport") or "").upper() or "UNK"


def ptype(x):
    return str(x.get("pick_type") or "").title() or "Unk"


def dir_side(x):
    d = str(x.get("direction") or x.get("dir") or x.get("over_under") or "").upper()
    if d in ("OVER", "O", "MORE"):
        return "OVER"
    if d in ("UNDER", "U", "LESS"):
        return "UNDER"
    return d or "?"


def l5_side_hits(x):
    """Return (hits, n, rate) for the played side from L5 counts or hit_rate_l5."""
    d = dir_side(x)
    lo = fnum(x.get("l5_over"))
    lu = fnum(x.get("l5_under"))
    if lo is not None or lu is not None:
        lo = lo or 0.0
        lu = lu or 0.0
        n = lo + lu
        if n <= 0:
            return None, None, None
        hits = lo if d == "OVER" else lu if d == "UNDER" else None
        if hits is None:
            return None, None, None
        return hits, n, hits / n

    # fallback: hit_rate_l5 often already side-aligned
    hr = fnum(x.get("hit_rate_l5") or x.get("l5_side_hit_rate") or x.get("l5_hit_rate"))
    if hr is not None:
        # assume rate over 5 games when only rate present
        if hr > 1.0:
            hr = hr / 100.0
        return hr * 5.0, 5.0, hr
    return None, None, None


def l5_ge4(x):
    hits, n, rate = l5_side_hits(x)
    if hits is None or n is None:
        return False
    # require full-ish sample and >=4 hits (or rate >= 0.8 with n>=5)
    if n >= 5 and hits >= 4:
        return True
    if n >= 4 and hits >= 4 and (rate or 0) >= 0.8:
        return True
    return False


def summarize(label, rows):
    c = Counter(res(x) for x in rows)
    d = c["HIT"] + c["MISS"]
    hr = round(100 * c["HIT"] / d, 1) if d else None
    print(
        f"{label}: HIT={c['HIT']} MISS={c['MISS']} PUSH={c['PUSH']} "
        f"PEND={c['PENDING']} HR={hr}% decided={d} n={len(rows)}"
    )
    return hr, d, c


# coverage
has_l5 = 0
ge4 = []
lt4 = []
unk = []
for x in props:
    hits, n, rate = l5_side_hits(x)
    if hits is None:
        unk.append(x)
    elif l5_ge4(x):
        ge4.append(x)
        has_l5 += 1
    else:
        lt4.append(x)
        has_l5 += 1

print(f"date={date} total={len(props)} with_l5={has_l5} L5>=4={len(ge4)} L5<4={len(lt4)} unk={len(unk)}")
print()

print("=== ALL PROPS ===")
summarize("ALL", props)
summarize("L5>=4", ge4)
summarize("L5<4", lt4)
summarize("L5 unk", unk)

print("\n=== L5>=4 BY SPORT ===")
by = defaultdict(list)
for x in ge4:
    by[sport(x)].append(x)
for sp in sorted(by):
    summarize(sp, by[sp])

print("\n=== L5>=4 BY PICK TYPE ===")
by2 = defaultdict(list)
for x in ge4:
    by2[ptype(x)].append(x)
for pt in sorted(by2):
    summarize(pt, by2[pt])

print("\n=== L5>=4 BY SPORT x PICK TYPE (decided>=15) ===")
by3 = defaultdict(list)
for x in ge4:
    by3[(sport(x), ptype(x))].append(x)
for k in sorted(by3):
    rows = by3[k]
    c = Counter(res(x) for x in rows)
    d = c["HIT"] + c["MISS"]
    if d < 15:
        continue
    print(f"  {k[0]} {k[1]}: {round(100*c['HIT']/d,1)}% ({c['HIT']}/{d})")

print("\n=== COMPARISON (decided HR) ===")
for label, rows in [("ALL", props), ("L5>=4", ge4), ("L5<4", lt4)]:
    c = Counter(res(x) for x in rows)
    d = c["HIT"] + c["MISS"]
    print(f"  {label}: {round(100*c['HIT']/d,1) if d else None}% ({c['HIT']}/{d})")

# Also break L5 exactly 4/5 vs 5/5
print("\n=== L5 bucket among ge4 ===")
b45 = defaultdict(list)
for x in ge4:
    hits, n, rate = l5_side_hits(x)
    key = f"{int(round(hits))}/{int(round(n))}" if hits is not None else "?"
    if n and n >= 5:
        if hits >= 5:
            key = "5/5"
        elif hits >= 4:
            key = "4/5"
        else:
            key = f"{int(hits)}/{int(n)}"
    b45[key].append(x)
for k in sorted(b45):
    summarize(k, b45[k])

# Ticket legs proxy: if on_ticket fields empty, skip
print("\n=== L5>=4 excluding Demons ===")
no_dem = [x for x in ge4 if ptype(x) != "Demon"]
summarize("L5>=4 no Demon", no_dem)
by4 = defaultdict(list)
for x in no_dem:
    by4[sport(x)].append(x)
for sp in sorted(by4):
    summarize(sp, by4[sp])
