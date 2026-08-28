#!/usr/bin/env python3
"""
cfb_step5b_attach_boxscore_stats.py  (upgraded)
------------------------------------------------
Mirrors NBA step4 logic exactly.

Improvements over original:
- stat_season_avg added (all games in window)
- stat_last10_avg already present, now also stat_last5_avg
- line_hit_rate_over_ou_5  (last 5 vs line, excl push)
- line_hit_rate_over_ou_10 (last 10 vs line, excl push)  ← NEW
- line_hit_rate_over_5 / line_hit_rate_under_5
- MIN averages: min_last5_avg, min_season_avg
- Matches by espn_athlete_id first, then player_norm fallback

Input : step2_normalized_cfb.csv  (or step3_cfb.csv)
Output: step5b_with_stats_cfb.csv
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd
import requests

# Ensure <repo>/PropOracle is on sys.path so we can import PropOracle-level helpers.
_PROPORACLE_ROOT = Path(__file__).resolve().parents[4]
if str(_PROPORACLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROPORACLE_ROOT))

from scripts.db_utils import log_pipeline_health
from scripts.espn_boxscore_cache import load_boxscore_cache, save_boxscore_cache, sport_key_from_espn_league

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"}
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/{league}/scoreboard"
ESPN_SUMMARY_URL    = "https://site.web.api.espn.com/apis/site/v2/sports/football/{league}/summary"
ESPN_LEAGUE = "college-football"


def norm(s: str) -> str:
    """Canonical player name normalizer — matches cbb_step2_normalize.norm_str()."""
    s = (s or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# PrizePicks often uses the legal first name; ESPN boxscores use the nickname.
_NFL_FIRST_ALIASES = {
    "cameron": ("cam",),
    "cam": ("cameron",),
    "nicholas": ("nick",),
    "nick": ("nicholas",),
    "drew": ("andrew",),
    "andrew": ("drew",),
    "joshua": ("josh",),
    "josh": ("joshua",),
    "matthew": ("matt",),
    "matt": ("matthew",),
    "michael": ("mike",),
    "mike": ("michael",),
    "christopher": ("chris",),
    "chris": ("christopher",),
    "william": ("will",),
    "will": ("william",),
    "joseph": ("joe",),
    "joe": ("joseph",),
    "benjamin": ("ben",),
    "ben": ("benjamin",),
    "samuel": ("sam",),
    "sam": ("samuel",),
    "alexander": ("alex",),
    "alex": ("alexander",),
    "anthony": ("tony",),
    "tony": ("anthony",),
}


def _parse_box_date(value) -> Optional[dt.date]:
    """Parse cache game_date values stored as YYYY-MM-DD or YYYYMMDD."""
    s = str(value or "").strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    if len(s) == 8 and s.isdigit():
        try:
            return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _is_nfl_regular_season(d: dt.date) -> bool:
    """NFL regular season + playoffs (Sep–Feb). August is preseason — never L5."""
    return d.month >= 9 or d.month <= 2


def _nfl_name_keys(pn: str) -> set[str]:
    """Name keys for NFL matching: nickname aliases + collapsed apostrophe names."""
    p = norm(pn)
    if not p:
        return set()
    keys = {p, p.replace(" ", "")}
    parts = p.split()
    if not parts:
        return keys
    first, rest = parts[0], parts[1:]
    for alt in _NFL_FIRST_ALIASES.get(first, ()):
        keys.add(" ".join([alt, *rest]))
        keys.add("".join([alt, *rest]))
    if first == "wandale":
        keys.add(" ".join(["wan", "dale", *rest]))
    if first == "wan" and rest and rest[0] == "dale":
        keys.add(" ".join(["wandale", *rest[1:]]))
        keys.add("wandale" + "".join(rest[1:]))
    return {k for k in keys if k}


def _lookup_nfl_box_games(
    pn: str,
    aid: str,
    hist_aid: Dict[Tuple[str, str], List[dict]],
    hist_name: Dict[Tuple[str, str], List[dict]],
) -> List[dict]:
    """NFL/NFLP L5 is prior NFL boxscores for the player, regardless of current team."""
    games: List[dict] = []
    if aid:
        for (_t, a), g in hist_aid.items():
            if a == aid:
                games.extend(g)
        if games:
            return games
    keys = _nfl_name_keys(pn)
    collapsed = {k.replace(" ", "") for k in keys}
    for (_t, p), g in hist_name.items():
        if p in keys or p.replace(" ", "") in collapsed:
            games.extend(g)
    return games


def _nfl_regular_season_games(games: List[dict]) -> List[dict]:
    """Newest-first NFL regular-season/playoff games; drops August preseason."""
    out: List[dict] = []
    seen: set[str] = set()
    for g in games:
        d = _parse_box_date(g.get("game_date"))
        if d is None or not _is_nfl_regular_season(d):
            continue
        eid = str(g.get("event_id") or "").strip()
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        row = dict(g)
        row["_dt"] = d
        out.append(row)
    out.sort(key=lambda r: r.get("_dt") or dt.date.min, reverse=True)
    return out


def request_json(url, params=None, max_tries=5, backoff=1.4, sleep=0.0):
    for i in range(1, max_tries + 1):
        try:
            if sleep: time.sleep(sleep)
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff ** (i - 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(backoff ** (i - 1))
    log_pipeline_health(
        "cfb.step5b_attach_boxscore_stats",
        "request_json_failed",
        extra={"url": url, "params": params, "max_tries": max_tries},
        start=Path(__file__),
    )
    return None


def date_range(end_date: dt.date, days_back: int) -> List[str]:
    dates = [(end_date - dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(days_back + 1)]
    if ESPN_LEAGUE == "nfl":
        # NFLP and NFL share the same boxscores. Skip Mar–Aug so L5 cannot
        # pick up last year's (or this year's) preseason games.
        dates = [d for d in dates if d[4:6] not in ("03", "04", "05", "06", "07", "08")]
    return dates


def pull_scoreboard(d: str) -> dict:
    params = {"dates": d, "limit": "500"}
    if ESPN_LEAGUE == "college-football":
        params["groups"] = "80"  # FBS
    return request_json(ESPN_SCOREBOARD_URL.format(league=ESPN_LEAGUE), params=params, sleep=0.10) or {}


def _nfl_abbr_to_team_id() -> dict[str, str]:
    """ESPN team abbreviation -> team id (NFL scoreboard filter)."""
    data = request_json(
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams",
        params={"limit": "50"},
        sleep=0.05,
    ) or {}
    out: dict[str, str] = {}
    for ent in (data.get("sports") or [{}])[0].get("leagues", [{}])[0].get("teams", []) or []:
        t = ent.get("team") or {}
        ab = str(t.get("abbreviation") or "").strip().upper()
        tid = str(t.get("id") or "").strip()
        if ab and tid:
            out[ab] = tid
    _SLATE = {"LA": "LAR", "WAS": "WSH", "JAC": "JAX"}
    for k, v in _SLATE.items():
        if v in out and k not in out:
            out[k] = out[v]
    return out


def extract_events(sb: dict) -> List[Tuple[str, str, str, str]]:
    """Return list of (eid, team1_id, team2_id, date_str YYYYMMDD)."""
    out = []
    for ev in sb.get("events", []) or []:
        eid = str(ev.get("id", "")).strip()
        if not eid:
            continue
        date_str = str(ev.get("date", ""))[:10].replace("-", "")
        comps = ev.get("competitions", []) or []
        if not comps:
            continue
        competitors = comps[0].get("competitors", []) or []
        tids = []
        for c in competitors:
            tid = str((c.get("team") or {}).get("id", "")).strip()
            if tid:
                tids.append(tid)
        if len(tids) >= 2:
            out.append((eid, tids[0], tids[1], date_str))
    return out


def pull_summary(eid: str) -> dict:
    return request_json(ESPN_SUMMARY_URL.format(league=ESPN_LEAGUE), params={"event": eid}, sleep=0.08) or {}


def parse_min(x) -> float:
    try:
        s = str(x).strip()
        if s in ("", "--", "nan", "None"): return 0.0
        if ":" in s:
            mm, ss = s.split(":", 1)
            return float(mm) + float(ss) / 60.0
        return float(s)
    except Exception:
        return 0.0


def parse_players(summary: dict, game_date: str = "", event_id: str = "") -> List[dict]:
    """Parse CFB boxscore rows (passing / rushing / receiving)."""
    if not game_date:
        hdr = summary.get("header", {}) or {}
        comps = hdr.get("competitions", [{}])
        game_date = str(comps[0].get("date", "") if comps else "")[:10].replace("-", "")

    box = summary.get("boxscore", {}) or {}
    blocks = box.get("players", []) or []
    by_ath: Dict[str, dict] = {}

    def _f(val) -> float:
        try:
            s = str(val).strip()
            if s in ("", "--", "nan", "None"):
                return 0.0
            if "/" in s:
                s = s.split("/", 1)[0]
            return float(s)
        except Exception:
            return 0.0

    for tb in blocks:
        team_id = str((tb.get("team") or {}).get("id", "")).strip()
        if not team_id:
            continue
        for grp in tb.get("statistics", []) or []:
            if not isinstance(grp, dict):
                continue
            cat = str(grp.get("name", "")).strip().lower()
            labels = [str(x).upper() for x in (grp.get("labels") or [])]
            athletes = grp.get("athletes") or []
            if not labels or not athletes:
                continue

            def idx(lbl: str):
                return labels.index(lbl) if lbl in labels else None

            for a in athletes:
                ath = a.get("athlete", {}) or {}
                aid = str(ath.get("id", "")).strip()
                pn = norm(ath.get("displayName") or ath.get("fullName") or "")
                if not pn:
                    continue
                st = a.get("stats", []) or []
                key = aid or f"{pn}|{team_id}"
                row = by_ath.setdefault(
                    key,
                    {
                        "team_id": team_id,
                        "player_norm": pn,
                        "espn_athlete_id": aid,
                        "game_date": game_date,
                        "event_id": event_id,
                    },
                )
                if cat == "passing":
                    y = idx("YDS")
                    td = idx("TD")
                    cmp_i = idx("C")
                    if cmp_i is None:
                        cmp_i = idx("CMP")
                    int_i = idx("INT")
                    lng = idx("LONG")
                    if lng is None:
                        lng = idx("LNG")
                    if y is not None and y < len(st):
                        row["PASS_YDS"] = _f(st[y])
                    if td is not None and td < len(st):
                        row["PASS_TD"] = _f(st[td])
                    if cmp_i is not None and cmp_i < len(st):
                        row["PASS_CMP"] = _f(st[cmp_i])
                    if int_i is not None and int_i < len(st):
                        row["PASS_INT"] = _f(st[int_i])
                    if lng is not None and lng < len(st):
                        row["PASS_LONG"] = _f(st[lng])
                elif cat == "rushing":
                    y = idx("YDS")
                    td = idx("TD")
                    lng = idx("LONG")
                    if lng is None:
                        lng = idx("LNG")
                    if y is not None and y < len(st):
                        row["RUSH_YDS"] = _f(st[y])
                    if td is not None and td < len(st):
                        row["RUSH_TD"] = _f(st[td])
                    if lng is not None and lng < len(st):
                        row["RUSH_LONG"] = _f(st[lng])
                elif cat == "receiving":
                    rec = idx("REC")
                    y = idx("YDS")
                    td = idx("TD")
                    lng = idx("LONG")
                    if lng is None:
                        lng = idx("LNG")
                    tgt = idx("TGTS")
                    if tgt is None:
                        tgt = idx("TGT")
                    if tgt is None:
                        tgt = idx("TARGETS")
                    if rec is not None and rec < len(st):
                        row["REC"] = _f(st[rec])
                    if y is not None and y < len(st):
                        row["REC_YDS"] = _f(st[y])
                    if td is not None and td < len(st):
                        row["REC_TD"] = _f(st[td])
                    if lng is not None and lng < len(st):
                        row["REC_LONG"] = _f(st[lng])
                    if tgt is not None and tgt < len(st):
                        row["REC_TGT"] = _f(st[tgt])
                elif cat == "defensive":
                    tot = idx("TOT")
                    sack = idx("SACK")
                    if sack is None:
                        sack = idx("SACKS")
                    dint = idx("INT")
                    tfl = idx("TFL")
                    if tot is not None and tot < len(st):
                        row["TACK_TOT"] = _f(st[tot])
                    if sack is not None and sack < len(st):
                        row["SACK"] = _f(st[sack])
                    if dint is not None and dint < len(st):
                        row["DEF_INT"] = _f(st[dint])
                    if tfl is not None and tfl < len(st):
                        row["TFL"] = _f(st[tfl])
                elif cat == "kicking":
                    pts = idx("PTS")
                    fg = idx("FG")
                    if fg is None:
                        fg = idx("FGM")
                    xp = idx("XP")
                    if xp is None:
                        xp = idx("XPM")
                    if pts is not None and pts < len(st):
                        row["KICK_PTS"] = _f(st[pts])
                    if fg is not None and fg < len(st):
                        row["KICK_FG"] = _f(st[fg])
                    if xp is not None and xp < len(st):
                        row["KICK_XP"] = _f(st[xp])

    _stat_keys = (
        "PASS_YDS", "RUSH_YDS", "REC_YDS", "REC", "PASS_TD", "RUSH_TD", "REC_TD",
        "PASS_CMP", "PASS_INT", "SACK", "TACK_TOT", "KICK_PTS", "KICK_FG", "KICK_XP", "DEF_INT",
        "PASS_LONG", "RUSH_LONG", "REC_LONG", "REC_TGT", "TFL",
    )
    # Do not zero-fill LONG / TGTS: missing means ESPN did not publish the stat
    # (passing has no LONG; receiving has no TGTS). Zero would fake L5 unders.
    _zero_fill = tuple(k for k in _stat_keys if k not in ("PASS_LONG", "RUSH_LONG", "REC_LONG", "REC_TGT"))
    rows: List[dict] = []
    for row in by_ath.values():
        if not any(row.get(k) for k in _stat_keys):
            continue
        for k in _zero_fill:
            row.setdefault(k, 0.0)
        # CFB boxscores have no MIN column; mark participation for rolling-window filters.
        # Volume soft (snap/play share) CANNOT-OBTAIN from ESPN CFB summary/boxscore:
        # athlete groups expose C/ATT, CAR, REC, etc. only — zero snap/participation %.
        # Passing boxscore has no LONG (longest completion CANNOT-OBTAIN here).
        # Receiving has LONG but no TGTS (rec targets CANNOT-OBTAIN here).
        # Optional: CFBD /player/usage → data/cache/cfb_usage_cache.json via
        # build_cfb_usage_cache.py when CFBD_API_KEY is set (usage share → minutes_tier).
        # Do not invent minutes_tier from MIN=1.
        row["MIN"] = 1.0
        rows.append(row)
    return rows


def game_played_for_prop(g: dict, prop: str) -> bool:
    """True when this cached game should count toward L5/L10 (prop stat exists or any CFB stat)."""
    if prop and prop_value(prop, g) is not None:
        return True
    return any(
        float(g.get(k, 0) or 0) != 0
        for k in (
            "PASS_YDS", "RUSH_YDS", "REC_YDS", "REC", "PASS_TD", "RUSH_TD", "REC_TD",
            "PASS_CMP", "PASS_INT", "SACK", "TACK_TOT", "KICK_PTS", "KICK_FG", "KICK_XP",
            "RUSH_LONG", "REC_LONG", "PASS_LONG", "REC_TGT", "TFL",
        )
    )


def fantasy(r: dict) -> float:
    return (
        0.04 * r.get("PASS_YDS", 0)
        + 4 * r.get("PASS_TD", 0)
        - 1 * r.get("INT", 0)
        + 0.1 * r.get("RUSH_YDS", 0)
        + 6 * r.get("RUSH_TD", 0)
        + 0.1 * r.get("REC_YDS", 0)
        + 6 * r.get("REC_TD", 0)
        + r.get("REC", 0)
    )


def _stat_num(r: dict, key: str) -> float:
    try:
        v = r.get(key)
        if v is None or v == "":
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def prop_value(prop_norm: str, r: dict) -> Optional[float]:
    p = str(prop_norm or "").strip().lower()
    p = re.sub(r"[^a-z0-9]+", "_", p).strip("_")
    m = {
        "pass_yds": r.get("PASS_YDS"),
        "rush_yds": r.get("RUSH_YDS"),
        "rec_yds": r.get("REC_YDS"),
        "pass_td": r.get("PASS_TD"),
        "rush_td": r.get("RUSH_TD"),
        "rec_td": r.get("REC_TD"),
        "rec": r.get("REC"),
        "int": r.get("PASS_INT") or r.get("DEF_INT"),
        "passing_yards": r.get("PASS_YDS"),
        "rushing_yards": r.get("RUSH_YDS"),
        "receiving_yards": r.get("REC_YDS"),
        "passing_tds": r.get("PASS_TD"),
        "rushing_tds": r.get("RUSH_TD"),
        "receiving_tds": r.get("REC_TD"),
        "receptions": r.get("REC"),
        "pass_completions": r.get("PASS_CMP"),
        "completions": r.get("PASS_CMP"),
        "interceptions_thrown": r.get("PASS_INT"),
        "interceptions": r.get("PASS_INT") or r.get("DEF_INT"),
        "sacks": r.get("SACK"),
        "tackles": r.get("TACK_TOT"),
        "tackles_assists": r.get("TACK_TOT"),
        "tfl": r.get("TFL"),
        "kicking_points": r.get("KICK_PTS"),
        "kick_pts": r.get("KICK_PTS"),
        "pat_made": r.get("KICK_XP"),
        "fg_made": r.get("KICK_FG"),
        "extra_points": r.get("KICK_XP"),
        "field_goals": r.get("KICK_FG"),
        "player_td": _stat_num(r, "PASS_TD") + _stat_num(r, "RUSH_TD") + _stat_num(r, "REC_TD"),
        "pass_rush_yds": _stat_num(r, "PASS_YDS") + _stat_num(r, "RUSH_YDS"),
        "rush_rec_yds": _stat_num(r, "RUSH_YDS") + _stat_num(r, "REC_YDS"),
        "pass_rush_rec_td": _stat_num(r, "PASS_TD") + _stat_num(r, "RUSH_TD") + _stat_num(r, "REC_TD"),
        "pass_long": r.get("PASS_LONG"),
        "rush_long": r.get("RUSH_LONG"),
        "rec_long": r.get("REC_LONG"),
        "rec_tgt": r.get("REC_TGT"),
        "fantasy": fantasy(r),
    }
    if p in m and m[p] is not None:
        return m[p]
    if "fantasy" in p:
        return fantasy(r)
    if "longest" in p and "completion" in p:
        return r.get("PASS_LONG")
    if "longest" in p and "rush" in p:
        return r.get("RUSH_LONG")
    if "longest" in p and ("rec" in p or "reception" in p):
        return r.get("REC_LONG")
    if "target" in p:
        return r.get("REC_TGT")
    if "pass" in p and "rush" in p and "rec" in p and "td" in p:
        return m["pass_rush_rec_td"]
    if "rush" in p and "rec" in p and "yd" in p:
        return m["rush_rec_yds"]
    if "pass" in p and "rush" in p and "yd" in p:
        return m["pass_rush_yds"]
    if "pass" in p and "yard" in p:
        return r.get("PASS_YDS")
    if "rush" in p and "yard" in p:
        return r.get("RUSH_YDS")
    if ("rec" in p or "receiv" in p) and "yard" in p:
        return r.get("REC_YDS")
    if "reception" in p or p == "rec":
        return r.get("REC")
    if "completion" in p:
        return r.get("PASS_CMP")
    if "sack" in p:
        return r.get("SACK")
    if "kick" in p and "point" in p:
        return r.get("KICK_PTS")
    if p in ("pat_made", "extra_points") or ("pat" in p and "made" in p):
        return r.get("KICK_XP")
    if p in ("fg_made", "field_goals") or ("field" in p and "goal" in p):
        return r.get("KICK_FG")
    if "fg" in p and "made" in p:
        return r.get("KICK_FG")
    if "tackle" in p:
        return r.get("TACK_TOT")
    if "touchdown" in p:
        return m["player_td"]
    return m.get(p)


def hit_rates(vals: List[float], line: float, n: int):
    """Compute hit rate over/under/push for last n games, excl push."""
    sub = vals[:n]
    over = sum(1 for v in sub if v > line)
    under = sum(1 for v in sub if v < line)
    push  = sum(1 for v in sub if v == line)
    denom_ou = len(sub) - push
    hr_over_ou  = over  / denom_ou if denom_ou > 0 else None
    hr_under_ou = under / denom_ou if denom_ou > 0 else None
    hr_over     = over  / len(sub) if sub else None
    hr_under    = under / len(sub) if sub else None
    return over, under, push, hr_over, hr_under, hr_over_ou, hr_under_ou


def _fetch_one_event_cfb(
    eid: str,
    t1: str,
    t2: str,
    slate_ids: set,
    date_str: str = "",   # FIX: was missing, causing TypeError
) -> Tuple[str, List[dict]]:
    """Fetch and parse a single CFB ESPN event. Returns (eid, player_rows)."""
    if slate_ids and t1 not in slate_ids and t2 not in slate_ids:
        return eid, []
    try:
        time.sleep(random.uniform(0.05, 0.25))
        summ = pull_summary(eid)
        return eid, parse_players(summ, game_date=date_str, event_id=eid)
    except Exception as e:
        print(f"  [WARN] CFB summary failed event={eid}: {e}")
        log_pipeline_health(
            "cfb.step5b_attach_boxscore_stats",
            "event_summary_failed",
            extra={"event_id": eid, "error": f"{type(e).__name__}: {e}"},
            start=Path(__file__),
        )
        return eid, []


def build_player_histories(
    days: int,
    slate_ids: set,
    workers: int = 4,
    cache_path: str = "",
    tid_to_abbr: dict = None,
    end_date: Optional[dt.date] = None,
    force_refetch_keys: Optional[set] = None,
) -> Tuple[Dict, Dict]:
    """
    Parallelized boxscore fetch for CFB with persistent cache + deterministic ordering.
    Returns (hist_aid, hist_name) sorted newest-first per player.
    """
    import os

    # Phase 0: load cache (SQLite first; CSV is backfill only)
    cached_rows: List[dict] = []
    cached_eids: set = set()
    cache_source = "empty"
    sport_key = sport_key_from_espn_league(ESPN_LEAGUE)
    if cache_path:
        try:
            cached_rows, cache_source = load_boxscore_cache(sport_key, cache_path)
            stale_eids: set = set()
            for rr in cached_rows:
                has_opp = (
                    ("opp_team_abbr" in rr and str(rr.get("opp_team_abbr","")).strip() not in ("", "nan"))
                    or ("opp_team_id" in rr and str(rr.get("opp_team_id","")).strip() not in ("", "nan"))
                )
                for col in (
                    "PASS_YDS", "RUSH_YDS", "REC_YDS", "REC", "PASS_TD", "RUSH_TD", "REC_TD",
                    "PASS_CMP", "PASS_INT", "SACK", "TACK_TOT", "KICK_PTS", "KICK_FG", "KICK_XP", "DEF_INT",
                    "PASS_LONG", "RUSH_LONG", "REC_LONG", "REC_TGT", "TFL",
                ):
                    if col not in rr:
                        continue
                    raw = str(rr[col]).strip()
                    if raw in ("", "nan", "None"):
                        # Missing LONG/TGTS stay absent so L5 is not invented as 0.
                        rr[col] = None if col in (
                            "PASS_LONG", "RUSH_LONG", "REC_LONG", "REC_TGT",
                        ) else 0.0
                        continue
                    try:
                        rr[col] = float(raw)
                    except Exception:
                        rr[col] = None if col in (
                            "PASS_LONG", "RUSH_LONG", "REC_LONG", "REC_TGT",
                        ) else 0.0
                if not has_opp:
                    stale_eids.add(str(rr.get("event_id","")))
            if stale_eids:
                cached_rows = [rr for rr in cached_rows if str(rr.get("event_id","")) not in stale_eids]
                print(f"  [CACHE] Dropped {len(stale_eids)} stale events missing opponent — will refetch")
            cached_eids = {str(rr.get("event_id","")) for rr in cached_rows if rr.get("event_id")}
            if force_refetch_keys:
                drop_eids: set[str] = set()
                for rr in cached_rows:
                    pn = str(rr.get("player_norm") or "").strip()
                    if not (_nfl_name_keys(pn) & set(force_refetch_keys)):
                        continue
                    if str(rr.get("KICK_FG", "")).strip() in ("", "nan"):
                        drop_eids.add(str(rr.get("event_id", "")).strip())
                drop_eids.discard("")
                if drop_eids:
                    cached_rows = [rr for rr in cached_rows if str(rr.get("event_id", "")).strip() not in drop_eids]
                    cached_eids -= drop_eids
                    print(f"  [CACHE] Refetch {len(drop_eids)} events to split FG/XP kicking stats")
            print(f"  [CACHE] Loaded {len(cached_rows)} rows ({len(cached_eids)} events)")
        except Exception as e:
            print(f"  [CACHE] Load failed ({e}) — full refresh")
            cached_rows, cached_eids = [], set()
            cache_source = "empty"
    # Phase 1: scoreboards
    all_events: List[Tuple[str, str, str, str]] = []
    seen_eids: set = set()
    print(f"-> Scanning {days + 1} days of {ESPN_LEAGUE} scoreboards...")
    try:
        from tqdm import tqdm as _tqdm
    except ImportError:
        import subprocess as _sp, sys as _sys
        _sp.check_call([_sys.executable, "-m", "pip", "install", "tqdm", "--break-system-packages", "-q"])
        from tqdm import tqdm as _tqdm
    anchor = end_date or dt.date.today()
    for d in _tqdm(date_range(anchor, days), desc="Scanning scoreboards", unit="day"):
        sb = pull_scoreboard(d)
        for eid, t1, t2, date_str in extract_events(sb):
            if eid not in seen_eids:
                seen_eids.add(eid)
                all_events.append((eid, t1, t2, date_str))

    if slate_ids:
        all_events = [(e, t1, t2, ds) for e, t1, t2, ds in all_events
                      if t1 in slate_ids or t2 in slate_ids]

    pending = [(eid, t1, t2, ds) for eid, t1, t2, ds in all_events
               if eid not in cached_eids]

    def _cached_has_rush_long(rr: dict) -> bool:
        v = rr.get("RUSH_LONG")
        if v is None:
            return False
        s = str(v).strip()
        return s not in ("", "nan", "None")

    if cached_rows:
        scan_eids = {str(eid) for eid, _, _, _ in all_events}
        scan_cached = [
            rr for rr in cached_rows
            if str(rr.get("event_id", "")).strip() in scan_eids
        ]
        if scan_cached and not any(_cached_has_rush_long(rr) for rr in scan_cached):
            cached_rows = [
                rr for rr in cached_rows
                if str(rr.get("event_id", "")).strip() not in scan_eids
            ]
            cached_eids -= scan_eids
            pending = [(eid, t1, t2, ds) for eid, t1, t2, ds in all_events]
            print(f"  [CACHE] Refetch {len(pending)} events to add rush/rec LONG + SACKS")

    print(f"-> {len(all_events)} total | {len(cached_eids)} cached | "
          f"{len(pending)} new ({workers} workers)...")

    # Phase 2: parallel fetch
    new_rows: List[dict] = []
    if pending:
        from concurrent.futures import ThreadPoolExecutor, as_completed as _ac
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_fetch_one_event_cfb, eid, t1, t2, slate_ids, ds): eid
                for eid, t1, t2, ds in pending
            }
            fetched = 0
            with _tqdm(total=len(pending), desc="Fetching games", unit="game") as pbar:
                for future in _ac(futures):
                    eid, rows = future.result()
                    if rows:
                        fetched += 1
                        new_rows.extend(rows)
                    pbar.update(1)
        print(f"  [FETCH] Got {fetched} new games with player data")

    # Phase 3: update cache
    all_rows = cached_rows + new_rows
    # Resolve opp_team_id -> opp_team_abbr using slate map (for H2H matching in step6)
    if tid_to_abbr:
        for rr in all_rows:
            if not rr.get("opp_team_abbr"):
                opp_id = str(rr.get("opp_team_id", "")).strip()
                rr["opp_team_abbr"] = tid_to_abbr.get(opp_id, opp_id)
    if cache_path and all_rows:
        try:
            save_boxscore_cache(sport_key, all_rows, cache_path, cache_source)
        except Exception as e:
            print(f"  [CACHE] Save failed: {e}")

    # Phase 4: build sorted, deduplicated histories (newest-first)
    raw_by_aid:  Dict[Tuple[str,str], List[dict]] = {}
    raw_by_name: Dict[Tuple[str,str], List[dict]] = {}
    for rr in all_rows:
        tid = str(rr.get("team_id","")).strip()
        aid = str(rr.get("espn_athlete_id","")).strip()
        pn  = str(rr.get("player_norm","")).strip()
        if tid and aid: raw_by_aid.setdefault((tid, aid), []).append(rr)
        if tid and pn:  raw_by_name.setdefault((tid, pn), []).append(rr)

    def dedup_sort(game_list):
        def _key(r):
            d = _parse_box_date(r.get("game_date"))
            return d or dt.date.min
        sorted_games = sorted(game_list, key=_key, reverse=True)
        seen, out = set(), []
        for g in sorted_games:
            eid = str(g.get("event_id",""))
            if eid and eid in seen: continue
            if eid: seen.add(eid)
            out.append(g)
        return out

    hist_aid  = {k: dedup_sort(v) for k, v in raw_by_aid.items()}
    hist_name = {k: dedup_sort(v) for k, v in raw_by_name.items()}

    print(f"-> {ESPN_LEAGUE} histories built | by_id={len(hist_aid)} | by_name={len(hist_name)}")
    return hist_aid, hist_name


def main():
    try:
        from tqdm import tqdm as _tqdm
    except ImportError:
        import subprocess as _sp, sys as _sys
        _sp.check_call([_sys.executable, "-m", "pip", "install", "tqdm", "--break-system-packages", "-q"])
        from tqdm import tqdm as _tqdm

    ap = argparse.ArgumentParser()
    ap.add_argument("--input",    required=True)
    ap.add_argument("--output",   default="step5b_with_stats_cfb.csv")
    ap.add_argument("--days",     type=int, default=180,
                    help="Days of history to scan backward from --date (default 180 for cross-season L5)")
    ap.add_argument("--date",     default="",
                    help="Anchor date YYYY-MM-DD for scoreboard scan (default: today)")
    ap.add_argument("--n",        type=int, default=10)
    ap.add_argument("--workers",  type=int, default=4)
    ap.add_argument("--cache",    default="cfb_boxscore_cache.csv",
                    help="Persistent cache CSV path (default: cfb_boxscore_cache.csv)")
    ap.add_argument(
        "--league",
        default="auto",
        choices=["auto", "college-football", "wocollege-football", "nfl"],
        help="ESPN league slug for scoreboard/summary fetches (default: auto by wcbb in paths).",
    )
    ap.add_argument("--no_cache", action="store_true",
                    help="Ignore existing cache and force full refresh")
    args = ap.parse_args()
    cache_path = "" if args.no_cache else args.cache

    global ESPN_LEAGUE
    if args.league == "auto":
        hint = f"{args.input} {args.output} {cache_path}".lower()
        if "nfl" in hint:
            ESPN_LEAGUE = "nfl"
        else:
            ESPN_LEAGUE = "wocollege-football" if "wcbb" in hint else "college-football"
    else:
        ESPN_LEAGUE = args.league
    print(f"-> ESPN league: {ESPN_LEAGUE}")

    print("→ Loading:", args.input)
    try:
        df = pd.read_csv(args.input, dtype=str).fillna("")
    except Exception as e:
        log_pipeline_health(
            "cfb.step5b_attach_boxscore_stats",
            "read_failed",
            extra={"input": args.input, "error": f"{type(e).__name__}: {e}"},
            start=Path(__file__),
        )
        raise
    df["line"] = pd.to_numeric(df["line"], errors="coerce")
    if "player_norm" not in df.columns:
        pname_col = next((c for c in ("player", "player_name", "pp_player") if c in df.columns), None)
        if pname_col:
            df["player_norm"] = df[pname_col].astype(str).apply(norm)
        else:
            df["player_norm"] = ""
    if ESPN_LEAGUE == "nfl":
        if "player" not in df.columns and "player_name" in df.columns:
            df["player"] = df["player_name"]
        if "team_abbr" not in df.columns and "team" in df.columns:
            df["team_abbr"] = df["team"].astype(str).str.strip().str.upper()
        abbr_map = _nfl_abbr_to_team_id()
        if "team_id" not in df.columns:
            df["team_id"] = ""
        if abbr_map and "team_abbr" in df.columns:
            df["team_id"] = df["team_abbr"].map(abbr_map).fillna(df["team_id"]).astype(str)
        ref_map = _PROPORACLE_ROOT / "data" / "reference" / "pp_to_espn_id_map_nfl.csv"
        if ref_map.is_file() and "espn_athlete_id" not in df.columns:
            try:
                ref = pd.read_csv(ref_map, dtype=str).fillna("")
                if "player_name" in ref.columns and "espn_athlete_id" in ref.columns:
                    pn = df.get("player_name", df.get("player", "")).astype(str).str.strip()
                    m = ref.drop_duplicates("player_name").set_index("player_name")["espn_athlete_id"]
                    df["espn_athlete_id"] = pn.map(m).fillna("")
            except Exception:
                pass
    if "team_id" not in df.columns:
        df["team_id"] = ""
    if "espn_athlete_id" not in df.columns:
        df["espn_athlete_id"] = ""

    # ── Flag 2nd-half props before any stat attachment ────────────────────────
    # ESPN boxscores are full-game only. Props with duration="2nd Half" need a
    # separate data source — attaching full-game stats produces wrong averages
    # and hit rates (~2x the actual 2H numbers). Mark UNSUPPORTED_2H so step6
    # excludes them from scoring entirely rather than using corrupted stats.
    if "duration" in df.columns:
        h2_mask = df["duration"].str.lower().str.contains("2nd|half", na=False)
        n_h2 = int(h2_mask.sum())
        if n_h2:
            print(f"  ⚠️  {n_h2} 2nd-half props tagged UNSUPPORTED_2H — full-game ESPN stats invalid for 2H lines")
            df_2h = df[h2_mask].copy()
            df_2h["stat_status"] = "UNSUPPORTED_2H"
            df = df[~h2_mask].copy()
        else:
            df_2h = pd.DataFrame()
    else:
        df_2h = pd.DataFrame()

    # use prop_norm if available, else prop_type
    if ESPN_LEAGUE == "nfl" and "prop_type_normalized" in df.columns:
        prop_col = "prop_type_normalized"
    else:
        prop_col = "prop_norm" if "prop_norm" in df.columns else "prop_type"

    # ── Bouncer (slate-level) ───────────────────────────────────────────────
    before = len(df)
    df = df[df.get("player", "").astype(str).str.strip() != ""].copy()
    if "pp_team" in df.columns:
        df = df[df["pp_team"].astype(str).str.strip() != ""].copy()
    df = df[df[prop_col].astype(str).str.strip() != ""].copy()
    # Line must be numeric & non-negative for hit-rate math
    df = df[df["line"].notna() & (df["line"] >= 0)].copy()
    bounced = before - len(df)
    if bounced:
        print(f"  🧹 Bouncer: removed {bounced} junk slate rows")
        log_pipeline_health(
            "cfb.step5b_attach_boxscore_stats",
            "bouncer_removed_slate_rows",
            extra={"removed": bounced, "before": before, "after": len(df)},
            start=Path(__file__),
        )

    slate_ids = {x for x in df["team_id"].astype(str).str.strip() if x and x != "nan"}
    print("→ Slate team_ids:", len(slate_ids))

    # If NO_MATCH rows have blank team_id but we know the team from team_abbr,
    # fetch all games rather than filtering — the team_id filter is an optimization
    # but it silently drops players whose ESPN ID wasn't found. If >10% of rows
    # have no team_id, disable the slate_ids filter entirely for safety.
    no_team_id = (df["team_id"].astype(str).str.strip().isin(["", "nan"])).sum()
    if no_team_id > 0:
        print(f"→ {no_team_id} rows have no team_id — fetching all CBB games (no team filter)")
        slate_ids = set()  # empty set = fetch all games

    # Build team_id -> team_abbr reverse map from slate for opp resolution in cache
    tid_to_abbr: dict = {}
    for _, r in df.iterrows():
        tid  = str(r.get("team_id", "")).strip()
        abbr = str(r.get("team_abbr", "")).strip()
        if tid and abbr and tid != "nan":
            tid_to_abbr[tid] = abbr

    end_d = dt.date.today()
    if str(args.date or "").strip():
        end_d = dt.datetime.strptime(str(args.date).strip()[:10], "%Y-%m-%d").date()

    kick_refetch_keys: set[str] = set()
    if ESPN_LEAGUE == "nfl":
        kick_props = {"fg_made", "pat_made", "field_goals", "extra_points"}
        for _, r in df.iterrows():
            if str(r.get(prop_col, "")).strip().lower() in kick_props:
                kick_refetch_keys |= _nfl_name_keys(str(r.get("player_norm", "")))

    # ── Parallelized fetch ────────────────────────────────────────────────────
    hist_aid, hist_name = build_player_histories(
        args.days,
        slate_ids,
        workers=args.workers,
        cache_path=cache_path,
        tid_to_abbr=tid_to_abbr,
        end_date=end_d,
        force_refetch_keys=kick_refetch_keys or None,
    )
    if not hist_aid and not hist_name:
        log_pipeline_health(
            "cfb.step5b_attach_boxscore_stats",
            "no_histories_built",
            extra={"days": args.days, "workers": args.workers},
            start=Path(__file__),
        )

    if ESPN_LEAGUE == "nfl":
        name_to_aid: dict[str, str] = {}
        for (_t, a), glist in hist_aid.items():
            if not a or not glist:
                continue
            pn0 = str(glist[0].get("player_norm") or "").strip()
            for k in _nfl_name_keys(pn0):
                name_to_aid.setdefault(k, a)
        filled = 0
        new_aids = []
        for _, row in df.iterrows():
            cur = str(row.get("espn_athlete_id") or "").strip()
            if cur:
                new_aids.append(cur)
                continue
            found = ""
            for k in _nfl_name_keys(str(row.get("player_norm") or "")):
                if k in name_to_aid:
                    found = name_to_aid[k]
                    filled += 1
                    break
            new_aids.append(found)
        df["espn_athlete_id"] = new_aids
        if filled:
            print(f"  [NFL] Filled {filled} espn_athlete_id values from boxscore cache")

    out_rows, stat_status = [], []

    for _, row in _tqdm(df.iterrows(), total=len(df), desc="Attaching stats", unit="prop"):
        tid  = str(row.get("team_id",       "")).strip()
        pn   = str(row.get("player_norm",   "")).strip()
        aid  = str(row.get("espn_athlete_id","")).strip()
        prop = str(row.get(prop_col,        "")).strip()
        line = row.get("line", None)

        # NFL / NFLP: last year's NFL regular-season boxscores, any team.
        # Preseason (August) is excluded. Nickname aliases cover Cam/Cameron etc.
        if ESPN_LEAGUE == "nfl":
            games = _lookup_nfl_box_games(pn, aid, hist_aid, hist_name)
            games = _nfl_regular_season_games(games)
        elif not tid:
            games = []
            # Strategy A: espn_athlete_id across all teams (fastest, most accurate)
            if aid:
                for (t, a), g in hist_aid.items():
                    if a == aid:
                        games.extend(g)
            # Strategy B: player_norm across all teams (name-only fallback)
            if not games and pn:
                for (t, p), g in hist_name.items():
                    if p == pn:
                        games.extend(g)
            if not games:
                stat_status.append("NO_BOX_HISTORY"); out_rows.append({}); continue
        else:
            games = (hist_aid.get((tid, aid), []) if aid else []) or hist_name.get((tid, pn), [])
        if not games:
            stat_status.append("NO_BOX_HISTORY"); out_rows.append({}); continue

        played = [g for g in games if game_played_for_prop(g, prop)]
        vals = [float(v) for g in played
                if (v := prop_value(prop, g)) is not None]

        if not vals:
            stat_status.append("UNSUPPORTED_PROP"); out_rows.append({}); continue
        # NFL/NFLP L5 is prior regular-season boxes. Backup QBs often have
        # 1–4 games — still attach those logs. Other leagues keep the 5-game floor.
        if ESPN_LEAGUE != "nfl" and len(vals) < 5:
            stat_status.append("INSUFFICIENT_GAMES"); out_rows.append({"games_used": len(vals)}); continue

        # vals is now newest-first (already sorted from dedup_sort)

        # FIX: preserve full season history BEFORE truncating to --n games
        season_vals = vals[:]           # full window
        game_log    = vals[:args.n]     # truncated for g1..gN columns
        last5       = game_log[:5]
        last10      = game_log[:10]

        o = {"games_used": len(season_vals)}   # true season game count
        for k in range(1, args.n + 1):
            o[f"stat_g{k}"] = game_log[k-1] if k-1 < len(game_log) else ""

        o["stat_last5_avg"]  = round(sum(last5)       / len(last5),       3) if last5       else ""
        o["stat_last10_avg"] = round(sum(last10)      / len(last10),      3) if last10      else ""
        o["stat_season_avg"] = round(sum(season_vals) / len(season_vals), 3) if season_vals else ""

        # minutes averages (CFB: participation flag only)
        min_vals = [float(g.get("MIN", 1) or 1) for g in played]
        min5 = min_vals[:5]
        o["min_last5_avg"]   = round(sum(min5)    / len(min5),    1) if min5    else ""
        o["min_season_avg"]  = round(sum(min_vals) / len(min_vals), 1) if min_vals else ""

        # hit rates vs line
        if pd.notna(line):
            ln = float(line)

            over5, under5, push5, hr_ov5, hr_un5, hr_ov_ou5, hr_un_ou5 = hit_rates(game_log, ln, 5)
            o["line_hits_over_5"]         = over5
            o["line_hits_under_5"]        = under5
            o["line_hits_push_5"]         = push5
            o["last5_over"]               = over5
            o["last5_under"]              = under5
            o["l5_over"]                  = over5
            o["l5_under"]                 = under5
            o["line_hit_rate_over_5"]     = round(hr_ov5,    3) if hr_ov5    is not None else ""
            o["line_hit_rate_under_5"]    = round(hr_un5,    3) if hr_un5    is not None else ""
            o["line_hit_rate_over_ou_5"]  = round(hr_ov_ou5, 3) if hr_ov_ou5 is not None else ""
            o["line_hit_rate_under_ou_5"] = round(hr_un_ou5, 3) if hr_un_ou5 is not None else ""

            over10, under10, push10, hr_ov10, hr_un10, hr_ov_ou10, hr_un_ou10 = hit_rates(game_log, ln, 10)
            o["line_hits_over_10"]         = over10
            o["line_hits_under_10"]        = under10
            o["line_hits_push_10"]         = push10
            o["line_hit_rate_over_10"]     = round(hr_ov10,    3) if hr_ov10    is not None else ""
            o["line_hit_rate_under_10"]    = round(hr_un10,    3) if hr_un10    is not None else ""
            o["line_hit_rate_over_ou_10"]  = round(hr_ov_ou10, 3) if hr_ov_ou10 is not None else ""
            o["line_hit_rate_under_ou_10"] = round(hr_un_ou10, 3) if hr_un_ou10 is not None else ""

            o["model_dir_5"] = "OVER" if over5 >= under5 else "UNDER"

        stat_status.append("OK")
        out_rows.append(o)

    stats_df = pd.DataFrame(out_rows).fillna("")
    df["stat_status"] = stat_status
    out = pd.concat([df.reset_index(drop=True), stats_df], axis=1)

    # Re-attach the 2H rows (they carry UNSUPPORTED_2H status, no stat columns)
    if not df_2h.empty:
        out = pd.concat([out, df_2h], ignore_index=True, sort=False).fillna("")

    out.to_csv(args.output, index=False)

    print(f"✅ Saved → {args.output} | rows={len(out)}")
    print("stat_status breakdown:")
    print(out["stat_status"].value_counts().to_string())




if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_pipeline_health(
            "cfb.step5b_attach_boxscore_stats",
            "run_failed",
            extra={"error": f"{type(e).__name__}: {e}"},
            start=Path(__file__),
        )
        print(f"❌ CFB step5b failed (logged). {type(e).__name__}: {e}")
        raise
