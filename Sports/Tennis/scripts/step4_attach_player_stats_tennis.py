#!/usr/bin/env python3
"""
Tennis step4 — Sackmann match history (stat_g1..10) + ESPN scoreboard fallback.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from tennis_shared import (
    SACKMANN_PLAYER_STALE_DAYS,
    apply_format_matched_stat_g,
    build_sackmann_player_index,
    build_sackmann_player_log,
    collect_history_values,
    ensure_sackmann_matches,
    fetch_athlete_statistics,
    history_value_key,
    load_match_games_cache,
    norm_key,
    parse_tennis_season_stats,
    refresh_match_games_cache,
    sackmann_coverage_end,
    sackmann_player_fresh,
)


_ESPN_MATCH_KEYS = {
    "games_won",
    "match_total_games",
    "sets_won",
    "total_sets",
    "total_tie_breaks",
}


def _row_line(row: pd.Series) -> object:
    if "line" in row.index and str(row.get("line") or "").strip():
        return row.get("line")
    if "line_score" in row.index and str(row.get("line_score") or "").strip():
        return row.get("line_score")
    return None


def _espn_vals_from_cache(cache: dict, aid: str, hk: str, *, line: object = None, last_n: int = 10) -> list[float]:
    # ESPN tennis scoreboards have linescores (games/sets) but almost never
    # per-match aces / double faults. Do not treat missing stats as 0.
    # Skip slam / BO5 matches when the posted line is a BO3 market.
    if hk not in _ESPN_MATCH_KEYS:
        return []
    hist = cache.get(aid) or []
    if not isinstance(hist, list):
        return []
    return collect_history_values(hist, hk, last_n, line=line)


def main() -> None:
    print("[Tennis step4] Starting...")
    root = _SCRIPT_DIR.parent
    repo_root = _SCRIPT_DIR.parent.parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="YYYY-MM-DD run folder under outputs/{date}/tennis/")
    ap.add_argument("--input", default="")
    ap.add_argument("--output", default="")
    ap.add_argument("--match-cache", default="cache/tennis_match_games.json")
    ap.add_argument("--stats-cache", default="data/tennis_stats_cache.csv")
    ap.add_argument("--refresh-cache", action="store_true")
    ap.add_argument("--fetch-espn-stats", action="store_true", help="Fetch /statistics per player (slow)")
    ap.add_argument(
        "--history-source",
        choices=("sackmann", "espn", "both"),
        default="sackmann",
        help="sackmann=Jeff Sackmann CSVs (default); espn=scoreboard only; both=same as sackmann + cache refresh",
    )
    ap.add_argument("--history-n", type=int, default=20, help="Max Sackmann matches per player for stat_g*")
    ap.add_argument("--sackmann-min", type=int, default=1, help="Min Sackmann values required to use Sackmann row")
    args = ap.parse_args()

    run_date = str(args.date or "").strip()[:10]
    default_in = "outputs/step3_tennis_with_defense.csv"
    default_out = "outputs/step4_tennis_with_stats.csv"
    if run_date:
        run_dir = repo_root / "outputs" / run_date / "tennis"
        default_in = str(run_dir / "step3_tennis_with_defense.csv")
        default_out = str(run_dir / "step4_tennis_with_stats.csv")

    inp = Path(args.input or default_in)
    if not inp.is_absolute():
        inp = root / inp
    out = Path(args.output or default_out)
    if not out.is_absolute():
        out = root / out
    mpath = Path(args.match_cache)
    if not mpath.is_absolute():
        mpath = root / mpath
    stat_path = Path(args.stats_cache)
    if not stat_path.is_absolute():
        stat_path = root / stat_path

    df = pd.read_csv(inp, dtype=str, encoding="utf-8-sig").fillna("")
    if df.empty:
        print("ERROR [Tennis step4] empty input")
        sys.exit(1)

    history_src = str(args.history_source).strip().lower()
    use_sackmann = history_src in ("sackmann", "both")
    # Always allow ESPN scoreboard fallback for games/sets. Sackmann-only used to
    # skip it and leave RG-era L5 on summer boards.
    use_espn = True
    try:
        slate_date = date.fromisoformat(str(args.date or "").strip()[:10])
    except ValueError:
        slate_date = date.today()

    sackmann_df = pd.DataFrame()
    sackmann_index: dict[str, list] = {}
    coverage_end = None
    if use_sackmann:
        print("[Tennis step4] Loading Sackmann match history...")
        sackmann_df = ensure_sackmann_matches()
        if sackmann_df.empty:
            print("  [WARN] Sackmann matches empty — ESPN fallback only")
            use_espn = True
        else:
            sackmann_index = build_sackmann_player_index(sackmann_df)
            coverage_end = sackmann_coverage_end(sackmann_df)
            print(f"  Sackmann rows={len(sackmann_df):,}  indexed_players={len(sackmann_index):,}")
            if coverage_end:
                age_days = (slate_date - coverage_end).days
                print(f"  Sackmann newest tourney_date={coverage_end.isoformat()} ({age_days}d before slate {slate_date})")
                if age_days > SACKMANN_PLAYER_STALE_DAYS:
                    print(
                        "  [WARN] Sackmann is stale vs the slate. "
                        "Aces / DF / break points L5 will not use May-era matches. "
                        "ESPN scoreboard covers games/sets."
                    )
                    use_espn = True

    cache_age_h = None
    if mpath.is_file():
        cache_age_h = (time.time() - mpath.stat().st_mtime) / 3600.0
    if args.refresh_cache or not mpath.is_file() or (
        use_espn and (cache_age_h is None or cache_age_h > 12)
    ):
        days_back = 80 if use_espn else 2
        print(f"[Tennis step4] Refreshing ESPN match games cache (scoreboard, days_back={days_back})...")
        cache = refresh_match_games_cache(mpath, days_back=days_back)
    else:
        print(f"[Tennis step4] Using ESPN match cache ({cache_age_h:.1f}h old)")
        cache = load_match_games_cache(mpath)

    stat_cache: dict[tuple[str, str], dict[str, float | None]] = {}

    def _parse_float_cell(series: pd.Series, col: str) -> float | None:
        if col not in series.index:
            return None
        v = str(series.get(col, "")).strip()
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    if stat_path.is_file():
        try:
            sc = pd.read_csv(stat_path, dtype=str, encoding="utf-8-sig").fillna("")
            for _, r in sc.iterrows():
                aid = str(r.get("espn_athlete_id", "")).strip()
                tour = str(r.get("tour", "ATP")).strip().upper() or "ATP"
                if not aid:
                    continue
                stat_cache[(aid, tour)] = {
                    "aces_per_match": _parse_float_cell(r, "aces_per_match"),
                    "double_faults_per_match": _parse_float_cell(r, "double_faults_per_match"),
                    "first_serve_pct": _parse_float_cell(r, "first_serve_pct"),
                    "games_won_per_match": _parse_float_cell(r, "games_won_per_match"),
                    "sets_won_per_match": _parse_float_cell(r, "sets_won_per_match"),
                    "win_rate_L10": _parse_float_cell(r, "win_rate_L10"),
                }
        except Exception as e:
            print(f"  [WARN] stats cache read failed: {e}")

    df["stat_status"] = "PENDING"
    for c in (
        "aces_per_match",
        "double_faults_per_match",
        "first_serve_pct",
        "games_won_per_match",
        "sets_won_per_match",
        "win_rate_L10",
        "best_surface",
    ):
        if c not in df.columns:
            df[c] = np.nan

    hkeys = [history_value_key(str(x)) or "" for x in df["prop_norm"].tolist()]

    for gi in range(1, 11):
        df[f"stat_g{gi}"] = np.nan

    if args.fetch_espn_stats:
        seen: set[tuple[str, str]] = set()
        for _, r in df.iterrows():
            aid = str(r.get("espn_athlete_id", "")).strip()
            tour = str(r.get("tour", "ATP")).strip().upper() or "ATP"
            if not aid or (aid, tour) in seen:
                continue
            seen.add((aid, tour))
            key = (aid, tour)
            if key in stat_cache and stat_cache[key].get("aces_per_match") is not None:
                continue
            try:
                time.sleep(0.35)
                payload = fetch_athlete_statistics(tour, aid)
                parsed = parse_tennis_season_stats(payload)
                if not parsed or all(v is None for v in parsed.values()):
                    print(f"  [WARN] ESPN statistics empty for athlete_id={aid} tour={tour}")
                wr = None
                hist = cache.get(aid) or []
                if hist:
                    wins = sum(1 for m in hist[:10] if float(m.get("games_won") or 0) >= 12.0)
                    wr = wins / min(10, len(hist))
                stat_cache[key] = {
                    "aces_per_match": parsed.get("aces_per_match"),
                    "double_faults_per_match": parsed.get("double_faults_per_match"),
                    "first_serve_pct": parsed.get("first_serve_pct"),
                    "games_won_per_match": parsed.get("games_won_per_match"),
                    "sets_won_per_match": parsed.get("sets_won_per_match"),
                    "win_rate_L10": wr,
                }
            except Exception as e:
                print(f"  [WARN] stats fetch failed {aid}: {e}")

        stat_path.parent.mkdir(parents=True, exist_ok=True)
        rows_out: list[dict[str, object]] = []
        for (aid, tour), vals in stat_cache.items():
            row = {"espn_athlete_id": aid, "tour": tour}
            for k, v in vals.items():
                row[k] = "" if v is None else v
            rows_out.append(row)
        if rows_out:
            pd.DataFrame(rows_out).to_csv(stat_path, index=False, encoding="utf-8-sig")

    sack_fill = 0
    espn_fill = 0
    min_sack = max(1, int(args.sackmann_min))
    last_n = max(1, int(args.history_n))

    player_col = "player" if "player" in df.columns else "Player"

    for pos in range(len(df)):
        r = df.iloc[pos]
        aid = str(r.get("espn_athlete_id", "")).strip()
        tour = str(r.get("tour", "ATP")).strip().upper() or "ATP"
        hk = hkeys[pos]
        unsup = int(float(r.get("unsupported_prop", 0) or 0))
        if unsup == 1 or not hk:
            df.iat[pos, df.columns.get_loc("stat_status")] = "UNSUPPORTED_PROP" if unsup == 1 else "NO_STAT_KEY"
            continue

        player_name = str(r.get(player_col) or r.get("player") or "")
        pk = norm_key(player_name)
        line = _row_line(r)
        filled = False
        espn_ok = bool(use_espn and hk in _ESPN_MATCH_KEYS and aid)

        # Live ESPN linescores beat Sackmann for games/sets. Sackmann ATP/WTA
        # files stop at RG (~May), so using them here inflated Tiafoe Games Won
        # L5 to 24/31/29 (BO5) vs PrizePicks 12/17/13/27/23.
        if espn_ok:
            vals = _espn_vals_from_cache(cache, aid, hk, line=line, last_n=10)
            if len(vals) >= 3:
                for j, v in enumerate(vals[:10]):
                    df.iat[pos, df.columns.get_loc(f"stat_g{j + 1}")] = v
                df.iat[pos, df.columns.get_loc("stat_status")] = "OK"
                espn_fill += 1
                filled = True

        if (not filled) and use_sackmann and sackmann_index and pk and sackmann_player_fresh(
            sackmann_index, pk, slate_date
        ):
            sack_vals = build_sackmann_player_log(
                sackmann_df,
                pk,
                hk,
                last_n=last_n,
                player_index=sackmann_index,
                line=line,
            )
            if len(sack_vals) >= min_sack:
                for j, v in enumerate(sack_vals[:10]):
                    df.iat[pos, df.columns.get_loc(f"stat_g{j + 1}")] = v
                df.iat[pos, df.columns.get_loc("stat_status")] = "OK"
                sack_fill += 1
                filled = True

        if not filled and use_espn:
            if not aid:
                df.iat[pos, df.columns.get_loc("stat_status")] = "NO_ID"
            else:
                vals = _espn_vals_from_cache(cache, aid, hk, line=line, last_n=10)
                if not vals:
                    df.iat[pos, df.columns.get_loc("stat_status")] = "STALE_HISTORY" if use_sackmann else "NO_DATA"
                else:
                    df.iat[pos, df.columns.get_loc("stat_status")] = "OK"
                    for j, v in enumerate(vals[:10]):
                        df.iat[pos, df.columns.get_loc(f"stat_g{j + 1}")] = v
                    espn_fill += 1
                    filled = True
        elif not filled:
            df.iat[pos, df.columns.get_loc("stat_status")] = "STALE_HISTORY" if use_sackmann else "NO_DATA"

        st = stat_cache.get((aid, tour))
        if st:
            for k, v in st.items():
                if k in df.columns and v is not None:
                    df.iat[pos, df.columns.get_loc(k)] = v

    gcols = [f"stat_g{i}" for i in range(1, 11)]
    dropped = apply_format_matched_stat_g(df, n=10)
    if dropped:
        print(f"[Tennis step4] Format filter dropped BO5 history on {dropped} BO3-line rows")
    sub = df[gcols].apply(pd.to_numeric, errors="coerce")
    df["stat_last5_avg"] = sub.iloc[:, :5].mean(axis=1)
    df["stat_last10_avg"] = sub.mean(axis=1)
    df["stat_season_avg"] = df["stat_last10_avg"]
    df["actual_series"] = ""

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    ok_n = int((df["stat_status"] == "OK").sum())
    print(f"[Tennis step4] Sackmann fill: {sack_fill}/{len(df)} rows got stat_g from Sackmann")
    print(f"[Tennis step4] ESPN fallback: {espn_fill} rows used scoreboard cache")
    print(f"OK [Tennis step4] -> {out}  rows={len(df)}  stat_OK={ok_n}")


if __name__ == "__main__":
    main()
