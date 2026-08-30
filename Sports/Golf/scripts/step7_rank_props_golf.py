#!/usr/bin/env python3
"""
step7_rank_props_golf.py — rank PrizePicks golf props for step8.

Keeps upstream columns (stat_g1..10, L5 hits) so step8 can recompute real
round history. Writes step7_golf_ranked.xlsx (sheet ALL).

Run:
  py -3.14 Sports/Golf/scripts/step7_rank_props_golf.py --input outputs/step5_golf_hit_rates.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_GOLF_REPO = Path(__file__).resolve().parents[3]
if str(_GOLF_REPO) not in sys.path:
    sys.path.insert(0, str(_GOLF_REPO))
from utils.consistency_grade_scores import apply_consistency_grade_scores  # noqa: E402
from utils.group_rank_tier import (  # noqa: E402
    assign_tier_column,
    print_tier_distribution_by_pick_direction_group,
    report_goblin_demon_standard_line_fill,
)
from utils.prop_signal_score import apply_ml_rank_blend  # noqa: E402
from proporacle.data.table_io import write_excel_sheets, write_parquet_sidecar


def _norm_pick_type(x: str) -> str:
    t = (str(x) if x is not None else "").strip().lower()
    if "gob" in t:
        return "Goblin"
    if "dem" in t:
        return "Demon"
    return "Standard"


def _forced_over_only(pick_type: str) -> int:
    return 1 if _norm_pick_type(pick_type) in ("Goblin", "Demon") else 0


def _num_series(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def main() -> None:
    print("[Golf step7] Starting...")
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Golf step7 — rank props from step4/5 CSV.")
    ap.add_argument("--input", default="outputs/step1_golf_props.csv")
    ap.add_argument("--output", default="outputs/step7_golf_ranked.xlsx")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.is_absolute():
        inp = root / inp
    if not inp.is_file():
        raise SystemExit(f"Missing input: {inp}")

    work = pd.read_csv(inp, low_memory=False, encoding="utf-8-sig")
    if "line" not in work.columns and "line_score" in work.columns:
        work["line"] = work["line_score"]
    work["line"] = pd.to_numeric(work.get("line"), errors="coerce")
    work = work.dropna(subset=["line"])
    work = work[work["line"] >= 0]
    if work.empty:
        raise SystemExit("No rows with valid line values.")

    if "player" not in work.columns or work["player"].astype(str).str.strip().eq("").all():
        work["player"] = work.get("player_name", "").fillna("").astype(str).str.strip()
    else:
        work["player"] = work["player"].fillna("").astype(str).str.strip()

    line = work["line"]
    l5 = _num_series(work, "stat_last5_avg")
    seas = _num_series(work, "stat_season_avg")
    proj = l5.fillna(seas).fillna(line)
    edge = proj - line

    hr5 = _num_series(work, "line_hit_rate_over_ou_5")
    hr10 = _num_series(work, "line_hit_rate_over_ou_10")
    hr10 = hr10.fillna(hr5)
    composite_hr = (0.5 * hr5.fillna(0.5) + 0.5 * hr10.fillna(0.5)).clip(0.0, 1.0)

    pick = work.get("pick_type", pd.Series(["Standard"] * len(work))).fillna("Standard").astype(str)
    forced = pick.map(_forced_over_only).astype(int)
    bet_dir = np.where(forced.eq(1), "OVER", np.where(edge >= 0, "OVER", "UNDER"))

    course_fit = _num_series(work, "course_fit_score", default=0.0).fillna(0.0).clip(-1.0, 1.0)
    sg_bonus = (
        _num_series(work, "sg_ott", default=0.0).fillna(0.0)
        + _num_series(work, "sg_app", default=0.0).fillna(0.0)
        + _num_series(work, "sg_arg", default=0.0).fillna(0.0)
    ).clip(-3.0, 3.0) * 0.05

    edge_z = (edge.abs().clip(0, 6) / 6.0).fillna(0.0)
    rank_score = (
        3.5
        + composite_hr * 5.0
        + edge_z * 1.5
        + course_fit * 0.4
        + sg_bonus
    ).clip(0.0, 10.0)

    work["rank_score"] = rank_score.round(4)
    work["projection"] = proj.round(4)
    work["edge"] = edge.round(4)
    work["abs_edge"] = edge.abs().round(4)
    work["composite_hit_rate"] = composite_hr.round(4)
    work["line_hit_rate"] = composite_hr.round(4)
    work["line_hit_rate_over_ou_5"] = hr5
    work["line_hit_rate_over_ou_10"] = hr10
    work["stat_last5_avg"] = l5
    work["stat_season_avg"] = seas
    work["ml_prob"] = (0.40 + 0.25 * composite_hr).clip(0.38, 0.78).round(4)
    work["pick_type"] = pick
    work["bet_direction"] = bet_dir
    work["final_bet_direction"] = bet_dir
    work["sport"] = "Golf"
    if "league" not in work.columns or work["league"].astype(str).str.strip().eq("").all():
        work["league"] = "PGA"
    work["league"] = work["league"].fillna("PGA").astype(str)
    event = work.get("event", work.get("tournament", pd.Series("", index=work.index)))
    if "team" not in work.columns or work["team"].astype(str).str.strip().eq("").all():
        work["team"] = event.fillna("").astype(str)
    if "event" not in work.columns:
        work["event"] = event.fillna("").astype(str)
    if "tournament" not in work.columns:
        work["tournament"] = work.get("event", "").fillna("").astype(str)
    if "course" not in work.columns:
        work["course"] = ""
    if "opp_team" not in work.columns:
        work["opp_team"] = work["course"].fillna("").astype(str)
    if "pos" not in work.columns:
        work["pos"] = ""
    if "pp_projection_id" not in work.columns:
        work["pp_projection_id"] = work.get("projection_id", "").fillna("").astype(str)
    # Individual sport — no opponent D. N/A is skipped in badges, not a miss.
    work["DEF_TIER"] = "N/A"
    work["OVERALL_DEF_RANK"] = "N/A"

    work = apply_ml_rank_blend(
        work,
        rank_col="rank_score",
        composite_hr_col="composite_hit_rate",
        label="Golf step7",
    )
    apply_consistency_grade_scores(work, "Golf")
    work["tier"] = assign_tier_column(work, sport="golf")
    report_goblin_demon_standard_line_fill(work, "[Golf step7]")
    print_tier_distribution_by_pick_direction_group(work, label="[Golf step7]")

    g1 = int(pd.to_numeric(work.get("stat_g1"), errors="coerce").notna().sum()) if "stat_g1" in work.columns else 0
    print(f"[Golf step7] stat_g1 fill={g1}/{len(work)}")

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    write_excel_sheets(out_path, {"ALL": work})
    write_parquet_sidecar(work, out_path)
    print(f"[Golf step7] Saved → {out_path}  rows={len(work)}")


if __name__ == "__main__":
    main()
