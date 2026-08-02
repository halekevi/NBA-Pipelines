#!/usr/bin/env python3
"""Force-refresh remaining stale MLB hitters (deep pull) then re-patch slate."""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Sports/MLB/scripts"))
sys.path.insert(0, str(ROOT))
import step4_attach_player_stats_mlb as step4  # noqa: E402

PROP_MAP = {
    "hits": "hits", "total bases": "total_bases", "home runs": "home_runs", "rbis": "rbi", "rbi": "rbi",
    "runs": "runs", "walks": "walks", "stolen bases": "stolen_bases", "fantasy score": "fantasy_score",
    "hits+runs+rbis": "hits_runs_rbi", "singles": "singles", "doubles": "doubles", "triples": "triples",
    "hitter strikeouts": "hitter_strikeouts", "plate appearances": "plate_appearances",
    "pitcher strikeouts": "strikeouts", "pitching outs": "pitching_outs", "innings pitched": "innings_pitched",
    "hits allowed": "hits_allowed", "earned runs": "earned_runs", "earned runs allowed": "earned_runs",
    "walks allowed": "walks_allowed", "batters faced": "batters_faced", "pitches thrown": "pitches_thrown",
}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s\.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


cache_path = ROOT / "Sports/MLB/mlb_stats_cache.csv"
scripts_cache = ROOT / "Sports/MLB/scripts/mlb_stats_cache.csv"
cache = step4.load_cache(cache_path)
ids = pd.read_csv(ROOT / "Sports/MLB/mlb_id_cache.csv")
name_to_id: dict[str, str] = {}
for _, r in ids.iterrows():
    pid = str(r["mlb_player_id"]).strip()
    name_to_id[fold(r["player_norm"])] = pid
    name_to_id[str(r["player_norm"]).strip().lower()] = pid
# known missing from id cache
name_to_id.setdefault("bryan de la cruz", "650559")

raw = json.loads((ROOT / "ui_runner/templates/slate_latest.json").read_text(encoding="utf-8"))
mlb = raw["sports"]["mlb"]
season = "2026"
stale_before = pd.Timestamp("2026-08-01")

pitcher_props = {
    "pitcher strikeouts", "pitching outs", "innings pitched", "hits allowed",
    "earned runs", "earned runs allowed", "walks allowed", "batters faced", "pitches thrown",
}
players: dict[str, str] = {}
for r in mlb:
    name = str(r.get("player") or "").strip()
    if " + " in name:
        continue
    pid = name_to_id.get(fold(name)) or name_to_id.get(name.lower())
    if not pid:
        continue
    prop = str(r.get("prop") or "").strip().lower()
    ptype = "pitcher" if prop in pitcher_props else "hitter"
    if pid not in players or (players[pid] == "pitcher" and ptype == "hitter"):
        players[pid] = ptype

stale = []
for pid, ptype in players.items():
    md = step4.player_cache_max_date(cache, pid, season)
    if md is None or pd.Timestamp(md).normalize() < stale_before:
        stale.append((pid, ptype, md))

print(f"stale players: {len(stale)}", flush=True)
for i, (pid, ptype, md) in enumerate(stale, 1):
    print(f"[{i}/{len(stale)}] {pid} {ptype} was {md}", flush=True)
    time.sleep(0.2)
    try:
        cache, added = step4.update_cache(cache, pid, ptype, season, n_games=25)
    except Exception as e:
        print("  FAIL", e, flush=True)
        continue
    print(f"  +{added} now {step4.player_cache_max_date(cache, pid, season)}", flush=True)
    if i % 15 == 0:
        step4.save_cache(cache, cache_path)
        step4.save_cache(cache, scripts_cache)

step4.save_cache(cache, cache_path)
step4.save_cache(cache, scripts_cache)

# index + patch
cache2 = pd.read_csv(cache_path, low_memory=False)
cache2["GAME_DATE"] = pd.to_datetime(cache2["GAME_DATE"], errors="coerce")
cache2["STAT_VALUE"] = pd.to_numeric(cache2["STAT_VALUE"], errors="coerce")
cache2 = cache2.dropna(subset=["STAT_VALUE", "GAME_DATE"]).sort_values("GAME_DATE", ascending=False)
vals_map = defaultdict(list)
for pid, prop, val in zip(cache2["MLB_PLAYER_ID"].astype(str), cache2["PROP_NORM"].astype(str), cache2["STAT_VALUE"].astype(float)):
    key = (pid, prop)
    if len(vals_map[key]) < 10:
        vals_map[key].append(float(val))

patched = 0
for r in mlb:
    name = str(r.get("player") or "").strip()
    pid = name_to_id.get(fold(name)) or name_to_id.get(name.lower())
    if not pid:
        continue
    pn = PROP_MAP.get(str(r.get("prop") or "").strip().lower())
    if not pn:
        continue
    vals = vals_map.get((pid, pn)) or []
    if not vals:
        continue
    try:
        line_f = float(r.get("line"))
    except Exception:
        continue
    for i, v in enumerate(vals, 1):
        r[f"stat_g{i}"] = v
        r[f"g{i}"] = v
    r["actual_series"] = list(vals)
    r["line_series"] = [line_f] * len(vals)
    o5 = sum(1 for v in vals[:5] if v > line_f)
    u5 = sum(1 for v in vals[:5] if v < line_f)
    o10 = sum(1 for v in vals[:10] if v > line_f)
    u10 = sum(1 for v in vals[:10] if v < line_f)
    r["l5_over"], r["l5_under"] = o5, u5
    r["l10_over"], r["l10_under"] = o10, u10
    d = str(r.get("dir") or "OVER").upper()
    n5 = max(1, min(5, len(vals)))
    hr = (o5 / n5) if d != "UNDER" else (u5 / n5)
    r["l5_side_hit_rate"] = hr
    r["hit_rate"] = hr
    patched += 1

raw["sports"]["mlb"] = mlb
payload = json.dumps(raw, ensure_ascii=False, default=str)
(ROOT / "ui_runner/templates/slate_latest.json").write_text(payload, encoding="utf-8")
(ROOT / "mobile/www/slate_latest.json").write_text(payload, encoding="utf-8")
sport = json.dumps({"ok": True, "sport": "mlb", "rows": mlb}, ensure_ascii=False, default=str)
(ROOT / "ui_runner/templates/slate_sport_mlb.json").write_text(sport, encoding="utf-8")
(ROOT / "mobile/www/slate_sport_mlb.json").write_text(sport, encoding="utf-8")
print("patched", patched, flush=True)

# final stale count
still = []
for pid, ptype in players.items():
    md = step4.player_cache_max_date(cache, pid, season)
    if md is None or pd.Timestamp(md).normalize() < stale_before:
        still.append((pid, ptype, str(md)[:10] if md is not None else None))
print("still stale", len(still), still[:20], flush=True)
print("DONE", flush=True)
