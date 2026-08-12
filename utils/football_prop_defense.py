"""NFL/CFB prop-specific opponent defense ranks (pass / rush / points).

Uses pre-built ESPN unit rankings:
  - NFL: data/reference/nfl_team_defense.csv (+ sync Sports/NFL/data/defense_rankings.csv)
  - CFB: Sports/CFB/data/reference/cfb_team_unit_rankings.csv

Ranks: 1 = stingiest (fewest yards/points allowed) = HARD for OVER.
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

# Display / normalized prop labels -> defense category
PROP_TO_CAT: dict[str, str] = {
    # Pass attack vs pass D
    "Passing Yards": "pass",
    "passing_yards": "pass",
    "Pass Yards": "pass",
    "Passing TDs": "pass",
    "passing_tds": "pass",
    "Pass TDs": "pass",
    "Pass Completions": "pass",
    "pass_completions": "pass",
    "Completions": "pass",
    "Pass Attempts": "pass",
    "pass_attempts": "pass",
    "Passing Attempts": "pass",
    "Receiving Yards": "pass",
    "receiving_yards": "pass",
    "Rec Yards": "pass",
    "Receptions": "pass",
    "receptions": "pass",
    "Receiving TDs": "pass",
    "receiving_tds": "pass",
    # Rush attack vs rush D
    "Rushing Yards": "rush",
    "rushing_yards": "rush",
    "Rush Yards": "rush",
    "Rushing TDs": "rush",
    "rushing_tds": "rush",
    # Scoring / fantasy → points allowed
    "Touchdowns": "points",
    "touchdowns": "points",
    "TDs": "points",
    "Fantasy Score": "points",
    "fantasy_score": "points",
    "Kicking Points": "points",
    "kicking_points": "points",
    # Pressure / takeaways (team D rates)
    "Sacks": "sacks",
    "sacks": "sacks",
    "Interceptions": "to",
    "interceptions": "to",
    "Interceptions Thrown": "to",
    "interceptions_thrown": "to",
    "Tackles Assists": "points",
    "tackles_assists": "points",
    "Tackles + Assists": "points",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def prop_category(prop: object) -> str:
    p = str(prop or "").strip()
    if p in PROP_TO_CAT:
        return PROP_TO_CAT[p]
    key = " ".join(p.replace("_", " ").replace("-", " ").split())
    for label, cat in PROP_TO_CAT.items():
        if label.lower() == key.lower():
            return cat
    # snake fallbacks
    s = key.lower().replace(" ", "_")
    return PROP_TO_CAT.get(s, "")


def nfl_csv_path() -> Path:
    return _repo_root() / "Sports" / "NFL" / "data" / "nfl_defense_by_stat.csv"


def cfb_csv_path() -> Path:
    return _repo_root() / "Sports" / "CFB" / "data" / "cfb_defense_by_stat.csv"


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


def rebuild_nfl_defense_by_stat(out_path: Optional[Path] = None) -> pd.DataFrame:
    """Normalize reference NFL defense into by-stat rank table."""
    root = _repo_root()
    ref = root / "data" / "reference" / "nfl_team_defense.csv"
    legacy = root / "Sports" / "NFL" / "data" / "defense_rankings.csv"
    out_path = Path(out_path or nfl_csv_path())

    src = ref if ref.is_file() else legacy
    if not src.is_file():
        return pd.DataFrame()

    df = pd.read_csv(src, encoding="utf-8-sig")
    if df.empty:
        return df

    # Map either reference or legacy schema
    rename = {
        "team_abbr": "team",
        "opp_pass_ypg": "opp_pass",
        "opp_rush_ypg": "opp_rush",
        "points_allowed_pg": "opp_points",
        "pass_yards_allowed_pg": "opp_pass",
        "rush_yards_allowed_pg": "opp_rush",
        "pass_tds_allowed": "opp_pass_td",
    }
    work = df.rename(columns={k: v for k, v in rename.items() if k in df.columns}).copy()
    if "team" not in work.columns and "team_abbr" in df.columns:
        work["team"] = df["team_abbr"]
    work["team"] = work["team"].astype(str).str.strip().str.upper()

    n = len(work)
    # Prefer existing ranks; else rank from allowed yards (ascending = stingiest = 1)
    if "pass_def_rank" in work.columns:
        work["pass_rank"] = pd.to_numeric(work["pass_def_rank"], errors="coerce")
    elif "opp_pass" in work.columns:
        work["pass_rank"] = pd.to_numeric(work["opp_pass"], errors="coerce").rank(method="min", ascending=True)
    else:
        work["pass_rank"] = pd.NA

    if "rush_def_rank" in work.columns:
        work["rush_rank"] = pd.to_numeric(work["rush_def_rank"], errors="coerce")
    elif "opp_rush" in work.columns:
        work["rush_rank"] = pd.to_numeric(work["opp_rush"], errors="coerce").rank(method="min", ascending=True)
    else:
        work["rush_rank"] = pd.NA

    if "pa_rank" in work.columns:
        work["points_rank"] = pd.to_numeric(work["pa_rank"], errors="coerce")
    elif "opp_points" in work.columns:
        work["points_rank"] = pd.to_numeric(work["opp_points"], errors="coerce").rank(
            method="min", ascending=True
        )
    else:
        work["points_rank"] = pd.NA

    if "sacks_rank" in work.columns:
        # Low rank = more sacks (good D). For OVER on defender sacks this is EASY pressure.
        work["sacks_rank"] = pd.to_numeric(work["sacks_rank"], errors="coerce")
    else:
        work["sacks_rank"] = pd.NA

    if "to_rank" in work.columns:
        work["to_rank"] = pd.to_numeric(work["to_rank"], errors="coerce")
    else:
        work["to_rank"] = pd.NA

    for cat in ("pass", "rush", "points", "sacks", "to"):
        col = f"{cat}_rank"
        if col not in work.columns:
            continue
        work[f"{cat}_tier"] = work[col].map(
            lambda r: _tier_label(float(r), n) if pd.notna(r) else ""
        )

    work["overall_rank"] = work["points_rank"]
    work["n_teams"] = n

    keep = ["team", "n_teams", "overall_rank"]
    for cat in ("pass", "rush", "points", "sacks", "to"):
        for suffix in ("rank", "tier"):
            c = f"{cat}_{suffix}"
            if c in work.columns:
                keep.append(c)
    for c in ("opp_pass", "opp_rush", "opp_points", "sacks", "turnovers_forced", "season"):
        if c in work.columns:
            keep.append(c)

    out = work[[c for c in keep if c in work.columns]].drop_duplicates(subset=["team"], keep="first")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    # Keep legacy NFL path in sync with real ranks (pass/rush) for older readers.
    legacy_out = root / "Sports" / "NFL" / "data" / "defense_rankings.csv"
    try:
        leg = out.copy()
        by = work.drop_duplicates(subset=["team"]).set_index("team")
        leg["pass_yards_allowed_pg"] = leg["team"].map(
            by["opp_pass"] if "opp_pass" in by.columns else {}
        )
        leg["rush_yards_allowed_pg"] = leg["team"].map(
            by["opp_rush"] if "opp_rush" in by.columns else {}
        )
        leg["points_allowed_pg"] = leg["team"].map(
            by["opp_points"] if "opp_points" in by.columns else {}
        )
        leg["pass_tds_allowed"] = pd.NA
        legacy_df = leg.rename(
            columns={"pass_rank": "pass_def_rank", "rush_rank": "rush_def_rank"}
        )[
            [
                c
                for c in (
                    "team",
                    "pass_yards_allowed_pg",
                    "rush_yards_allowed_pg",
                    "pass_tds_allowed",
                    "points_allowed_pg",
                    "pass_def_rank",
                    "rush_def_rank",
                )
                if c in leg.columns or c in ("pass_def_rank", "rush_def_rank")
            ]
        ]
        # ensure renamed cols present
        if "pass_rank" in out.columns:
            legacy_df["pass_def_rank"] = out["pass_rank"].values
        if "rush_rank" in out.columns:
            legacy_df["rush_def_rank"] = out["rush_rank"].values
        legacy_out.parent.mkdir(parents=True, exist_ok=True)
        legacy_df.to_csv(legacy_out, index=False)
    except Exception:
        pass

    return out


def rebuild_cfb_defense_by_stat(out_path: Optional[Path] = None) -> pd.DataFrame:
    root = _repo_root()
    src = root / "Sports" / "CFB" / "data" / "reference" / "cfb_team_unit_rankings.csv"
    alt = root / "Sports" / "CFB" / "data" / "reference" / "cfb_def_rankings.csv"
    out_path = Path(out_path or cfb_csv_path())
    if not src.is_file():
        if alt.is_file():
            src = alt
        else:
            return pd.DataFrame()

    df = pd.read_csv(src, encoding="utf-8-sig")
    if df.empty:
        return df
    work = df.copy()
    if "team_abbr" in work.columns:
        work["team"] = work["team_abbr"].astype(str).str.strip().str.upper()
    elif "team" not in work.columns:
        return pd.DataFrame()

    n = len(work)
    # unit rankings schema
    if "def_pass_rank" in work.columns:
        work["pass_rank"] = pd.to_numeric(work["def_pass_rank"], errors="coerce")
    elif "pass_def_rank" in work.columns:
        work["pass_rank"] = pd.to_numeric(work["pass_def_rank"], errors="coerce")
    else:
        work["pass_rank"] = pd.NA

    if "def_rush_rank" in work.columns:
        work["rush_rank"] = pd.to_numeric(work["def_rush_rank"], errors="coerce")
    elif "rush_def_rank" in work.columns:
        work["rush_rank"] = pd.to_numeric(work["rush_def_rank"], errors="coerce")
    else:
        work["rush_rank"] = pd.NA

    if "def_points_rank" in work.columns:
        work["points_rank"] = pd.to_numeric(work["def_points_rank"], errors="coerce")
    elif "overall_rank" in work.columns:
        work["points_rank"] = pd.to_numeric(work["overall_rank"], errors="coerce")
    else:
        work["points_rank"] = pd.NA

    work["sacks_rank"] = pd.NA
    work["to_rank"] = pd.NA
    for cat in ("pass", "rush", "points"):
        work[f"{cat}_tier"] = work[f"{cat}_rank"].map(
            lambda r: _tier_label(float(r), n) if pd.notna(r) else ""
        )
    work["overall_rank"] = work["points_rank"]
    work["n_teams"] = n

    keep = [
        "team",
        "n_teams",
        "overall_rank",
        "pass_rank",
        "pass_tier",
        "rush_rank",
        "rush_tier",
        "points_rank",
        "points_tier",
    ]
    for c in (
        "def_pass_ypg_allowed",
        "def_rush_ypg_allowed",
        "def_points_allowed_pg",
        "team_id",
        "team_name",
        "season",
    ):
        if c in work.columns:
            keep.append(c)

    out = work[[c for c in keep if c in work.columns]].drop_duplicates(subset=["team"], keep="first")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


@lru_cache(maxsize=8)
def load_defense_table(sport: str, csv_path: str = "") -> pd.DataFrame:
    sport_u = str(sport or "").strip().upper()
    if csv_path:
        path = Path(csv_path)
    else:
        path = nfl_csv_path() if sport_u == "NFL" else cfb_csv_path()
    if not path.is_file() or path.stat().st_size < 50:
        if sport_u == "NFL":
            rebuild_nfl_defense_by_stat(out_path=path)
        else:
            rebuild_cfb_defense_by_stat(out_path=path)
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


def lookup_stat_defense(sport: str, opp: object, prop: object, *, csv_path: str = "") -> dict:
    cat = prop_category(prop)
    team = str(opp or "").strip().upper()
    # CFB may need alias normalize
    if str(sport).upper() == "CFB":
        try:
            from utils.cfb_playoff_metadata import norm_cfb_team_abbr

            team = norm_cfb_team_abbr(team) or team
        except Exception:
            pass
    empty = empty_stat_def(cat)
    if not cat or not team:
        return empty
    df = load_defense_table(sport, csv_path)
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


def attach_stat_defense_columns(
    df: pd.DataFrame,
    *,
    sport: str,
    csv_path: str = "",
) -> pd.DataFrame:
    sport_u = str(sport).upper()

    def _lookup(opp, prop):
        return lookup_stat_defense(sport_u, opp, prop, csv_path=csv_path)

    return attach_lookup_columns(df, sport=sport_u, lookup_fn=_lookup)
