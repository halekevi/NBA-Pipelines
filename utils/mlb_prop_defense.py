"""MLB prop-specific opponent pitching/defense ranks.

Source: Sports/MLB/mlb_defense_summary.csv (ERA / WHIP / OBP allowed ranks).
Hitter props map to pitching allowed; pitcher props use overall (or inverted matchup later).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from utils.prop_defense_common import (
    attach_lookup_columns,
    coarse_bucket_from_rank,
    empty_stat_def,
)

# Prop label / norm -> category (rank col = f"{cat}_rank")
PROP_TO_CAT: dict[str, str] = {
    # Contact / on-base → OBP allowed
    "Hits": "obp",
    "hits": "obp",
    "Hits Allowed": "obp",
    "hits_allowed": "obp",
    "Total Bases": "obp",
    "total_bases": "obp",
    "Walks": "obp",
    "walks": "obp",
    "Batter Walks": "obp",
    "Hitter Fantasy Score": "obp",
    "hitter_fantasy_score": "obp",
    # Power → ERA / run prevention (overall)
    "Home Runs": "era",
    "home_runs": "era",
    "HR": "era",
    "RBIs": "era",
    "rbis": "era",
    "Runs": "era",
    "runs": "era",
    "Hits+Runs+RBIs": "era",
    "hitter_hrr": "era",
    "HRR": "era",
    # Ks / pitcher dominance → WHIP / K environment proxy via WHIP
    "Pitcher Strikeouts": "whip",
    "pitcher_strikeouts": "whip",
    "Strikeouts": "whip",
    "strikeouts": "whip",
    "Pitcher Outs": "whip",
    "pitching_outs": "whip",
    "Outs": "whip",
    "Earned Runs Allowed": "era",
    "earned_runs_allowed": "era",
    "ERA Allowed": "era",
    "Hits Allowed": "obp",
    "Walks Allowed": "obp",
    "Pitcher Fantasy Score": "whip",
    "pitcher_fantasy_score": "whip",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_csv_path() -> Path:
    return _repo_root() / "Sports" / "MLB" / "data" / "mlb_defense_by_stat.csv"


def prop_category(prop: object) -> str:
    p = str(prop or "").strip()
    if p in PROP_TO_CAT:
        return PROP_TO_CAT[p]
    key = " ".join(p.replace("_", " ").replace("-", " ").split())
    for label, cat in PROP_TO_CAT.items():
        if label.lower() == key.lower():
            return cat
    return PROP_TO_CAT.get(key.lower().replace(" ", "_"), "")


def _tier_label(rank: float, n_teams: int) -> str:
    q = max(n_teams / 5.0, 1.0)
    if rank <= q:
        return "HARD"
    if rank <= 2 * q:
        return "HARD_MID"
    if rank <= 3 * q:
        return "MID"
    if rank <= 4 * q:
        return "EASY_MID"
    return "EASY"


def rebuild_defense_by_stat(out_path: Optional[Path] = None) -> pd.DataFrame:
    src = _repo_root() / "Sports" / "MLB" / "mlb_defense_summary.csv"
    out_path = Path(out_path or default_csv_path())
    if not src.is_file():
        return pd.DataFrame()
    df = pd.read_csv(src, encoding="utf-8-sig")
    if df.empty:
        return df
    work = df.copy()
    team_col = "TEAM_ABBREVIATION" if "TEAM_ABBREVIATION" in work.columns else "team"
    work["team"] = work[team_col].astype(str).str.strip().str.upper()
    # ATH / AZ aliases
    alias = {"ATH": "OAK", "AZ": "ARI", "WAS": "WSH", "CWS": "CHW"}
    work["team"] = work["team"].map(lambda t: alias.get(t, t))

    n = len(work)
    work["era_rank"] = pd.to_numeric(work.get("ERA_RANK", work.get("era_rank")), errors="coerce")
    work["whip_rank"] = pd.to_numeric(work.get("WHIP_RANK", work.get("whip_rank")), errors="coerce")
    work["obp_rank"] = pd.to_numeric(
        work.get("OBP_ALLOWED_RANK", work.get("obp_rank")), errors="coerce"
    )
    work["overall_rank"] = pd.to_numeric(
        work.get("OVERALL_DEF_RANK", work.get("def_rank", work.get("overall_rank"))),
        errors="coerce",
    )
    for cat in ("era", "whip", "obp"):
        work[f"{cat}_tier"] = work[f"{cat}_rank"].map(
            lambda r: _tier_label(float(r), n) if pd.notna(r) else ""
        )
    work["n_teams"] = n
    keep = [
        "team",
        "n_teams",
        "overall_rank",
        "era_rank",
        "era_tier",
        "whip_rank",
        "whip_tier",
        "obp_rank",
        "obp_tier",
        "SP_ERA",
        "WHIP",
        "OBP_ALLOWED",
        "DEF_TIER",
    ]
    out = work[[c for c in keep if c in work.columns]].drop_duplicates(subset=["team"], keep="first")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


@lru_cache(maxsize=4)
def load_defense_table(csv_path: str = "") -> pd.DataFrame:
    path = Path(csv_path) if csv_path else default_csv_path()
    if not path.is_file() or path.stat().st_size < 50:
        rebuild_defense_by_stat(out_path=path)
    if not path.is_file():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()
    if "team" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["team"] = df["team"].astype(str).str.strip().str.upper()
    return df


def clear_defense_cache() -> None:
    load_defense_table.cache_clear()


def lookup_stat_defense(opp: object, prop: object, *, csv_path: str = "") -> dict:
    cat = prop_category(prop)
    team = str(opp or "").strip().upper()
    alias = {"ATH": "OAK", "AZ": "ARI", "WAS": "WSH", "CWS": "CHW", "OAK": "OAK"}
    team = alias.get(team, team)
    empty = empty_stat_def(cat)
    if not cat or not team:
        return empty
    df = load_defense_table(csv_path)
    if df.empty:
        return empty
    sub = df[df["team"] == team]
    if sub.empty:
        return empty
    row = sub.iloc[0]
    rank_col = f"{cat}_rank"
    rank = None
    if rank_col in row.index and pd.notna(row[rank_col]):
        try:
            rank = int(float(row[rank_col]))
        except (TypeError, ValueError):
            rank = None
    n_teams = int(row["n_teams"]) if "n_teams" in row.index and pd.notna(row.get("n_teams")) else len(df)
    coarse = coarse_bucket_from_rank(rank, n_teams) if rank is not None else "UNK"
    return {
        "stat_def_category": cat,
        "stat_def_rank": rank,
        "stat_def_tier": coarse,
        "stat_def_coarse": coarse,
    }


def attach_stat_defense_columns(df: pd.DataFrame, *, csv_path: str = "") -> pd.DataFrame:
    return attach_lookup_columns(
        df,
        sport="MLB",
        lookup_fn=lambda opp, prop: lookup_stat_defense(opp, prop, csv_path=csv_path),
    )
