"""WNBA team defensive efficiency from box-score logs (pace-adjusted overall D).

Defensive efficiency = opponent points / opponent possessions.
Possessions (Dean Oliver): FGA + 0.44*FTA - OREB + TOV.

Lower DEF_EFF = stingier defense (TeamRankings-style, points per possession).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from utils.wnba_team_keys import defense_team_key

FTA_COEFF = 0.44
WNBA_FRANCHISE_KEYS = frozenset(
    {
        "ATL",
        "CHI",
        "CON",
        "DAL",
        "GS",
        "IND",
        "LA",
        "LV",
        "MIN",
        "NY",
        "PHX",
        "POR",
        "SEA",
        "TOR",
        "WSH",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_db_path() -> Path:
    return _repo_root() / "data" / "cache" / "proporacle_ref.db"


def possessions(fga, fta, oreb, tov) -> float:
    """Estimate offensive possessions for a team-game."""
    return float(fga) + FTA_COEFF * float(fta) - float(oreb) + float(tov)


def _load_player_logs(db_path: Path, *, min_date: str) -> pd.DataFrame:
    import sqlite3

    if not db_path.is_file():
        return pd.DataFrame()
    con = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(
            """
            SELECT event_id, game_date, team, pts, fga, fta, oreb, tov
            FROM wnba
            WHERE team IS NOT NULL AND TRIM(team) != ''
              AND event_id IS NOT NULL
              AND game_date >= ?
            """,
            con,
            params=(min_date,),
        )
    finally:
        con.close()
    return df


def team_defensive_efficiency(
    db_path: Optional[Path] = None,
    *,
    min_date: str = "2026-05-01",
    min_games: int = 3,
) -> pd.DataFrame:
    """
    Per-franchise DEF_EFF, rank, games.

    Columns: TEAM_ABBREVIATION, GP, OPP_PTS, OPP_POSS, DEF_EFF, DEF_EFF_RANK
    Rank 1 = lowest DEF_EFF (best defense).
    """
    db_path = Path(db_path or default_db_path())
    df = _load_player_logs(db_path, min_date=min_date)
    if df.empty:
        return pd.DataFrame()

    for c in ("pts", "fga", "fta", "oreb", "tov"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["team"] = df["team"].map(defense_team_key)
    df = df[df["team"].isin(WNBA_FRANCHISE_KEYS)].copy()
    if df.empty:
        return pd.DataFrame()

    team_game = (
        df.groupby(["event_id", "game_date", "team"], as_index=False)[
            ["pts", "fga", "fta", "oreb", "tov"]
        ].sum()
    )
    team_game["poss"] = team_game.apply(
        lambda r: possessions(r["fga"], r["fta"], r["oreb"], r["tov"]),
        axis=1,
    )

    rows: list[dict] = []
    for _eid, grp in team_game.groupby("event_id"):
        teams = [t for t in grp["team"].tolist() if t]
        if len(set(teams)) != 2:
            continue
        a, b = list(dict.fromkeys(teams))[:2]
        ra = grp[grp["team"] == a].iloc[0]
        rb = grp[grp["team"] == b].iloc[0]
        if float(ra["poss"]) <= 0 or float(rb["poss"]) <= 0:
            continue
        rows.append(
            {
                "team": a,
                "game_date": ra["game_date"],
                "opp_pts": float(rb["pts"]),
                "opp_poss": float(rb["poss"]),
            }
        )
        rows.append(
            {
                "team": b,
                "game_date": rb["game_date"],
                "opp_pts": float(ra["pts"]),
                "opp_poss": float(ra["poss"]),
            }
        )

    if not rows:
        return pd.DataFrame()

    allowed = pd.DataFrame(rows)
    summary = allowed.groupby("team", as_index=False).agg(
        GP=("game_date", "nunique"),
        OPP_PTS=("opp_pts", "mean"),
        OPP_POSS=("opp_poss", "mean"),
        opp_pts_sum=("opp_pts", "sum"),
        opp_poss_sum=("opp_poss", "sum"),
    )
    summary = summary[summary["GP"] >= int(min_games)].copy()
    if summary.empty:
        return pd.DataFrame()
    summary["DEF_EFF"] = summary["opp_pts_sum"] / summary["opp_poss_sum"]
    summary["DEF_EFF_RANK"] = (
        summary["DEF_EFF"].rank(method="min", ascending=True).astype(int)
    )
    summary = summary.rename(columns={"team": "TEAM_ABBREVIATION"})
    return summary[
        ["TEAM_ABBREVIATION", "GP", "OPP_PTS", "OPP_POSS", "DEF_EFF", "DEF_EFF_RANK"]
    ].sort_values("DEF_EFF_RANK")
