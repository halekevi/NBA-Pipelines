"""
Team averages + player share % of each prop category.

Used by Matchup Edge enrichment and scripts/build_team_share_json.py.

Feasible sports:
  wnba, nba, cbb, wcbb — full basketball boxscore share
  mlb — partial (hitter counting stats via long-format cache)
  nhl — partial (from proporacle_ref.db nhl table when present)

Skipped:
  tennis — no team
  soccer — weak/no TEAM on primary cache (defer)
  nfl — boxscore cache often missing offseason
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]

# Matchup Edge category id -> share prop name
CAT_ID_TO_PROP: dict[str, str] = {
    "pts": "Points",
    "reb": "Rebounds",
    "ast": "Assists",
    "fg3m": "3-PT Made",
    "stl": "Steals",
    "blk": "Blocked Shots",
    "pra": "Pts+Rebs+Asts",
    "pr": "Pts+Rebs",
    "pa": "Pts+Asts",
    "ra": "Rebs+Asts",
    "stocks": "Blks+Stls",
    "tov": "Turnovers",
    "goals": "Goals",
    "assists": "Assists",
    "points": "Points",
    "shots": "Shots",
    "hits": "Hits",
    "tb": "Total Bases",
    "hr": "Home Runs",
    "rbi": "RBIs",
    "runs": "Runs",
    "hrr": "Hits+Runs+RBIs",
    "singles": "Singles",
    "doubles": "Doubles",
    "sb": "Stolen Bases",
    "bb": "Walks",
}

SLATE_PROP_TO_SHARE: dict[str, str] = {
    "points": "Points",
    "rebounds": "Rebounds",
    "assists": "Assists",
    "steals": "Steals",
    "blocked shots": "Blocked Shots",
    "blocks": "Blocked Shots",
    "turnovers": "Turnovers",
    "3-pt made": "3-PT Made",
    "3-pt attempted": "3-PT Attempted",
    "fg made": "FG Made",
    "fg attempted": "FG Attempted",
    "two pointers made": "Two Pointers Made",
    "two pointers attempted": "Two Pointers Attempted",
    "free throws made": "Free Throws Made",
    "free throws attempted": "Free Throws Attempted",
    "pts+rebs+asts": "Pts+Rebs+Asts",
    "pts+rebs": "Pts+Rebs",
    "pts+asts": "Pts+Asts",
    "rebs+asts": "Rebs+Asts",
    "blks+stls": "Blks+Stls",
    "goals": "Goals",
    "shots": "Shots",
    "shots on goal": "Shots",
    "hits": "Hits",
    "total bases": "Total Bases",
    "home runs": "Home Runs",
    "rbis": "RBIs",
    "runs": "Runs",
    "hits+runs+rbis": "Hits+Runs+RBIs",
    "singles": "Singles",
    "doubles": "Doubles",
    "stolen bases": "Stolen Bases",
    "walks": "Walks",
}


def _norm_name(s: object) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _norm_prop(s: object) -> str:
    p = str(s or "").strip().lower().replace(" (combo)", "")
    return SLATE_PROP_TO_SHARE.get(p, str(s or "").strip())


def share_artifact_path(sport: str, repo: Path | None = None) -> Path:
    root = repo or _REPO
    sport = str(sport or "").strip().lower()
    mapping = {
        "wnba": root / "Sports/WNBA/data/wnba_team_share.json",
        "nba": root / "Sports/NBA/data/nba_team_share.json",
        "nba1h": root / "Sports/NBA/data/nba_team_share.json",
        "nba1q": root / "Sports/NBA/data/nba_team_share.json",
        "cbb": root / "Sports/CBB/data/cbb_team_share.json",
        "wcbb": root / "Sports/CBB/data/wcbb_team_share.json",
        "mlb": root / "Sports/MLB/data/mlb_team_share.json",
        "nhl": root / "Sports/NHL/data/nhl_team_share.json",
    }
    return mapping.get(sport, root / f"data/{sport}_team_share.json")


def load_share_payload(sport: str, repo: Path | None = None) -> dict[str, Any] | None:
    path = share_artifact_path(sport, repo)
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    cache_key = (str(path.resolve()), mtime)
    cached = _SHARE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    # keep cache bounded
    if len(_SHARE_CACHE) > 24:
        _SHARE_CACHE.clear()
    _SHARE_CACHE[cache_key] = data
    return data


_SHARE_CACHE: dict[tuple[str, float], dict[str, Any]] = {}


def lookup_player_share(
    payload: dict[str, Any] | None,
    *,
    team: str,
    player: str,
    prop: str,
) -> dict[str, Any] | None:
    if not payload:
        return None
    by_player = payload.get("by_player") or {}
    team_u = str(team or "").strip().upper()
    pn = _norm_name(player)
    prop_name = _norm_prop(prop)
    aliases = payload.get("team_aliases") or {}
    team_key = aliases.get(team_u, team_u)
    key = f"{team_key}|{pn}|{prop_name}"
    hit = by_player.get(key)
    if hit:
        return hit
    suffix = f"|{pn}|{prop_name}"
    for k, v in by_player.items():
        if k.endswith(suffix):
            return v
    return None


def _finalize_basketball_frame(
    df: pd.DataFrame,
    *,
    team_col: str,
    player_col: str,
    game_col: str,
    min_games: int = 5,
    min_mpg: float = 5.0,
) -> dict[str, Any]:
    work = df.copy()
    work["TEAM"] = work[team_col].astype(str).str.strip().str.upper()
    work["PLAYER"] = work[player_col].astype(str).str.strip()
    work["PLAYER_NORM"] = work["PLAYER"].map(_norm_name)
    work["event_id"] = work[game_col].astype(str)

    for c in [
        "MIN", "PTS", "REB", "AST", "STL", "BLK", "TO",
        "FGM", "FGA", "FG3M", "FG3A", "FG2M", "FG2A", "FTM", "FTA",
    ]:
        if c not in work.columns:
            work[c] = 0.0
        work[c] = pd.to_numeric(work[c], errors="coerce").fillna(0.0)

    work["Pts+Rebs+Asts"] = work["PTS"] + work["REB"] + work["AST"]
    work["Pts+Rebs"] = work["PTS"] + work["REB"]
    work["Pts+Asts"] = work["PTS"] + work["AST"]
    work["Rebs+Asts"] = work["REB"] + work["AST"]
    work["Blks+Stls"] = work["BLK"] + work["STL"]

    base = {
        "Points": "PTS",
        "Rebounds": "REB",
        "Assists": "AST",
        "Steals": "STL",
        "Blocked Shots": "BLK",
        "Turnovers": "TO",
        "FG Made": "FGM",
        "FG Attempted": "FGA",
        "3-PT Made": "FG3M",
        "3-PT Attempted": "FG3A",
        "Two Pointers Made": "FG2M",
        "Two Pointers Attempted": "FG2A",
        "Free Throws Made": "FTM",
        "Free Throws Attempted": "FTA",
        "Pts+Rebs+Asts": "Pts+Rebs+Asts",
        "Pts+Rebs": "Pts+Rebs",
        "Pts+Asts": "Pts+Asts",
        "Rebs+Asts": "Rebs+Asts",
        "Blks+Stls": "Blks+Stls",
    }
    keep_props = {}
    for name, col in base.items():
        if float(work[col].sum()) > 0 or name in ("Points", "Rebounds", "Assists", "Pts+Rebs+Asts"):
            keep_props[name] = col

    cols = list(dict.fromkeys(keep_props.values()))
    tgt = work.groupby(["TEAM", "event_id"], as_index=False)[cols].sum()
    team_avg = tgt.groupby("TEAM", as_index=False).agg(
        games=("event_id", "nunique"),
        **{c: (c, "mean") for c in cols},
    )

    played = work[work["MIN"] > 0].copy()
    pavg = played.groupby(["TEAM", "PLAYER", "PLAYER_NORM"], as_index=False).agg(
        games=("event_id", "nunique"),
        MIN=("MIN", "mean"),
        **{c: (c, "mean") for c in cols},
    )

    by_player: dict[str, dict[str, Any]] = {}
    leaders: dict[str, dict[str, list]] = {}
    team_avgs_out: dict[str, dict[str, float]] = {}

    for _, tr in team_avg.iterrows():
        team = str(tr["TEAM"])
        team_avgs_out[team] = {
            "games": int(tr["games"]),
            **{prop: round(float(tr[col]), 2) for prop, col in keep_props.items()},
        }
        leaders[team] = {}

    merged = pavg.merge(team_avg, on="TEAM", suffixes=("", "_TEAM"))
    for _, r in merged.iterrows():
        if int(r["games"]) < min_games or float(r["MIN"]) < min_mpg:
            continue
        team = str(r["TEAM"])
        player = str(r["PLAYER"])
        pn = str(r["PLAYER_NORM"])
        for prop, col in keep_props.items():
            pval = float(r[col])
            tval = float(r.get(f"{col}_TEAM", np.nan))
            if not np.isfinite(tval) or tval <= 0:
                continue
            share = round(100.0 * pval / tval, 1)
            rec = {
                "player": player,
                "player_norm": pn,
                "team": team,
                "prop": prop,
                "player_avg": round(pval, 2),
                "team_avg": round(tval, 2),
                "share_pct": share,
                "games": int(r["games"]),
                "min_avg": round(float(r["MIN"]), 1),
            }
            by_player[f"{team}|{pn}|{prop}"] = rec
            leaders.setdefault(team, {}).setdefault(prop, []).append(rec)

    for team, props in leaders.items():
        for prop, rows in props.items():
            rows.sort(key=lambda x: -x["share_pct"])
            leaders[team][prop] = rows[:10]

    return {
        "team_averages": team_avgs_out,
        "leaders": leaders,
        "by_player": by_player,
        "props": list(keep_props.keys()),
        "player_count": len({k.split("|")[1] for k in by_player}),
        "team_count": len(team_avgs_out),
    }


def build_wnba_share(repo: Path | None = None, season: int = 2026) -> dict[str, Any]:
    root = repo or _REPO
    path = root / "Sports/WNBA/wnba_espn_cache.csv"
    df = pd.read_csv(path)
    df = df[pd.to_numeric(df.get("SEASON"), errors="coerce") == season].copy()
    skip = {"BRZL", "JPN", "NIGER", "TOY"}
    df = df[~df["TEAM"].astype(str).str.upper().isin(skip)]
    slate_prefer = {"LV": "LVA", "LA": "LAS", "NY": "NYL", "GS": "GSV", "CONN": "CON", "PHO": "PHX", "WAS": "WSH"}
    df["TEAM_SLATE"] = df["TEAM"].astype(str).str.upper().map(lambda t: slate_prefer.get(t, t))

    out = _finalize_basketball_frame(
        df, team_col="TEAM_SLATE", player_col="PLAYER_NAME", game_col="event_id"
    )
    out.update(
        {
            "sport": "wnba",
            "season": season,
            "source": str(path.relative_to(root)),
            "applicable": True,
            "team_aliases": {
                "LV": "LVA", "LVA": "LVA", "LA": "LAS", "LAS": "LAS",
                "NY": "NYL", "NYL": "NYL", "GS": "GSV", "GSV": "GSV",
                "PHO": "PHX", "PHX": "PHX", "WAS": "WSH", "WSH": "WSH",
                "CONN": "CON", "CON": "CON",
            },
        }
    )
    return out


def build_nba_share(repo: Path | None = None) -> dict[str, Any]:
    root = repo or _REPO
    path = root / "Sports/NBA/data/cache/espn_boxscores_cache.csv"
    df = pd.read_csv(path)
    rename = {
        "points": "PTS",
        "totalRebounds": "REB",
        "assists": "AST",
        "steals": "STL",
        "blocks": "BLK",
        "threePointFieldGoalsMade": "FG3M",
        "freeThrowsMade": "FTM",
    }
    df = df.rename(columns=rename)
    for c in ["TO", "FGM", "FGA", "FG3A", "FG2M", "FG2A", "FTA"]:
        df[c] = 0.0
    statsum = df[["PTS", "REB", "AST", "STL", "BLK", "FG3M", "FTM"]].sum(axis=1)
    df["MIN"] = np.where(statsum > 0, 20.0, 0.0)
    nba_map = {
        "GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS",
        "PHO": "PHX", "WSH": "WAS", "UTAH": "UTA", "BRK": "BKN",
    }
    df["TEAM_N"] = df["team"].astype(str).str.upper().map(lambda t: nba_map.get(t, t))
    out = _finalize_basketball_frame(
        df, team_col="TEAM_N", player_col="player", game_col="game_id", min_games=5, min_mpg=1.0
    )
    out.update(
        {
            "sport": "nba",
            "source": str(path.relative_to(root)),
            "applicable": True,
            "note": "Thin ESPN cache (no FGA/TO/true MIN); share uses available counting stats.",
            "team_aliases": dict(nba_map),
        }
    )
    return out


def _cbb_team_id_to_abbr(root: Path) -> dict[str, str]:
    master = root / "Sports/CBB/data/reference/ncaa_mbb_athletes_master.csv"
    if not master.exists():
        return {}
    m = pd.read_csv(master, usecols=["team_id", "team_abbr"])
    m["team_id"] = m["team_id"].astype(str)
    m["team_abbr"] = m["team_abbr"].astype(str).str.strip().str.upper()
    m = m[m["team_abbr"].astype(bool)]
    return dict(zip(m["team_id"], m["team_abbr"]))


def build_cbb_share(repo: Path | None = None, *, womens: bool = False) -> dict[str, Any]:
    root = repo or _REPO
    sport = "wcbb" if womens else "cbb"
    path = root / (
        "Sports/CBB/data/cache/wcbb_boxscore_cache.csv"
        if womens
        else "Sports/CBB/data/cache/cbb_boxscore_cache.csv"
    )
    df = pd.read_csv(path)
    id_map = _cbb_team_id_to_abbr(root)
    df["team_id"] = df["team_id"].astype(str)
    if womens:
        # Prefer abbr when present in men's master (some overlap); else T{id}
        df["TEAM_N"] = df["team_id"].map(lambda i: id_map.get(str(i), f"T{i}"))
    else:
        df["TEAM_N"] = df["team_id"].map(lambda i: id_map.get(str(i), f"T{i}"))
    df["PLAYER"] = df["player_norm"].astype(str).str.title()
    df["FG3M"] = pd.to_numeric(df.get("3PM", df.get("FG3M")), errors="coerce").fillna(0.0)
    for c in ["FGM", "FGA", "FG3A", "FG2M", "FG2A", "FTM", "FTA"]:
        df[c] = 0.0
    out = _finalize_basketball_frame(
        df, team_col="TEAM_N", player_col="PLAYER", game_col="event_id", min_games=5, min_mpg=5.0
    )
    out.update(
        {
            "sport": sport,
            "source": str(path.relative_to(root)),
            "applicable": True,
            "note": "Cache has PTS/REB/AST/STL/BLK/TO/3PM only (no FGA/FTA).",
            "team_aliases": {},
        }
    )
    return out


def build_mlb_share(repo: Path | None = None, season: int = 2026) -> dict[str, Any]:
    root = repo or _REPO
    path = root / "Sports/MLB/mlb_stats_cache.csv"
    if not path.exists():
        return {
            "sport": "mlb",
            "applicable": False,
            "reason": f"missing {path}",
            "by_player": {},
            "team_averages": {},
        }

    peek = pd.read_csv(path, nrows=2)
    name_col = next((c for c in ("PLAYER_NAME", "player", "NAME") if c in peek.columns), None)
    usecols = [
        "GAME_ID", "TEAM_ID", "PLAYER_TYPE", "PROP_NORM", "STAT_VALUE", "SEASON", "MLB_PLAYER_ID"
    ]
    if name_col:
        usecols.append(name_col)
    df = pd.read_csv(path, usecols=lambda c: c in usecols)
    if "SEASON" in df.columns:
        df = df[pd.to_numeric(df["SEASON"], errors="coerce") == season]
    df = df[df["PLAYER_TYPE"].astype(str).str.lower().isin(["hitter", "batter", "batting"])]
    df = df[pd.to_numeric(df["TEAM_ID"], errors="coerce").notna()]
    df["STAT_VALUE"] = pd.to_numeric(df["STAT_VALUE"], errors="coerce").fillna(0.0)
    df["PROP_NORM"] = df["PROP_NORM"].astype(str).str.strip().str.lower()
    prop_map = {
        "hits": "Hits",
        "total_bases": "Total Bases",
        "home_runs": "Home Runs",
        "rbi": "RBIs",
        "runs": "Runs",
        "hits_runs_rbi": "Hits+Runs+RBIs",
        "singles": "Singles",
        "doubles": "Doubles",
        "stolen_bases": "Stolen Bases",
        "walks": "Walks",
    }
    df = df[df["PROP_NORM"].isin(prop_map)].copy()
    if df.empty:
        return {
            "sport": "mlb",
            "applicable": False,
            "reason": "no hitter props",
            "by_player": {},
            "team_averages": {},
        }

    df["prop"] = df["PROP_NORM"].map(prop_map)
    df["TEAM"] = df["TEAM_ID"].astype(int).astype(str)
    df["PLAYER"] = df[name_col].astype(str) if name_col else df["MLB_PLAYER_ID"].astype(str)
    df["PLAYER_NORM"] = df["PLAYER"].map(_norm_name)

    wide = (
        df.groupby(["TEAM", "PLAYER", "PLAYER_NORM", "GAME_ID", "prop"], as_index=False)["STAT_VALUE"]
        .sum()
        .pivot_table(
            index=["TEAM", "PLAYER", "PLAYER_NORM", "GAME_ID"],
            columns="prop",
            values="STAT_VALUE",
            fill_value=0.0,
        )
        .reset_index()
    )
    props = [c for c in wide.columns if c not in ("TEAM", "PLAYER", "PLAYER_NORM", "GAME_ID")]
    tgt = wide.groupby(["TEAM", "GAME_ID"], as_index=False)[props].sum()
    team_avg = tgt.groupby("TEAM", as_index=False).agg(
        games=("GAME_ID", "nunique"), **{p: (p, "mean") for p in props}
    )
    pavg = wide.groupby(["TEAM", "PLAYER", "PLAYER_NORM"], as_index=False).agg(
        games=("GAME_ID", "nunique"), **{p: (p, "mean") for p in props}
    )

    by_player: dict[str, Any] = {}
    team_avgs_out: dict[str, Any] = {}
    leaders: dict[str, Any] = {}
    for _, tr in team_avg.iterrows():
        team = str(tr["TEAM"])
        team_avgs_out[team] = {"games": int(tr["games"]), **{p: round(float(tr[p]), 2) for p in props}}
        leaders[team] = {}

    merged = pavg.merge(team_avg, on="TEAM", suffixes=("", "_TEAM"))
    for _, r in merged.iterrows():
        if int(r["games"]) < 10:
            continue
        team = str(r["TEAM"])
        pn = str(r["PLAYER_NORM"])
        for prop in props:
            pval = float(r[prop])
            tval = float(r.get(f"{prop}_TEAM", np.nan))
            if not np.isfinite(tval) or tval <= 0:
                continue
            rec = {
                "player": str(r["PLAYER"]),
                "player_norm": pn,
                "team": team,
                "prop": prop,
                "player_avg": round(pval, 2),
                "team_avg": round(tval, 2),
                "share_pct": round(100.0 * pval / tval, 1),
                "games": int(r["games"]),
                "min_avg": None,
            }
            by_player[f"{team}|{pn}|{prop}"] = rec
            leaders.setdefault(team, {}).setdefault(prop, []).append(rec)
    for team, props_d in leaders.items():
        for prop, rows in props_d.items():
            rows.sort(key=lambda x: -x["share_pct"])
            leaders[team][prop] = rows[:10]

    return {
        "sport": "mlb",
        "season": season,
        "source": str(path.relative_to(root)),
        "applicable": True,
        "note": "Hitter props only; TEAM keyed by MLB TEAM_ID. Pitcher props are not team-share.",
        "team_averages": team_avgs_out,
        "leaders": leaders,
        "by_player": by_player,
        "props": props,
        "team_aliases": {},
        "player_count": len({k.split("|")[1] for k in by_player}),
        "team_count": len(team_avgs_out),
    }


def build_nhl_share(repo: Path | None = None) -> dict[str, Any]:
    root = repo or _REPO
    db_paths = [
        root / "Sports/NHL/data/cache/proporacle_ref.db",
        root / "data/cache/proporacle_ref.db",
    ]
    import sqlite3

    db = next((p for p in db_paths if p.exists()), None)
    if db is None:
        return {
            "sport": "nhl",
            "applicable": False,
            "reason": "no proporacle_ref.db",
            "by_player": {},
            "team_averages": {},
        }

    con = sqlite3.connect(str(db))
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "nhl" not in tables:
            return {
                "sport": "nhl",
                "applicable": False,
                "reason": "no nhl table",
                "by_player": {},
                "team_averages": {},
            }
        cols = {r[1] for r in con.execute("PRAGMA table_info(nhl)").fetchall()}
        player_col = "player" if "player" in cols else ("player_name" if "player_name" in cols else None)
        if player_col is None or "team" not in cols or "event_id" not in cols:
            return {
                "sport": "nhl",
                "applicable": False,
                "reason": f"nhl schema mismatch: {sorted(cols)[:20]}",
                "by_player": {},
                "team_averages": {},
            }
        qcols = [player_col, "team", "event_id"]
        for c in ("goals", "assists", "points", "shots_on_goal", "shots", "toi", "minutes"):
            if c in cols:
                qcols.append(c)
        df = pd.read_sql_query(f"SELECT {', '.join(qcols)} FROM nhl", con)
    finally:
        con.close()

    df = df.rename(columns={player_col: "PLAYER", "shots_on_goal": "Shots"})
    if "Shots" not in df.columns and "shots" in df.columns:
        df["Shots"] = df["shots"]
    for c, dest in [("goals", "Goals"), ("assists", "Assists"), ("points", "Points")]:
        if c in df.columns:
            df[dest] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    if "Shots" in df.columns:
        df["Shots"] = pd.to_numeric(df["Shots"], errors="coerce").fillna(0.0)
    if "Points" not in df.columns and "Goals" in df.columns and "Assists" in df.columns:
        df["Points"] = df["Goals"] + df["Assists"]
    df["MIN"] = pd.to_numeric(df.get("toi", df.get("minutes", 1.0)), errors="coerce").fillna(1.0)
    props = [c for c in ("Goals", "Assists", "Points", "Shots") if c in df.columns]
    if not props:
        return {
            "sport": "nhl",
            "applicable": False,
            "reason": "no goal/assist/shot cols",
            "by_player": {},
            "team_averages": {},
        }

    nhl_map = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "CLB": "CBJ", "ARZ": "UTA"}
    df["TEAM"] = df["team"].astype(str).str.upper().map(lambda t: nhl_map.get(t, t))
    df["PLAYER_NORM"] = df["PLAYER"].map(_norm_name)
    df["event_id"] = df["event_id"].astype(str)

    tgt = df.groupby(["TEAM", "event_id"], as_index=False)[props].sum()
    team_avg = tgt.groupby("TEAM", as_index=False).agg(
        games=("event_id", "nunique"), **{p: (p, "mean") for p in props}
    )
    played = df[df["MIN"] > 0]
    pavg = played.groupby(["TEAM", "PLAYER", "PLAYER_NORM"], as_index=False).agg(
        games=("event_id", "nunique"), MIN=("MIN", "mean"), **{p: (p, "mean") for p in props}
    )
    by_player: dict[str, Any] = {}
    team_avgs_out: dict[str, Any] = {}
    leaders: dict[str, Any] = {}
    for _, tr in team_avg.iterrows():
        team = str(tr["TEAM"])
        team_avgs_out[team] = {"games": int(tr["games"]), **{p: round(float(tr[p]), 2) for p in props}}
        leaders[team] = {}
    merged = pavg.merge(team_avg, on="TEAM", suffixes=("", "_TEAM"))
    for _, r in merged.iterrows():
        if int(r["games"]) < 5:
            continue
        team = str(r["TEAM"])
        pn = str(r["PLAYER_NORM"])
        for prop in props:
            pval = float(r[prop])
            tval = float(r.get(f"{prop}_TEAM", np.nan))
            if not np.isfinite(tval) or tval <= 0:
                continue
            rec = {
                "player": str(r["PLAYER"]),
                "player_norm": pn,
                "team": team,
                "prop": prop,
                "player_avg": round(pval, 2),
                "team_avg": round(tval, 2),
                "share_pct": round(100.0 * pval / tval, 1),
                "games": int(r["games"]),
                "min_avg": round(float(r["MIN"]), 1) if np.isfinite(r["MIN"]) else None,
            }
            by_player[f"{team}|{pn}|{prop}"] = rec
            leaders.setdefault(team, {}).setdefault(prop, []).append(rec)
    for team, props_d in leaders.items():
        for prop, rows in props_d.items():
            rows.sort(key=lambda x: -x["share_pct"])
            leaders[team][prop] = rows[:10]

    return {
        "sport": "nhl",
        "source": str(db.relative_to(root)),
        "applicable": True,
        "note": "Goals/Assists/Points/Shots share from DB boxscores.",
        "team_averages": team_avgs_out,
        "leaders": leaders,
        "by_player": by_player,
        "props": props,
        "team_aliases": nhl_map,
        "player_count": len({k.split("|")[1] for k in by_player}),
        "team_count": len(team_avgs_out),
    }


def build_sport_share(sport: str, repo: Path | None = None) -> dict[str, Any]:
    s = str(sport or "").strip().lower()
    if s == "wnba":
        return build_wnba_share(repo)
    if s in ("nba", "nba1h", "nba1q"):
        return build_nba_share(repo)
    if s == "cbb":
        return build_cbb_share(repo, womens=False)
    if s == "wcbb":
        return build_cbb_share(repo, womens=True)
    if s == "mlb":
        return build_mlb_share(repo)
    if s == "nhl":
        return build_nhl_share(repo)
    if s == "tennis":
        return {
            "sport": "tennis",
            "applicable": False,
            "reason": "No team — player vs player only.",
            "by_player": {},
            "team_averages": {},
        }
    if s == "soccer":
        return {
            "sport": "soccer",
            "applicable": False,
            "reason": "Team share deferred (sparse events / weak team linkage).",
            "by_player": {},
            "team_averages": {},
        }
    if s == "nfl":
        return {
            "sport": "nfl",
            "applicable": False,
            "reason": "nfl_boxscore_cache.csv missing — rebuild when season active.",
            "by_player": {},
            "team_averages": {},
        }
    return {
        "sport": s,
        "applicable": False,
        "reason": "unsupported sport",
        "by_player": {},
        "team_averages": {},
    }


def write_sport_share(sport: str, repo: Path | None = None) -> Path:
    root = repo or _REPO
    payload = build_sport_share(sport, root)
    path = share_artifact_path(sport, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Matchup Edge only needs by_player (+ meta). Drop bulky leaders for disk size.
    lean = {k: v for k, v in payload.items() if k != "leaders"}
    # Compact by_player records (drop redundant keys mirrored in the lookup key)
    bp = lean.get("by_player") or {}
    if isinstance(bp, dict) and bp:
        compact = {}
        for key, rec in bp.items():
            if not isinstance(rec, dict):
                continue
            compact[key] = {
                "player_avg": rec.get("player_avg"),
                "team_avg": rec.get("team_avg"),
                "share_pct": rec.get("share_pct"),
                "games": rec.get("games"),
                "min_avg": rec.get("min_avg"),
            }
        lean["by_player"] = compact
    path.write_text(json.dumps(lean, separators=(",", ":")), encoding="utf-8")
    # Optional human-readable leaders sidecar for analysis canvases
    leaders = payload.get("leaders")
    if leaders:
        side = path.with_name(path.stem + "_leaders.json")
        side.write_text(
            json.dumps(
                {
                    "sport": payload.get("sport"),
                    "team_averages": payload.get("team_averages"),
                    "leaders": leaders,
                    "props": payload.get("props"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return path


def attach_share_fields(
    player_obj: dict[str, Any],
    share_payload: dict[str, Any] | None,
    *,
    team: str,
    category_id: str | None = None,
    prop: str | None = None,
    line: float | None = None,
) -> dict[str, Any]:
    if not share_payload or not share_payload.get("applicable"):
        return player_obj
    prop_name = prop or CAT_ID_TO_PROP.get(str(category_id or "").strip().lower(), "")
    if not prop_name:
        return player_obj
    hit = lookup_player_share(
        share_payload,
        team=team,
        player=player_obj.get("player") or player_obj.get("player_norm") or "",
        prop=prop_name,
    )
    if not hit:
        return player_obj
    player_obj["team_avg"] = hit.get("team_avg")
    player_obj["share_pct"] = hit.get("share_pct")
    player_obj["share_player_avg"] = hit.get("player_avg")
    use_line = line
    if use_line is None:
        try:
            use_line = float(player_obj["pp_line"]) if player_obj.get("pp_line") is not None else None
        except Exception:
            use_line = None
    if use_line is not None and hit.get("team_avg"):
        try:
            line_pct = 100.0 * float(use_line) / float(hit["team_avg"])
            player_obj["line_as_pct_of_team"] = round(line_pct, 1)
            player_obj["share_vs_line"] = round(float(hit["share_pct"]) - line_pct, 1)
        except Exception:
            pass
    pav = hit.get("player_avg")
    if use_line is not None and pav is not None:
        gap = float(pav) - float(use_line)
        player_obj["avg_vs_line"] = round(gap, 2)
        if gap >= 1.5:
            player_obj["share_lean"] = "OVER"
        elif gap <= -1.5:
            player_obj["share_lean"] = "UNDER"
        else:
            player_obj["share_lean"] = "NEAR"
    return player_obj


def enrich_matchup_edge_payload(
    payload: dict[str, Any], sport: str, repo: Path | None = None
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("error"):
        return payload
    share = load_share_payload(sport, repo)
    if not share or not share.get("applicable"):
        payload["team_share"] = {
            "applicable": False,
            "reason": (share or {}).get("reason")
            or "team share artifact missing — run scripts/build_team_share_json.py",
        }
        return payload

    pbtc = payload.get("players_by_team_cat")
    if isinstance(pbtc, dict):
        for key, block in pbtc.items():
            if not isinstance(block, dict):
                continue
            team = str(block.get("team_slate") or key.split("|")[0] or "").strip().upper()
            cat = str(
                block.get("category") or (key.split("|")[1] if "|" in key else "")
            ).strip().lower()
            for p in block.get("players") or []:
                if isinstance(p, dict):
                    attach_share_fields(p, share, team=team, category_id=cat)

    payload["team_share"] = {
        "applicable": True,
        "sport": share.get("sport"),
        "source": share.get("source"),
        "props": share.get("props"),
        "team_count": share.get("team_count"),
        "player_count": share.get("player_count"),
        "note": share.get("note"),
    }
    return payload


def enrich_slate_rows(
    rows: list[dict[str, Any]], sport: str, repo: Path | None = None
) -> list[dict[str, Any]]:
    share = load_share_payload(sport, repo)
    if not share or not share.get("applicable") or not rows:
        return rows
    for r in rows:
        if not isinstance(r, dict):
            continue
        team = str(r.get("team") or "").strip().upper()
        prop = str(r.get("prop") or r.get("prop_type") or "")
        try:
            line = float(r.get("line")) if r.get("line") is not None else None
        except Exception:
            line = None
        attach_share_fields(r, share, team=team, prop=prop, line=line)
    return rows
