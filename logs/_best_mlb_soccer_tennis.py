import json
from pathlib import Path

root = Path(r"H:/halek/ProfileFromC/Desktop/PropORACLE_main_cp")
d = json.loads((root / "ui_runner" / "templates" / "slate_latest.json").read_text(encoding="utf-8"))
print("date", d.get("date"), "gen", d.get("generated_at"))
sports = d.get("sports") or {}
for sk in ("mlb", "soccer", "tennis"):
    lst = sports.get(sk) or []
    print(sk, "rows", len(lst) if isinstance(lst, list) else 0)

# Also check sport-specific slate files
for sk in ("mlb", "soccer", "tennis"):
    p = root / "ui_runner" / "templates" / f"slate_sport_{sk}.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        rows = raw.get("rows") or raw.get("picks") or (raw if isinstance(raw, list) else [])
        print(f"slate_sport_{sk}", len(rows) if isinstance(rows, list) else type(rows), "mtime", p.stat().st_mtime)


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
    """Recompute L5 hit vs THIS line from series when possible."""
    line = num(r.get("line"))
    direction = str(r.get("dir") or "").upper()
    vals = series5(r)
    if line is None or not vals or direction not in ("OVER", "UNDER"):
        # fall back to stored
        if direction == "OVER":
            return num(r.get("l5_over")), num(r.get("l5_under")), None, vals
        return num(r.get("l5_under")), num(r.get("l5_over")), None, vals
    overs = sum(1 for v in vals if v > line)
    unders = sum(1 for v in vals if v < line)
    # pushes ignored for hit count toward direction
    hit = overs if direction == "OVER" else unders
    avg = sum(vals) / len(vals)
    return hit, (unders if direction == "OVER" else overs), avg, vals


def load_sport(sk):
    rows = []
    lst = sports.get(sk) or []
    if isinstance(lst, list) and lst:
        for r in lst:
            if isinstance(r, dict):
                rr = dict(r)
                rr["_sport"] = sk
                rows.append(rr)
        return rows
    p = root / "ui_runner" / "templates" / f"slate_sport_{sk}.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        src = raw.get("rows") or raw.get("picks") or (raw if isinstance(raw, list) else [])
        for r in src:
            if isinstance(r, dict):
                rr = dict(r)
                rr["_sport"] = sk
                rows.append(rr)
    return rows


def usable(r):
    player = str(r.get("player") or "")
    prop = str(r.get("prop") or "").lower()
    if not player or "+" in player or "fantasy" in prop:
        return False
    if pick_type(r) == "demon":
        return False
    edge = num(r.get("edge"))
    if edge is None:
        return False
    sea = num(r.get("season_avg"))
    proj = num(r.get("projection"))
    line = num(r.get("line"))
    if sea is None and proj is None:
        return False
    if sea is None and line is not None and abs(abs(edge) - abs(line)) < 0.05:
        return False
    return True


def score(r, hit, avg):
    edge = abs(num(r.get("edge"), 0) or 0)
    rank = num(r.get("rank_score"), 0) or 0
    ml = num(r.get("ml_prob"), 0) or 0
    hit_s = (hit / 5.0) if hit is not None else 0.0
    # Penalize if avg is on wrong side of line for the direction
    line = num(r.get("line"))
    direction = str(r.get("dir") or "").upper()
    side_pen = 0.0
    if avg is not None and line is not None:
        if direction == "OVER" and avg < line:
            side_pen = (line - avg) * 1.5
        if direction == "UNDER" and avg > line:
            side_pen = (avg - line) * 1.5
    return edge * 1.1 + rank * 1.0 + ml * 2.2 + hit_s * 2.5 - side_pen


def rank_sport(sk, rows):
    print(f"\n######## {sk.upper()} ({len(rows)} rows) ########")
    clean = [r for r in rows if usable(r)]
    print("usable", len(clean), "std", sum(1 for r in clean if pick_type(r) in ("standard", "std", "")), "gob", sum(1 for r in clean if pick_type(r) == "goblin"))

    std_items = []
    gob_items = []
    for r in clean:
        hit, miss, avg, vals = true_l5(r)
        edge = num(r.get("edge"), 0) or 0
        pt = pick_type(r)
        direction = str(r.get("dir") or "").upper()
        line = num(r.get("line"))
        stdl = num(r.get("standard_line"))

        # Require L5 >= 3 when we have series; drop wrong-side avg for overs/unders with weak hit
        if hit is not None and hit < 3:
            continue
        if avg is not None and line is not None:
            if direction == "OVER" and avg + 0.25 < line and hit < 4:
                continue
            if direction == "UNDER" and avg - 0.25 > line and hit < 4:
                continue

        sc = score(r, hit, avg)
        pack = (sc, r, hit, avg, vals)

        if pt in ("standard", "std", ""):
            if abs(edge) < 0.7:
                continue
            std_items.append(pack)
        elif pt == "goblin":
            if direction != "OVER" or edge < 1.0:
                continue
            if stdl is not None and line is not None and line >= stdl - 0.01:
                continue
            gob_items.append(pack)

    std_items.sort(key=lambda x: x[0], reverse=True)
    gob_items.sort(key=lambda x: x[0], reverse=True)

    def dump(title, items, n=8):
        print(f"\n--- {title} ---")
        if not items:
            print("  (none)")
            return
        seen = set()
        c = 0
        for sc, r, hit, avg, vals in items:
            key = (str(r.get("player")).lower(), str(r.get("prop")).lower(), str(r.get("dir")).upper())
            if key in seen:
                continue
            seen.add(key)
            ml = num(r.get("ml_prob"))
            sdr = r.get("stat_def_rank") or r.get("opponent_def_rank")
            sdt = r.get("stat_def_tier") or r.get("def_tier")
            stdl = r.get("standard_line")
            stored_l5 = r.get("l5_over") if str(r.get("dir")).upper() == "OVER" else r.get("l5_under")
            warn = ""
            if hit is not None and stored_l5 is not None and abs(float(stored_l5) - float(hit)) >= 1:
                warn = f" [slateL5={stored_l5}≠true {hit}]"
            print(
                f" {c+1}. {r.get('player')} ({r.get('team')} vs {r.get('opp')}) — "
                f"{str(r.get('dir')).upper()} {r.get('prop')} {r.get('line')}"
                + (f" (std {stdl})" if stdl not in (None, "", r.get("line")) else "")
                + f" | edge {num(r.get('edge')):+.2f}"
                + f" | trueL5 {hit}/5 avg {avg:.1f}" if avg is not None else f" | trueL5 {hit}/5"
                + (f" | series {vals}" if vals else "")
                + (f" | ML {ml*100:.0f}%" if ml else "")
                + (f" | oppD {sdt or ''}#{sdr}" if sdr is not None else "")
                + f" | sea {r.get('season_avg')}"
                + warn
            )
            c += 1
            if c >= n:
                break

    dump("STANDARD", std_items)
    dump("GOBLIN", gob_items)


for sk in ("mlb", "soccer", "tennis"):
    rank_sport(sk, load_sport(sk))
