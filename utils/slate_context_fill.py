"""Fill slate context columns when upstream step8 left them blank."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

_MIN_TIER_NUM_MAP = {0: "LOW", 1: "MEDIUM", 2: "HIGH", 3: "HIGH"}
_MIN_TIER_STR_MAP = {
    "0": "LOW",
    "1": "MEDIUM",
    "2": "HIGH",
    "3": "HIGH",
    "LOW": "LOW",
    "MED": "MEDIUM",
    "MEDIUM": "MEDIUM",
    "HIGH": "HIGH",
    "ELITE": "ELITE",
}


def fill_min_tier_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Restore HIGH/MEDIUM/LOW(/ELITE) from labels or 0–3 codes into min_tier."""
    out = df.copy()
    n = len(out)
    label = pd.Series([""] * n, index=out.index, dtype=object)
    for col in ("minutes_tier_label", "min_tier", "Min Tier", "minutes_tier"):
        if col not in out.columns:
            continue
        raw = out[col]
        raw_u = raw.astype(str).str.strip().str.upper().replace({"NAN": "", "NONE": "", "<NA>": ""})
        mapped = raw_u.map(_MIN_TIER_STR_MAP)
        num = pd.to_numeric(raw, errors="coerce")
        from_num = num.round().astype("Int64").map(_MIN_TIER_NUM_MAP)
        cand = mapped.where(mapped.isin(["LOW", "MEDIUM", "HIGH", "ELITE"]), from_num)
        empty = label.eq("") | label.isna()
        label = label.where(~empty, cand)
    ok = label.isin(["LOW", "MEDIUM", "HIGH", "ELITE"])
    out["min_tier"] = label.where(ok, pd.NA)
    if "minutes_tier" in out.columns:
        out["minutes_tier"] = out["min_tier"]
    return out


def fill_cv_pct_if_missing(df: pd.DataFrame, *, min_games: int = 3) -> pd.DataFrame:
    """CV% = std/mean of G1–G10 / stat_g1–g10. Only fills blank cells."""
    out = df.copy()
    gcols = [c for c in (f"stat_g{i}" for i in range(1, 11)) if c in out.columns]
    if not gcols:
        gcols = [c for c in (f"G{i}" for i in range(1, 11)) if c in out.columns]
    existing = pd.to_numeric(out["cv_pct"], errors="coerce") if "cv_pct" in out.columns else pd.Series(np.nan, index=out.index)
    if not gcols:
        out["cv_pct"] = existing
        return out
    g = out[gcols].apply(pd.to_numeric, errors="coerce")
    n = g.notna().sum(axis=1)
    mean = g.mean(axis=1)
    std = g.std(axis=1, ddof=0)
    cv = (std / mean.replace(0, np.nan)) * 100.0
    cv = cv.where(n.ge(min_games) & mean.gt(0), np.nan).round(1)
    out["cv_pct"] = existing.combine_first(cv)
    return out


def summarize_board_context_fill(df: pd.DataFrame) -> dict[str, int]:
    """Counts for daily Combined logs: L5 / CV% / Min Tier vs rows with game logs."""
    n = 0 if df is None else int(len(df))
    if df is None or n == 0:
        return {"rows": 0, "l5": 0, "cv": 0, "min_tier": 0, "g3": 0}
    l5 = pd.to_numeric(df["l5_over"], errors="coerce") if "l5_over" in df.columns else pd.Series(np.nan, index=df.index)
    cv = pd.to_numeric(df["cv_pct"], errors="coerce") if "cv_pct" in df.columns else pd.Series(np.nan, index=df.index)
    mt = df["min_tier"] if "min_tier" in df.columns else pd.Series(pd.NA, index=df.index)
    mt_txt = mt.astype(str).str.strip().str.upper()
    mt_ok = mt.notna() & ~mt_txt.isin(["", "NAN", "NONE", "<NA>"])
    gcols = [c for c in (f"stat_g{i}" for i in range(1, 6)) if c in df.columns]
    g3 = int((df[gcols].apply(pd.to_numeric, errors="coerce").notna().sum(axis=1) >= 3).sum()) if gcols else 0
    return {
        "rows": n,
        "l5": int(l5.notna().sum()),
        "cv": int(cv.notna().sum()),
        "min_tier": int(mt_ok.sum()),
        "g3": g3,
    }


def _norm_txt(v: object) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def _norm_pick_type_label(x: object) -> str:
    t = str(x or "").strip().lower()
    if "gob" in t:
        return "Goblin"
    if "dem" in t:
        return "Demon"
    return "Standard"


def is_pitcher_strikeout_row(row: pd.Series | dict) -> bool:
    """True when the market is pitcher Ks (not hitter/batter Ks)."""
    if isinstance(row, dict):
        prop = row.get("prop_type") or row.get("prop") or row.get("prop_norm") or ""
        ptype = row.get("player_type") or row.get("player_type_norm") or row.get("pos") or ""
    else:
        prop = row.get("prop_type") or row.get("prop") or row.get("prop_norm") or ""
        ptype = row.get("player_type") or row.get("player_type_norm") or row.get("pos") or ""
    p = _norm_txt(prop)
    compact = "".join(ch for ch in p if ch.isalnum())
    if "hitter" in p or "batter" in p:
        return False
    pt = _norm_txt(ptype)
    if "hitter" in pt or "batter" in pt:
        return False
    is_k = (
        "strikeout" in p
        or compact in {"ks", "so", "k", "pitchingstrikeouts", "pitcherstrikeouts"}
    )
    if not is_k:
        return False
    if "pitch" in pt or pt in {"p", "sp", "rp", "cp", "lhp", "rhp"}:
        return True
    return "hitter" not in p and "batter" not in p


def strip_pitcher_ks_hitter_defense(df: pd.DataFrame) -> pd.DataFrame:
    """Pitcher Ks face opposing bats, not opposing 'defense' rank/tier (hitter D)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    mask = out.apply(is_pitcher_strikeout_row, axis=1)
    if not bool(mask.any()):
        return out
    for col in (
        "opponent_def_rank",
        "opp_def_rank",
        "OVERALL_DEF_RANK",
        "def_rank",
        "def_tier",
        "DEF_TIER",
        "opponent_def_tier",
    ):
        if col in out.columns:
            out.loc[mask, col] = pd.NA
    return out


def overlay_live_step1_board(df: pd.DataFrame, step1: pd.DataFrame) -> pd.DataFrame:
    """Prefer live PrizePicks line + pick_type from latest step1 onto step8 rows.

    Match projection_id when present, else player+prop (and pick_type when unique).
    Goblin/Demon live cards force OVER (PP alt markets are More-only).
    """
    if df is None or df.empty or step1 is None or step1.empty:
        return df
    out = df.copy()
    s1 = step1.copy()
    for col in ("player", "prop_type", "pick_type", "line"):
        if col not in s1.columns:
            if col == "prop_type" and "prop" in s1.columns:
                s1["prop_type"] = s1["prop"]
            elif col == "pick_type" and "pick" in s1.columns:
                s1["pick_type"] = s1["pick"]
    if "player" not in s1.columns or "prop_type" not in s1.columns:
        return out
    if "pick_type" in s1.columns:
        s1["pick_type"] = s1["pick_type"].map(_norm_pick_type_label)
    s1["_p"] = s1["player"].map(_norm_txt)
    s1["_pr"] = s1["prop_type"].map(_norm_txt)
    s1["_line"] = pd.to_numeric(s1.get("line"), errors="coerce")

    live_by_id: dict[str, pd.Series] = {}
    id_col = next((c for c in ("projection_id", "pp_projection_id") if c in s1.columns), None)
    if id_col:
        for _, r in s1.iterrows():
            kid = str(r.get(id_col) or "").strip()
            if kid and kid.lower() not in {"nan", "none", ""}:
                live_by_id[kid] = r

    groups: dict[tuple[str, str], pd.DataFrame] = {}
    for (p, pr), g in s1.groupby(["_p", "_pr"], dropna=False):
        groups[(str(p), str(pr))] = g

    out_id = None
    for c in ("projection_id", "pp_projection_id"):
        if c in out.columns:
            out_id = c
            break

    for idx, row in out.iterrows():
        live = None
        if out_id is not None:
            kid = str(row.get(out_id) or "").strip()
            live = live_by_id.get(kid)
        if live is None:
            key = (_norm_txt(row.get("player")), _norm_txt(row.get("prop_type") or row.get("prop")))
            g = groups.get(key)
            if g is None or g.empty:
                continue
            if len(g) == 1:
                live = g.iloc[0]
            else:
                pt = _norm_pick_type_label(row.get("pick_type"))
                same_pt = g[g["pick_type"].astype(str) == pt] if "pick_type" in g.columns else g.iloc[0:0]
                if len(same_pt) == 1:
                    live = same_pt.iloc[0]
                else:
                    live_pts = set(g["pick_type"].astype(str).tolist()) if "pick_type" in g.columns else set()
                    if pt == "Standard" and live_pts and live_pts.isdisjoint({"Standard"}):
                        live = g.iloc[0]
                    else:
                        line = pd.to_numeric(pd.Series([row.get("line")]), errors="coerce").iloc[0]
                        if pd.notna(line) and "_line" in g.columns:
                            near = g[np.isclose(g["_line"].fillna(-999), float(line), atol=0.05)]
                            if len(near) >= 1:
                                live = near.iloc[0]
                        if live is None:
                            live = g.iloc[0]
        if live is None:
            continue
        live_line = pd.to_numeric(pd.Series([live.get("line")]), errors="coerce").iloc[0]
        live_pt = _norm_pick_type_label(live.get("pick_type"))
        if pd.notna(live_line):
            out.at[idx, "line"] = float(live_line)
        if live_pt:
            out.at[idx, "pick_type"] = live_pt
        if live_pt in ("Goblin", "Demon"):
            out.at[idx, "direction"] = "OVER"
    return out


def tennis_total_games_over_blocked_by_l5(row: pd.Series | dict) -> bool:
    """Do not rank Total Games OVER when L5 is all under the current line."""
    if isinstance(row, dict):
        prop = row.get("prop_type") or row.get("prop") or ""
        direction = row.get("direction") or row.get("over_under") or ""
        l5o = row.get("l5_over")
        l5u = row.get("l5_under")
    else:
        prop = row.get("prop_type") or row.get("prop") or ""
        direction = row.get("direction") or row.get("over_under") or ""
        l5o = row.get("l5_over") if "l5_over" in row.index else None
        l5u = row.get("l5_under") if "l5_under" in row.index else None
    p = _norm_txt(prop)
    compact = "".join(ch for ch in p if ch.isalnum())
    if "games won" in p or compact in {"gameswon", "totalgameswon"}:
        return False
    if "total games" not in p and compact not in {"totalgames", "gamesplayed", "matchtotalgames"}:
        return False
    if str(direction or "").strip().upper() != "OVER":
        return False
    over_n = pd.to_numeric(pd.Series([l5o]), errors="coerce").iloc[0]
    under_n = pd.to_numeric(pd.Series([l5u]), errors="coerce").iloc[0]
    if pd.isna(over_n) or pd.isna(under_n):
        return False
    return float(over_n) <= 0.0 and float(under_n) >= 4.0


def flip_tennis_total_games_all_under(df: pd.DataFrame) -> pd.DataFrame:
    """If L5 vs current line is 0 over / ≥4 under, recommend UNDER not OVER."""
    if df is None or df.empty or "direction" not in df.columns:
        return df
    out = df.copy()
    for idx, row in out.iterrows():
        if tennis_total_games_over_blocked_by_l5(row):
            out.at[idx, "direction"] = "UNDER"
    return out
