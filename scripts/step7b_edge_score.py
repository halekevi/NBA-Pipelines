#!/usr/bin/env python3
"""Apply unified edge model scores to step7 ranked workbook (daily, post-step7).

Writes ml_prob, edge_score, blended_score into the step7 xlsx (primary sheet). Run this
before step8 / slate grading so Box Raw exports can include those columns (slate_grader
and nhl_soccer_grader pass them through when present).
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import edge_ml_bundle  # noqa: F401 — EdgeCalibratedModel pickle root
from edge_feature_engineering import _direction_series, build_feature_vector
from edge_predict_utils import apply_ml_prob_post_calibration, load_unified_edge_model

SCRIPT_NAME = "step7b_edge_score"

SPORT_ALIASES = {"NBA", "CBB", "CFB", "NHL", "SOCCER", "MLB", "SOC", "NBA1H", "NBA1Q", "WCBB", "TENNIS", "WNBA", "NFL"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _norm_sport(s: str) -> str:
    x = str(s or "").strip().upper()
    if x == "SOC":
        return "SOCCER"
    if x in ("NBA1H", "NBA1Q"):
        return "NBA"
    if x == "WCBB":
        return "CBB"
    return x


def _is_zip_xlsx(path: Path) -> bool:
    """True if path looks like a real .xlsx (OOXML zip), not an HTML stub or empty file."""
    try:
        if not path.is_file() or path.stat().st_size < 64:
            return False
        with path.open("rb") as fh:
            return fh.read(2) == b"PK"
    except OSError:
        return False


def resolve_step7_path(root: Path, sport: str, pipeline_date: str = "") -> Path | None:
    sp = _norm_sport(sport)
    raw_sp = str(sport or "").strip().upper()
    sl = sp.lower()
    Sr = root / "Sports"
    candidates: list[Path] = []

    if raw_sp == "NBA1Q":
        candidates = [
            Sr / "NBA" / "data" / "outputs" / "step7_nba1q_ranked_props.xlsx",
            Sr / "NBA" / "step7_nba1q_ranked_props.xlsx",
            root / "NBA" / "data" / "outputs" / "step7_nba1q_ranked_props.xlsx",
            root / "NBA" / "step7_nba1q_ranked_props.xlsx",
        ]
    elif raw_sp == "NBA1H":
        candidates = [
            Sr / "NBA" / "data" / "outputs" / "step7_nba1h_ranked_props.xlsx",
            Sr / "NBA" / "step7_nba1h_ranked_props.xlsx",
            root / "NBA" / "data" / "outputs" / "step7_nba1h_ranked_props.xlsx",
            root / "NBA" / "step7_nba1h_ranked_props.xlsx",
        ]
    elif raw_sp == "WCBB":
        candidates = [
            Sr / "CBB" / "outputs" / "step6_ranked_wcbb.xlsx",
            Sr / "CBB" / "step6_ranked_wcbb.xlsx",
            root / "CBB" / "step6_ranked_wcbb.xlsx",
            root / "CBB" / "outputs" / "step6_ranked_wcbb.xlsx",
        ]
    elif sp == "MLB":
        mlb_root = root / "Sports" / "MLB"
        candidates = [
            mlb_root / "step7_mlb_ranked.xlsx",
            mlb_root / "outputs" / "step7_mlb_ranked.xlsx",
            mlb_root / "scripts" / "step7_mlb_ranked.xlsx",
        ]
    elif sp == "WNBA":
        candidates = [
            Sr / "WNBA" / "outputs" / "step7_wnba_ranked.xlsx",
            Sr / "WNBA" / "step7_wnba_ranked.xlsx",
            root / "WNBA" / "outputs" / "step7_wnba_ranked.xlsx",
            root / "WNBA" / "step7_wnba_ranked.xlsx",
        ]
    elif sp == "NFL":
        candidates = [
            root / "NFL" / "outputs" / "step7_nfl_ranked.xlsx",
            root / "NFL" / "data" / "outputs" / "step7_nfl_ranked.xlsx",
        ]
    elif sp == "NHL":
        candidates = [
            Sr / "NHL" / f"step7_{sl}_ranked.xlsx",
            Sr / "NHL" / "outputs" / f"step7_{sl}_ranked.xlsx",
            root / "NHL" / f"step7_{sl}_ranked.xlsx",
            root / "NHL" / "outputs" / f"step7_{sl}_ranked.xlsx",
        ]
    elif sp == "SOCCER":
        candidates = [
            Sr / "Soccer" / "outputs" / "step7_soccer_ranked.xlsx",
            Sr / "Soccer" / "step7_soccer_ranked.xlsx",
            root / "Soccer" / "outputs" / "step7_soccer_ranked.xlsx",
            root / "Soccer" / "step7_soccer_ranked.xlsx",
        ]
    elif sp == "TENNIS":
        candidates: list[Path] = []
        pd_str = str(pipeline_date or "").strip()[:10]
        if pd_str:
            candidates.append(root / "outputs" / pd_str / "tennis" / "step7_tennis_ranked.xlsx")
        out_glob = sorted(
            (root / "outputs").glob("*/tennis/step7_tennis_ranked.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates.extend(out_glob)
        candidates.extend([
            Sr / "Tennis" / "outputs" / "step7_tennis_ranked.xlsx",
            Sr / "Tennis" / "step7_tennis_ranked.xlsx",
            root / "Tennis" / "outputs" / "step7_tennis_ranked.xlsx",
        ])
    elif sp == "CFB":
        out_glob = sorted(
            (root / "outputs").glob("*/cfb/step6_ranked_cfb.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates = list(out_glob) + [
            Sr / "CFB" / "step6_ranked_cfb.xlsx",
            root / "Sports" / "CFB" / "step6_ranked_cfb.xlsx",
            root / "CFB" / "step6_ranked_cfb.xlsx",
        ]
    elif sp == "CBB":
        candidates = [
            Sr / "CBB" / "outputs" / f"step7_{sl}_ranked.xlsx",
            Sr / "CBB" / "outputs" / "step6_ranked_cbb.xlsx",
            Sr / "CBB" / "step6_ranked_cbb.xlsx",
            root / "CBB" / "outputs" / f"step7_{sl}_ranked.xlsx",
            root / "CBB" / "outputs" / "step6_ranked_cbb.xlsx",
            root / "CBB" / "step6_ranked_cbb.xlsx",
        ]
    elif sp == "NBA" and raw_sp == "NBA":
        candidates = [
            Sr / "NBA" / "data" / "outputs" / "step7_ranked_props.xlsx",
            Sr / "NBA" / "outputs" / "step7_nba_ranked.xlsx",
            root / "NBA" / "data" / "outputs" / "step7_ranked_props.xlsx",
            root / "NBA" / "outputs" / "step7_nba_ranked.xlsx",
        ]
    else:
        candidates = [
            root / sp / "outputs" / f"step7_{sl}_ranked.xlsx",
            Sr / sp / "outputs" / f"step7_{sl}_ranked.xlsx",
        ]

    for p in candidates:
        if p.is_file() and _is_zip_xlsx(p):
            return p
    return None


def _first_sheet(path: Path) -> str:
    # Pandas 2.2+ / Py3.14: engine must be explicit for .xlsx (otherwise ValueError).
    xl = pd.ExcelFile(path, engine="openpyxl")
    return xl.sheet_names[0]


def score_step7_workbook(
    *,
    root: Path,
    sport_label: str,
    model,
    feats: list[str],
    step7_xlsx: str = "",
    pipeline_date: str = "",
    skip_if_unified: bool = False,
) -> bool:
    """Score one sport's step7 workbook. Returns True if rows were scored."""
    sp = _norm_sport(sport_label)
    feat_sp = "MLB" if sp == "NFL" else sp
    cal_sp = sp
    if sp not in SPORT_ALIASES and sp != "SOCCER":
        print(f"[WARN] Unknown sport {sport_label!r}, proceeding with key {sp!r}")

    mdir = root / "models"
    xlsx: Path | None = None
    explicit_step7 = str(step7_xlsx or "").strip()
    if explicit_step7:
        p = Path(explicit_step7)
        if not p.is_absolute():
            p = (root / p).resolve()
        if p.is_file():
            xlsx = p
        else:
            print(f"[WARN] --step7-xlsx not found: {p} — skip (no stale fallback)")
            return False
    if xlsx is None:
        xlsx = resolve_step7_path(root, str(sport_label).strip().upper(), str(pipeline_date or "").strip())
    if xlsx is None:
        print(f"[WARN] No step7 workbook found for sport={sp} — skip.")
        return False

    sheet = _first_sheet(xlsx)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        df = pd.read_excel(xlsx, sheet_name=sheet, engine="openpyxl")
    if df.empty:
        print(f"[WARN] Empty sheet {sheet!r} in {xlsx} — skip.")
        return False

    if skip_if_unified and "prob_source" in df.columns and "ml_prob" in df.columns:
        src = df["prob_source"].astype(str).str.strip().str.lower()
        ml_ok = pd.to_numeric(df["ml_prob"], errors="coerce").notna()
        if bool(((src == "ml_prob_unified") & ml_ok).mean() > 0.5):
            print(f"  [step7b] {sp}: already unified — skip re-score ({xlsx.name})")
            return False

    if "void_reason" in df.columns:
        eligible_mask = df["void_reason"].isna() | (df["void_reason"].astype(str).str.strip() == "")
    else:
        eligible_mask = pd.Series(True, index=df.index)
    n_eligible = int(eligible_mask.sum())
    n_total = len(df)
    if n_eligible < n_total:
        print(f"  [step7b] {sp}: scoring {n_eligible}/{n_total} eligible rows")
    if n_eligible == 0:
        print(f"[WARN] 0 eligible rows for {sp} — skip.")
        return False

    eligible_df = df.loc[eligible_mask].copy()

    preserve_cols = [
        "minutes_tier",
        "shot_role",
        "usage_role",
        "min_player_avg",
        "fga_player_avg",
        "pts_player_avg",
    ]
    preserved = {c: eligible_df[c].copy() for c in preserve_cols if c in eligible_df.columns}

    df2 = build_feature_vector(eligible_df, feat_sp)
    if len(df2) == 0:
        print(f"[WARN] 0 rows after feature build for {sp} (feat={feat_sp}) — skip.")
        return False

    missing = [c for c in feats if c not in df2.columns]
    if missing:
        print(f"[WARN] Missing {len(missing)} feature cols for {sp} — filling with 0.0: {missing[:8]}")
        for col in missing:
            df2[col] = 0.0

    X = df2[feats].astype(float)
    p_platt = np.asarray(model.predict_proba(X)[:, 1], dtype=float)
    dirs_u = _direction_series(df2).astype(str).str.strip().str.upper()
    pt_l = df2.get("pick_type", pd.Series("", index=df2.index)).astype(str).str.strip().str.lower()
    ml_prob = apply_ml_prob_post_calibration(p_platt, cal_sp, pt_l, dirs_u, mdir)
    edge_col = pd.to_numeric(df2.get("edge", pd.Series(0.0, index=df2.index)), errors="coerce").fillna(0.0)
    abs_edge_col = pd.to_numeric(df2.get("abs_edge", pd.Series(np.nan, index=df2.index)), errors="coerce")
    signed_edge = edge_col.where(dirs_u.eq("OVER"), -edge_col)
    edge_mag = abs_edge_col.where(abs_edge_col.notna(), signed_edge.abs()).fillna(0.0)
    implied_prob = 1.0 / (1.0 + np.exp(-edge_mag.clip(-20, 20)))
    comp = pd.to_numeric(
        df2.get("composite_hit_rate", df2.get("line_hit_rate", pd.Series(0.5, index=df2.index))),
        errors="coerce",
    ).fillna(0.5)
    if sp in ("NBA", "WNBA") and "l5_vs_same_opp_hit_rate" in df2.columns:
        opp_l5 = pd.to_numeric(df2["l5_vs_same_opp_hit_rate"], errors="coerce")
        opp_l5 = pd.Series(np.where(opp_l5 > 1.0, opp_l5 / 100.0, opp_l5), index=df2.index)
        playoff = (
            df2.get("is_playoff_game", pd.Series(False, index=df2.index))
            .astype(str)
            .str.strip()
            .str.lower()
            .isin(["1", "true", "t", "yes", "y"])
        )
        use_opp_l5 = playoff & opp_l5.notna()
        if use_opp_l5.any():
            comp = pd.Series(np.where(use_opp_l5, (0.55 * comp + 0.45 * opp_l5), comp), index=df2.index)
    if sp == "MLB":
        src_col = (
            "l5_vs_same_opp_hit_rate"
            if "l5_vs_same_opp_hit_rate" in df2.columns
            else ("same_series_hit_rate" if "same_series_hit_rate" in df2.columns else "")
        )
        if src_col:
            opp_l5 = pd.to_numeric(df2[src_col], errors="coerce")
            opp_l5 = pd.Series(np.where(opp_l5 > 1.0, opp_l5 / 100.0, opp_l5), index=df2.index)
            use_opp_l5 = opp_l5.notna()
            if use_opp_l5.any():
                comp = pd.Series(np.where(use_opp_l5, (0.70 * comp + 0.30 * opp_l5), comp), index=df2.index)

    if sp in ("NBA", "WNBA"):
        _def_pos = pd.to_numeric(
            df2.get("intel_opp_vs_league_pct_pos", pd.Series(np.nan, index=df2.index)),
            errors="coerce",
        )
        _def_pool = pd.to_numeric(
            df2.get("intel_opp_vs_league_pct", pd.Series(np.nan, index=df2.index)),
            errors="coerce",
        )
        _def_pct = _def_pos.combine_first(_def_pool)
        _def_known = _def_pct.notna()
        if _def_known.any():
            _def_norm = ((_def_pct.clip(-30, 30) / 30.0) + 1.0) / 2.0
            _def_norm = _def_norm.fillna(0.5)
            comp = pd.Series(
                np.where(_def_known, 0.85 * comp + 0.15 * _def_norm, comp),
                index=df2.index,
            )

    ml_s = pd.Series(ml_prob, index=df2.index, dtype=float)
    edge_score = ml_s - implied_prob
    if sp in ("NHL", "SOCCER", "NFL", "NBA", "WNBA"):
        blended = 0.15 * ml_s + 0.85 * comp
    else:
        blended = 0.3 * ml_s + 0.7 * comp

    for col in ("ml_prob", "edge_score", "blended_score"):
        if col not in df.columns:
            df[col] = np.nan
    df.loc[eligible_mask, "ml_prob"] = ml_s.values
    df.loc[eligible_mask, "edge_score"] = edge_score.values
    df.loc[eligible_mask, "blended_score"] = blended.values
    if "prob_source" not in df.columns:
        df["prob_source"] = ""
    df.loc[eligible_mask, "prob_source"] = "ml_prob_unified"
    for c, s in preserved.items():
        if len(s) == len(df2):
            df.loc[eligible_mask, c] = s.values
    if sp.upper() != "NHL":
        df = df.sort_values("blended_score", ascending=False, na_position="last", kind="mergesort")

    try:
        with pd.ExcelWriter(
            xlsx,
            engine="openpyxl",
            mode="a",
            if_sheet_exists="replace",
        ) as w:
            df.to_excel(w, sheet_name=sheet, index=False)
    except Exception:
        xl_obj = pd.ExcelFile(xlsx, engine="openpyxl")
        all_sheets: dict[str, pd.DataFrame] = {}
        for sn in xl_obj.sheet_names:
            if sn == sheet:
                all_sheets[sn] = df
            else:
                all_sheets[sn] = pd.read_excel(xlsx, sheet_name=sn, engine="openpyxl")
        with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
            for sn, frame in all_sheets.items():
                frame.to_excel(w, sheet_name=sn, index=False)

    print(f"  Scored {n_eligible} eligible / {n_total} rows for {sp} -> {xlsx} (sheet={sheet!r})")
    top = df.head(5)
    pc = next((c for c in ("player_name", "player", "pp_player") if c in top.columns), None)
    prop_c = next((c for c in ("prop_norm", "prop_type", "stat_norm") if c in top.columns), None)
    for rank, (_, row) in enumerate(top.iterrows(), start=1):
        label = ""
        if pc:
            label += f" {row.get(pc, '')}"
        if prop_c:
            label += f" | {row.get(prop_c, '')}"
        print(f"    #{rank} blended={float(row['blended_score']):.4f}{label}")
    return True


def main() -> None:
    print(f"[PropORACLE-{SCRIPT_NAME}] Starting...")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="", help="NBA, WNBA, CBB, NHL, Soccer, MLB, Tennis, …")
    ap.add_argument(
        "--sports",
        default="",
        help="Comma-separated sports to score in one process (warm model cache). Example: MLB,WNBA,Tennis",
    )
    ap.add_argument(
        "--step7-xlsx",
        default="",
        help="Optional full path to step7 workbook (single --sport only).",
    )
    ap.add_argument("--repo-root", type=Path, default=None)
    ap.add_argument(
        "--pipeline-date",
        default="",
        help="Bundle folder date (YYYY-MM-DD) for outputs/<date>/ sport paths; use pipeline -Date, not tennis slate day.",
    )
    ap.add_argument(
        "--skip-if-unified",
        action="store_true",
        help="Skip sports already tagged prob_source=ml_prob_unified.",
    )
    args = ap.parse_args()
    root = Path(args.repo_root).resolve() if args.repo_root else _repo_root()

    sports: list[str] = []
    for part in str(args.sports or "").split(","):
        p = part.strip()
        if p:
            sports.append(p)
    single = str(args.sport or "").strip()
    if single:
        sports.insert(0, single)
    # de-dupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for s in sports:
        key = s.upper()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(s)
    if not ordered:
        ap.error("Provide --sport or --sports")

    mdir = root / "models"
    loaded = load_unified_edge_model(mdir)
    if loaded is None:
        print(f"[WARN] Edge model not found ({mdir / 'edge_model_unified.pkl'}) — skipping scoring.")
        return
    model, feats = loaded

    explicit = str(args.step7_xlsx or "").strip()
    if explicit and len(ordered) > 1:
        print("[WARN] --step7-xlsx applies only to the first sport when using --sports")

    n_ok = 0
    for i, sport_label in enumerate(ordered):
        ok = score_step7_workbook(
            root=root,
            sport_label=sport_label,
            model=model,
            feats=feats,
            step7_xlsx=explicit if i == 0 else "",
            pipeline_date=str(args.pipeline_date or "").strip(),
            skip_if_unified=bool(args.skip_if_unified),
        )
        if ok:
            n_ok += 1
    if len(ordered) > 1:
        print(f"[step7b] multi-sport done: {n_ok}/{len(ordered)} scored (model kept warm)")


if __name__ == "__main__":
    main()
