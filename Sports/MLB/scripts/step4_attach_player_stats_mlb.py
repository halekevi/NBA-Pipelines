#!/usr/bin/env python3
"""
step4_attach_player_stats_mlb.py  (MLB Pipeline)

Pulls last-N game stats from the official MLB Stats API:
  https://statsapi.mlb.com/api/v1/people/{id}/stats?stats=gameLog&group=hitting&season={year}
  https://statsapi.mlb.com/api/v1/people/{id}/stats?stats=gameLog&group=pitching&season={year}

Handles:
  - Hitter props: hits, total_bases, home_runs, rbi, runs, walks,
                  stolen_bases, fantasy_score, hits_runs_rbi, singles, doubles, triples,
                  hitter_strikeouts (game log strikeOuts), plate_appearances,
                  pitches_seen (numberOfPitches), balls_counted / strikes_counted (PBP)
  - Pitcher props: strikeouts, pitching_outs, innings_pitched, hits_allowed,
                   earned_runs, walks_allowed, batters_faced, pitches_thrown (numberOfPitches),
                   strikes_thrown / balls_thrown (game log), pitches_thrown_95 (PBP >= 95 mph),
                   first_inning_runs_allowed, first_inning_walks_allowed (PBP feed/live)
  - Combo pitcher Ks: strikeouts_combo aliases to strikeouts and sums both arms
  - Pitcher Strikeouts + Total Bases: same-game Ks+TB for one player; recency
    sum of pitcher Ks + hitter TB for two-player combos

Outputs:
  step4_mlb_with_stats.csv
  mlb_stats_cache.csv   (grows over time — don't delete)

Run:
  py -3.14 step4_attach_player_stats_mlb.py \
    --input step3_mlb_with_defense.csv \
    --cache mlb_stats_cache.csv \
    --output step4_mlb_with_stats.csv
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from functools import lru_cache

import numpy as np
import pandas as pd
import requests

# Ensure repo root + scripts/ are on sys.path (role_stability lives under scripts/).
_PROPORACLE_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_ROOT = _PROPORACLE_ROOT / "scripts"
for _p in (_PROPORACLE_ROOT, _SCRIPTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.db_utils import (
    ensure_mlb_schema,
    log_pipeline_health,
    mlb_gamelog_counts,
    open_db,
    upsert_rows,
)
from utils.pipeline_dated_outputs import copy_pipeline_output_to_dated_dirs

COMBO_SEP = "|"

MLB_HEADERS = {
    # Browser-like headers to avoid intermittent MLB Stats API 405/blocks.
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://www.mlb.com",
    "Referer": "https://www.mlb.com/",
    "Connection": "keep-alive",
}

GAMELOG_URL = (
    "https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
    "?stats=gameLog&group={group}&season={season}&language=en"
)
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

PITCHER_PROPS = {
    "strikeouts", "pitching_outs", "innings_pitched",
    "hits_allowed", "earned_runs", "walks_allowed", "batters_faced",
    "pitches_thrown", "pitcher_fantasy_score",
    "first_inning_runs_allowed", "first_inning_walks_allowed",
    "balls_thrown", "strikes_thrown", "pitches_thrown_95",
}

PROP_ALIASES = {
    # Safe aliases: preserve existing stat derivations/cache shape.
    "hitter_fantasy_score": "fantasy_score",
    "earned_runs_allowed": "earned_runs",
    "strikeouts_combo": "strikeouts",
}

# Pitch-level stats that need feed/live playEvents. Empty cache rows are skipped
# so a failed fetch can retry on the next run.
PBP_PROPS = frozenset({
    "balls_counted",
    "strikes_counted",
    "pitches_thrown_95",
})

UNSUPPORTED_PROPS: set[str] = set()

_WARNED_UNSUPPORTED_PROPS: set[str] = set()
_WARNED_PITCHER_WIN_FALLBACK: set[tuple[str, str]] = set()
_PITCHER_WIN_FIELD_AVAILABLE: dict[tuple[str, str], bool] = {}
_FIRST_INNING_BY_GAME: Dict[str, Dict[str, Dict[str, float]]] = {}
_LIVE_FEED_STATS_BY_GAME: Dict[str, dict] = {}

# MLB Stats API teamId values (regular season). Common slate abbreviations included.
MLB_TEAM_ID_MAP: Dict[str, int] = {
    "ARI": 109, "AZ": 109,
    "ATL": 144,
    "BAL": 110,
    "BOS": 111,
    "CHC": 112,
    "CIN": 113,
    "CLE": 114,
    "COL": 115,
    "CWS": 145, "CHW": 145,
    "DET": 116,
    "HOU": 117,
    "KC": 118, "KCR": 118,
    "LAA": 108,
    "LAD": 119,
    "MIA": 146,
    "MIL": 158,
    "MIN": 142,
    "NYM": 121,
    "NYY": 147,
    "ATH": 133, "OAK": 133,
    "PHI": 143,
    "PIT": 134,
    "SD": 135, "SDP": 135,
    "SF": 137, "SFG": 137,
    "SEA": 136,
    "STL": 138,
    "TB": 139, "TBR": 139,
    "TEX": 140,
    "TOR": 141,
    "WSH": 120, "WSN": 120, "WAS": 120,
}

_MLB_SCHEDULE_CACHE: Dict[Tuple[str, int], List[str]] = {}


def _parse_slate_game_date(row: pd.Series) -> str:
    for col in ("game_date", "game_start", "start_time", "fetched_at"):
        raw = str(row.get(col, "") or "").strip()
        if not raw:
            continue
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.notna(ts):
            return ts.strftime("%Y-%m-%d")
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            return raw[:10]
    return ""


def fetch_mlb_team_schedule(team_abbrev: str, season: int) -> List[str]:
    """Regular-season game dates for team from MLB Stats API schedule endpoint."""
    team_abbrev = str(team_abbrev or "").strip().upper()
    season = int(season)
    cache_key = (team_abbrev, season)
    if cache_key in _MLB_SCHEDULE_CACHE:
        return _MLB_SCHEDULE_CACHE[cache_key]

    team_id = MLB_TEAM_ID_MAP.get(team_abbrev)
    if not team_id:
        print(f"[WARN] MLB schedule: unknown team abbreviation '{team_abbrev}'")
        _MLB_SCHEDULE_CACHE[cache_key] = []
        return []

    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&season={season}&teamId={team_id}&gameType=R"
    )
    try:
        resp = requests.get(url, headers=MLB_HEADERS, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        print(f"[WARN] MLB schedule fetch failed for {team_abbrev} (season {season}): {exc}")
        _MLB_SCHEDULE_CACHE[cache_key] = []
        return []

    dates: List[str] = []
    for block in payload.get("dates", []) or []:
        gd = str(block.get("date", "") or "").strip()[:10]
        if len(gd) >= 10:
            dates.append(gd)
    dates = sorted(set(dates))
    _MLB_SCHEDULE_CACHE[cache_key] = dates
    return dates


def compute_mlb_rest_days(team_abbrev: str, game_date: str, season: int) -> int:
    team_abbrev = str(team_abbrev or "").strip().upper()
    game_date = str(game_date or "").strip()[:10]
    if not team_abbrev or len(game_date) < 10:
        return -1
    schedule = fetch_mlb_team_schedule(team_abbrev, season)
    if not schedule:
        return -1
    prior = [d for d in schedule if d < game_date]
    if not prior:
        return -1
    try:
        return (
            datetime.strptime(game_date, "%Y-%m-%d")
            - datetime.strptime(prior[-1], "%Y-%m-%d")
        ).days
    except Exception:
        return -1


def attach_mlb_b2b_columns(df: pd.DataFrame, season: int, sport_label: str = "MLB") -> pd.DataFrame:
    out = df.copy()
    out["days_rest"] = -1
    out["is_back_to_back"] = 0
    out["opp_days_rest"] = -1
    out["opp_b2b"] = 0
    if "team" not in out.columns:
        print(f"[B2B] {sport_label}: 0 rows, 0 back-to-backs found (no team column)")
        return out

    game_dates = out.apply(_parse_slate_game_date, axis=1)
    rest_cache: Dict[Tuple[str, str], int] = {}

    def _lookup(team_val: str, gd: str) -> int:
        key = (str(team_val or "").strip().upper(), str(gd or "").strip()[:10])
        if not key[0] or len(key[1]) < 10:
            return -1
        if key not in rest_cache:
            rest_cache[key] = compute_mlb_rest_days(key[0], key[1], season)
        return rest_cache[key]

    out["days_rest"] = [_lookup(out.at[i, "team"], game_dates.at[i]) for i in out.index]
    out["is_back_to_back"] = (pd.to_numeric(out["days_rest"], errors="coerce") == 1).astype(int)
    if "opp_team" in out.columns:
        out["opp_days_rest"] = [_lookup(out.at[i, "opp_team"], game_dates.at[i]) for i in out.index]
        out["opp_b2b"] = (pd.to_numeric(out["opp_days_rest"], errors="coerce") == 1).astype(int)
    b2b_n = int((out["is_back_to_back"] == 1).sum())
    print(f"[B2B] {sport_label}: {len(out)} rows, {b2b_n} back-to-backs found")
    return out


def _sleep(base: float = 0.2) -> None:
    time.sleep(max(0.0, base + random.uniform(0, 0.15)))


def _get(url: str, retries: int = 3) -> Optional[dict]:
    for attempt in range(1, retries + 1):
        try:
            _sleep()
            r = requests.get(url, headers=MLB_HEADERS, timeout=20)
            if r.status_code == 404:
                return None

            # Treat 405 as soft rate-limiting / blocking; back off briefly then retry.
            if r.status_code in (405, 429):
                if attempt < retries:
                    time.sleep(1.0 + 0.75 * attempt)  # short, non-hammering backoff
                    continue
                log_pipeline_health(
                    "mlb.step4_attach_player_stats",
                    "mlb_api_get_blocked",
                    extra={"url": url, "status_code": r.status_code, "attempts": retries},
                    start=Path(__file__),
                )
                return None

            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt < retries:
                time.sleep(2.0 * attempt)
                continue
            log_pipeline_health(
                "mlb.step4_attach_player_stats",
                "mlb_api_get_failed",
                extra={"url": url, "attempts": retries},
                start=Path(__file__),
            )
    return None


def _parse_ids(mlb_player_id: str) -> List[str]:
    s = str(mlb_player_id).strip()
    if not s or s == "nan":
        return []

    def _norm_id_token(token: str) -> str:
        t = str(token).strip()
        if not t:
            return ""
        try:
            # CSV round-trips can turn IDs into "123456.0" strings.
            n = float(t)
            if np.isnan(n):
                return ""
            i = int(n)
            return str(i) if i > 0 else ""
        except Exception:
            return t if t.isdigit() else ""

    if COMBO_SEP in s:
        return [nid for nid in (_norm_id_token(p) for p in s.split(COMBO_SEP)) if nid]
    nid = _norm_id_token(s)
    return [nid] if nid else []


def fmt_num(x: float) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return ""
    return f"{float(x):.3f}".rstrip("0").rstrip(".")


def _ip_to_outs(ip_str) -> float:
    """Convert 'innings pitched' string like '6.1' to decimal outs (6*3+1=19)."""
    try:
        ip = float(ip_str)
        full   = int(ip)
        partial = round((ip - full) * 10)   # .1 → 1 out, .2 → 2 outs
        return float(full * 3 + partial)
    except (TypeError, ValueError):
        return np.nan


def _parse_first_inning_pitcher_stats(feed: dict) -> Dict[str, Dict[str, float]]:
    """
    Per-pitcher 1st-inning stats from feed/live allPlays.
    runs_allowed: RBI on scoring plays while pitcher is on mound in inning 1.
    walks: walk + intentional_walk events in inning 1.
    """
    out: Dict[str, Dict[str, float]] = {}
    plays = (feed.get("liveData") or {}).get("plays", {}).get("allPlays") or []
    for play in plays:
        about = play.get("about") or {}
        if about.get("inning") != 1:
            continue
        pitcher = (play.get("matchup") or {}).get("pitcher") or {}
        pid = str(pitcher.get("id") or "").strip()
        if not pid:
            continue
        if pid not in out:
            out[pid] = {"runs_allowed": 0.0, "walks": 0.0}
        result = play.get("result") or {}
        ev = str(result.get("eventType") or "").strip().lower()
        if ev in ("walk", "intent_walk"):
            out[pid]["walks"] += 1.0
        if about.get("isScoringPlay"):
            rbi = result.get("rbi")
            try:
                runs = float(rbi) if rbi is not None and str(rbi).strip() != "" else 1.0
            except (TypeError, ValueError):
                runs = 1.0
            out[pid]["runs_allowed"] += max(0.0, runs)
    return out


def _parse_pitch_level_from_feed(feed: dict) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Per-player balls/strikes/pitches-seen and 95+ mph counts from feed/live playEvents."""
    pitcher: Dict[str, Dict[str, float]] = {}
    hitter: Dict[str, Dict[str, float]] = {}
    plays = (feed.get("liveData") or {}).get("plays", {}).get("allPlays") or []
    for play in plays:
        matchup = play.get("matchup") or {}
        batter_id = str((matchup.get("batter") or {}).get("id") or "").strip()
        pitcher_id = str((matchup.get("pitcher") or {}).get("id") or "").strip()
        for ev in play.get("playEvents") or []:
            if not ev.get("isPitch"):
                continue
            details = ev.get("details") or {}
            is_ball = bool(details.get("isBall"))
            is_strike = bool(details.get("isStrike")) or bool(details.get("isInPlay"))
            speed_raw = (ev.get("pitchData") or {}).get("startSpeed")
            try:
                speed = float(speed_raw) if speed_raw is not None else None
            except (TypeError, ValueError):
                speed = None
            if pitcher_id:
                rec = pitcher.setdefault(
                    pitcher_id,
                    {"balls_thrown": 0.0, "strikes_thrown": 0.0, "pitches_thrown_95": 0.0},
                )
                if is_ball:
                    rec["balls_thrown"] += 1.0
                if is_strike:
                    rec["strikes_thrown"] += 1.0
                if speed is not None and speed >= 95.0:
                    rec["pitches_thrown_95"] += 1.0
            if batter_id:
                rec = hitter.setdefault(
                    batter_id,
                    {"pitches_seen": 0.0, "balls_counted": 0.0, "strikes_counted": 0.0},
                )
                rec["pitches_seen"] += 1.0
                if is_ball:
                    rec["balls_counted"] += 1.0
                if is_strike:
                    rec["strikes_counted"] += 1.0
    return {"pitcher": pitcher, "hitter": hitter}


def fetch_live_feed_stats(game_pk: str) -> dict:
    """Fetch and cache first-inning + pitch-level stats for a gamePk."""
    key = str(game_pk or "").strip()
    if not key:
        return {"first_inning": {}, "pitcher": {}, "hitter": {}}
    if key in _LIVE_FEED_STATS_BY_GAME:
        return _LIVE_FEED_STATS_BY_GAME[key]
    url = LIVE_FEED_URL.format(game_pk=key)
    data = _get(url) or {}
    pitch = _parse_pitch_level_from_feed(data)
    parsed = {
        "first_inning": _parse_first_inning_pitcher_stats(data),
        "pitcher": pitch.get("pitcher") or {},
        "hitter": pitch.get("hitter") or {},
    }
    _LIVE_FEED_STATS_BY_GAME[key] = parsed
    _FIRST_INNING_BY_GAME[key] = parsed["first_inning"]
    time.sleep(0.12)
    return parsed


def fetch_first_inning_pitcher_stats(game_pk: str) -> Dict[str, Dict[str, float]]:
    """Fetch and cache inning-1 pitcher stats for a gamePk."""
    key = str(game_pk or "").strip()
    if not key:
        return {}
    if key in _FIRST_INNING_BY_GAME:
        return _FIRST_INNING_BY_GAME[key]
    return fetch_live_feed_stats(key).get("first_inning") or {}


def _pitch_level_stat(game: dict, role: str, pid: str, key: str) -> float:
    game_pk = str((game.get("game") or {}).get("gamePk", "")).strip()
    if not game_pk or not pid:
        return np.nan
    rec = ((fetch_live_feed_stats(game_pk).get(role) or {}).get(pid) or {})
    if key not in rec:
        return np.nan
    try:
        return float(rec[key])
    except (TypeError, ValueError):
        return np.nan


def _pitcher_id_from_split(split: dict) -> str:
    player = split.get("player") or {}
    return str(player.get("id") or "").strip()


def derive_hitter_stat(game: dict, prop_norm: str) -> float:
    """Extract a stat value from a MLB Stats API game log entry (hitter)."""
    s = game.get("stat") or {}

    def g(key, default=np.nan):
        v = s.get(key)
        try:
            return float(v) if v is not None and str(v).strip() not in ("", "-", ".---") else default
        except (ValueError, TypeError):
            return default

    h  = g("hits",        0)
    h_so = g("strikeOuts", 0)
    hr = g("homeRuns",    0)
    bb = g("baseOnBalls", 0)
    sb = g("stolenBases", 0)
    rbi= g("rbi",         0)
    r  = g("runs",        0)
    ab = g("atBats",      0)
    hbp = g("hitByPitch", 0)
    sf = g("sacFlies", 0)
    sh = g("sacBunts", 0)
    pa = g("plateAppearances", np.nan)
    if pa != pa:  # NaN
        pa = ab + bb + hbp + sf + sh

    # singles = hits - doubles - triples - HR
    d2 = g("doubles",  0)
    t3 = g("triples",  0)
    sg = max(0.0, h - d2 - t3 - hr)

    total_bases = sg * 1 + d2 * 2 + t3 * 3 + hr * 4
    fantasy     = h * 3 + d2 * 2 + t3 * 5 + hr * 7 + rbi * 2 + r * 2 + bb * 2 + sb * 5
    hits_r_rbi  = h + r + rbi

    mapping = {
        "hits":                h,
        "total_bases":         total_bases,
        "home_runs":           hr,
        "rbi":                 rbi,
        "runs":                r,
        "walks":               bb,
        "stolen_bases":        sb,
        "fantasy_score":       fantasy,
        "hits_runs_rbi":       hits_r_rbi,
        "singles":             sg,
        "doubles":             d2,
        "triples":             t3,
        "hitter_strikeouts":   h_so,
        "plate_appearances":   pa,
        "pitches_seen":        g("numberOfPitches", 0),
    }
    if prop_norm in mapping:
        return mapping[prop_norm]
    if prop_norm in ("balls_counted", "strikes_counted"):
        pid = str((game.get("player") or {}).get("id") or "").strip()
        return _pitch_level_stat(game, "hitter", pid, prop_norm)
    return np.nan


def derive_pitcher_stat(game: dict, prop_norm: str) -> float:
    """Extract a stat value from a MLB Stats API game log entry (pitcher)."""
    prop_norm = PROP_ALIASES.get(prop_norm, prop_norm)
    if prop_norm in ("first_inning_runs_allowed", "first_inning_walks_allowed"):
        game_pk = str((game.get("game") or {}).get("gamePk", "")).strip()
        pid = _pitcher_id_from_split(game)
        if not game_pk or not pid:
            return np.nan
        by_pitcher = fetch_first_inning_pitcher_stats(game_pk)
        row = by_pitcher.get(pid) or {}
        if prop_norm == "first_inning_runs_allowed":
            return float(row.get("runs_allowed", np.nan))
        return float(row.get("walks", np.nan))

    s = game.get("stat") or {}

    def g(key, default=np.nan):
        v = s.get(key)
        try:
            return float(v) if v is not None and str(v).strip() not in ("", "-", ".---") else default
        except (ValueError, TypeError):
            return default

    ip_str    = s.get("inningsPitched", "0")
    outs      = _ip_to_outs(ip_str)
    ip_dec    = float(outs) / 3.0 if not np.isnan(outs) else np.nan

    so = g("strikeOuts", 0)

    def _pitch_count() -> float:
        for key in ("pitchesThrown", "numberOfPitches"):
            v = s.get(key)
            try:
                if v is not None and str(v).strip() not in ("", "-", ".---"):
                    return float(v)
            except (TypeError, ValueError):
                continue
        return 0.0

    pitches = _pitch_count()
    strikes = g("strikes", np.nan)
    if strikes != strikes:  # NaN
        strikes = 0.0
    balls_thrown = max(0.0, float(pitches) - float(strikes))
    ha        = g("hits",            0)
    er        = g("earnedRuns",      0)
    bb        = g("baseOnBalls",     0)
    bf        = g("battersFaced",    0)
    wins      = g("wins",            0)
    quality_start = 1.0 if (float(outs) >= 18.0 and float(er) <= 3.0) else 0.0
    pitcher_fantasy = (
        float(outs) * 1.0
        + float(so) * 3.0
        + float(er) * -3.0
        + float(wins) * 6.0
        + float(quality_start) * 4.0
    )

    mapping = {
        "strikeouts":      so,
        "pitching_outs":   outs,
        "innings_pitched": ip_dec,
        "hits_allowed":    ha,
        "earned_runs":     er,
        "walks_allowed":   bb,
        "batters_faced":   bf,
        "pitches_thrown":  pitches,
        "strikes_thrown":  float(strikes),
        "balls_thrown":    balls_thrown,
        "pitcher_fantasy_score": pitcher_fantasy,
    }
    if prop_norm in mapping:
        return mapping[prop_norm]
    if prop_norm == "pitches_thrown_95":
        pid = _pitcher_id_from_split(game)
        return _pitch_level_stat(game, "pitcher", pid, "pitches_thrown_95")
    return np.nan


# ── Cache management ──────────────────────────────────────────────────────────

CACHE_COLS = [
    "MLB_PLAYER_ID", "SEASON", "GAME_DATE", "GAME_ID",
    "PLAYER_TYPE", "PROP_NORM", "STAT_VALUE",
    "TEAM_ID", "OPP_TEAM_ID",
]

def _load_cache_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=CACHE_COLS)
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False).fillna("")
        for c in CACHE_COLS:
            if c not in df.columns:
                df[c] = ""
        print(f"  Loaded cache: {len(df)} rows from {path.name}")
        return df
    except Exception as e:
        print(f"  ⚠️ Could not load cache: {e}")
        return pd.DataFrame(columns=CACHE_COLS)


def _load_cache_db(
    con,
    *,
    player_ids: list[str] | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    q = """
    SELECT mlb_player_id AS MLB_PLAYER_ID,
           season AS SEASON,
           game_date AS GAME_DATE,
           game_id AS GAME_ID,
           COALESCE(player_type,'') AS PLAYER_TYPE,
           prop_norm AS PROP_NORM,
           COALESCE(CAST(stat_value AS TEXT),'') AS STAT_VALUE,
           COALESCE(team_id,'') AS TEAM_ID,
           COALESCE(opp_team_id,'') AS OPP_TEAM_ID
    FROM mlb_gamelog
    """
    clauses: list[str] = []
    params: list[str] = []
    ids = [str(p).strip() for p in (player_ids or []) if str(p).strip()]
    seas = [str(s).strip()[:4] for s in (seasons or []) if str(s).strip()]
    if ids:
        # Chunked IN — sqlite variable limit. Merge frames.
        frames: list[pd.DataFrame] = []
        chunk = 400
        extra = ""
        extra_params: list[str] = []
        if seas:
            extra = " AND season IN (" + ",".join("?" * len(seas)) + ")"
            extra_params = seas
        for i in range(0, len(ids), chunk):
            part = ids[i : i + chunk]
            where = " WHERE mlb_player_id IN (" + ",".join("?" * len(part)) + ")" + extra
            frames.append(pd.read_sql_query(q + where, con, params=part + extra_params, dtype=str).fillna(""))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CACHE_COLS)
    else:
        if seas:
            clauses.append("season IN (" + ",".join("?" * len(seas)) + ")")
            params.extend(seas)
        if clauses:
            q = q + " WHERE " + " AND ".join(clauses)
        df = pd.read_sql_query(q, con, params=params, dtype=str).fillna("")
    print(
        f"  Loaded cache: {len(df)} rows from proporacle_ref.db mlb_gamelog"
        + (f" (players={len(ids)})" if ids else "")
        + (f" seasons={seas}" if seas else "")
    )
    return df


def upsert_cache_to_db(con, cache: pd.DataFrame) -> int:
    if con is None or cache is None or cache.empty:
        return 0
    ts = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for rec in cache.fillna("").to_dict("records"):
        pid = str(rec.get("MLB_PLAYER_ID", "")).strip()
        prop = str(rec.get("PROP_NORM", "")).strip()
        gid = str(rec.get("GAME_ID", "")).strip()
        if not pid or not prop or not gid:
            continue
        stat = pd.to_numeric(rec.get("STAT_VALUE", ""), errors="coerce")
        rows.append(
            {
                "mlb_player_id": pid,
                "season": str(rec.get("SEASON", "")).strip(),
                "game_date": str(rec.get("GAME_DATE", "")).strip()[:10],
                "game_id": gid,
                "player_type": str(rec.get("PLAYER_TYPE", "")).strip() or None,
                "prop_norm": prop,
                "stat_value": None if pd.isna(stat) else float(stat),
                "team_id": str(rec.get("TEAM_ID", "")).strip() or None,
                "opp_team_id": str(rec.get("OPP_TEAM_ID", "")).strip() or None,
                "updated_at": ts,
            }
        )
    n = 0
    chunk = 5000
    for i in range(0, len(rows), chunk):
        n += upsert_rows(con, "mlb_gamelog", rows[i : i + chunk])
    return n


_MLB_CACHE_SOURCE = "csv"


def load_cache(
    path: Path,
    con=None,
    *,
    player_ids: list[str] | None = None,
    seasons: list[str] | None = None,
    min_db_rows: int = 1000,
) -> pd.DataFrame:
    """Prefer SQLite mlb_gamelog; only parse CSV when the DB is empty/thin."""
    global _MLB_CACHE_SOURCE
    _MLB_CACHE_SOURCE = "csv"
    if con is not None:
        ensure_mlb_schema(con)
        total, with_opp = mlb_gamelog_counts(con)
        if total >= min_db_rows:
            _MLB_CACHE_SOURCE = "db"
            return _load_cache_db(con, player_ids=player_ids, seasons=seasons)

    csv_df = _load_cache_csv(path)
    if con is None:
        return csv_df if not csv_df.empty else pd.DataFrame(columns=CACHE_COLS)

    ensure_mlb_schema(con)
    total, with_opp = mlb_gamelog_counts(con)
    csv_has_opp = (
        (not csv_df.empty)
        and "OPP_TEAM_ID" in csv_df.columns
        and (csv_df["OPP_TEAM_ID"].astype(str).str.strip() != "").any()
    )
    if csv_has_opp and (total == 0 or with_opp < max(int(total * 0.5), 1)):
        print(
            f"  Backfilling mlb_gamelog team/opp ids from CSV "
            f"(db_rows={total} with_opp={with_opp})..."
        )
        n = upsert_cache_to_db(con, csv_df)
        print(f"  Upserted {n} CSV rows → mlb_gamelog")
        total, with_opp = mlb_gamelog_counts(con)

    if total >= min_db_rows and (csv_df.empty or total >= int(len(csv_df) * 0.8)):
        db_df = _load_cache_db(con, player_ids=player_ids, seasons=seasons)
        if not db_df.empty:
            _MLB_CACHE_SOURCE = "db"
            return db_df
    if not csv_df.empty:
        if total == 0:
            upsert_cache_to_db(con, csv_df)
        return csv_df
    if total > 0:
        _MLB_CACHE_SOURCE = "db"
        return _load_cache_db(con, player_ids=player_ids, seasons=seasons)
    return pd.DataFrame(columns=CACHE_COLS)


def save_cache(cache: pd.DataFrame, path: Path) -> None:
    if _MLB_CACHE_SOURCE == "db":
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.tmp{path.suffix}")
    cache.to_csv(tmp, index=False, encoding="utf-8-sig", lineterminator="\n")
    tmp.replace(path)


_CACHE_SAVE_PENDING = 0
_CACHE_INDEX: Optional["_MlbCacheIndex"] = None


class _MlbCacheIndex:
    """O(1) lookups over mlb_stats_cache.csv (464k+ rows). Rebuilt per player after a live refresh."""

    __slots__ = ("vals", "opp_vals", "max_date")

    def __init__(self, cache: pd.DataFrame):
        self.vals: Dict[Tuple[str, str, str], List[float]] = {}
        self.opp_vals: Dict[Tuple[str, str, str, str], List[float]] = {}
        self.max_date: Dict[Tuple[str, str], pd.Timestamp] = {}
        self.rebuild(cache)

    def rebuild(self, cache: pd.DataFrame) -> None:
        self.vals.clear()
        self.opp_vals.clear()
        self.max_date.clear()
        if cache is None or cache.empty:
            return
        work = pd.DataFrame(
            {
                "pid": cache["MLB_PLAYER_ID"].astype(str),
                "season": cache["SEASON"].astype(str),
                "prop": cache["PROP_NORM"].astype(str),
                "opp": cache["OPP_TEAM_ID"].astype(str) if "OPP_TEAM_ID" in cache.columns else "",
                "gdate": pd.to_datetime(cache["GAME_DATE"], errors="coerce"),
                "stat": pd.to_numeric(cache["STAT_VALUE"], errors="coerce"),
            }
        )
        work = work[work["stat"].notna()]
        if work.empty:
            return
        work = work.sort_values("gdate", ascending=False)
        for (p, s, pr), grp in work.groupby(["pid", "season", "prop"], sort=False):
            self.vals[(str(p), str(s), str(pr))] = [float(v) for v in grp["stat"].tolist()]
        if "OPP_TEAM_ID" in cache.columns:
            for (p, s, pr, o), grp in work.groupby(["pid", "season", "prop", "opp"], sort=False):
                oid = str(o).strip()
                if oid and oid.lower() != "nan":
                    self.opp_vals[(str(p), str(s), str(pr), oid)] = [
                        float(v) for v in grp["stat"].tolist()
                    ]
        mx = work.groupby(["pid", "season"], sort=False)["gdate"].max()
        for (p, s), ts in mx.items():
            if pd.notna(ts):
                self.max_date[(str(p), str(s))] = pd.Timestamp(ts)

    def refresh_player(self, cache: pd.DataFrame, player_id: str, season: str) -> None:
        pid = str(player_id)
        seas = str(season)
        drop_keys = [k for k in self.vals if k[0] == pid and k[1] == seas]
        for k in drop_keys:
            del self.vals[k]
        drop_opp = [k for k in self.opp_vals if k[0] == pid and k[1] == seas]
        for k in drop_opp:
            del self.opp_vals[k]
        self.max_date.pop((pid, seas), None)
        if cache is None or cache.empty:
            return
        mask = (cache["MLB_PLAYER_ID"].astype(str) == pid) & (cache["SEASON"].astype(str) == seas)
        sub = cache.loc[mask]
        if sub.empty:
            return
        gdate = pd.to_datetime(sub["GAME_DATE"], errors="coerce")
        stat = pd.to_numeric(sub["STAT_VALUE"], errors="coerce")
        prop = sub["PROP_NORM"].astype(str)
        opp = sub["OPP_TEAM_ID"].astype(str) if "OPP_TEAM_ID" in sub.columns else pd.Series("", index=sub.index)
        work = pd.DataFrame({"prop": prop, "opp": opp, "gdate": gdate, "stat": stat})
        work = work[work["stat"].notna()].sort_values("gdate", ascending=False)
        if work.empty:
            return
        for pr, grp in work.groupby("prop", sort=False):
            self.vals[(pid, seas, str(pr))] = [float(v) for v in grp["stat"].tolist()]
        for (pr, o), grp in work.groupby(["prop", "opp"], sort=False):
            oid = str(o).strip()
            if oid and oid.lower() != "nan":
                self.opp_vals[(pid, seas, str(pr), oid)] = [float(v) for v in grp["stat"].tolist()]
        mx = work["gdate"].max()
        if pd.notna(mx):
            self.max_date[(pid, seas)] = pd.Timestamp(mx)


def _maybe_save_cache(cache: pd.DataFrame, path: Path, *, force: bool = False) -> None:
    """CSV is a backup dump. Durable writes go to SQLite; only flush CSV at end."""
    global _CACHE_SAVE_PENDING
    if not force:
        _CACHE_SAVE_PENDING += 1
        return
    save_cache(cache, path)
    _CACHE_SAVE_PENDING = 0


def fetch_game_log(player_id: str, group: str, season: str) -> List[dict]:
    """Fetch raw game log entries from MLB Stats API."""
    url  = GAMELOG_URL.format(player_id=player_id, group=group, season=season)
    data = _get(url)
    if not data:
        return []
    for stat_block in (data.get("stats") or []):
        splits = stat_block.get("splits") or []
        if splits:
            return splits
    return []


@lru_cache(maxsize=1)
def _mlb_team_lookup() -> Dict[str, str]:
    """
    Return MLB team code/name aliases -> team_id as strings.
    Uses live statsapi lookup once per run.
    """
    out: Dict[str, str] = {}
    try:
        data = _get("https://statsapi.mlb.com/api/v1/teams?sportId=1")
        teams = (data or {}).get("teams") or []
        for t in teams:
            tid = str(t.get("id", "")).strip()
            if not tid:
                continue
            aliases = {
                str(t.get("abbreviation", "")).strip().upper(),
                str(t.get("teamName", "")).strip().upper(),
                str(t.get("name", "")).strip().upper(),
                str(t.get("clubName", "")).strip().upper(),
                str(t.get("locationName", "")).strip().upper(),
            }
            for a in aliases:
                if a:
                    out[a] = tid
    except Exception:
        return {}
    return out


def _resolve_team_id(team_value: str) -> str:
    key = str(team_value or "").strip().upper()
    if not key:
        return ""
    return _mlb_team_lookup().get(key, "")


def _infer_opp_team_for_row(slate: pd.DataFrame, idx: int) -> str:
    """
    Infer opp team code for rows where opp_team is missing using pp_game_id.
    """
    try:
        row = slate.loc[idx]
    except Exception:
        return ""
    opp = str(row.get("opp_team", "")).strip().upper()
    if opp:
        return opp
    gid = str(row.get("pp_game_id", "")).strip()
    team = str(row.get("team", "")).strip().upper()
    if not gid or not team:
        return ""
    sub = slate.loc[slate.get("pp_game_id", pd.Series(dtype=str)).astype(str).str.strip().eq(gid), "team"].astype(str).str.strip().str.upper()
    teams = sorted({t for t in sub.tolist() if t and t != "NAN"})
    if len(teams) == 2 and team in teams:
        return teams[0] if teams[1] == team else teams[1]
    return ""


def update_cache(
    cache: pd.DataFrame,
    player_id: str,
    player_type: str,
    season: str,
    n_games: int,
) -> Tuple[pd.DataFrame, int]:
    """Fetch game log and add new rows to cache."""
    group = "pitching" if player_type == "pitcher" else "hitting"

    existing_game_ids = set(
        cache.loc[
            (cache["MLB_PLAYER_ID"].astype(str) == str(player_id)) &
            (cache["SEASON"].astype(str)         == str(season)),
            "GAME_ID",
        ].astype(str).tolist()
    )

    splits  = fetch_game_log(player_id, group, season)
    if player_type == "pitcher":
        key = (str(player_id), str(season))
        _wins_available = any("wins" in (sp.get("stat") or {}) for sp in splits)
        _PITCHER_WIN_FIELD_AVAILABLE[key] = bool(_wins_available)
        if not _wins_available and key not in _WARNED_PITCHER_WIN_FALLBACK:
            print(f"  ⚠ Pitcher FS fallback (wins unavailable -> win=0): player_id={player_id} season={season}")
            _WARNED_PITCHER_WIN_FALLBACK.add(key)
    # Most-recent first
    splits  = list(reversed(splits))
    added   = 0
    new_rows = []

    prop_list = (
        ["strikeouts", "pitching_outs", "innings_pitched",
         "hits_allowed", "earned_runs", "walks_allowed", "batters_faced", "pitches_thrown",
         "strikes_thrown", "balls_thrown", "pitches_thrown_95",
         "pitcher_fantasy_score", "first_inning_runs_allowed", "first_inning_walks_allowed"]
        if player_type == "pitcher" else
        ["hits", "total_bases", "home_runs", "rbi", "runs", "walks",
         "stolen_bases", "fantasy_score", "hits_runs_rbi", "singles", "doubles", "triples",
         "hitter_strikeouts", "plate_appearances",
         "pitches_seen", "balls_counted", "strikes_counted"]
    )
    derive_fn = derive_pitcher_stat if player_type == "pitcher" else derive_hitter_stat

    cached_props_by_game: Dict[str, set[str]] = {}
    if len(cache) > 0:
        sub = cache[
            (cache["MLB_PLAYER_ID"].astype(str) == str(player_id))
            & (cache["SEASON"].astype(str) == str(season))
        ]
        for gid, grp in sub.groupby(sub["GAME_ID"].astype(str)):
            cached_props_by_game[str(gid)] = set(grp["PROP_NORM"].astype(str).tolist())

    for split in splits:
        game_id  = str(split.get("game", {}).get("gamePk", "")).strip()
        date_str = str(split.get("date", "")).strip()
        if not game_id:
            continue
        cached_props = cached_props_by_game.get(game_id, set())
        props_to_write = [p for p in prop_list if p not in cached_props]
        if not props_to_write:
            continue

        for prop_norm in props_to_write:
            val = derive_fn(split, prop_norm)
            # ── Bouncer: reject impossible/junk values ───────────────────────
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                try:
                    v = float(val)
                except Exception:
                    continue
                if v < 0:
                    continue
                # generous caps
                if prop_norm in ("hits", "total_bases", "hits_runs_rbi") and v > 25:
                    continue
                if prop_norm in ("home_runs", "rbi", "runs", "walks", "stolen_bases") and v > 10:
                    continue
                if prop_norm == "hitter_strikeouts" and v > 10:
                    continue
                if prop_norm in ("strikeouts", "pitching_outs", "batters_faced") and v > 100:
                    continue
                if prop_norm == "pitches_thrown" and v > 200:
                    continue
                if prop_norm in ("innings_pitched",) and v > 15:
                    continue
                if prop_norm in ("earned_runs", "hits_allowed", "walks_allowed") and v > 30:
                    continue
                if prop_norm == "pitcher_fantasy_score" and v > 120:
                    continue
                if prop_norm == "first_inning_runs_allowed" and v > 10:
                    continue
                if prop_norm == "first_inning_walks_allowed" and v > 5:
                    continue
                if prop_norm in ("pitches_seen", "balls_counted", "strikes_counted") and v > 80:
                    continue
                if prop_norm in ("balls_thrown", "strikes_thrown") and v > 200:
                    continue
                if prop_norm == "pitches_thrown_95" and v > 150:
                    continue

            if prop_norm in PBP_PROPS and (val is None or (isinstance(val, float) and np.isnan(val))):
                continue

            new_rows.append({
                "MLB_PLAYER_ID": str(player_id),
                "SEASON":        str(season),
                "GAME_DATE":     date_str,
                "GAME_ID":       game_id,
                "PLAYER_TYPE":   player_type,
                "PROP_NORM":     prop_norm,
                "STAT_VALUE":    fmt_num(val) if not np.isnan(val) else "",
                "TEAM_ID":       str((split.get("team") or {}).get("id", "")).strip(),
                "OPP_TEAM_ID":   str((split.get("opponent") or {}).get("id", "")).strip(),
            })

        if game_id not in existing_game_ids:
            existing_game_ids.add(game_id)
            added += 1
            if added >= n_games:
                break

    if new_rows:
        cache = pd.concat([cache, pd.DataFrame(new_rows)], ignore_index=True)
        if _CACHE_INDEX is not None:
            _CACHE_INDEX.refresh_player(cache, player_id, season)

    return cache, added


def player_cache_max_date(
    cache: pd.DataFrame,
    player_id: str,
    season: str,
) -> Optional[pd.Timestamp]:
    """Newest GAME_DATE in cache for this player+season (or None)."""
    if _CACHE_INDEX is not None:
        return _CACHE_INDEX.max_date.get((str(player_id), str(season)))
    if cache is None or cache.empty:
        return None
    mask = (
        (cache["MLB_PLAYER_ID"].astype(str) == str(player_id))
        & (cache["SEASON"].astype(str) == str(season))
    )
    if not bool(mask.any()):
        return None
    dt = pd.to_datetime(cache.loc[mask, "GAME_DATE"], errors="coerce").max()
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt)


def player_cache_is_stale(
    cache: pd.DataFrame,
    player_id: str,
    season: str,
    *,
    stale_before: Optional[pd.Timestamp] = None,
) -> bool:
    """
    True when cache has no rows or newest game is older than stale_before.

    Default stale_before = yesterday (UTC date) so daily runs pull the prior
    night's box scores instead of freezing on an old 10-game window.
    """
    max_dt = player_cache_max_date(cache, player_id, season)
    if max_dt is None:
        return True
    if stale_before is None:
        stale_before = pd.Timestamp(datetime.utcnow().date()) - pd.Timedelta(days=1)
    return pd.Timestamp(max_dt).normalize() < pd.Timestamp(stale_before).normalize()


def ks_tb_arm_ids(row: pd.Series, ids: List[str]) -> Tuple[str, str]:
    """Pitcher id, hitter id for strikeouts_total_bases (same id when two-way)."""
    if not ids:
        return "", ""
    if len(ids) == 1:
        return ids[0], ids[0]
    try:
        from step2_attach_picktypes_mlb import order_ks_tb_ids
    except Exception:
        from Sports.MLB.scripts.step2_attach_picktypes_mlb import order_ks_tb_ids  # type: ignore
    return order_ks_tb_ids(ids[0], ids[1], str(row.get("pos", "") or ""))


def strikeouts_plus_total_bases(pitch_split: Optional[dict], hit_split: Optional[dict]) -> float:
    """Same-game pitcher Ks + hitter TB. Missing hitting log counts as 0 TB."""
    if not pitch_split:
        return np.nan
    ks = derive_pitcher_stat(pitch_split, "strikeouts")
    if ks is None or (isinstance(ks, float) and np.isnan(ks)):
        return np.nan
    tb = 0.0
    if hit_split:
        raw = derive_hitter_stat(hit_split, "total_bases")
        if raw is not None and not (isinstance(raw, float) and np.isnan(raw)):
            tb = float(raw)
    return float(ks) + float(tb)


def get_dated_vals_from_cache(
    cache: pd.DataFrame,
    player_id: str,
    prop_norm: str,
    season: str,
) -> List[Tuple[str, str, float]]:
    """(game_id, YYYY-MM-DD, value) newest first."""
    if cache is None or cache.empty:
        return []
    mask = (
        (cache["MLB_PLAYER_ID"].astype(str) == str(player_id))
        & (cache["SEASON"].astype(str) == str(season))
        & (cache["PROP_NORM"].astype(str) == str(prop_norm))
        & (cache["STAT_VALUE"].astype(str).str.strip() != "")
    )
    sub = cache.loc[mask].copy()
    if sub.empty:
        return []
    sub["GAME_DATE"] = pd.to_datetime(sub["GAME_DATE"], errors="coerce")
    sub = sub[sub["GAME_DATE"].notna()].sort_values("GAME_DATE", ascending=False)
    out: List[Tuple[str, str, float]] = []
    for _, r in sub.iterrows():
        try:
            val = float(r["STAT_VALUE"])
        except (TypeError, ValueError):
            continue
        if val != val:
            continue
        gid = str(r.get("GAME_ID", "") or "").strip()
        d = pd.Timestamp(r["GAME_DATE"]).strftime("%Y-%m-%d")
        out.append((gid, d, val))
    return out


def compose_strikeouts_total_bases(
    cache: pd.DataFrame,
    pitcher_id: str,
    hitter_id: str,
    season: str,
    n: int = 10,
) -> List[float]:
    """L5/L10 values for Pitcher Strikeouts + Total Bases."""
    pitcher_id = str(pitcher_id or "").strip()
    hitter_id = str(hitter_id or "").strip()
    if not pitcher_id or not hitter_id:
        return []
    if pitcher_id == hitter_id:
        so = get_dated_vals_from_cache(cache, pitcher_id, "strikeouts", season)
        tb_rows = get_dated_vals_from_cache(cache, hitter_id, "total_bases", season)
        tb_by_gid = {gid: v for gid, _d, v in tb_rows if gid}
        tb_by_date: Dict[str, float] = {}
        for _gid, d, v in tb_rows:
            tb_by_date.setdefault(d, v)
        vals: List[float] = []
        for gid, d, ks in so:
            tb = tb_by_gid.get(gid)
            if tb is None:
                tb = tb_by_date.get(d, 0.0)
            vals.append(float(ks) + float(tb))
            if len(vals) >= n:
                break
        return vals
    so_vals = get_vals_from_cache(cache, pitcher_id, "strikeouts", season, n=n)
    tb_vals = get_vals_from_cache(cache, hitter_id, "total_bases", season, n=n)
    min_g = min(len(so_vals), len(tb_vals))
    return [float(so_vals[i]) + float(tb_vals[i]) for i in range(min_g)]


def get_vals_from_cache(
    cache: pd.DataFrame,
    player_id: str,
    prop_norm: str,
    season: str,
    n: int = 10,
) -> List[float]:
    """Return most-recent N stat values from cache for player+prop+season."""
    if _CACHE_INDEX is not None:
        vals = _CACHE_INDEX.vals.get((str(player_id), str(season), str(prop_norm)), [])
        return vals[:n]
    mask = (
        (cache["MLB_PLAYER_ID"].astype(str) == str(player_id)) &
        (cache["SEASON"].astype(str)         == str(season))    &
        (cache["PROP_NORM"].astype(str)       == str(prop_norm)) &
        (cache["STAT_VALUE"].astype(str).str.strip() != "")
    )
    sub = cache.loc[mask].copy()
    if sub.empty:
        return []

    sub["GAME_DATE"] = pd.to_datetime(sub["GAME_DATE"], errors="coerce")
    sub = sub.sort_values("GAME_DATE", ascending=False)
    vals = pd.to_numeric(sub["STAT_VALUE"], errors="coerce").dropna().tolist()
    return vals[:n]


def get_vals_vs_opp_from_cache(
    cache: pd.DataFrame,
    player_id: str,
    prop_norm: str,
    season: str,
    opp_team_id: str,
    n: int = 5,
) -> List[float]:
    if not opp_team_id:
        return []
    if _CACHE_INDEX is not None:
        vals = _CACHE_INDEX.opp_vals.get(
            (str(player_id), str(season), str(prop_norm), str(opp_team_id)), []
        )
        return vals[:n]
    mask = (
        (cache["MLB_PLAYER_ID"].astype(str) == str(player_id)) &
        (cache["SEASON"].astype(str) == str(season)) &
        (cache["PROP_NORM"].astype(str) == str(prop_norm)) &
        (cache["OPP_TEAM_ID"].astype(str) == str(opp_team_id)) &
        (cache["STAT_VALUE"].astype(str).str.strip() != "")
    )
    sub = cache.loc[mask].copy()
    if sub.empty:
        return []
    sub["GAME_DATE"] = pd.to_datetime(sub["GAME_DATE"], errors="coerce")
    sub = sub.sort_values("GAME_DATE", ascending=False)
    vals = pd.to_numeric(sub["STAT_VALUE"], errors="coerce").dropna().tolist()
    return vals[:n]


def calc_hit_context(vals: List[float], line: float, k: int = 5):
    recent = vals[:k] if len(vals) >= k else vals
    if not recent:
        return 0, 0, 0, np.nan, np.nan, np.nan
    over  = sum(1 for v in recent if v >  line)
    under = sum(1 for v in recent if v <  line)
    push  = sum(1 for v in recent if v == line)
    played = len(recent)
    hr_all = over / played if played else np.nan
    denom  = over + under
    hr_ou  = over  / denom if denom else np.nan
    ur_ou  = under / denom if denom else np.nan
    return over, under, push, hr_all, hr_ou, ur_ou


NO_CACHE_POST_REFRESH_CAP = 50
NO_CACHE_REFRESH_SLEEP_S = 0.3


def _row_stat_refresh_keys(row: pd.Series) -> set[tuple[str, str]]:
    """(mlb_player_id, player_type) pairs used for cache refresh for this slate row."""
    mlb_id_raw = str(row.get("mlb_player_id", "")).strip()
    ids = _parse_ids(mlb_id_raw)
    if not ids:
        return set()
    prop = str(row.get("prop_norm", "")).lower().strip()
    ptype = str(row.get("player_type", "")).lower().strip()
    if ptype not in ("pitcher", "hitter"):
        from step2_attach_picktypes_mlb import PITCHER_PROPS

        ptype = "pitcher" if prop in PITCHER_PROPS else "hitter"
    is_combo = (len(ids) > 1) or (
        str(row.get("is_combo_player", "")).strip().lower() in ("1", "true", "yes")
    )
    if prop == "strikeouts_total_bases":
        pid_p, pid_h = ks_tb_arm_ids(row, ids)
        out: set[tuple[str, str]] = set()
        if pid_p:
            out.add((pid_p, "pitcher"))
        if pid_h:
            out.add((pid_h, "hitter"))
        return out
    if not is_combo:
        return {(ids[0], ptype)}
    return {(str(pid), ptype) for pid in ids}


def _db_mirror_player_cache_rows(
    cache: pd.DataFrame,
    con,
    pid: str,
    season: str,
) -> None:
    from datetime import datetime, timezone

    try:
        fresh = cache.loc[
            (cache["MLB_PLAYER_ID"].astype(str) == str(pid))
            & (cache["SEASON"].astype(str) == str(season))
        ].copy()
        if fresh.empty:
            return
        fresh["STAT_VALUE_NUM"] = pd.to_numeric(fresh["STAT_VALUE"], errors="coerce")
        ts = datetime.now(timezone.utc).isoformat()
        rows_db = []
        for _, r in fresh.iterrows():
            rows_db.append(
                {
                    "mlb_player_id": str(r.get("MLB_PLAYER_ID", "")).strip(),
                    "season": str(r.get("SEASON", "")).strip(),
                    "game_date": str(r.get("GAME_DATE", "")).strip()[:10],
                    "game_id": str(r.get("GAME_ID", "")).strip(),
                    "player_type": str(r.get("PLAYER_TYPE", "")).strip() or None,
                    "prop_norm": str(r.get("PROP_NORM", "")).strip(),
                    "stat_value": float(r["STAT_VALUE_NUM"])
                    if not pd.isna(r.get("STAT_VALUE_NUM"))
                    else None,
                    "team_id": str(r.get("TEAM_ID", "")).strip() or None,
                    "opp_team_id": str(r.get("OPP_TEAM_ID", "")).strip() or None,
                    "updated_at": ts,
                }
            )
        upsert_rows(con, "mlb_gamelog", rows_db)
    except Exception as e:
        log_pipeline_health(
            "mlb.step4_attach_player_stats",
            "db_mirror_failed",
            extra={"mlb_player_id": pid, "error": f"{type(e).__name__}: {e}"},
            start=Path(__file__),
        )


def _process_slate_row_for_stats(
    idx: int,
    slate: pd.DataFrame,
    cache: pd.DataFrame,
    cache_path: Path,
    season: str,
    n_games: int,
    con,
    attempted_refresh: dict[tuple[str, str], int],
    max_refresh_attempts: int,
    misses: list,
    *,
    allow_live_refresh: bool,
) -> tuple[pd.DataFrame, int]:
    """Fill stat columns for one slate row. Returns (cache, cache_row_updates)."""
    row = slate.loc[idx]
    prop = str(row.get("prop_norm", "")).lower().strip()
    prop_for_stats = PROP_ALIASES.get(prop, prop)
    player = str(row.get("player", "")).strip()
    team = str(row.get("team", "")).strip()
    ptype = str(row.get("player_type", "")).lower().strip()
    mlb_id_raw = str(row.get("mlb_player_id", "")).strip()
    line = row.get("_line_num", np.nan)
    try:
        line = float(line)
    except Exception:
        line = np.nan

    ids = _parse_ids(mlb_id_raw)
    is_combo = (len(ids) > 1) or (
        str(row.get("is_combo_player", "")).strip().lower() in ("1", "true", "yes")
    )

    if prop in UNSUPPORTED_PROPS:
        if prop not in _WARNED_UNSUPPORTED_PROPS:
            print(f"  ⚠ Unsupported MLB prop in step4 stats attachment: {prop}")
            _WARNED_UNSUPPORTED_PROPS.add(prop)
        slate.at[idx, "stat_status"] = "UNSUPPORTED_PROP"
        slate.at[idx, "stat_coverage"] = "unsupported"
        return cache, 0

    slate.at[idx, "stat_coverage"] = "aliased" if prop_for_stats != prop else "supported"

    if not ids:
        slate.at[idx, "stat_status"] = "NO_MLB_PLAYER_ID"
        misses.append(
            {
                "player": player,
                "team": team,
                "prop_norm": prop,
                "line": str(row.get("line", "")),
                "mlb_player_id": mlb_id_raw,
            }
        )
        return cache, 0

    if ptype not in ("pitcher", "hitter"):
        from step2_attach_picktypes_mlb import PITCHER_PROPS

        ptype = "pitcher" if prop in PITCHER_PROPS else "hitter"

    cache_updates = 0
    same_opp_vals: List[float] = []

    if prop == "strikeouts_total_bases":
        pitcher_id, hitter_id = ks_tb_arm_ids(row, ids)
        if not pitcher_id or not hitter_id:
            slate.at[idx, "stat_status"] = "NO_MLB_PLAYER_ID"
            return cache, 0
        for pid_arm, ptype_arm in ((pitcher_id, "pitcher"), (hitter_id, "hitter")):
            if not allow_live_refresh:
                continue
            key = (pid_arm, ptype_arm)
            attempts = attempted_refresh.get(key, 0)
            arm_prop = "strikeouts" if ptype_arm == "pitcher" else "total_bases"
            arm_vals = get_vals_from_cache(cache, pid_arm, arm_prop, season, n=n_games)
            needs_refresh = (len(arm_vals) < 3) or player_cache_is_stale(cache, pid_arm, season)
            if needs_refresh and attempts < max_refresh_attempts:
                attempted_refresh[key] = attempts + 1
                cache, added = update_cache(cache, pid_arm, ptype_arm, season, n_games=n_games)
                if added > 0:
                    cache_updates += added
                    _maybe_save_cache(cache, cache_path)
                    _db_mirror_player_cache_rows(cache, con, pid_arm, season)
        vals = compose_strikeouts_total_bases(
            cache, pitcher_id, hitter_id, season, n=n_games
        )
        if not vals:
            slate.at[idx, "stat_status"] = "NO_CACHE_DATA"
            return cache, cache_updates
        same_opp_vals = []
    elif not is_combo:
        pid = ids[0]
        cached_vals = get_vals_from_cache(cache, pid, prop_for_stats, season, n=n_games)
        if allow_live_refresh:
            key = (pid, ptype)
            attempts = attempted_refresh.get(key, 0)
            # Refresh when thin OR when newest cached game is older than yesterday.
            # Old logic only refreshed len<3, so hot players froze on July logs.
            needs_refresh = (len(cached_vals) < 3) or player_cache_is_stale(
                cache, pid, season
            )
            if needs_refresh and attempts < max_refresh_attempts:
                attempted_refresh[key] = attempts + 1
                cache, added = update_cache(cache, pid, ptype, season, n_games=n_games)
                if added > 0:
                    cache_updates += added
                    _maybe_save_cache(cache, cache_path)
                    _db_mirror_player_cache_rows(cache, con, pid, season)
                cached_vals = get_vals_from_cache(cache, pid, prop_for_stats, season, n=n_games)
        else:
            cached_vals = get_vals_from_cache(cache, pid, prop_for_stats, season, n=n_games)

        if not cached_vals:
            slate.at[idx, "stat_status"] = "NO_CACHE_DATA"
            return cache, cache_updates
        vals = cached_vals
        if prop_for_stats == "pitcher_fantasy_score":
            avail = _PITCHER_WIN_FIELD_AVAILABLE.get((str(pid), str(season)))
            if avail is False:
                slate.at[idx, "stat_coverage"] = "partial"
        opp_team_code = _infer_opp_team_for_row(slate, idx)
        opp_team_id = _resolve_team_id(opp_team_code)
        same_opp_vals = get_vals_vs_opp_from_cache(cache, pid, prop_for_stats, season, opp_team_id, n=5)

    else:
        per_player_vals = []
        any_empty = False
        for i, pid in enumerate(ids):
            sub_ptype = ptype
            cv = get_vals_from_cache(cache, pid, prop_for_stats, season, n=n_games)
            if allow_live_refresh:
                key = (pid, sub_ptype)
                attempts = attempted_refresh.get(key, 0)
                needs_refresh = (len(cv) < 3) or player_cache_is_stale(cache, pid, season)
                if needs_refresh and attempts < max_refresh_attempts:
                    attempted_refresh[key] = attempts + 1
                    cache, added = update_cache(cache, pid, sub_ptype, season, n_games=n_games)
                    if added > 0:
                        cache_updates += added
                        _maybe_save_cache(cache, cache_path)
                    cv = get_vals_from_cache(cache, pid, prop_for_stats, season, n=n_games)
            else:
                cv = get_vals_from_cache(cache, pid, prop_for_stats, season, n=n_games)
            if not cv:
                any_empty = True
                break
            per_player_vals.append(cv)

        if any_empty or not per_player_vals:
            slate.at[idx, "stat_status"] = "NO_CACHE_DATA"
            return cache, cache_updates

        min_g = min(len(pv) for pv in per_player_vals)
        vals = [float(sum(pv[i] for pv in per_player_vals)) for i in range(min_g)]

        if not vals:
            slate.at[idx, "stat_status"] = "INSUFFICIENT_GAMES"
            return cache, cache_updates
        same_opp_vals = []

    n = n_games
    for i in range(1, n + 1):
        v = vals[i - 1] if (i - 1) < len(vals) else np.nan
        slate.at[idx, f"stat_g{i}"] = fmt_num(v)

    def avg_k(k: int) -> float:
        s = vals[:k] if len(vals) >= k else vals
        return float(np.mean(s)) if s else np.nan

    slate.at[idx, "stat_last5_avg"] = fmt_num(avg_k(5))
    slate.at[idx, "stat_last10_avg"] = fmt_num(avg_k(10))
    slate.at[idx, "stat_season_avg"] = fmt_num(float(np.mean(vals)) if vals else np.nan)

    if not np.isnan(line):
        o5, u5, p5, hr5, hr5_ou, ur5_ou = calc_hit_context(vals, line, k=5)
        slate.at[idx, "last5_over"] = str(o5)
        slate.at[idx, "last5_under"] = str(u5)
        slate.at[idx, "last5_push"] = str(p5)
        slate.at[idx, "last5_hit_rate"] = fmt_num(hr5)
        slate.at[idx, "line_hit_rate_over_ou_5"] = fmt_num(hr5_ou)
        slate.at[idx, "line_hit_rate_under_ou_5"] = fmt_num(ur5_ou)

        _, _, _, _, hr10_ou, ur10_ou = calc_hit_context(vals, line, k=10)
        slate.at[idx, "line_hit_rate_over_ou_10"] = fmt_num(hr10_ou)
        slate.at[idx, "line_hit_rate_under_ou_10"] = fmt_num(ur10_ou)
        if same_opp_vals:
            _, _, _, _, same_opp_over_ou, _ = calc_hit_context(same_opp_vals, line, k=5)
            slate.at[idx, "same_opp_games_l5"] = str(int(len(same_opp_vals)))
            slate.at[idx, "same_opp_over_rate_l5"] = fmt_num(same_opp_over_ou)

    slate.at[idx, "stat_status"] = "OK"
    return cache, cache_updates


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",        default="step3_mlb_with_defense.csv")
    ap.add_argument("--cache",        default="mlb_stats_cache.csv")
    ap.add_argument("--output",       default="step4_mlb_with_stats.csv")
    ap.add_argument("--db",           default="", help="Override DB path (default: data/cache/proporacle_ref.db)")
    ap.add_argument("--n",            type=int,   default=10, help="Games per player")
    ap.add_argument("--season",       default="2026")
    ap.add_argument("--debug_misses", default="")
    args = ap.parse_args()

    print(f"→ Loading Step3: {args.input}")
    slate = pd.read_csv(args.input, low_memory=False, encoding="utf-8-sig").fillna("")

    # Central DB mirror (MLB game logs)
    db_path = Path(args.db) if args.db else None
    con = open_db(db_path)
    ensure_mlb_schema(con)

    global _CACHE_INDEX
    cache_path = Path(args.cache)
    seasons = [str(args.season).strip()[:4]]
    try:
        seasons.append(str(int(seasons[0]) - 1))
    except ValueError:
        pass
    pids: list[str] = []
    if "mlb_player_id" in slate.columns:
        for raw in slate["mlb_player_id"].astype(str):
            pids.extend(_parse_ids(raw))
    pids = sorted(set(pids))
    cache      = load_cache(cache_path, con, player_ids=pids or None, seasons=seasons)
    t_idx = time.perf_counter()
    _CACHE_INDEX = _MlbCacheIndex(cache)
    print(
        f"  Cache index: {len(_CACHE_INDEX.vals)} prop-keys, "
        f"{len(_CACHE_INDEX.max_date)} player-seasons "
        f"({time.perf_counter() - t_idx:.1f}s)"
    )

    N         = int(args.n)
    stat_cols = [f"stat_g{i}" for i in range(1, N + 1)]
    out_cols  = stat_cols + [
        "stat_last5_avg", "stat_last10_avg", "stat_season_avg",
        "last5_over", "last5_under", "last5_push", "last5_hit_rate",
        "line_hit_rate_over_ou_5", "line_hit_rate_under_ou_5",
        "line_hit_rate_over_ou_10", "line_hit_rate_under_ou_10",
        "same_opp_games_l5", "same_opp_over_rate_l5",
        "stat_status", "stat_coverage",
    ]
    for c in out_cols:
        if c not in slate.columns:
            slate[c] = ""

    slate["_line_num"] = pd.to_numeric(slate.get("line", ""), errors="coerce")

    misses: list = []
    cache_updates = 0
    # Allow up to 2 refresh attempts per (player_id, player_type) in a single run.
    attempted_refresh: dict[tuple[str, str], int] = {}
    max_refresh_attempts = 2

    print(f"\n→ Attaching stats | rows={len(slate)}")

    for idx, _row in slate.iterrows():
        cache, du = _process_slate_row_for_stats(
            idx,
            slate,
            cache,
            cache_path,
            args.season,
            N,
            con,
            attempted_refresh,
            max_refresh_attempts,
            misses,
            allow_live_refresh=True,
        )
        cache_updates += du

    no_cache_idx = [
        i
        for i in slate.index
        if str(slate.at[i, "stat_status"]) == "NO_CACHE_DATA"
        and str(slate.at[i, "mlb_player_id"]).strip() not in ("", "nan", "NaN")
    ]
    keys_to_refresh: list[tuple[str, str]] = []
    seen_refresh: set[tuple[str, str]] = set()
    for idx in no_cache_idx:
        for key in _row_stat_refresh_keys(slate.loc[idx]):
            if key in seen_refresh:
                continue
            seen_refresh.add(key)
            keys_to_refresh.append(key)
            if len(keys_to_refresh) >= NO_CACHE_POST_REFRESH_CAP:
                break
        if len(keys_to_refresh) >= NO_CACHE_POST_REFRESH_CAP:
            break

    refreshed_keys = set(keys_to_refresh)
    for pid, ptype in keys_to_refresh:
        time.sleep(NO_CACHE_REFRESH_SLEEP_S)
        cache, added = update_cache(cache, pid, ptype, args.season, n_games=N)
        if added > 0:
            cache_updates += added
            _maybe_save_cache(cache, cache_path)
            _db_mirror_player_cache_rows(cache, con, pid, args.season)

    for idx in no_cache_idx:
        cache, du = _process_slate_row_for_stats(
            idx,
            slate,
            cache,
            cache_path,
            args.season,
            N,
            con,
            attempted_refresh,
            max_refresh_attempts,
            misses,
            allow_live_refresh=False,
        )
        cache_updates += du

    for idx in no_cache_idx:
        if str(slate.at[idx, "stat_status"]) != "NO_CACHE_DATA":
            continue
        row = slate.loc[idx]
        if not (_row_stat_refresh_keys(row) & refreshed_keys):
            continue
        prop = str(row.get("prop_norm", "")).lower().strip()
        player = str(row.get("player", "")).strip()
        mlb_id_raw = str(row.get("mlb_player_id", "")).strip()
        print(f"[MLB step4] cache miss after refresh: {player} | {prop} | id={mlb_id_raw}")

    if args.debug_misses and misses:
        pd.DataFrame(misses).drop_duplicates().to_csv(
            args.debug_misses, index=False, encoding="utf-8-sig"
        )
        print(f"Wrote misses → {args.debug_misses}")

    slate.drop(columns=["_line_num"], errors="ignore", inplace=True)
    _maybe_save_cache(cache, cache_path, force=True)

    from role_stability import role_stability

    def _usage_l10(row: pd.Series) -> list:
        vals: list = []
        for i in range(1, N + 1):
            v = pd.to_numeric(row.get(f"stat_g{i}"), errors="coerce")
            if pd.notna(v) and float(v) >= 0:
                vals.append(float(v))
        return vals

    slate["minutes_L10_list"] = slate.apply(_usage_l10, axis=1)
    slate["role_stability_score"] = slate["minutes_L10_list"].apply(role_stability)
    slate["high_variance_role"] = pd.to_numeric(slate["role_stability_score"], errors="coerce").lt(0.35)

    try:
        season_year = int(str(args.season).strip()[:4])
    except (TypeError, ValueError):
        season_year = datetime.now().year
    slate = attach_mlb_b2b_columns(slate, season=season_year, sport_label="MLB")

    slate.to_csv(args.output, index=False, encoding="utf-8-sig")
    copy_pipeline_output_to_dated_dirs(
        output_path=args.output,
        df=slate,
        sport_dir_name="MLB",
        repo_root=_PROPORACLE_ROOT,
    )

    print(f"\n✅ Saved → {args.output}")
    print(f"Cache updates: {cache_updates}")
    print("\nstat_status breakdown:")
    print(slate["stat_status"].astype(str).value_counts().to_string())
    print("\nstat_coverage breakdown:")
    print(slate["stat_coverage"].astype(str).value_counts().to_string())
    _vc = slate["stat_status"].astype(str).value_counts()
    _ok = int(_vc.get("OK", 0))
    _nc = int(_vc.get("NO_CACHE_DATA", 0))
    _nid = int(_vc.get("NO_MLB_PLAYER_ID", 0))
    _uns = int(_vc.get("UNSUPPORTED_PROP", 0))
    print(
        f"[MLB step4] stat_attach: OK={_ok} | NO_CACHE_DATA={_nc} | NO_MLB_PLAYER_ID={_nid} | UNSUPPORTED_PROP={_uns} | total={len(slate)}"
    )
    con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_pipeline_health(
            "mlb.step4_attach_player_stats",
            "run_failed",
            extra={"error": f"{type(e).__name__}: {e}"},
            start=Path(__file__),
        )
        print(f"❌ MLB step4 failed (logged). {type(e).__name__}: {e}")
        sys.exit(1)
