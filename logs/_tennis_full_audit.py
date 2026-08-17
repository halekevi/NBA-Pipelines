"""Full tennis slate audit: validate L5 vs actual series, rank playable STD/Goblin."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

root = Path(r"H:/halek/ProfileFromC/Desktop/PropORACLE_main_cp")
d = json.loads((root / "ui_runner" / "templates" / "slate_latest.json").read_text(encoding="utf-8"))
rows = [dict(r) for r in (d.get("sports") or {}).get("tennis") or [] if isinstance(r, dict)]
print("TENNIS BOARD", d.get("date"), d.get("generated_at"), "rows", len(rows))


def num(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def pick_type(r):
    return str(r.get("pick_type") or r.get("pick") or "").strip().lower()


def direction(r):
    return str(r.get("dir") or r.get("direction") or "").strip().upper()


def series_all(r):
    out = []
    if isinstance(r.get("actual_series"), list):
        for x in r["actual_series"]:
            v = num(x)
            if v is not None:
                out.append(v)
    if out:
        return out
    for i in range(1, 11):
        v = num(r.get(f"stat_g{i}") or r.get(f"g{i}"))
        if v is not None:
            out.append(v)
    return out


def l5_vs_line(vals, line, direc):
    if not vals or line is None or direc not in ("OVER", "UNDER"):
        return None, None, None, None
    five = vals[:5]
    overs = sum(1 for v in five if v > line)
    unders = sum(1 for v in five if v < line)
    pushes = sum(1 for v in five if v == line)
    hit = overs if direc == "OVER" else unders
    avg = sum(five) / len(five)
    return hit, overs, unders, avg


def prop_key(r):
    return str(r.get("prop") or "").strip()


# Overview
print("\n=== BOARD MIX ===")
print("pick_type", Counter(pick_type(r) for r in rows))
print("dir", Counter(direction(r) for r in rows))
print("props", Counter(prop_key(r) for r in rows).most_common())
print("players", len({str(r.get("player") or "").lower() for r in rows}))

# Data quality flags
print("\n=== DATA QUALITY ===")
no_series = 0
mismatch = 0
wrong_side = 0
examples_mismatch = []
examples_wrong = []
for r in rows:
    if pick_type(r) == "demon":
        continue
    vals = series_all(r)
    line = num(r.get("line"))
    direc = direction(r)
    if not vals:
        no_series += 1
        continue
    hit, overs, unders, avg = l5_vs_line(vals, line, direc)
    stored = num(r.get("l5_over") if direc == "OVER" else r.get("l5_under"))
    if hit is not None and stored is not None and abs(stored - hit) >= 1:
        mismatch += 1
        if len(examples_mismatch) < 12:
            examples_mismatch.append(
                (
                    r.get("player"),
                    prop_key(r),
                    direc,
                    r.get("line"),
                    stored,
                    hit,
                    vals[:5],
                    avg,
                    pick_type(r),
                )
            )
    if avg is not None and line is not None:
        if direc == "OVER" and avg + 0.05 < line:
            wrong_side += 1
            if len(examples_wrong) < 8:
                examples_wrong.append((r.get("player"), prop_key(r), direc, line, avg, vals[:5], pick_type(r), r.get("edge")))
        if direc == "UNDER" and avg - 0.05 > line:
            wrong_side += 1

print("non-demon rows missing series:", no_series)
print("L5 stored vs recomputed mismatch (|d|>=1):", mismatch)
print("direction wrong-side of L5 avg:", wrong_side)
print("\nMismatch examples (slate L5 vs true L5):")
for e in examples_mismatch:
    print(" ", e)
print("\nWrong-side avg examples:")
for e in examples_wrong:
    print(" ", e)

# Build validated candidate list
cands = []
for r in rows:
    pt = pick_type(r)
    if pt == "demon":
        continue
    if "+" in str(r.get("player") or ""):
        continue
    edge = num(r.get("edge"))
    if edge is None:
        continue
    vals = series_all(r)
    line = num(r.get("line"))
    direc = direction(r)
    hit, overs, unders, avg = l5_vs_line(vals, line, direc)
    stored = num(r.get("l5_over") if direc == "OVER" else r.get("l5_under"))
    stdl = num(r.get("standard_line"))
    sea = num(r.get("season_avg"))
    proj = num(r.get("projection"))
    ml = num(r.get("ml_prob"))
    prop = prop_key(r)

    flags = []
    if not vals:
        flags.append("NO_SERIES")
    if hit is not None and stored is not None and abs(stored - hit) >= 1:
        flags.append(f"L5_MISMATCH(slate={stored},true={hit})")
    if avg is not None and line is not None:
        if direc == "OVER" and avg < line:
            flags.append("AVG_UNDER_LINE")
        if direc == "UNDER" and avg > line:
            flags.append("AVG_OVER_LINE")
    if prop.lower() == "total games":
        flags.append("TOTAL_GAMES_UNTRUSTED")  # known bad logs vs UI chart

    # playable gates using TRUE L5
    playable = True
    if hit is None:
        playable = False
        flags.append("NO_TRUE_L5")
    elif hit < 3:
        playable = False
    if avg is not None and line is not None:
        if direc == "OVER" and avg + 0.25 < line:
            playable = False
        if direc == "UNDER" and avg - 0.25 > line:
            playable = False
    if "TOTAL_GAMES_UNTRUSTED" in flags:
        playable = False
    if pt == "goblin":
        if direc != "OVER" or (edge or 0) < 0.8:
            playable = False
        if stdl is not None and line is not None and line >= stdl - 0.01:
            playable = False
            flags.append("GOBLIN_GE_STD")
    elif pt in ("standard", "std", ""):
        if abs(edge or 0) < 0.7:
            playable = False
    else:
        playable = False

    # score from true metrics
    sc = 0.0
    if hit is not None:
        sc += (hit / 5.0) * 3.0
    sc += abs(edge or 0) * 1.0
    if ml:
        sc += ml * 1.5
    sc += (num(r.get("rank_score"), 0) or 0) * 0.5
    if avg is not None and line is not None and direc == "OVER":
        sc += max(0.0, avg - line) * 0.8
    if avg is not None and line is not None and direc == "UNDER":
        sc += max(0.0, line - avg) * 0.8
    if flags:
        sc -= 1.5 * len([f for f in flags if f.startswith("L5_MISMATCH") or f == "AVG_UNDER_LINE" or f == "AVG_OVER_LINE"])

    cands.append(
        {
            "playable": playable,
            "score": sc,
            "pt": pt,
            "player": r.get("player"),
            "opp": r.get("opp"),
            "prop": prop,
            "dir": direc,
            "line": line,
            "std": stdl,
            "edge": edge,
            "hit": hit,
            "avg": avg,
            "vals": vals[:5],
            "sea": sea,
            "proj": proj,
            "ml": ml,
            "flags": flags,
            "start": r.get("game_time") or r.get("start_time") or r.get("game_date"),
        }
    )

play = [c for c in cands if c["playable"]]
play_std = sorted([c for c in play if c["pt"] in ("standard", "std", "")], key=lambda x: x["score"], reverse=True)
play_gob = sorted([c for c in play if c["pt"] == "goblin"], key=lambda x: x["score"], reverse=True)
bad = [c for c in cands if c["flags"] and c["pt"] in ("standard", "goblin", "std", "")]

print("\n=== PLAYABLE COUNTS ===")
print("playable std", len(play_std), "gob", len(play_gob), "flagged non-demon", len(bad))


def dump(title, items, n=15):
    print(f"\n######## {title} ########")
    seen = set()
    c = 0
    for x in items:
        key = (str(x["player"]).lower(), str(x["prop"]).lower(), x["dir"])
        if key in seen:
            continue
        seen.add(key)
        std_s = f" (std {x['std']})" if x["std"] not in (None, x["line"]) else ""
        ml_s = f" ML {x['ml']*100:.0f}%" if x["ml"] is not None else ""
        avg_s = f" L5avg {x['avg']:.1f}" if x["avg"] is not None else ""
        print(
            f"{c+1:2}. {x['player']} vs {x['opp']} — {x['dir']} {x['prop']} {x['line']}{std_s}"
            f" | edge {x['edge']:+.2f} | trueL5 {x['hit']}/5{avg_s} {x['vals']}"
            f" | sea {x['sea']} proj {x['proj']}{ml_s} | score {x['score']:.1f}"
        )
        c += 1
        if c >= n:
            break
    if c == 0:
        print("(none)")


dump("STANDARD — CHART-VALIDATED", play_std)
dump("GOBLIN — CHART-VALIDATED", play_gob)

# By prop breakdown of playable
print("\n=== PLAYABLE BY PROP ===")
print("std", Counter(x["prop"] for x in play_std))
print("gob", Counter(x["prop"] for x in play_gob))

# Top flagged traps (high edge but fail validation)
print("\n######## TRAPS / DO NOT PLAY (high |edge| but failed validation) ########")
traps = sorted(
    [c for c in cands if c["pt"] in ("standard", "goblin", "std", "") and abs(c["edge"] or 0) >= 2 and not c["playable"]],
    key=lambda x: abs(x["edge"] or 0),
    reverse=True,
)
seen = set()
c = 0
for x in traps:
    key = (str(x["player"]).lower(), str(x["prop"]).lower(), x["dir"], x["line"])
    if key in seen:
        continue
    seen.add(key)
    print(
        f" X {x['player']} {x['dir']} {x['prop']} {x['line']} edge {x['edge']:+.2f}"
        f" trueL5 {x['hit']}/5 avg {x['avg']} vals {x['vals']} flags {x['flags']}"
    )
    c += 1
    if c >= 20:
        break

# Match list
print("\n=== MATCHUPS ON BOARD ===")
matches = sorted({(str(r.get("player") or ""), str(r.get("opp") or "")) for r in rows})
# collapse to unique unordered pairs roughly
pairs = set()
for a, b in matches:
    if not a or not b:
        continue
    key = tuple(sorted([a.upper(), b.upper()]))
    pairs.add(key)
for p in sorted(pairs):
    print(" -", " vs ".join(p))
