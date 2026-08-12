"""WNBA prop-specific opponent defense ranks (allowed PTS/REB/AST/…).

Ranks: 1 = stingiest (lowest opp-allowed) for that stat = HARD for OVER.
Built from box-score game logs in proporacle_ref.db when CSV is missing.
"""
from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

# Prop label -> defense category column prefix (rank col = f"{cat}_rank")
PROP_TO_CAT: dict[str, str] = {
    "Points": "pts",
    "Points (Combo)": "pts",
    "Rebounds": "reb",
    "Rebounds (Combo)": "reb",
    "Assists": "ast",
    "Assists (Combo)": "ast",
    "3-PT Made": "fg3m",
    "3-PT Made (Combo)": "fg3m",
    "3-PT Attempted": "fg3a",
    "Steals": "stl",
    "Blocked Shots": "blk",
    "Blks+Stls": "bs",
    "Pts+Rebs+Asts": "pra",
    "Pts+Rebs": "pr",
    "Pts+Asts": "pa",
    "Rebs+Asts": "ra",
    "FG Made": "fgm",
    "FG Attempted": "fga",
    "Two Pointers Made": "fg2m",
    "Two Pointers Attempted": "fg2a",
    "Free Throws Made": "ftm",
    "Free Throws Attempted": "fta",
    "Turnovers": "tov",
    "Defensive Rebounds": "dreb",
    "Offensive Rebounds": "oreb",
}

# Soft-priority whitelist (measured lift on 30d review)
SOFT_PRIORITY_PROPS: frozenset[str] = frozenset(
    {
        "Rebounds",
        "Rebs+Asts",
        "Pts+Asts",
        "Pts+Rebs+Asts",
        "3-PT Made",
        "FG Attempted",
        "Free Throws Made",
        "Free Throws Attempted",
        "Two Pointers Made",
    }
)

# UNDER soft nudge only where UNDER samples showed alignment
SOFT_UNDER_PROPS: frozenset[str] = frozenset(
    {
        "Rebounds",
        "Pts+Rebs+Asts",
        "Pts+Rebs",
        "Pts+Asts",
        "Assists",
        "Rebs+Asts",
    }
)

TEAM_MAP: dict[str, str] = {
    "ATL": "ATL",
    "CHI": "CHI",
    "CON": "CON",
    "CONN": "CON",
    "DAL": "DAL",
    "GS": "GS",
    "GSV": "GS",
    "IND": "IND",
    "LA": "LA",
    "LAS": "LA",
    "LV": "LV",
    "LVA": "LV",
    "MIN": "MIN",
    "NY": "NY",
    "NYL": "NY",
    "PHX": "PHX",
    "PHO": "PHX",
    "POR": "POR",
    "SEA": "SEA",
    "TOR": "TOR",
    "WSH": "WSH",
    "WAS": "WSH",
}

_STAT_COLS = [
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "fg2m",
    "fg2a",
    "ftm",
    "fta",
    "oreb",
    "dreb",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def canon_team(raw: object) -> str:
    s = str(raw or "").strip().upper()
    if not s or "/" in s:
        return ""
    return TEAM_MAP.get(s, s)


def prop_category(prop: object) -> str:
    p = str(prop or "").strip()
    if p in PROP_TO_CAT:
        return PROP_TO_CAT[p]
    # light normalize
    key = " ".join(p.replace("-", " ").split())
    for label, cat in PROP_TO_CAT.items():
        if label.lower() == key.lower():
            return cat
    return ""


def coarse_bucket_from_tier(tier: object) -> str:
    """Map CSV tier (HARD/HARD_MID/MID/EASY_MID/EASY) → HARD/MID/EASY/UNK."""
    t = str(tier or "").strip().upper().replace(" ", "_")
    if t in ("HARD", "HARD_MID"):
        return "HARD"
    if t in ("EASY", "EASY_MID"):
        return "EASY"
    if t == "MID":
        return "MID"
    return "UNK"


def coarse_bucket_from_rank(rank: object, n_teams: int) -> str:
    try:
        r = float(rank)
        n = max(int(n_teams), 1)
    except (TypeError, ValueError):
        return "UNK"
    if r != r:  # NaN
        return "UNK"
    q = max(n / 5.0, 1.0)
    if r <= 2 * q:
        return "HARD"
    if r <= 3 * q:
        return "MID"
    return "EASY"


def default_csv_path() -> Path:
    return _repo_root() / "Sports" / "WNBA" / "data" / "wnba_defense_by_stat.csv"


def default_db_path() -> Path:
    return _repo_root() / "data" / "cache" / "proporacle_ref.db"


def rebuild_defense_by_stat(
    db_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Aggregate opp-allowed stats from wnba game logs; write CSV; return frame."""
    db_path = Path(db_path or default_db_path())
    out_path = Path(out_path or default_csv_path())
    if not db_path.is_file():
        return pd.DataFrame()

    con = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(
            """
            SELECT event_id, game_date, team, pts, reb, ast, stl, blk, tov,
                   fgm, fga, fg3m, fg3a, fg2m, fg2a, ftm, fta, oreb, dreb
            FROM wnba
            WHERE team IS NOT NULL AND team != ''
              AND event_id IS NOT NULL
            """,
            con,
        )
    finally:
        con.close()

    if df.empty:
        return df

    bad = {"COOP", "SPO"}
    df = df[~df["team"].astype(str).str.upper().isin(bad)].copy()
    for c in _STAT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    gcols = ["event_id", "game_date", "team"] + [c for c in _STAT_COLS if c in df.columns]
    team_game = df[gcols].groupby(["event_id", "game_date", "team"], as_index=False).sum(
        numeric_only=True
    )
    team_game["pra"] = team_game["pts"] + team_game["reb"] + team_game["ast"]
    team_game["pr"] = team_game["pts"] + team_game["reb"]
    team_game["pa"] = team_game["pts"] + team_game["ast"]
    team_game["ra"] = team_game["reb"] + team_game["ast"]
    team_game["bs"] = team_game["stl"] + team_game["blk"]

    allowed_rows: list[dict] = []
    for _eid, grp in team_game.groupby("event_id"):
        teams = grp["team"].tolist()
        if len(teams) != 2:
            continue
        a, b = teams[0], teams[1]
        ra = grp[grp["team"] == a].iloc[0]
        rb = grp[grp["team"] == b].iloc[0]
        row_a: dict = {"team": a, "game_date": ra["game_date"]}
        row_b: dict = {"team": b, "game_date": rb["game_date"]}
        for c in [
            "pts",
            "reb",
            "ast",
            "stl",
            "blk",
            "tov",
            "fgm",
            "fga",
            "fg3m",
            "fg3a",
            "fg2m",
            "fg2a",
            "ftm",
            "fta",
            "oreb",
            "dreb",
            "pra",
            "pr",
            "pa",
            "ra",
            "bs",
        ]:
            if c not in ra.index:
                continue
            row_a[f"opp_{c}"] = float(rb[c])
            row_b[f"opp_{c}"] = float(ra[c])
        allowed_rows.extend([row_a, row_b])

    if not allowed_rows:
        return pd.DataFrame()

    allowed = pd.DataFrame(allowed_rows)
    metrics = [c for c in allowed.columns if c.startswith("opp_")]
    summary = allowed.groupby("team", as_index=False).agg(
        **{m: (m, "mean") for m in metrics},
        games=("game_date", "nunique"),
    )
    n_teams = len(summary)
    for m in metrics:
        cat = m.replace("opp_", "")
        summary[f"{cat}_rank"] = summary[m].rank(method="min", ascending=True).astype(int)
        summary[f"{cat}_tier"] = summary[f"{cat}_rank"].map(
            lambda r: _tier_label(float(r), n_teams)
        )
    summary["overall_rank"] = summary["pts_rank"]
    summary["n_teams"] = n_teams
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_path, index=False)
    return summary


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
    df["team"] = df["team"].astype(str).str.strip().str.upper().map(canon_team)
    return df


def clear_defense_cache() -> None:
    load_defense_table.cache_clear()


def lookup_stat_defense(
    opp: object,
    prop: object,
    *,
    csv_path: str = "",
) -> dict:
    """
    Return {category, rank, tier, coarse} for opponent × prop.
    Missing data → empty strings / None.
    """
    cat = prop_category(prop)
    team = canon_team(opp)
    empty = {
        "stat_def_category": cat or "",
        "stat_def_rank": None,
        "stat_def_tier": "",
        "stat_def_coarse": "UNK",
    }
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
    tier_col = f"{cat}_tier"
    rank = None
    if rank_col in row.index and pd.notna(row[rank_col]):
        try:
            rank = int(float(row[rank_col]))
        except (TypeError, ValueError):
            rank = None
    tier_raw = str(row[tier_col]) if tier_col in row.index and pd.notna(row.get(tier_col)) else ""
    n_teams = int(row["n_teams"]) if "n_teams" in row.index and pd.notna(row.get("n_teams")) else len(df)
    coarse = coarse_bucket_from_tier(tier_raw) if tier_raw else coarse_bucket_from_rank(rank, n_teams)
    return {
        "stat_def_category": cat,
        "stat_def_rank": rank,
        "stat_def_tier": coarse,  # store coarse HARD/MID/EASY for priority
        "stat_def_coarse": coarse,
        "stat_def_tier_raw": tier_raw,
    }


def soft_priority_enabled() -> bool:
    return str(os.getenv("PROPORACLE_WNBA_STAT_DEF_SOFT", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def soft_priority_delta(
    *,
    sport: object,
    prop: object,
    direction: object,
    stat_def_tier: object,
) -> float:
    """
    Soft score nudge for whitelist props.
    OVER vs EASY +0.06 / HARD -0.04; UNDER (subset) HARD +0.04 / EASY -0.03.
    """
    if not soft_priority_enabled():
        return 0.0
    if str(sport or "").strip().upper() != "WNBA":
        return 0.0
    p = str(prop or "").strip()
    d = str(direction or "").strip().upper()
    tier = str(stat_def_tier or "").strip().upper()
    if tier not in ("HARD", "EASY", "MID"):
        # accept raw labels
        tier = coarse_bucket_from_tier(stat_def_tier)
    if d.startswith("O"):
        if p not in SOFT_PRIORITY_PROPS:
            return 0.0
        if tier == "EASY":
            return 0.06
        if tier == "HARD":
            return -0.04
        return 0.0
    if d.startswith("U"):
        if p not in SOFT_UNDER_PROPS:
            return 0.0
        if tier == "HARD":
            return 0.04
        if tier == "EASY":
            return -0.03
        return 0.0
    return 0.0


def attach_stat_defense_columns(df: pd.DataFrame, *, csv_path: str = "") -> pd.DataFrame:
    """Add stat_def_category / stat_def_rank / stat_def_tier columns (WNBA rows)."""
    if df is None or len(df) == 0:
        return df
    out = df.copy()
    sport_col = None
    for c in ("sport", "Sport"):
        if c in out.columns:
            sport_col = c
            break
    if sport_col is None:
        # assume caller already filtered to WNBA
        is_wnba = pd.Series(True, index=out.index)
    else:
        is_wnba = out[sport_col].astype(str).str.upper().str.strip().eq("WNBA")

    opp_col = "opp" if "opp" in out.columns else ("opp_team" if "opp_team" in out.columns else None)
    prop_col = None
    for c in ("prop_type", "prop", "Prop"):
        if c in out.columns:
            prop_col = c
            break
    if not opp_col or not prop_col:
        return out

    cats: list[str] = []
    ranks: list[object] = []
    tiers: list[str] = []
    for i, row in out.iterrows():
        if not bool(is_wnba.loc[i]):
            cats.append("")
            ranks.append(None)
            tiers.append("")
            continue
        info = lookup_stat_defense(row.get(opp_col), row.get(prop_col), csv_path=csv_path)
        cats.append(info.get("stat_def_category") or "")
        ranks.append(info.get("stat_def_rank"))
        tiers.append(info.get("stat_def_tier") or "")

    out["stat_def_category"] = cats
    out["stat_def_rank"] = ranks
    out["stat_def_tier"] = tiers
    return out
