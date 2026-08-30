#!/usr/bin/env python3
"""
NFL step4 — team defensive summary for pass / rush / field-goal matchup context.

Priority:
  1. Pro Football Reference (skipped here: Cloudflare blocks simple HTTP clients)
  2. ESPN: NFL standings (points against) + team statistics byteam
     (opponent pass/rush/kicking). Offseason default is last completed season.

Output: NFL/data/defense_rankings.csv

  set NFL_PIPELINE_ACTIVE=1
  py -3.14 scripts/step4_defense_rankings.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests

_SCRIPT_DIR = Path(__file__).resolve().parent
_NFL_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _SCRIPT_DIR.resolve().parents[2]
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _nfl_pipeline_active import require_nfl_pipeline_active_or_exit
from utils.nfl_prop_defense import (
    defense_table_is_complete,
    last_completed_nfl_season,
    sync_nfl_reference_defense,
)

REFERENCE_DEFENSE_CSV = _REPO_ROOT / "data" / "reference" / "nfl_team_defense.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

# Fallback if ESPN is unreachable (32 teams; ranks are placeholders).
_FALLBACK_ABBR = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WSH",
]


def _standings_points_against(season: int) -> dict[str, dict[str, float]]:
    url = f"https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season={season}&type=0"
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    j = r.json()
    out: dict[str, dict[str, float]] = {}
    for child in j.get("children") or []:
        for entry in (child.get("standings") or {}).get("entries") or []:
            team = entry.get("team") or {}
            abbr = str(team.get("abbreviation") or "").strip().upper()
            if not abbr:
                continue
            games = 0.0
            pa = 0.0
            for st in entry.get("stats") or []:
                name = str(st.get("name") or "")
                if name == "wins":
                    games += float(st.get("value") or 0)
                elif name == "losses":
                    games += float(st.get("value") or 0)
                elif name == "ties":
                    games += float(st.get("value") or 0)
                elif name == "pointsAgainst":
                    pa = float(st.get("value") or 0)
            out[abbr] = {"points_against": pa, "games": max(games, 1.0)}
    return out


def _byteam_opponent_yards(season: int) -> dict[str, dict[str, float]]:
    url = (
        "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/statistics/byteam"
        f"?season={season}&seasontype=2&contentorigin=espn"
    )
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    root_labels: dict[str, list[str]] = {}
    for cat in j.get("categories") or []:
        name = str(cat.get("name") or "")
        if name in ("passing", "rushing", "kicking") and cat.get("labels"):
            root_labels[name] = list(cat["labels"])

    def _lab_val(labs: list[str], vals: list, lab: str) -> float:
        if lab not in labs:
            return float("nan")
        i = labs.index(lab)
        if i >= len(vals) or vals[i] is None:
            return float("nan")
        try:
            return float(vals[i])
        except (TypeError, ValueError):
            return float("nan")

    out: dict[str, dict[str, float]] = {}
    for t in j.get("teams") or []:
        team = t.get("team") or {}
        abbr = str(team.get("abbreviation") or "").strip().upper()
        if not abbr:
            continue
        pass_pg = rush_pg = pass_td = float("nan")
        fg_made = fg_att = fg_pct = xp_made = float("nan")
        for cat in t.get("categories") or []:
            disp = str(cat.get("displayName") or "")
            vals = cat.get("values") or []
            if disp == "Opponent Passing" and "passing" in root_labels:
                labs = root_labels["passing"]
                yds_g_idx = [i for i, lab in enumerate(labs) if lab == "YDS/G"]
                # ESPN lists two YDS/G blocks; the last one pairs with opponent passing YDS.
                if yds_g_idx and yds_g_idx[-1] < len(vals):
                    pass_pg = float(vals[yds_g_idx[-1]])
                if "TD" in labs:
                    ti = labs.index("TD")
                    if ti < len(vals):
                        pass_td = float(vals[ti])
            if disp == "Opponent Rushing" and "rushing" in root_labels:
                labs = root_labels["rushing"]
                yds_g_idx = [i for i, lab in enumerate(labs) if lab == "YDS/G"]
                if yds_g_idx and yds_g_idx[0] < len(vals):
                    rush_pg = float(vals[yds_g_idx[0]])
            if disp == "Opponent Kicking" and "kicking" in root_labels:
                labs = root_labels["kicking"]
                fg_made = _lab_val(labs, vals, "FGM")
                fg_att = _lab_val(labs, vals, "FGA")
                fg_pct = _lab_val(labs, vals, "FG%")
                xp_made = _lab_val(labs, vals, "XPM")
        out[abbr] = {
            "pass_yards_allowed_pg": pass_pg,
            "rush_yards_allowed_pg": rush_pg,
            "pass_tds_allowed": pass_td,
            "opp_fg_made": fg_made,
            "opp_fg_att": fg_att,
            "opp_fg_pct": fg_pct,
            "opp_xp_made": xp_made,
        }
    return out


def _rank_series(values: pd.Series, *, ascending: bool = True) -> pd.Series:
    """1 = best (lowest yards allowed when ascending=True). NaN stays NA."""
    return values.rank(method="min", ascending=ascending)


def _fallback_df() -> pd.DataFrame:
    rows = []
    for i, abbr in enumerate(_FALLBACK_ABBR):
        rows.append(
            {
                "team": abbr,
                "pass_yards_allowed_pg": 230.0,
                "rush_yards_allowed_pg": 115.0,
                "pass_tds_allowed": 24.0,
                "points_allowed_pg": 22.0,
                "pass_def_rank": i + 1,
                "rush_def_rank": i + 1,
                "opp_fg_made": 28.0,
                "opp_fg_att": 33.0,
                "opp_fg_pct": 84.0,
                "opp_fg_made_pg": 1.65,
                "opp_xp_made": 35.0,
                "opp_kick_pts_pg": 7.0,
                "fg_def_rank": i + 1,
                "kick_pts_def_rank": i + 1,
            }
        )
    return pd.DataFrame(rows)


def _reference_as_legacy() -> pd.DataFrame | None:
    """Map data/reference/nfl_team_defense.csv onto the step4 legacy columns."""
    if not REFERENCE_DEFENSE_CSV.is_file():
        return None
    try:
        raw = pd.read_csv(REFERENCE_DEFENSE_CSV, encoding="utf-8-sig")
    except Exception:
        return None
    if raw.empty:
        return None
    out = pd.DataFrame()
    if "team_abbr" in raw.columns:
        out["team"] = raw["team_abbr"].astype(str).str.strip().str.upper()
    elif "team" in raw.columns:
        out["team"] = raw["team"].astype(str).str.strip().str.upper()
    else:
        return None
    out["pass_yards_allowed_pg"] = pd.to_numeric(raw.get("opp_pass_ypg"), errors="coerce")
    out["rush_yards_allowed_pg"] = pd.to_numeric(raw.get("opp_rush_ypg"), errors="coerce")
    out["pass_tds_allowed"] = pd.to_numeric(raw.get("sacks"), errors="coerce")
    out["points_allowed_pg"] = pd.to_numeric(raw.get("points_allowed_pg"), errors="coerce")
    out["pass_def_rank"] = pd.to_numeric(raw.get("pass_def_rank"), errors="coerce")
    out["rush_def_rank"] = pd.to_numeric(raw.get("rush_def_rank"), errors="coerce")
    out["opp_fg_made"] = pd.to_numeric(raw.get("opp_fg_made"), errors="coerce")
    out["opp_fg_att"] = pd.to_numeric(raw.get("opp_fg_att"), errors="coerce")
    out["opp_fg_pct"] = pd.to_numeric(raw.get("opp_fg_pct"), errors="coerce")
    out["opp_fg_made_pg"] = pd.to_numeric(raw.get("opp_fg_made_pg"), errors="coerce")
    out["opp_xp_made"] = pd.to_numeric(raw.get("opp_xp_made"), errors="coerce")
    out["opp_kick_pts_pg"] = pd.to_numeric(raw.get("opp_kick_pts_pg"), errors="coerce")
    out["fg_def_rank"] = pd.to_numeric(raw.get("fg_def_rank"), errors="coerce")
    out["kick_pts_def_rank"] = pd.to_numeric(raw.get("kick_pts_def_rank"), errors="coerce")
    out = out.dropna(subset=["team"]).drop_duplicates("team")
    if out.empty or out["pass_def_rank"].nunique(dropna=True) <= 1:
        return None
    print(f"[NFL step4] Using reference defense {REFERENCE_DEFENSE_CSV} ({len(out)} teams)")
    return out.sort_values("team").reset_index(drop=True)


def fetch_defense_table(season: int) -> pd.DataFrame:
    try:
        pa = _standings_points_against(season)
        yd = _byteam_opponent_yards(season)
        rows: list[dict[str, Any]] = []
        for abbr in sorted(set(pa.keys()) | set(yd.keys())):
            g = pa.get(abbr, {}).get("games", 17.0)
            pts = pa.get(abbr, {}).get("points_against", float("nan"))
            y = yd.get(abbr, {})
            fg_made = float(y.get("opp_fg_made", float("nan")))
            xp_made = float(y.get("opp_xp_made", float("nan")))
            fg_pg = (fg_made / g) if g and fg_made == fg_made else float("nan")
            kick_pts = (3.0 * fg_made + xp_made) if fg_made == fg_made and xp_made == xp_made else float("nan")
            kick_pts_pg = (kick_pts / g) if g and kick_pts == kick_pts else float("nan")
            rows.append(
                {
                    "team": abbr,
                    "season": season,
                    "pass_yards_allowed_pg": y.get("pass_yards_allowed_pg", float("nan")),
                    "rush_yards_allowed_pg": y.get("rush_yards_allowed_pg", float("nan")),
                    "pass_tds_allowed": y.get("pass_tds_allowed", float("nan")),
                    "points_allowed_pg": float(pts) / float(g) if g else float("nan"),
                    "opp_fg_made": fg_made,
                    "opp_fg_att": y.get("opp_fg_att", float("nan")),
                    "opp_fg_pct": y.get("opp_fg_pct", float("nan")),
                    "opp_fg_made_pg": fg_pg,
                    "opp_xp_made": xp_made,
                    "opp_kick_pts_pg": kick_pts_pg,
                }
            )
        df = pd.DataFrame(rows)
        df = df.dropna(subset=["team"])
        df["pass_def_rank"] = _rank_series(df["pass_yards_allowed_pg"], ascending=True)
        df["rush_def_rank"] = _rank_series(df["rush_yards_allowed_pg"], ascending=True)
        df["fg_def_rank"] = _rank_series(df["opp_fg_made_pg"], ascending=True)
        df["kick_pts_def_rank"] = _rank_series(df["opp_kick_pts_pg"], ascending=True)
        return df.sort_values("team").reset_index(drop=True)
    except Exception as exc:
        print(f"[NFL step4] ESPN fetch failed ({type(exc).__name__}: {exc}); using fallback table.")
        ref = _reference_as_legacy()
        if ref is not None:
            return ref
        return _fallback_df()


def main() -> None:
    require_nfl_pipeline_active_or_exit()

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--season",
        type=int,
        default=0,
        help="NFL league year (0 = last completed; 2025 before 2026 Week 1)",
    )
    ap.add_argument("--output", default="data/defense_rankings.csv")
    args = ap.parse_args()
    season = int(args.season) if int(args.season) else last_completed_nfl_season()

    df = fetch_defense_table(season)
    used = season
    if not defense_table_is_complete(df):
        prev = season - 1
        print(f"[NFL step4] season {season} incomplete ({len(df)} rows); trying {prev}")
        prev_df = fetch_defense_table(prev)
        if defense_table_is_complete(prev_df):
            df = prev_df
            used = prev
    if "season" not in df.columns:
        df = df.copy()
        df["season"] = used

    out = Path(args.output)
    if not out.is_absolute():
        out = _NFL_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[NFL step4] Wrote {out} rows={len(df)} (season={used})")

    sync_nfl_reference_defense(df, season=used, reference_path=REFERENCE_DEFENSE_CSV)
    # Prop-aware def_tier is assigned in step7 (utils.nfl_prop_defense).


if __name__ == "__main__":
    main()
