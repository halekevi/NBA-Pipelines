#!/usr/bin/env python3
"""Post-verify MLB L5 after full refresh."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Sports/MLB/scripts"))
sys.path.insert(0, str(ROOT))
import step4_attach_player_stats_mlb as step4  # noqa: E402

raw = json.loads((ROOT / "ui_runner/templates/slate_latest.json").read_text(encoding="utf-8"))
mlb = raw["sports"]["mlb"]
print("slate", raw.get("date"), "rows", len(mlb))

# 1) series-internal L5 consistency
drift = 0
checked = 0
drift_ex = []
for r in mlb:
    series = r.get("actual_series") or []
    if len(series) < 5:
        continue
    if str(r.get("pick_type") or "").lower() not in ("standard", "goblin"):
        continue
    try:
        line = float(r.get("line"))
        stored = int(float(r.get("l5_over")))
    except Exception:
        continue
    truth = sum(1 for v in series[:5] if float(v) > line)
    checked += 1
    if truth != stored:
        drift += 1
        if len(drift_ex) < 12:
            drift_ex.append(
                (r.get("player"), r.get("pick_type"), r.get("prop"), line, stored, truth, series[:5])
            )
print(f"L5 series-consistency: {checked - drift}/{checked} ({100 * (checked - drift) / checked if checked else 0:.1f}%)")
for x in drift_ex:
    print("  DRIFT", x)

# 2) Aug 1 graded most-recent match
gdf = pd.read_excel(ROOT / "outputs/2026-08-01/graded_mlb_2026-08-01.xlsx", sheet_name="Box Raw", header=0)
gdf = gdf[gdf["result"].astype(str).str.upper().isin(["HIT", "MISS"])]
gdf = gdf[gdf["bet_direction"].astype(str).str.upper() == "OVER"]
gdf = gdf[gdf["pick_type"].astype(str).str.lower().isin(["standard", "goblin"])]

idx = defaultdict(list)
for r in mlb:
    idx[(str(r.get("player")), str(r.get("pick_type")).lower(), str(r.get("prop")).lower())].append(r)

checks = ok = 0
bad = []
for _, gr in gdf.iterrows():
    player = str(gr["player"])
    pick = str(gr["pick_type"]).lower()
    prop = str(gr["prop_type_norm"])
    try:
        line = float(gr["line"])
        actual = float(gr["actual"])
    except Exception:
        continue
    cands = idx.get((player, pick, prop.lower()), [])
    if not cands:
        for (pl, pk, pr), rows in idx.items():
            if pl == player and pk == pick and (prop.lower() in pr or pr in prop.lower() or prop.lower().replace("+", "") in pr.replace("+", "")):
                cands = rows
                break
    match = None
    for r in cands:
        try:
            if abs(float(r.get("line")) - line) < 1e-6:
                match = r
                break
        except Exception:
            pass
    if not match:
        continue
    series = match.get("actual_series") or []
    if not series:
        continue
    checks += 1
    recent = float(series[0])
    if abs(recent - actual) < 1e-6:
        ok += 1
    else:
        bad.append((player, pick, prop, line, actual, recent, match.get("l5_over")))
    if checks >= 600:
        break
print(f"Aug1 series[0] vs graded actual: {ok}/{checks} ({100 * ok / checks if checks else 0:.1f}%)")
for b in bad[:20]:
    print("  BAD", b)

# 3) stale audit
ids = pd.read_csv(ROOT / "Sports/MLB/mlb_id_cache.csv")
name_to_id = {str(r["player_norm"]).strip().lower(): str(r["mlb_player_id"]).strip() for _, r in ids.iterrows()}
cache = step4.load_cache(ROOT / "Sports/MLB/mlb_stats_cache.csv")
stale_before = pd.Timestamp("2026-08-01")
players = {}
pitcher_like = set()
for r in mlb:
    pid = name_to_id.get(str(r.get("player") or "").lower())
    if not pid:
        continue
    players[pid] = str(r.get("player"))
    prop = str(r.get("prop") or "").lower()
    if any(x in prop for x in ("pitcher", "earned runs", "hits allowed", "walks allowed", "pitching", "innings", "pitches thrown", "batters faced")):
        pitcher_like.add(pid)

still_h = []
still_p = []
for pid, name in players.items():
    md = step4.player_cache_max_date(cache, pid, "2026")
    if md is None or pd.Timestamp(md).normalize() < stale_before:
        row = (name, pid, str(md)[:10] if md is not None else None)
        (still_p if pid in pitcher_like else still_h).append(row)
print(f"max_date < Aug1 hitters={len(still_h)} pitchers/pitcher-props={len(still_p)}")
print("hitter sample", still_h[:20])
print("pitcher sample", still_p[:20])

# 4) elite standards remaining
elite_std = []
for r in mlb:
    if str(r.get("pick_type")).lower() != "standard":
        continue
    if str(r.get("dir")).upper() != "OVER":
        continue
    try:
        if float(r.get("edge") or 0) <= 0:
            continue
        if int(float(r.get("l5_over") or 0)) < 5:
            continue
        if int(float(r.get("l10_over") or 0)) < 8:
            continue
    except Exception:
        continue
    elite_std.append(r)
print(f"Elite Standards L5=5 L10>=8 edge>0: {len(elite_std)}")
for r in sorted(elite_std, key=lambda x: -float(x.get("edge") or 0))[:20]:
    print(
        " ",
        r.get("player"),
        f"O{r.get('line')}",
        r.get("prop"),
        f"L5 {r.get('l5_over')} L10 {r.get('l10_over')} edge {r.get('edge')} series {r.get('actual_series')[:5]}",
    )

# 5) trio
print("TRIO")
for name in ["James Wood", "Brayan Rocchio", "Jordan Walker"]:
    for r in mlb:
        if r.get("player") != name:
            continue
        if str(r.get("prop")) not in ("Hits+Runs+RBIs", "Runs", "Hits"):
            continue
        if str(r.get("pick_type") or "").lower() not in ("standard", "goblin"):
            continue
        print(
            f"  {name} {r.get('pick_type')} O{r.get('line')} {r.get('prop')} "
            f"L5 {r.get('l5_over')}/5 L10 {r.get('l10_over')}/10 series={r.get('actual_series')[:5]}"
        )

out = {
    "l5_consistency_pct": 100 * (checked - drift) / checked if checked else None,
    "aug1_series0_match": f"{ok}/{checks}",
    "still_stale_hitters": still_h,
    "still_stale_pitchers": still_p[:40],
    "elite_std_count": len(elite_std),
}
(ROOT / "logs/_mlb_l5_postverify.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print("wrote logs/_mlb_l5_postverify.json")
