"""NHL prop-specific opponent defense ranks (GAA / shots against).

Built from unique opp rows on Sports/NHL/step3_nhl_with_defense.csv when present.
When opp_saa is missing/all-zero (common standings-only fallback), saa_rank
proxies from gaa_rank / overall_rank so lookups still return integers.
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

PROP_TO_CAT: dict[str, str] = {
    "Goals": "gaa",
    "goals": "gaa",
    "Points": "gaa",
    "points": "gaa",
    "Assists": "gaa",
    "assists": "gaa",
    "Shots On Goal": "saa",
    "shots_on_goal": "saa",
    "SOG": "saa",
    "Goalie Saves": "saa",
    "goalie_saves": "saa",
    "Saves": "saa",
    "Blocked Shots": "saa",
    "blocked_shots": "saa",
    "Power Play Points": "gaa",
    "power_play_points": "gaa",
}

TEAM_ALIASES: dict[str, str] = {
    "TORONTO": "TOR",
    "MAPLE LEAFS": "TOR",
    "TORONTO MAPLE LEAFS": "TOR",
    "BUFFALO": "BUF",
    "SABRES": "BUF",
    "BUFFALO SABRES": "BUF",
    "CAROLINA": "CAR",
    "HURRICANES": "CAR",
    "CAROLINA HURRICANES": "CAR",
    "CHICAGO": "CHI",
    "BLACKHAWKS": "CHI",
    "CHICAGO BLACKHAWKS": "CHI",
    "COLORADO": "COL",
    "AVALANCHE": "COL",
    "COLORADO AVALANCHE": "COL",
    "DALLAS": "DAL",
    "STARS": "DAL",
    "DALLAS STARS": "DAL",
    "DETROIT": "DET",
    "RED WINGS": "DET",
    "DETROIT RED WINGS": "DET",
    "FLORIDA": "FLA",
    "PANTHERS": "FLA",
    "FLORIDA PANTHERS": "FLA",
    "LOS ANGELES": "LA",
    "LAKINGS": "LA",
    "LA KINGS": "LA",
    "KINGS": "LA",
    "MONTREAL": "MTL",
    "CANADIENS": "MTL",
    "MONTREAL CANADIENS": "MTL",
    "NEW JERSEY": "NJ",
    "DEVILS": "NJ",
    "NEW JERSEY DEVILS": "NJ",
    "NASHVILLE": "NSH",
    "PREDATORS": "NSH",
    "NASHVILLE PREDATORS": "NSH",
    "NY ISLANDERS": "NYI",
    "NEW YORK ISLANDERS": "NYI",
    "ISLANDERS": "NYI",
    "NY RANGERS": "NYR",
    "NEW YORK RANGERS": "NYR",
    "RANGERS": "NYR",
    "PHILADELPHIA": "PHI",
    "FLYERS": "PHI",
    "PHILADELPHIA FLYERS": "PHI",
    "PITTSBURGH": "PIT",
    "PENGUINS": "PIT",
    "PITTSBURGH PENGUINS": "PIT",
    "ST LOUIS": "STL",
    "ST. LOUIS": "STL",
    "BLUES": "STL",
    "ST LOUIS BLUES": "STL",
    "ST. LOUIS BLUES": "STL",
    "UTAH": "UTA",
    "UTAH HOCKEY CLUB": "UTA",
    "WINNIPEG": "WPG",
    "JETS": "WPG",
    "WINNIPEG JETS": "WPG",
    "VEGAS": "VGK",
    "GOLDEN KNIGHTS": "VGK",
    "LAS VEGAS": "VGK",
    "SEATTLE": "SEA",
    "KRAKEN": "SEA",
    "EDMONTON": "EDM",
    "OILERS": "EDM",
    "CALGARY": "CGY",
    "FLAMES": "CGY",
    "VANCOUVER": "VAN",
    "CANUCKS": "VAN",
    "OTTAWA": "OTT",
    "SENATORS": "OTT",
    "BOSTON": "BOS",
    "BRUINS": "BOS",
    "TAMPA BAY": "TB",
    "TAMPA": "TB",
    "LIGHTNING": "TB",
    "WASHINGTON": "WSH",
    "CAPITALS": "WSH",
    "MINNESOTA": "MIN",
    "WILD": "MIN",
    "COLUMBUS": "CBJ",
    "BLUE JACKETS": "CBJ",
    "SAN JOSE": "SJ",
    "SHARKS": "SJ",
    "ANAHEIM": "ANA",
    "DUCKS": "ANA",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_csv_path() -> Path:
    return _repo_root() / "Sports" / "NHL" / "data" / "nhl_defense_by_stat.csv"


def prop_category(prop: object) -> str:
    p = str(prop or "").strip()
    if p in PROP_TO_CAT:
        return PROP_TO_CAT[p]
    key = " ".join(p.replace("_", " ").split())
    for label, cat in PROP_TO_CAT.items():
        if label.lower() == key.lower():
            return cat
    return ""


def _normalize_team(opp: object) -> str:
    team = str(opp or "").strip().upper()
    if not team or team in {"NAN", "NONE", "UNKNOWN", "UNKNOWN_OPP"}:
        return ""
    return TEAM_ALIASES.get(team, team)


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


def _series_usable(s: pd.Series) -> bool:
    """True when series has finite values with real variance (not all-zero ties)."""
    if s is None or s.empty:
        return False
    num = pd.to_numeric(s, errors="coerce")
    valid = num.dropna()
    if valid.empty:
        return False
    if float(valid.nunique()) <= 1 and float(valid.iloc[0]) == 0.0:
        return False
    return True


def rebuild_defense_by_stat(out_path: Optional[Path] = None) -> pd.DataFrame:
    src = _repo_root() / "Sports" / "NHL" / "step3_nhl_with_defense.csv"
    out_path = Path(out_path or default_csv_path())
    if not src.is_file():
        return pd.DataFrame()
    df = pd.read_csv(src, encoding="utf-8-sig", low_memory=False)
    if "opponent" not in df.columns and "opp" not in df.columns:
        return pd.DataFrame()
    team_col = "opponent" if "opponent" in df.columns else "opp"
    keep = [
        c
        for c in (
            team_col,
            "opp_gaa",
            "opp_saa",
            "opp_sf_per_game",
            "opp_shots_allowed_avg",
            "def_rank",
            "def_tier",
        )
        if c in df.columns
    ]
    work = df[keep].copy()
    work["team"] = work[team_col].map(_normalize_team)
    work = work[work["team"].ne("")]
    for c in ("opp_gaa", "opp_saa", "opp_sf_per_game", "opp_shots_allowed_avg", "def_rank"):
        if c in work.columns:
            work[c] = pd.to_numeric(work[c], errors="coerce")

    if "opp_saa" not in work.columns:
        work["opp_saa"] = pd.NA
    if not _series_usable(work["opp_saa"]) and "opp_shots_allowed_avg" in work.columns:
        work["opp_saa"] = pd.to_numeric(work["opp_shots_allowed_avg"], errors="coerce")
    if not _series_usable(work["opp_saa"]) and "opp_sf_per_game" in work.columns:
        work["opp_saa"] = pd.to_numeric(work["opp_sf_per_game"], errors="coerce")

    aggs: dict = {"opp_gaa": ("opp_gaa", "mean")}
    if "opp_saa" in work.columns:
        aggs["opp_saa"] = ("opp_saa", "mean")
    if "def_rank" in work.columns:
        aggs["overall_rank"] = ("def_rank", "min")
    agg = work.groupby("team", as_index=False).agg(**aggs)
    n = len(agg)

    if "opp_gaa" in agg.columns and _series_usable(agg["opp_gaa"]):
        agg["gaa_rank"] = agg["opp_gaa"].rank(method="min", ascending=True)
    else:
        agg["gaa_rank"] = pd.NA

    if "opp_saa" in agg.columns and _series_usable(agg["opp_saa"]):
        agg["saa_rank"] = agg["opp_saa"].rank(method="min", ascending=True)
    elif "gaa_rank" in agg.columns and agg["gaa_rank"].notna().any():
        # Standings-only feeds often leave opp_saa=0 for every team → all rank 1.
        agg["saa_rank"] = agg["gaa_rank"]
    elif "overall_rank" in agg.columns:
        agg["saa_rank"] = agg["overall_rank"]
    else:
        agg["saa_rank"] = pd.NA

    if "overall_rank" not in agg.columns or agg["overall_rank"].isna().all():
        if "gaa_rank" in agg.columns and agg["gaa_rank"].notna().any():
            agg["overall_rank"] = agg["gaa_rank"]
        else:
            agg["overall_rank"] = pd.NA

    for cat in ("gaa", "saa"):
        agg[f"{cat}_tier"] = agg[f"{cat}_rank"].map(
            lambda r: _tier_label(float(r), n) if pd.notna(r) else ""
        )
    agg["n_teams"] = n
    out_path.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(out_path, index=False)
    clear_defense_cache()
    return agg


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
    if (
        "saa_rank" in df.columns
        and "gaa_rank" in df.columns
        and df["gaa_rank"].notna().any()
        and (
            df["saa_rank"].isna().all()
            or (
                df["saa_rank"].nunique(dropna=True) <= 1
                and float(df["saa_rank"].dropna().iloc[0]) == 1.0
            )
        )
        and not csv_path
    ):
        rebuilt = rebuild_defense_by_stat(out_path=path)
        if not rebuilt.empty:
            return rebuilt
    return df


def clear_defense_cache() -> None:
    load_defense_table.cache_clear()


def lookup_stat_defense(opp: object, prop: object, *, csv_path: str = "") -> dict:
    cat = prop_category(prop)
    team = _normalize_team(opp)
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
    if rank is None:
        for alt in ("overall_rank", "gaa_rank", "saa_rank"):
            if alt in row.index and pd.notna(row[alt]):
                try:
                    rank = int(float(row[alt]))
                    break
                except (TypeError, ValueError):
                    continue
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
        sport="NHL",
        lookup_fn=lambda opp, prop: lookup_stat_defense(opp, prop, csv_path=csv_path),
    )
