"""League-wide and within-team category ranks for Matchup Edge players."""
from __future__ import annotations

from typing import Any

import pandas as pd

from utils.matchup_edge.slate_io import norm_player_name

TOP_TEAM_CUT = 5
BOTTOM_TEAM_CUT = 5


def _norm_player(series_or_val: object) -> str:
    if isinstance(series_or_val, pd.Series):
        return norm_player_name(series_or_val.iloc[0] if len(series_or_val) else "")
    return norm_player_name(series_or_val)


def team_rank_label(top_rank: int | None, bottom_rank: int | None) -> str:
    parts: list[str] = []
    if top_rank is not None and top_rank <= TOP_TEAM_CUT:
        parts.append(f"T{top_rank}")
    if bottom_rank is not None and bottom_rank <= 3:
        parts.append(f"B{bottom_rank}")
    return "/".join(parts)


def assign_league_ranks(
    agg: pd.DataFrame,
    *,
    player_norm_col: str = "PLAYER_NORM",
    stat_col: str = "season_avg",
) -> dict[str, dict[str, Any]]:
    """Rank every qualifying player league-wide for one category (1 = highest avg)."""
    if agg.empty or stat_col not in agg.columns:
        return {}
    sub = agg.dropna(subset=[stat_col]).sort_values(stat_col, ascending=False)
    n = int(len(sub))
    if n <= 0:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(sub.itertuples(index=False), start=1):
        pn = norm_player_name(getattr(r, player_norm_col, ""))
        if not pn:
            continue
        out[pn] = {
            "league_rank": i,
            "league_n": n,
            "league_rank_label": f"L#{i}",
        }
    return out


def assign_team_ranks(
    grp: pd.DataFrame,
    *,
    player_norm_col: str = "PLAYER_NORM",
    stat_col: str = "season_avg",
    top_n: int = TOP_TEAM_CUT,
    bottom_n: int = BOTTOM_TEAM_CUT,
) -> dict[str, dict[str, Any]]:
    """Rank every player on a team for one category."""
    if grp.empty or stat_col not in grp.columns:
        return {}
    sub = grp.dropna(subset=[stat_col]).sort_values(stat_col, ascending=False)
    n = int(len(sub))
    if n <= 0:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(sub.itertuples(index=False), start=1):
        pn = norm_player_name(getattr(r, player_norm_col, ""))
        if not pn:
            continue
        bottom_from_worst = n - i + 1
        bottom_rank = bottom_from_worst if bottom_from_worst <= bottom_n else None
        if bottom_from_worst <= bottom_n and i > top_n:
            leader_slice = "bottom"
        elif i <= top_n:
            leader_slice = "top"
        else:
            leader_slice = "mid"
        out[pn] = {
            "rank_on_team": i,
            "bottom_rank_on_team": bottom_rank,
            "leader_slice": leader_slice,
            "team_rank_label": team_rank_label(i, bottom_rank if bottom_from_worst <= 3 else None),
            "bottom3_on_team": bottom_from_worst <= 3,
        }
    return out


def format_category_rank_label(
    player: dict[str, Any],
    *,
    opp_def_rank: object = None,
    cat_short: str = "",
) -> str:
    """Compact badge: L#7 · T1 · vs #3 reb D."""
    parts: list[str] = []
    lr = player.get("league_rank")
    if lr is not None:
        parts.append(f"L#{lr}")
    tr = player.get("rank_on_team")
    if tr is not None:
        parts.append(f"T{tr}")
    elif player.get("team_rank_label"):
        parts.append(str(player["team_rank_label"]))
    opp = opp_def_rank if opp_def_rank is not None else player.get("opp_def_rank")
    if opp is not None and str(opp).strip() not in ("", "—", "nan"):
        suffix = f" {cat_short} D" if cat_short else " D"
        parts.append(f"vs #{opp}{suffix}")
    return " · ".join(parts)


def stamp_player_ranks(
    player: dict[str, Any],
    *,
    league: dict[str, Any] | None = None,
    team: dict[str, Any] | None = None,
    opp_def_rank: object = None,
    cat_short: str = "",
) -> dict[str, Any]:
    """Merge rank fields onto a player dict (mutates and returns player)."""
    if league:
        player.update(league)
    if team:
        for k, v in team.items():
            if k not in player or player.get(k) is None:
                player[k] = v
        # Prefer computed team ranks over stale top-5-only values.
        if team.get("rank_on_team") is not None:
            player["rank_on_team"] = team["rank_on_team"]
        if team.get("bottom_rank_on_team") is not None:
            player["bottom_rank_on_team"] = team["bottom_rank_on_team"]
        if team.get("leader_slice"):
            player["leader_slice"] = team["leader_slice"]
        if team.get("team_rank_label"):
            player["team_rank_label"] = team["team_rank_label"]
        if "bottom3_on_team" in team:
            player["bottom3_on_team"] = team["bottom3_on_team"]
    if opp_def_rank is not None:
        player["opp_def_rank"] = opp_def_rank
    lbl = format_category_rank_label(player, opp_def_rank=opp_def_rank, cat_short=cat_short)
    if lbl:
        player["category_rank_label"] = lbl
    return player
