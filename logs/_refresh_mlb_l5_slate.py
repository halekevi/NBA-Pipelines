#!/usr/bin/env python3
"""Refresh stale MLB game-log cache for today's slate players and patch L5/L10 on slate_latest."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MLB = ROOT / "Sports" / "MLB"
SCRIPTS = MLB / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

import step4_attach_player_stats_mlb as step4  # noqa: E402

PROP_MAP = {
    "hits": "hits",
    "total bases": "total_bases",
    "home runs": "home_runs",
    "rbis": "rbi",
    "rbi": "rbi",
    "runs": "runs",
    "walks": "walks",
    "stolen bases": "stolen_bases",
    "fantasy score": "fantasy_score",
    "hits+runs+rbis": "hits_runs_rbi",
    "hits + runs + rbis": "hits_runs_rbi",
    "singles": "singles",
    "doubles": "doubles",
    "triples": "triples",
    "hitter strikeouts": "hitter_strikeouts",
    "strikeouts": "hitter_strikeouts",
    "plate appearances": "plate_appearances",
    "pitcher strikeouts": "strikeouts",
    "pitching outs": "pitching_outs",
    "innings pitched": "innings_pitched",
    "hits allowed": "hits_allowed",
    "earned runs": "earned_runs",
    "earned runs allowed": "earned_runs",
    "walks allowed": "walks_allowed",
    "batters faced": "batters_faced",
    "pitches thrown": "pitches_thrown",
}


def prop_norm(prop: str) -> str | None:
    p = str(prop or "").strip().lower()
    if p in PROP_MAP:
        return PROP_MAP[p]
    p2 = p.replace(" ", "_")
    return PROP_MAP.get(p2)


def main() -> int:
    slate_path = ROOT / "ui_runner/templates/slate_latest.json"
    cache_path = MLB / "mlb_stats_cache.csv"
    raw = json.loads(slate_path.read_text(encoding="utf-8"))
    mlb_rows = raw.get("sports", {}).get("mlb") or []
    print("slate", raw.get("date"), "mlb rows", len(mlb_rows))

    cache = step4.load_cache(cache_path)
    season = "2026"

    # Collect unique player ids from slate
    id_cache = pd.read_csv(MLB / "mlb_id_cache.csv")
    name_to_id = {
        str(r["player_norm"]).strip().lower(): str(r["mlb_player_id"]).strip()
        for _, r in id_cache.iterrows()
    }

    players: dict[str, str] = {}  # pid -> name
    for r in mlb_rows:
        name = str(r.get("player") or "").strip()
        if not name:
            continue
        pid = name_to_id.get(name.lower())
        if not pid:
            continue
        players[pid] = name

    stale = []
    for pid, name in players.items():
        if step4.player_cache_is_stale(cache, pid, season):
            stale.append((pid, name))
    print(f"unique players on slate: {len(players)}  stale: {len(stale)}")

    # Prioritize the reported trio then rest
    priority = {"james wood", "brayan rocchio", "jordan walker"}
    stale.sort(key=lambda x: (0 if x[1].lower() in priority else 1, x[1].lower()))

    added_total = 0
    for i, (pid, name) in enumerate(stale, 1):
        # Infer pitcher vs hitter from cache or default hitter
        sub = cache[
            (cache["MLB_PLAYER_ID"].astype(str) == str(pid))
            & (cache["SEASON"].astype(str) == season)
        ]
        ptype = "hitter"
        if len(sub) and str(sub.iloc[0].get("PLAYER_TYPE", "")).lower() == "pitcher":
            ptype = "pitcher"
        print(f"[{i}/{len(stale)}] refresh {name} ({pid}) {ptype} …", flush=True)
        time.sleep(0.25)
        cache, added = step4.update_cache(cache, pid, ptype, season, n_games=15)
        if added:
            added_total += added
            print(f"  +{added} games")
        if i % 15 == 0:
            step4.save_cache(cache, cache_path)
            print("  checkpoint save")

    step4.save_cache(cache, cache_path)
    # keep scripts copy in sync if present
    alt = SCRIPTS / "mlb_stats_cache.csv"
    if alt.exists() or True:
        step4.save_cache(cache, alt)
    print(f"cache refresh done; new games logged≈{added_total}")

    # Patch slate L5/L10/series from refreshed cache
    patched = 0
    for r in mlb_rows:
        name = str(r.get("player") or "").strip()
        pid = name_to_id.get(name.lower())
        if not pid:
            continue
        pn = prop_norm(str(r.get("prop") or ""))
        if not pn:
            continue
        vals = step4.get_vals_from_cache(cache, pid, pn, season, n=10)
        if not vals:
            continue
        line = r.get("line")
        try:
            line_f = float(line)
        except (TypeError, ValueError):
            continue
        for i, v in enumerate(vals, 1):
            r[f"stat_g{i}"] = v
            r[f"g{i}"] = v
        r["actual_series"] = [float(v) for v in vals]
        r["line_series"] = [line_f] * len(vals)
        o5, u5, _, _, _, _ = step4.calc_hit_context(vals, line_f, k=5)
        o10, u10, _, _, _, _ = step4.calc_hit_context(vals, line_f, k=10)
        r["l5_over"] = o5
        r["l5_under"] = u5
        r["l10_over"] = o10
        r["l10_under"] = u10
        played5 = min(5, len(vals))
        played10 = min(10, len(vals))
        if played5:
            r["l5_side_hit_rate"] = (o5 / played5) if str(r.get("dir", "OVER")).upper() != "UNDER" else (u5 / played5)
        if played5:
            r["hit_rate"] = (o5 / played5) if str(r.get("dir", "OVER")).upper() != "UNDER" else (u5 / played5)
        patched += 1

    raw["sports"]["mlb"] = mlb_rows
    slate_path.write_text(json.dumps(raw, ensure_ascii=False, default=str), encoding="utf-8")
    mobile = ROOT / "mobile/www/slate_latest.json"
    if mobile.exists():
        mobile.write_text(json.dumps(raw, ensure_ascii=False, default=str), encoding="utf-8")
    # sport file
    sport = ROOT / "ui_runner/templates/slate_sport_mlb.json"
    if sport.exists():
        sport.write_text(
            json.dumps({"ok": True, "sport": "mlb", "rows": mlb_rows}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        (ROOT / "mobile/www/slate_sport_mlb.json").write_text(
            json.dumps({"ok": True, "sport": "mlb", "rows": mlb_rows}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # Verify trio
    print("\n=== VERIFY trio H+R+RBI / Runs after patch ===")
    for name in ["James Wood", "Brayan Rocchio", "Jordan Walker"]:
        for r in mlb_rows:
            if r.get("player") != name:
                continue
            prop = str(r.get("prop") or "")
            if prop not in ("Hits+Runs+RBIs", "Runs", "Hits"):
                continue
            if str(r.get("pick_type") or "").lower() not in ("standard", "goblin"):
                continue
            print(
                f"{name} {r.get('pick_type')} O{r.get('line')} {prop} "
                f"L5 {r.get('l5_over')}/{r.get('l5_under')} L10 {r.get('l10_over')}/{r.get('l10_under')} "
                f"series={r.get('actual_series')[:5]}"
            )

    print(f"\npatched rows: {patched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
