"""NFL prop-aware defense rank selection (pass / rush / receiving).

Mirrors CFB ``_prop_def_keys``: pass props → pass D, rush → rush D,
receiving → pass D (coverage), else pass as overall fallback.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from utils.defense_tiers import def_tier_from_overall_rank
from utils.nfl_espn_context import canon_nfl_abbr

PASSING_PROPS = frozenset(
    {
        "passing_yards",
        "passing_tds",
        "pass_attempts",
        "completions",
        "interceptions",
        "pass_completions",
        "passing_attempts",
        "pass_yds",
        "pass_td",
    }
)
RUSHING_PROPS = frozenset(
    {
        "rushing_yards",
        "rushing_attempts",
        "rushing_tds",
        "carries",
        "rush_yds",
        "rush_td",
    }
)
RECEIVING_PROPS = frozenset(
    {
        "receiving_yards",
        "receptions",
        "targets",
        "receiving_tds",
        "rec_yds",
        "rec_td",
        "rec",
    }
)
KICKING_PROPS = frozenset(
    {
        "fg_made",
        "field_goals",
        "field_goals_made",
        "kicking_points",
        "kicking_pts",
        "extra_points",
        "pat_made",
        "xp_made",
        "fg",
    }
)


def _norm_prop(raw: object) -> str:
    s = str(raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def prop_def_axis(prop: object) -> str:
    """Return 'pass', 'rush', 'kick', or 'pass' (receiving / default)."""
    p = _norm_prop(prop)
    if p in KICKING_PROPS or "field_goal" in p or p.startswith("fg") or "kick" in p or p in ("xp", "pat"):
        return "kick"
    if p in PASSING_PROPS or "pass" in p:
        return "pass"
    if p in RUSHING_PROPS or "rush" in p or p == "carries":
        return "rush"
    if p in RECEIVING_PROPS or "rec" in p or "receiv" in p or "target" in p:
        return "pass"  # coverage / pass defense proxy
    return "pass"


_GAME_PAIR_RE = re.compile(
    r"\b([A-Za-z]{2,4})\s*(?:@|vs\.?|v\.?)\s*([A-Za-z]{2,4})\b",
    re.IGNORECASE,
)


def _tok_team(v: object) -> str:
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return canon_nfl_abbr(v)


def opp_from_game_text(text: object, team: object) -> str:
    """Opponent abbr from 'CHI @ TEN' / 'TEN vs CHI' given the player's team."""
    blob = str(text or "").strip()
    if not blob:
        return ""
    mine = _tok_team(team)
    m = _GAME_PAIR_RE.search(blob)
    if not m:
        m2 = re.search(r"\bvs\.?\s+([A-Za-z]{2,4})\b", blob, re.IGNORECASE)
        if m2:
            other = _tok_team(m2.group(1))
            return other if other and other != mine else ""
        return ""
    a, b = _tok_team(m.group(1)), _tok_team(m.group(2))
    if not a or not b:
        return ""
    if mine == a:
        return b
    if mine == b:
        return a
    return ""


def _opp_from_home_away(team: object, home: object, away: object) -> str:
    mine = _tok_team(team)
    h = _tok_team(home)
    a = _tok_team(away)
    if not mine or not h or not a:
        return ""
    if mine == h:
        return a
    if mine == a:
        return h
    return ""


def fill_opp_team_from_game(
    df: pd.DataFrame,
    *,
    espn_opp_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Fill blank opp_team from home/away, game_id pair, game text, or ESPN map.

    Thin boards (only one club posted) cannot infer from game_id alone — persist
    home_team/away_team from PrizePicks or pass espn_opp_map from the scoreboard.
    """
    out = df.copy()
    team_col = next((c for c in ("team", "team_abbr") if c in out.columns), None)
    if not team_col:
        return out
    if "opp_team" not in out.columns:
        out["opp_team"] = ""
    gid_col = next((c for c in ("game_id", "pp_game_id") if c in out.columns), None)
    home_col = next((c for c in ("home_team", "home") if c in out.columns), None)
    away_col = next((c for c in ("away_team", "away") if c in out.columns), None)
    text_cols = [c for c in ("game", "description", "matchup", "game_name") if c in out.columns]

    by_game: dict[object, set[str]] = {}
    if gid_col:
        for gid, team in zip(out[gid_col].tolist(), out[team_col].tolist()):
            t = _tok_team(team)
            if not t:
                continue
            by_game.setdefault(gid, set()).add(t)

    filled: list[str] = []
    n_fill = 0
    sources = {"home_away": 0, "game_id": 0, "game_text": 0, "espn": 0}
    n = len(out)
    teams = out[team_col].tolist()
    opps = out["opp_team"].tolist()
    gids = out[gid_col].tolist() if gid_col else [None] * n
    homes = out[home_col].tolist() if home_col else [None] * n
    aways = out[away_col].tolist() if away_col else [None] * n
    texts = (
        [" ".join(str(out.at[out.index[i], c] or "") for c in text_cols) for i in range(n)]
        if text_cols
        else [""] * n
    )

    for i in range(n):
        cur = _tok_team(opps[i])
        if cur:
            filled.append(cur)
            continue
        team = teams[i]
        hit = _opp_from_home_away(team, homes[i], aways[i])
        if hit:
            filled.append(hit)
            n_fill += 1
            sources["home_away"] += 1
            continue
        others = [t for t in by_game.get(gids[i], set()) if t != _tok_team(team)]
        if len(others) == 1:
            filled.append(others[0])
            n_fill += 1
            sources["game_id"] += 1
            continue
        hit = opp_from_game_text(texts[i], team)
        if hit:
            filled.append(hit)
            n_fill += 1
            sources["game_text"] += 1
            continue
        mapped = ""
        if espn_opp_map:
            mapped = _tok_team(espn_opp_map.get(_tok_team(team), ""))
        if mapped:
            filled.append(mapped)
            n_fill += 1
            sources["espn"] += 1
        else:
            filled.append(cur)

    out["opp_team"] = filled
    if n_fill:
        bits = ", ".join(f"{k}={v}" for k, v in sources.items() if v)
        print(f"[NFL] filled opp_team on {n_fill} rows ({bits})")
    return out


def select_opp_def_rank(
    row: pd.Series | dict,
    *,
    prop: object | None = None,
    n_teams: int = 32,
) -> float:
    """Pick opponent def rank for this prop (NaN if missing)."""
    if prop is None:
        prop = row.get("prop_type_normalized") or row.get("prop_norm") or row.get("prop_type")
    axis = prop_def_axis(prop)
    if axis == "rush":
        keys: Iterable[str] = ("opp_rush_def_rank", "rush_def_rank", "opp_pass_def_rank")
    elif axis == "kick":
        keys = (
            "opp_fg_def_rank",
            "fg_def_rank",
            "opp_kick_pts_def_rank",
            "kick_pts_def_rank",
            "opp_pass_def_rank",
        )
    else:
        keys = ("opp_pass_def_rank", "pass_def_rank", "opp_rush_def_rank")
    for k in keys:
        v = row.get(k) if hasattr(row, "get") else None
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f and f > 0:
            return f
    return float("nan")


def assign_prop_aware_def_tier(
    df: pd.DataFrame,
    *,
    prop_col: str | None = None,
    n_teams: int = 32,
    out_rank_col: str = "opp_def_rank_prop",
    out_tier_col: str = "def_tier",
) -> pd.DataFrame:
    """Write prop-aware opp rank + Elite→Weak def_tier onto df."""
    out = df.copy()
    if prop_col is None:
        for c in ("prop_type_normalized", "prop_norm", "prop_type", "stat_type"):
            if c in out.columns:
                prop_col = c
                break
    props = out[prop_col] if prop_col and prop_col in out.columns else pd.Series([""] * len(out))

    ranks: list[float] = []
    tiers: list[str] = []
    for i in range(len(out)):
        r = out.iloc[i]
        rk = select_opp_def_rank(r, prop=props.iloc[i] if len(props) else None, n_teams=n_teams)
        ranks.append(rk)
        if rk == rk:
            try:
                tiers.append(def_tier_from_overall_rank(int(rk), n_teams))
            except (TypeError, ValueError):
                tiers.append("UNKNOWN")
        else:
            tiers.append("UNKNOWN")

    out[out_rank_col] = ranks
    out[out_tier_col] = tiers
    if "opp_def_tier" not in out.columns or out["opp_def_tier"].astype(str).str.strip().eq("").all():
        out["opp_def_tier"] = tiers
    return out


def snap_pct_to_minutes_tier(snap_pct: object) -> str:
    """Map offensive snap % (0–100 or 0–1) → HIGH / MEDIUM / LOW / UNKNOWN."""
    try:
        v = float(snap_pct)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if v != v:
        return "UNKNOWN"
    if v <= 1.0:
        v *= 100.0
    if v >= 70.0:
        return "HIGH"
    if v >= 40.0:
        return "MEDIUM"
    if v >= 0.0:
        return "LOW"
    return "UNKNOWN"


def last_completed_nfl_season(today: datetime.date | None = None) -> int:
    """Regular-season year used for D ranks. Before September, use the prior league year."""
    d = today or datetime.date.today()
    if d.month >= 9:
        return d.year
    return d.year - 1


def defense_table_is_complete(df: pd.DataFrame, *, min_teams: int = 28) -> bool:
    if df is None or getattr(df, "empty", True):
        return False
    if "pass_def_rank" not in df.columns:
        return False
    ranks = pd.to_numeric(df["pass_def_rank"], errors="coerce")
    return int(ranks.notna().sum()) >= min_teams


def sync_nfl_reference_defense(
    step4_df: pd.DataFrame,
    *,
    season: int,
    reference_path: Path,
) -> None:
    """Patch data/reference/nfl_team_defense.csv from the ESPN byteam table.

    Keeps roster metadata (team_id, name, sacks, turnovers) and overwrites
    pass / rush / FG ranks so NFL and NFLP stay on the same 32-team D file.
    """
    src = step4_df.copy()
    if "team" not in src.columns:
        print("[NFL] skip reference sync: no team column")
        return
    src["team"] = src["team"].astype(str).str.strip().str.upper()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _col(frame: pd.DataFrame, *names: str) -> pd.Series:
        for n in names:
            if n in frame.columns:
                return pd.to_numeric(frame[n], errors="coerce")
        return pd.Series([pd.NA] * len(frame), index=frame.index)

    patch = pd.DataFrame(
        {
            "team_abbr": src["team"],
            "season": int(season),
            "points_allowed_pg": _col(src, "points_allowed_pg"),
            "opp_pass_ypg": _col(src, "pass_yards_allowed_pg", "opp_pass_ypg"),
            "pass_def_rank": _col(src, "pass_def_rank"),
            "opp_rush_ypg": _col(src, "rush_yards_allowed_pg", "opp_rush_ypg"),
            "rush_def_rank": _col(src, "rush_def_rank"),
            "opp_fg_made": _col(src, "opp_fg_made"),
            "opp_fg_att": _col(src, "opp_fg_att"),
            "opp_fg_pct": _col(src, "opp_fg_pct"),
            "opp_xp_made": _col(src, "opp_xp_made"),
            "opp_fg_made_pg": _col(src, "opp_fg_made_pg"),
            "opp_kick_pts_pg": _col(src, "opp_kick_pts_pg"),
            "fg_def_rank": _col(src, "fg_def_rank"),
            "kick_pts_def_rank": _col(src, "kick_pts_def_rank"),
            "updated_at": now,
        }
    )
    pa = pd.to_numeric(patch["points_allowed_pg"], errors="coerce")
    patch["pa_rank"] = pa.rank(method="min", ascending=True)

    keep = (
        "team_id",
        "team_name",
        "sacks",
        "sacks_rank",
        "turnovers_forced",
        "to_rank",
    )
    reference_path = Path(reference_path)
    preserved = pd.DataFrame()
    if reference_path.is_file():
        try:
            ref = pd.read_csv(reference_path, encoding="utf-8-sig")
        except Exception:
            ref = pd.DataFrame()
        if not ref.empty:
            key = "team_abbr" if "team_abbr" in ref.columns else ("team" if "team" in ref.columns else "")
            if key:
                ref["_k"] = ref[key].astype(str).str.strip().str.upper()
                cols = [c for c in keep if c in ref.columns]
                if cols:
                    preserved = ref.set_index("_k")[cols]

    out = patch.copy()
    if not preserved.empty:
        out = out.merge(preserved, left_on="team_abbr", right_index=True, how="left")
    else:
        for c in keep:
            if c not in out.columns:
                out[c] = pd.NA

    ordered = [
        "team_id",
        "team_abbr",
        "team_name",
        "season",
        "points_allowed_pg",
        "pa_rank",
        "opp_pass_ypg",
        "pass_def_rank",
        "opp_rush_ypg",
        "rush_def_rank",
        "sacks",
        "sacks_rank",
        "turnovers_forced",
        "to_rank",
        "updated_at",
        "opp_fg_made",
        "opp_fg_att",
        "opp_fg_pct",
        "opp_xp_made",
        "opp_fg_made_pg",
        "opp_kick_pts_pg",
        "fg_def_rank",
        "kick_pts_def_rank",
    ]
    rest = [c for c in out.columns if c not in ordered]
    out = out[[c for c in ordered if c in out.columns] + rest]
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(reference_path, index=False, encoding="utf-8-sig")
    print(f"[NFL] reference defense synced -> {reference_path} teams={len(out)} season={season}")
