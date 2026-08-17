import json
from collections import Counter
from pathlib import Path

root = Path(r"H:/halek/ProfileFromC/Desktop/PropORACLE_main_cp")
d = json.loads((root / "ui_runner" / "templates" / "slate_latest.json").read_text(encoding="utf-8"))


def num(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def pick_type(r):
    return str(r.get("pick_type") or r.get("pick") or "").strip().lower()


def series5(r):
    vals = []
    if isinstance(r.get("actual_series"), list) and r["actual_series"]:
        for x in r["actual_series"][:5]:
            v = num(x)
            if v is not None:
                vals.append(v)
        return vals
    for i in range(1, 6):
        v = num(r.get(f"stat_g{i}") or r.get(f"g{i}"))
        if v is not None:
            vals.append(v)
    return vals


def true_l5(r):
    line = num(r.get("line"))
    direction = str(r.get("dir") or "").upper()
    vals = series5(r)
    if line is None or not vals or direction not in ("OVER", "UNDER"):
        hit = num(r.get("l5_over") if direction == "OVER" else r.get("l5_under"))
        return hit, None, vals
    overs = sum(1 for v in vals if v > line)
    unders = sum(1 for v in vals if v < line)
    hit = overs if direction == "OVER" else unders
    avg = sum(vals) / len(vals)
    return hit, avg, vals


def std_note(r):
    stdl = r.get("standard_line")
    if stdl in (None, "", r.get("line")):
        return ""
    return f" (std {stdl})"


rows = [dict(r, _sport="soccer") for r in (d.get("sports") or {}).get("soccer") or [] if isinstance(r, dict)]
print("soccer", len(rows))
print("props", Counter(str(r.get("prop")) for r in rows).most_common(12))
print("picks", Counter(pick_type(r) for r in rows))

cands = []
for r in rows:
    if pick_type(r) == "demon":
        continue
    if "+" in str(r.get("player") or ""):
        continue
    edge = num(r.get("edge"))
    if edge is None:
        continue
    hit, avg, vals = true_l5(r)
    pt = pick_type(r)
    direction = str(r.get("dir") or "").upper()
    line = num(r.get("line"))
    stdl = num(r.get("standard_line"))
    if hit is not None and hit < 3:
        continue
    if avg is not None and line is not None:
        if direction == "OVER" and avg + 0.1 < line and (hit or 0) < 4:
            continue
        if direction == "UNDER" and avg - 0.1 > line and (hit or 0) < 4:
            continue
    if pt == "goblin":
        if direction != "OVER" or (edge or 0) < 0.5:
            continue
        if stdl is not None and line is not None and line >= stdl - 0.01:
            continue
    elif pt in ("standard", "std", ""):
        if abs(edge or 0) < 0.35:
            continue
    else:
        continue
    ml = num(r.get("ml_prob"), 0) or 0
    rank = num(r.get("rank_score"), 0) or 0
    sc = abs(edge or 0) * 1.2 + rank + ml * 2 + ((hit or 0) / 5) * 2
    if avg is not None and line is not None and direction == "OVER" and avg < line:
        sc -= (line - avg) * 1.5
    cands.append((sc, pt, r, hit, avg, vals))

cands.sort(key=lambda x: x[0], reverse=True)


def show(title, want, n=10):
    print(f"\n=== SOCCER {title} ===")
    seen = set()
    c = 0
    for sc, pt, r, hit, avg, vals in cands:
        if want == "standard" and pt not in ("standard", "std", ""):
            continue
        if want == "goblin" and pt != "goblin":
            continue
        key = (str(r.get("player")).lower(), str(r.get("prop")).lower(), str(r.get("dir")).upper())
        if key in seen:
            continue
        seen.add(key)
        ml = num(r.get("ml_prob"))
        sdr = r.get("stat_def_rank") or r.get("opponent_def_rank")
        sdt = r.get("stat_def_tier") or r.get("def_tier")
        avg_s = f" avg {avg:.2f}" if avg is not None else ""
        vals_s = f" {vals}" if vals else ""
        ml_s = f" | ML {ml*100:.0f}%" if ml is not None else ""
        def_s = f" | oppD {sdt or ''}#{sdr}" if sdr is not None else ""
        print(
            f"{c+1}. {r.get('player')} ({r.get('team')} vs {r.get('opp')}) "
            f"{str(r.get('dir')).upper()} {r.get('prop')} {r.get('line')}{std_note(r)}"
            f" | edge {num(r.get('edge')):+.2f}"
            f" | L5 {hit}/5{avg_s}{vals_s}"
            f" | sea {r.get('season_avg')}{ml_s}{def_s}"
            f" | score {sc:.1f}"
        )
        c += 1
        if c >= n:
            break
    if c == 0:
        # show top even if filters tight - debug
        print("(none after filters)")
        # dump a few raw standards
        raw = [r for r in rows if pick_type(r) in ("standard", "std", "") and num(r.get("edge")) is not None]
        raw.sort(key=lambda r: abs(num(r.get("edge"), 0) or 0), reverse=True)
        for r in raw[:5]:
            hit, avg, vals = true_l5(r)
            print(
                " raw:",
                r.get("player"),
                r.get("dir"),
                r.get("prop"),
                r.get("line"),
                "edge",
                r.get("edge"),
                "L5",
                hit,
                "avg",
                avg,
                "sea",
                r.get("season_avg"),
                "series",
                vals,
            )


show("STANDARD", "standard")
show("GOBLIN", "goblin")

print("\n=== MLB ===")
for p in [
    root / "Sports/MLB/step8_mlb_direction.csv",
    root / "ui_runner/templates/slate_sport_mlb.json",
    root / "mobile/www/slate_sport_mlb.json",
]:
    print(p.name, "exists" if p.exists() else "missing", "size", p.stat().st_size if p.exists() else 0)
    if p.suffix == ".json" and p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        src = raw.get("rows") or raw.get("picks") or (raw if isinstance(raw, list) else [])
        print("  rows", len(src) if isinstance(src, list) else type(src))

print("\n=== TENNIS excl Total Games ===")
trows = [dict(r, _sport="tennis") for r in (d.get("sports") or {}).get("tennis") or [] if isinstance(r, dict)]
safer = []
for r in trows:
    prop = str(r.get("prop") or "").lower()
    if prop == "total games":
        continue
    if pick_type(r) == "demon":
        continue
    edge = num(r.get("edge"))
    if edge is None:
        continue
    hit, avg, vals = true_l5(r)
    if hit is not None and hit < 3:
        continue
    pt = pick_type(r)
    direction = str(r.get("dir") or "").upper()
    line = num(r.get("line"))
    stdl = num(r.get("standard_line"))
    if pt == "goblin":
        if direction != "OVER" or (edge or 0) < 0.8:
            continue
        if stdl is not None and line is not None and line >= stdl - 0.01:
            continue
    elif pt in ("standard", "std", ""):
        if abs(edge or 0) < 0.7:
            continue
    else:
        continue
    if avg is not None and line is not None and direction == "OVER" and avg + 0.2 < line and (hit or 0) < 4:
        continue
    ml = num(r.get("ml_prob"), 0) or 0
    sc = abs(edge or 0) * 1.2 + (num(r.get("rank_score"), 0) or 0) + ml * 2 + ((hit or 0) / 5) * 2
    safer.append((sc, pt, r, hit, avg, vals))
safer.sort(key=lambda x: x[0], reverse=True)

for want in ("standard", "goblin"):
    print(f"\n-- tennis {want} --")
    seen = set()
    c = 0
    for sc, pt, r, hit, avg, vals in safer:
        if want == "standard" and pt not in ("standard", "std", ""):
            continue
        if want == "goblin" and pt != "goblin":
            continue
        key = (str(r.get("player")).lower(), str(r.get("prop")).lower(), str(r.get("dir")).upper())
        if key in seen:
            continue
        seen.add(key)
        avg_s = f" avg {avg:.1f}" if avg is not None else ""
        vals_s = f" {vals}" if vals else ""
        print(
            f"{c+1}. {r.get('player')} vs {r.get('opp')} "
            f"{str(r.get('dir')).upper()} {r.get('prop')} {r.get('line')}{std_note(r)}"
            f" | edge {num(r.get('edge')):+.2f} | L5 {hit}/5{avg_s}{vals_s} | sea {r.get('season_avg')}"
        )
        c += 1
        if c >= 8:
            break
    if c == 0:
        print("(none)")
