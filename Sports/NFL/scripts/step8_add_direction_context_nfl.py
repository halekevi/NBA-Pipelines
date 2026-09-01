#!/usr/bin/env python3
"""
NFL step8 — formatted direction workbook for combined_slate_tickets / web UI.

NFL (PrizePicks 9) and NFLP preseason (44) share this sheet. Defense ranks
are the last completed regular season until the new year has a full table.

Reads step7_nfl_ranked.xlsx (ALL), writes step8_nfl_direction_clean.xlsx.

Run from NFL/ with NFL_PIPELINE_ACTIVE=1.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from _nfl_pipeline_active import require_nfl_pipeline_active_or_exit
from proporacle.data.table_io import copy_parquet_sidecar, write_parquet_sidecar, read_table, table_exists, write_excel_sheets


def _copy_dated(out_xlsx: Path, slate_date: str) -> None:
    if not out_xlsx.is_file():
        return
    from utils.slate_id import dated_copy_ymd

    d = dated_copy_ymd(slate_date, context="NFL step8")
    if not d:
        return
    repo_root = Path(__file__).resolve().parents[3]
    for dated_dir in (
        repo_root / "outputs" / d / "nfl",
        Path(__file__).resolve().parents[1] / "outputs" / d,
    ):
        try:
            dated_dir.mkdir(parents=True, exist_ok=True)
            dst = dated_dir / f"step8_nfl_direction_clean_{d}.xlsx"
            shutil.copy2(out_xlsx, dst)
            copy_parquet_sidecar(out_xlsx, dst)
            print(f"[NFL step8] Dated copy -> {dst}")
        except Exception as e:
            print(f"[NFL step8] WARN dated copy: {e}")


def main() -> None:
    require_nfl_pipeline_active_or_exit()

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="outputs/step7_nfl_ranked.xlsx")
    ap.add_argument("--sheet", default="ALL")
    ap.add_argument("--output", default="outputs/step8_nfl_direction_clean.xlsx")
    ap.add_argument("--date", default="", help="Pipeline slate date YYYY-MM-DD (for dated copies)")
    args = ap.parse_args()

    src = Path(args.input)
    if not table_exists(src):
        print(f"[NFL step8] Missing input: {src}")
        sys.exit(1)

    df = read_table(src, sheet=args.sheet, sheet_order=(args.sheet, "ALL"))
    _repo = Path(__file__).resolve().parents[3]
    if str(_repo) not in sys.path:
        sys.path.insert(0, str(_repo))
    from utils.hit_tracking_columns import attach_hit_tracking_columns
    from utils.nfl_prop_defense import fill_opp_team_from_game, prop_def_axis

    if not df.empty:
        work = df.copy()
        if "player" not in work.columns and "player_name" in work.columns:
            work["player"] = work["player_name"]
        if "prop_type" not in work.columns:
            for c in ("stat_type", "prop_type_normalized"):
                if c in work.columns:
                    work["prop_type"] = work[c]
                    break
        if "final_bet_direction" not in work.columns:
            for c in ("recommended_side", "bet_direction", "direction"):
                if c in work.columns:
                    work["final_bet_direction"] = work[c]
                    break
        df = attach_hit_tracking_columns(work, "NFL")
        df = fill_opp_team_from_game(df)

    if df.empty:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_excel_sheets(out, {"ALL": pd.DataFrame()})
        write_parquet_sidecar(pd.DataFrame(), out)
        print(f"[NFL step8] Wrote empty {out}")
        return

    def col(*names: str) -> pd.Series:
        for n in names:
            if n in df.columns:
                return df[n]
        return pd.Series([""] * len(df), index=df.index)

    player = col("player_name", "player")
    tier = col("tier").astype(str).str.upper().str.strip()
    rs = pd.to_numeric(col("rank_score", "prop_score"), errors="coerce")
    pos = col("position_group", "pos")
    team = col("team")
    opp = col("opp_team", "opponent", "opp")
    gt = col("start_time", "game_time")
    prop = col("stat_type", "prop_type", "prop_type_normalized")
    pt = col("pick_type")
    line = pd.to_numeric(col("line_score", "line"), errors="coerce")
    direction = col("recommended_side", "bet_direction", "direction").astype(str).str.upper().str.strip()
    edge = pd.to_numeric(col("edge"), errors="coerce")
    proj = pd.to_numeric(col("projection"), errors="coerce")
    hr = pd.to_numeric(col("hit_rate", "composite_hit_rate"), errors="coerce")
    l5o = pd.to_numeric(col("l5_over", "last5_over"), errors="coerce")
    l5u = pd.to_numeric(col("l5_under", "last5_under"), errors="coerce")
    dtr = col("def_tier", "DEF_TIER")
    drk = pd.to_numeric(col("OVERALL_DEF_RANK", "opp_def_rank_prop", "def_rank"), errors="coerce")
    opp_pass_rk = pd.to_numeric(col("opp_pass_def_rank"), errors="coerce")
    opp_rush_rk = pd.to_numeric(col("opp_rush_def_rank"), errors="coerce")
    opp_fg_rk = pd.to_numeric(col("opp_fg_def_rank"), errors="coerce")
    axis = prop.map(prop_def_axis)
    tm_l5_rec = col("team_last5_record")
    tm_l5_pf = pd.to_numeric(col("team_last5_pf_pg"), errors="coerce")
    tm_l5_pa = pd.to_numeric(col("team_last5_pa_pg"), errors="coerce")
    tm_l5_pm = pd.to_numeric(col("team_last5_margin_avg"), errors="coerce")
    op_l5_rec = col("opp_last5_record")
    op_l5_pf = pd.to_numeric(col("opp_last5_pf_pg"), errors="coerce")
    op_l5_pa = pd.to_numeric(col("opp_last5_pa_pg"), errors="coerce")
    op_l5_pm = pd.to_numeric(col("opp_last5_margin_avg"), errors="coerce")

    clean = pd.DataFrame(
        {
            "Tier": tier,
            "Rank Score": rs.round(2),
            "Player": player,
            "Pos": pos,
            "Team": team,
            "Opp": opp,
            "Game Time": gt,
            "Prop": prop,
            "Pick Type": pt.fillna("Standard"),
            "Line": line,
            "Direction": direction,
            "Edge": edge.round(2),
            "Projection": proj.round(2),
            "Hit Rate (5g)": pd.to_numeric(col("hit_rate", "composite_hit_rate"), errors="coerce").combine_first(hr),
            "Hit Rate L5": pd.to_numeric(col("hit_rate_l5"), errors="coerce"),
            "Hit Rate L10": pd.to_numeric(col("hit_rate_l10"), errors="coerce"),
            "L5 Over": pd.to_numeric(col("l5_over", "last5_over"), errors="coerce").combine_first(l5o),
            "L5 Under": pd.to_numeric(col("l5_under", "last5_under"), errors="coerce").combine_first(l5u),
            "L10 Over": pd.to_numeric(col("l10_over"), errors="coerce"),
            "L10 Under": pd.to_numeric(col("l10_under"), errors="coerce"),
            "L10 Streak": col("l10_streak"),
            "Strat Hit Rate": pd.to_numeric(col("strat_hit_rate"), errors="coerce"),
            "Strat N": pd.to_numeric(col("strat_n"), errors="coerce"),
            "Player HR Hist": pd.to_numeric(col("player_hr_historical"), errors="coerce"),
            "Opp HR Hist": pd.to_numeric(col("opp_hr_historical"), errors="coerce"),
            "Sport Maturity": col("sport_signal_maturity"),
            "Confidence Tier": col("confidence_tier"),
            "Confidence Score": pd.to_numeric(col("confidence_score"), errors="coerce"),
            "Confidence Note": col("confidence_note"),
            "Team L5": tm_l5_rec,
            "Tm L5 PF/G": tm_l5_pf.round(1),
            "Tm L5 PA/G": tm_l5_pa.round(1),
            "Tm L5 +/-": tm_l5_pm.round(1),
            "Opp L5": op_l5_rec,
            "Opp L5 PF/G": op_l5_pf.round(1),
            "Opp L5 PA/G": op_l5_pa.round(1),
            "Opp L5 +/-": op_l5_pm.round(1),
            "Def Tier": dtr,
            "Def Rank": drk,
            "Def Axis": axis,
            "Opp Pass Def Rank": opp_pass_rk,
            "Opp Rush Def Rank": opp_rush_rk,
            "Opp FG Def Rank": opp_fg_rk,
            "League": col("league"),
            "Snap L3": pd.to_numeric(col("snap_pct_L3", "snap_pct_season"), errors="coerce"),
            "Starter Policy": col("starter_policy"),
            "Expected Snaps": col("expected_snaps"),
            "Depth Slot": col("depth_slot"),
            "Minutes Tier": col("minutes_tier"),
            "Injury": col("injury_status"),
            "Injury Type": col("injury_type"),
            "Weather": col("weather_flag"),
            "Wind MPH": pd.to_numeric(col("wind_mph"), errors="coerce"),
            "Indoor": col("indoor"),
            "Spread": pd.to_numeric(col("spread"), errors="coerce"),
            "Game Total": pd.to_numeric(col("game_total"), errors="coerce"),
            "Implied Total": pd.to_numeric(col("implied_team_total"), errors="coerce"),
            "Game Ctx": pd.to_numeric(col("game_context_score", "ctx_adj"), errors="coerce"),
            "Team Rank": pd.to_numeric(col("team_stat_rank"), errors="coerce"),
            "League Rank": pd.to_numeric(col("league_stat_rank"), errors="coerce"),
            "Leader Slice": col("leader_slice"),
            "Top3 Rank": pd.to_numeric(col("team_top3_rank"), errors="coerce"),
            "Bottom3 Rank": pd.to_numeric(col("team_bottom3_rank"), errors="coerce"),
        }
    )

    pt_low = clean["Pick Type"].astype(str).str.strip().str.lower()
    forced_rows = pt_low.isin(("goblin", "demon"))
    ln = pd.to_numeric(clean["Line"], errors="coerce")
    pj = pd.to_numeric(clean["Projection"], errors="coerce")
    has_pl = ln.notna() & pj.notna()
    prev_edge = pd.to_numeric(clean["Edge"], errors="coerce")
    signed_gap = pj - ln
    clean["Edge"] = signed_gap.where(has_pl, prev_edge).round(2)
    clean["Abs Edge"] = pd.to_numeric(clean["Edge"], errors="coerce").abs().round(2)

    d_prev = clean["Direction"].astype(str).str.upper().str.strip().replace("", "OVER")
    e_num = pd.to_numeric(clean["Edge"], errors="coerce")
    from_side = np.where(e_num >= 0, "OVER", "UNDER")
    # NFLP backups: keep step7 D-aligned side. Thin 2025 samples (0 yards in
    # two emergency games) should not flip a Weak-D over into an under.
    backup = clean.get("Starter Policy", pd.Series("", index=clean.index)).astype(str).str.lower().eq("backup")
    clean["Direction"] = np.where(
        forced_rows.to_numpy(),
        "OVER",
        np.where(
            backup.to_numpy(),
            d_prev.to_numpy(),
            np.where(has_pl.to_numpy(), from_side, d_prev.to_numpy()),
        ),
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheets = {"ALL": clean}
    for t in ("A", "B", "C", "D"):
        sub = clean[clean["Tier"] == t]
        if len(sub):
            sheets[f"Tier {t}"] = sub
    write_excel_sheets(out_path, sheets)
    print(f"[NFL step8] Wrote {out_path} rows={len(clean)}")
    write_parquet_sidecar(clean, out_path)
    _copy_dated(out_path, str(args.date or "").strip())


if __name__ == "__main__":
    main()
