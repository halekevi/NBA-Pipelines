"""NBA prop-specific opponent defense ranks (PTS / REB / AST allowed).

Source: Sports/NBA/data/nba_opp_defense_by_position.json

Note: Current season JSON values are identical across Guard/Forward/Center for
each team (team-level allowed rates duplicated per position). This util therefore
builds team-level pts/reb/ast ranks from those averages (one row per team).

Ranks: 1 = stingiest (lowest opp-allowed) = HARD for OVER.
"""
from __future__ import annotations

import json
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
    "Points": "pts",
    "points": "pts",
    "Points (Combo)": "pts",
    "Rebounds": "reb",
    "rebounds": "reb",
    "Rebounds (Combo)": "reb",
    "Assists": "ast",
    "assists": "ast",
    "Assists (Combo)": "ast",
    "Pts+Rebs+Asts": "pra",
    "pts_rebs_asts": "pra",
    "Pts+Rebs": "pr",
    "Pts+Asts": "pa",
    "Rebs+Asts": "ra",
    "3-PT Made": "pts",
    "FG Made": "pts",
    "Steals": "pts",
    "Blocked Shots": "pts",
    "Turnovers": "pts",
}

TEAM_ALIASES: dict[str, str] = {
    "GS": "GSW",
    "GOLDEN STATE": "GSW",
    "NY": "NYK",
    "NYK": "NYK",
    "NO": "NOP",
    "NOP": "NOP",
    "SA": "SAS",
    "SAS": "SAS",
    "UTAH": "UTA",
    "PHO": "PHX",
    "PHX": "PHX",
    "WSH": "WAS",
    "WAS": "WAS",
    "BRK": "BKN",
    "BKN": "BKN",
    "CHO": "CHA",
    "CHA": "CHA",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_csv_path() -> Path:
    return _repo_root() / "Sports" / "NBA" / "data" / "nba_defense_by_stat.csv"


def default_json_path() -> Path:
    return _repo_root() / "Sports" / "NBA" / "data" / "nba_opp_defense_by_position.json"


def prop_category(prop: object) -> str:
    p = str(prop or "").strip()
    if p in PROP_TO_CAT:
        return PROP_TO_CAT[p]
    key = " ".join(p.replace("_", " ").replace("-", " ").split())
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


def rebuild_defense_by_stat(
    out_path: Optional[Path] = None,
    json_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Build team-level ranks from position JSON (averaging identical position rows)."""
    src = Path(json_path or default_json_path())
    out_path = Path(out_path or default_csv_path())
    if not src.is_file():
        return pd.DataFrame()
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return pd.DataFrame()

    # Prefer newest season_* key
    season_keys = [k for k in payload.keys() if str(k).startswith("season_")]
    if not season_keys and "entries" in payload:
        entries = payload.get("entries") or {}
    else:
        season_keys = sorted(season_keys)
        block = payload.get(season_keys[-1], {}) if season_keys else {}
        entries = block.get("entries") or {}
    if not entries:
        return pd.DataFrame()

    rows: list[dict] = []
    for _key, ent in entries.items():
        if not isinstance(ent, dict):
            continue
        team = _normalize_team(ent.get("team"))
        if not team:
            continue
        try:
            pts = float(ent.get("pts_allowed"))
            reb = float(ent.get("reb_allowed"))
            ast = float(ent.get("ast_allowed"))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "team": team,
                "position_group": str(ent.get("position_group") or ""),
                "opp_pts": pts,
                "opp_reb": reb,
                "opp_ast": ast,
            }
        )
    if not rows:
        return pd.DataFrame()

    raw = pd.DataFrame(rows)
    # Detect identical-across-position: if per-team nunique of each metric == 1, team-level is correct.
    identical = True
    for t, grp in raw.groupby("team"):
        if (
            grp["opp_pts"].nunique() > 1
            or grp["opp_reb"].nunique() > 1
            or grp["opp_ast"].nunique() > 1
        ):
            identical = False
            break

    agg = raw.groupby("team", as_index=False).agg(
        opp_pts=("opp_pts", "mean"),
        opp_reb=("opp_reb", "mean"),
        opp_ast=("opp_ast", "mean"),
    )
    agg["opp_pra"] = agg["opp_pts"] + agg["opp_reb"] + agg["opp_ast"]
    agg["opp_pr"] = agg["opp_pts"] + agg["opp_reb"]
    agg["opp_pa"] = agg["opp_pts"] + agg["opp_ast"]
    agg["opp_ra"] = agg["opp_reb"] + agg["opp_ast"]
    n = len(agg)
    for cat, col in (
        ("pts", "opp_pts"),
        ("reb", "opp_reb"),
        ("ast", "opp_ast"),
        ("pra", "opp_pra"),
        ("pr", "opp_pr"),
        ("pa", "opp_pa"),
        ("ra", "opp_ra"),
    ):
        agg[f"{cat}_rank"] = agg[col].rank(method="min", ascending=True)
        agg[f"{cat}_tier"] = agg[f"{cat}_rank"].map(
            lambda r: _tier_label(float(r), n) if pd.notna(r) else ""
        )
    agg["overall_rank"] = agg["pts_rank"]
    agg["n_teams"] = n
    agg["positions_identical"] = bool(identical)
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
    df["team"] = df["team"].map(_normalize_team)
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
    if rank is None and "pts_rank" in row.index and pd.notna(row["pts_rank"]):
        try:
            rank = int(float(row["pts_rank"]))
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
        sport="NBA",
        lookup_fn=lambda opp, prop: lookup_stat_defense(opp, prop, csv_path=csv_path),
    )
