import json
from collections import Counter
from pathlib import Path

root = Path(r"H:/halek/ProfileFromC/Desktop/PropORACLE_main_cp")
d = json.loads((root / "ui_runner" / "templates" / "slate_latest.json").read_text(encoding="utf-8"))
print("date", d.get("date"), "gen", d.get("generated_at"))

rows = []
for sport, lst in (d.get("sports") or {}).items():
    if not isinstance(lst, list):
        continue
    for r in lst:
        if not isinstance(r, dict):
            continue
        r = dict(r)
        r["_sport"] = sport
        rows.append(r)


def num(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def is_goblin(r):
    return str(r.get("pick_type") or r.get("pick") or "").strip().lower() == "goblin"


def is_standard(r):
    return str(r.get("pick_type") or r.get("pick") or "").strip().lower() in ("standard", "std", "")


def is_demon(r):
    return str(r.get("pick_type") or "").strip().lower() == "demon"


clean = []
for r in rows:
    player = str(r.get("player") or "")
    prop = str(r.get("prop") or "").lower()
    if "+" in player or "fantasy" in prop:
        continue
    if is_demon(r):
        continue
    if num(r.get("edge")) is None:
        continue
    clean.append(r)

print(
    "clean",
    len(clean),
    "goblin",
    sum(1 for r in clean if is_goblin(r)),
    "std",
    sum(1 for r in clean if is_standard(r)),
)


def score(r):
    edge = abs(num(r.get("edge"), 0) or 0)
    rank = num(r.get("rank_score"), 0) or 0
    ml = num(r.get("ml_prob"), 0) or 0
    direction = str(r.get("dir") or r.get("direction") or "").upper()
    hit = None
    if direction == "OVER":
        hit = num(r.get("l5_over"))
    elif direction == "UNDER":
        hit = num(r.get("l5_under"))
    hit_s = (hit or 0) / 5.0 if hit is not None else 0
    return edge * 1.5 + rank * 0.8 + ml * 2.0 + hit_s * 1.2, edge, rank, ml, hit


def fmt(r, sc):
    sdr = r.get("stat_def_rank") or r.get("opponent_def_rank")
    sdt = r.get("stat_def_tier") or r.get("def_tier")
    lr, tr = r.get("league_rank"), r.get("rank_on_team")
    cr = r.get("category_rank_label")
    ml = num(r.get("ml_prob"))
    edge = num(r.get("edge"))
    rank = num(r.get("rank_score"))
    return {
        "sport": r.get("_sport") or r.get("sport"),
        "player": r.get("player"),
        "team": r.get("team"),
        "opp": r.get("opp"),
        "prop": r.get("prop"),
        "dir": str(r.get("dir") or "").upper(),
        "line": r.get("line"),
        "std_line": r.get("standard_line"),
        "pick": r.get("pick_type") or r.get("pick"),
        "edge": round(edge, 2) if edge is not None else None,
        "rank": round(rank, 2) if rank is not None else None,
        "ml": round(ml * 100, 1) if ml is not None else None,
        "season_avg": r.get("season_avg"),
        "l5_over": r.get("l5_over"),
        "l5_under": r.get("l5_under"),
        "opp_def": f"{sdt or ''} #{sdr}".strip() if (sdr is not None or sdt) else None,
        "cat_rank": cr or (f"L#{lr} T{tr}" if lr or tr else None),
        "score": round(sc[0], 2),
    }


goblins = []
for r in clean:
    if not is_goblin(r):
        continue
    edge = num(r.get("edge"), 0) or 0
    line = num(r.get("line"))
    std = num(r.get("standard_line"))
    if std is not None and line is not None and line >= std:
        continue
    direction = str(r.get("dir") or "").upper()
    if direction == "OVER" and edge <= 0:
        continue
    goblins.append((score(r), r))
goblins.sort(key=lambda x: x[0][0], reverse=True)

standards = []
for r in clean:
    if not is_standard(r):
        continue
    if abs(num(r.get("edge"), 0) or 0) < 0.5:
        continue
    standards.append((score(r), r))
standards.sort(key=lambda x: x[0][0], reverse=True)

print("\n=== TOP STANDARD ===")
seen = set()
n = 0
for sc, r in standards:
    key = (
        str(r.get("player")).lower(),
        str(r.get("prop")).lower(),
        str(r.get("dir")).upper(),
        str(r.get("line")),
    )
    if key in seen:
        continue
    seen.add(key)
    print(fmt(r, sc))
    n += 1
    if n >= 12:
        break

print("\n=== TOP GOBLIN ===")
seen = set()
n = 0
for sc, r in goblins:
    key = (str(r.get("player")).lower(), str(r.get("prop")).lower(), str(r.get("line")))
    if key in seen:
        continue
    seen.add(key)
    print(fmt(r, sc))
    n += 1
    if n >= 12:
        break

print("\nsports", Counter(r["_sport"] for r in clean))
print("std by sport", Counter(r["_sport"] for r in clean if is_standard(r)))
print("gob by sport", Counter(r["_sport"] for r in clean if is_goblin(r)))
