import json
from pathlib import Path

root = Path(r"H:/halek/ProfileFromC/Desktop/PropORACLE_main_cp")
d = json.loads((root / "ui_runner" / "templates" / "slate_latest.json").read_text(encoding="utf-8"))
print("date", d.get("date"), "gen", d.get("generated_at"))

rows = []
for sport, lst in (d.get("sports") or {}).items():
    if not isinstance(lst, list):
        continue
    for r in lst:
        if isinstance(r, dict):
            rr = dict(r)
            rr["_sport"] = sport
            rows.append(rr)


def num(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def pick_type(r):
    return str(r.get("pick_type") or r.get("pick") or "").strip().lower()


clean = []
for r in rows:
    player = str(r.get("player") or "")
    prop = str(r.get("prop") or "").lower()
    if not player or "+" in player or "fantasy" in prop:
        continue
    if pick_type(r) == "demon":
        continue
    edge = num(r.get("edge"))
    if edge is None:
        continue
    sea = num(r.get("season_avg"))
    proj = num(r.get("projection"))
    line = num(r.get("line"))
    # Drop broken rows: no season avg and edge ~= +/- line (proj~0)
    if sea is None and proj is None:
        continue
    if sea is None and line is not None and abs(abs(edge) - abs(line)) < 0.05:
        continue
    if sea is not None and sea <= 0 and abs(edge) > 5:
        continue
    clean.append(r)


def l5_for_dir(r):
    direction = str(r.get("dir") or "").upper()
    if direction == "OVER":
        return num(r.get("l5_over"))
    if direction == "UNDER":
        return num(r.get("l5_under"))
    return None


def score(r):
    edge = abs(num(r.get("edge"), 0) or 0)
    rank = num(r.get("rank_score"), 0) or 0
    ml = num(r.get("ml_prob"), 0) or 0
    hit = l5_for_dir(r)
    hit_s = (hit / 5.0) if hit is not None else 0.0
    # Prefer proven L5 + edge + ML
    return edge * 1.2 + rank * 1.0 + ml * 2.5 + hit_s * 2.0, edge, rank, ml, hit


def show(r, sc):
    sdr = r.get("stat_def_rank") or r.get("opponent_def_rank")
    sdt = r.get("stat_def_tier") or r.get("def_tier")
    ml = num(r.get("ml_prob"))
    return (
        f"{str(r.get('_sport')).upper():6} | {r.get('player')}"
        f" ({r.get('team')} vs {r.get('opp')}) | "
        f"{str(r.get('dir')).upper()} {r.get('prop')} {r.get('line')}"
        f" | edge {num(r.get('edge')):+.2f} | L5 {l5_for_dir(r)}/5"
        f" | avg {r.get('season_avg')} | ML {ml*100:.0f}%" if ml else ""
        f" | def {sdt or ''}#{sdr}" if sdr is not None else ""
        f" | rank {num(r.get('rank_score')):.2f}"
    )


# STANDARD
std = []
for r in clean:
    if pick_type(r) not in ("standard", "std", ""):
        continue
    if abs(num(r.get("edge"), 0) or 0) < 0.8:
        continue
    # Require some L5 signal when available, else keep strong edge+ml
    hit = l5_for_dir(r)
    ml = num(r.get("ml_prob"), 0) or 0
    if hit is not None and hit < 3 and abs(num(r.get("edge"), 0) or 0) < 3:
        continue
    if ml and ml < 0.45 and hit is not None and hit < 4:
        continue
    std.append((score(r), r))
std.sort(key=lambda x: x[0][0], reverse=True)

# GOBLIN — real goblins only (line < standard), OVER, positive edge
gob = []
for r in clean:
    if pick_type(r) != "goblin":
        continue
    line = num(r.get("line"))
    stdl = num(r.get("standard_line"))
    edge = num(r.get("edge"), 0) or 0
    direction = str(r.get("dir") or "").upper()
    if stdl is not None and line is not None and line >= stdl - 0.01:
        continue  # mislabeled hard line
    if direction != "OVER":
        continue
    if edge < 1.0:
        continue
    hit = l5_for_dir(r)
    if hit is not None and hit < 3:
        continue
    gob.append((score(r), r))
gob.sort(key=lambda x: x[0][0], reverse=True)


def print_top(title, items, n=10):
    print(f"\n=== {title} ===")
    seen = set()
    count = 0
    for sc, r in items:
        # dedupe player+prop (keep best line)
        key = (str(r.get("player")).lower(), str(r.get("prop")).lower(), str(r.get("dir")).upper())
        if key in seen:
            continue
        seen.add(key)
        edge = num(r.get("edge"))
        ml = num(r.get("ml_prob"))
        sdr = r.get("stat_def_rank") or r.get("opponent_def_rank")
        sdt = r.get("stat_def_tier") or r.get("def_tier")
        stdl = r.get("standard_line")
        print(
            f"{count+1:2}. [{str(r.get('_sport')).upper()}] {r.get('player')} "
            f"({r.get('team')} vs {r.get('opp')}) — "
            f"{str(r.get('dir')).upper()} {r.get('prop')} {r.get('line')}"
            + (f" (std {stdl})" if stdl not in (None, r.get("line")) else "")
            + f" | edge {edge:+.2f} | L5 {l5_for_dir(r)}/5 | avg {r.get('season_avg')}"
            + (f" | ML {ml*100:.0f}%" if ml else "")
            + (f" | oppD {sdt or ''} #{sdr}" if sdr is not None else "")
            + f" | score {sc[0]:.1f}"
        )
        count += 1
        if count >= n:
            break


print_top("BEST STANDARD (playable)", std, 12)
print_top("BEST GOBLIN (playable)", gob, 12)

# Split std overs / unders briefly
print("\n--- Standard OVER only ---")
overs = [(sc, r) for sc, r in std if str(r.get("dir")).upper() == "OVER"]
print_top("STD OVERS", overs, 6)
print("\n--- Standard UNDER only ---")
unders = [(sc, r) for sc, r in std if str(r.get("dir")).upper() == "UNDER"]
print_top("STD UNDERS", unders, 6)

# tickets hot legs if present
tp = root / "ui_runner" / "templates" / "tickets_latest.json"
td = json.loads(tp.read_text(encoding="utf-8"))
print("\ntickets date", td.get("date"), "gen", td.get("generated_at"))
hot = td.get("hot_legs") or []
print("hot_legs", len(hot) if isinstance(hot, list) else type(hot))
if isinstance(hot, list):
    for i, leg in enumerate(hot[:8], 1):
        if not isinstance(leg, dict):
            continue
        print(
            f" HOT{i}. [{leg.get('sport')}] {leg.get('player')} "
            f"{leg.get('dir')} {leg.get('prop')} {leg.get('line')} "
            f"pick={leg.get('pick_type') or leg.get('pick')} edge={leg.get('edge')} "
            f"ml={leg.get('ml_prob')}"
        )
