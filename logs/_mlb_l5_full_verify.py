#!/usr/bin/env python3
"""Full MLB L5/L10 verification for today's slate."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
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
    "singles": "singles",
    "doubles": "doubles",
    "triples": "triples",
    "hitter strikeouts": "hitter_strikeouts",
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
    return PROP_MAP.get(str(prop or "").strip().lower())


def index_cache(cache: pd.DataFrame):
    cache = cache.copy()
    cache["GAME_DATE"] = pd.to_datetime(cache["GAME_DATE"], errors="coerce")
    cache["STAT_VALUE"] = pd.to_numeric(cache["STAT_VALUE"], errors="coerce")
    cache = cache.dropna(subset=["STAT_VALUE", "GAME_DATE"])
    cache = cache.sort_values("GAME_DATE", ascending=False)
    vals_map: dict[tuple[str, str], list[float]] = defaultdict(list)
    max_date: dict[str, pd.Timestamp] = {}
    for pid, prop, val, dt in zip(
        cache["MLB_PLAYER_ID"].astype(str),
        cache["PROP_NORM"].astype(str),
        cache["STAT_VALUE"].astype(float),
        cache["GAME_DATE"],
    ):
        key = (pid, prop)
        if len(vals_map[key]) < 10:
            vals_map[key].append(float(val))
        if pid not in max_date or dt > max_date[pid]:
            max_date[pid] = dt
    return vals_map, max_date


def main() -> int:
    slate_path = ROOT / "ui_runner/templates/slate_latest.json"
    cache_path = MLB / "mlb_stats_cache.csv"
    scripts_cache = SCRIPTS / "mlb_stats_cache.csv"
    # Prefer the larger/newer of the two cache files
    if scripts_cache.exists() and (
        not cache_path.exists()
        or scripts_cache.stat().st_mtime >= cache_path.stat().st_mtime
    ):
        # Keep Sports/MLB path as canonical for step4 helpers
        if scripts_cache.resolve() != cache_path.resolve():
            cache_path.write_bytes(scripts_cache.read_bytes())

    raw = json.loads(slate_path.read_text(encoding="utf-8"))
    mlb_rows = raw.get("sports", {}).get("mlb") or []
    print("slate", raw.get("date"), "mlb rows", len(mlb_rows), flush=True)

    ids = pd.read_csv(MLB / "mlb_id_cache.csv")
    name_to_id = {
        str(r["player_norm"]).strip().lower(): str(r["mlb_player_id"]).strip()
        for _, r in ids.iterrows()
    }

    # player -> ptype guess from slate props
    players: dict[str, str] = {}
    pitcher_props = {
        "pitcher strikeouts",
        "pitching outs",
        "innings pitched",
        "hits allowed",
        "earned runs",
        "earned runs allowed",
        "walks allowed",
        "batters faced",
        "pitches thrown",
    }
    for r in mlb_rows:
        name = str(r.get("player") or "").strip()
        pid = name_to_id.get(name.lower())
        if not pid:
            continue
        prop = str(r.get("prop") or "").strip().lower()
        ptype = "pitcher" if prop in pitcher_props else "hitter"
        # if already hitter, keep hitter unless only pitcher props seen — prefer hitter if mixed
        if pid not in players:
            players[pid] = ptype
        elif players[pid] == "pitcher" and ptype == "hitter":
            players[pid] = "hitter"

    print("loading cache…", flush=True)
    cache = step4.load_cache(cache_path)
    season = "2026"
    stale_before = pd.Timestamp("2026-08-01")  # must include Aug 1 box scores

    stale = []
    for pid, ptype in players.items():
        max_dt = step4.player_cache_max_date(cache, pid, season)
        if max_dt is None or pd.Timestamp(max_dt).normalize() < stale_before:
            stale.append((pid, ptype, max_dt))
    print(
        f"unique players={len(players)} stale_before_aug1={len(stale)}",
        flush=True,
    )
    if stale[:10]:
        print("sample stale max dates:", [(p, t, str(d)[:10] if d is not None else None) for p, t, d in stale[:10]], flush=True)

    # Refresh remaining stale
    added_total = 0
    for i, (pid, ptype, _) in enumerate(stale, 1):
        print(f"[{i}/{len(stale)}] refresh {pid} {ptype}…", flush=True)
        time.sleep(0.2)
        try:
            cache, added = step4.update_cache(cache, pid, ptype, season, n_games=15)
        except Exception as e:
            print(f"  FAIL {e}", flush=True)
            continue
        if added:
            added_total += added
            print(f"  +{added}", flush=True)
        if i % 20 == 0:
            step4.save_cache(cache, cache_path)
            step4.save_cache(cache, scripts_cache)
            print("  checkpoint", flush=True)

    step4.save_cache(cache, cache_path)
    step4.save_cache(cache, scripts_cache)
    print(f"refresh done added≈{added_total}", flush=True)

    # Re-index and patch
    print("re-index + patch slate…", flush=True)
    vals_map, max_date = index_cache(cache)

    still_stale = []
    for pid in players:
        md = max_date.get(pid)
        if md is None or pd.Timestamp(md).normalize() < stale_before:
            still_stale.append((pid, str(md)[:10] if md is not None else None))
    print(f"still stale after refresh: {len(still_stale)}", flush=True)

    patched = 0
    mismatches_internal = 0
    for r in mlb_rows:
        name = str(r.get("player") or "").strip()
        pid = name_to_id.get(name.lower())
        if not pid:
            continue
        pn = prop_norm(str(r.get("prop") or ""))
        if not pn:
            continue
        vals = vals_map.get((pid, pn)) or []
        if not vals:
            continue
        try:
            line_f = float(r.get("line"))
        except Exception:
            continue
        # Recompute truth
        o5 = sum(1 for v in vals[:5] if v > line_f)
        u5 = sum(1 for v in vals[:5] if v < line_f)
        o10 = sum(1 for v in vals[:10] if v > line_f)
        u10 = sum(1 for v in vals[:10] if v < line_f)
        old_l5 = r.get("l5_over")
        try:
            if old_l5 is not None and int(float(old_l5)) != o5:
                mismatches_internal += 1
        except Exception:
            pass
        for i, v in enumerate(vals, 1):
            r[f"stat_g{i}"] = v
            r[f"g{i}"] = v
        r["actual_series"] = list(vals)
        r["line_series"] = [line_f] * len(vals)
        r["l5_over"], r["l5_under"] = o5, u5
        r["l10_over"], r["l10_under"] = o10, u10
        d = str(r.get("dir") or "OVER").upper()
        n5 = max(1, min(5, len(vals)))
        hr = (o5 / n5) if d != "UNDER" else (u5 / n5)
        r["l5_side_hit_rate"] = hr
        r["hit_rate"] = hr
        patched += 1

    raw["sports"]["mlb"] = mlb_rows
    payload = json.dumps(raw, ensure_ascii=False, default=str)
    slate_path.write_text(payload, encoding="utf-8")
    (ROOT / "mobile/www/slate_latest.json").write_text(payload, encoding="utf-8")
    sport = json.dumps({"ok": True, "sport": "mlb", "rows": mlb_rows}, ensure_ascii=False, default=str)
    (ROOT / "ui_runner/templates/slate_sport_mlb.json").write_text(sport, encoding="utf-8")
    (ROOT / "mobile/www/slate_sport_mlb.json").write_text(sport, encoding="utf-8")
    print(f"patched={patched} prior_l5_mismatches_fixed≈{mismatches_internal}", flush=True)

    # Cross-check vs Aug 1 graded box for Std/Gob OVER
    grade_path = ROOT / "outputs/2026-08-01/graded_mlb_2026-08-01.xlsx"
    if grade_path.exists():
        print("\n=== cross-check vs Aug 1 graded actuals (most-recent series[0]) ===", flush=True)
        gdf = pd.read_excel(grade_path, sheet_name="Box Raw", header=0)
        gdf = gdf[gdf["result"].astype(str).str.upper().isin(["HIT", "MISS"])]
        gdf = gdf[gdf["bet_direction"].astype(str).str.upper() == "OVER"]
        gdf = gdf[gdf["pick_type"].astype(str).str.lower().isin(["standard", "goblin"])]
        # build lookup player|prop|line|pick -> actual
        checks = 0
        ok = 0
        bad = []
        for _, gr in gdf.iterrows():
            player = str(gr["player"])
            prop = str(gr["prop_type_norm"])
            try:
                line = float(gr["line"])
                actual = float(gr["actual"])
            except Exception:
                continue
            pick = str(gr["pick_type"])
            # find matching slate row
            matches = [
                r
                for r in mlb_rows
                if str(r.get("player")) == player
                and str(r.get("prop")) == prop
                and str(r.get("pick_type")) == pick
                and abs(float(r.get("line") or -999) - line) < 1e-6
            ]
            if not matches:
                continue
            series = matches[0].get("actual_series") or []
            if not series:
                continue
            checks += 1
            recent = float(series[0])
            if abs(recent - actual) < 1e-6:
                ok += 1
            else:
                bad.append((player, pick, prop, line, actual, recent, matches[0].get("l5_over")))
            if checks >= 400:
                break
        print(f"graded Aug1 most-recent match: {ok}/{checks}", flush=True)
        if bad[:15]:
            print("mismatches (player pick prop line graded_actual series0 l5):", flush=True)
            for b in bad[:15]:
                print(" ", b, flush=True)

    # Elite L5 5/5 + edge>0 count after fix
    elite = []
    for r in mlb_rows:
        if str(r.get("pick_type") or "").lower() not in ("standard", "goblin"):
            continue
        if str(r.get("dir") or "").upper() != "OVER":
            continue
        try:
            if float(r.get("edge") or 0) <= 0:
                continue
            if int(float(r.get("l5_over") or 0)) < 5:
                continue
        except Exception:
            continue
        elite.append(r)
    print(f"\nMLB OVER Std/Gob L5==5 edge>0 remaining: {len(elite)}", flush=True)
    for r in sorted(elite, key=lambda x: -float(x.get("edge") or 0))[:20]:
        print(
            f"  {r.get('player')} {r.get('pick_type')} O{r.get('line')} {r.get('prop')} "
            f"L5 {r.get('l5_over')} L10 {r.get('l10_over')} edge {r.get('edge')} series {r.get('actual_series')[:5]}",
            flush=True,
        )

    # Explicit trio
    print("\n=== TRIO ===", flush=True)
    for name in ["James Wood", "Brayan Rocchio", "Jordan Walker"]:
        for r in mlb_rows:
            if r.get("player") != name:
                continue
            if str(r.get("prop")) not in ("Hits+Runs+RBIs", "Runs", "Hits"):
                continue
            if str(r.get("pick_type") or "").lower() not in ("standard", "goblin"):
                continue
            print(
                f"  {name} {r.get('pick_type')} O{r.get('line')} {r.get('prop')} "
                f"L5 {r.get('l5_over')}/5 L10 {r.get('l10_over')}/10 series={r.get('actual_series')[:5]}",
                flush=True,
            )

    report = {
        "date": raw.get("date"),
        "players": len(players),
        "stale_before_refresh": len(stale),
        "still_stale": still_stale[:50],
        "patched": patched,
        "elite_l5_5_count": len(elite),
    }
    (ROOT / "logs/_mlb_l5_full_verify.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print("\nwrote logs/_mlb_l5_full_verify.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
