"""Fill blank CFB PrizePicks opponents from ESPN scoreboard.

One-sided boards (only ILL / OKLA / MSU posted) never infer opp from game_id.
"""

from __future__ import annotations

import datetime
import json
import time
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from utils.cfb_playoff_metadata import cfb_abbr_lookup_keys, norm_cfb_team_abbr

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

CFB_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
    "/scoreboard?dates={dates}&limit=300"
)
_ET = ZoneInfo("America/New_York")


def _blank(v: object) -> bool:
    s = str(v or "").strip()
    return (not s) or s.lower() in ("nan", "none")


def dates_from_start_times(values: list[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        try:
            day = ts.tz_convert(_ET).strftime("%Y-%m-%d")
        except Exception:
            day = str(ts)[:10]
        if day and day not in seen:
            seen.add(day)
            out.append(day)
    return out


def parse_scoreboard_pairs(payload: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for ev in payload.get("events") or []:
        comps = ev.get("competitions") or []
        if not comps:
            continue
        home = away = ""
        for c in comps[0].get("competitors") or []:
            abbr = str((c.get("team") or {}).get("abbreviation") or "").strip().upper()
            if not abbr:
                continue
            if str(c.get("homeAway") or "").lower() == "home":
                home = abbr
            else:
                away = abbr
        if home and away:
            pairs.append((home, away))
    return pairs


def expand_opp_map(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """team abbr (any alias) → opponent's ESPN/rankings abbr."""
    m: dict[str, str] = {}
    for a, b in pairs:
        a_n, b_n = norm_cfb_team_abbr(a) or a, norm_cfb_team_abbr(b) or b
        for key in cfb_abbr_lookup_keys(a) | {a, a_n}:
            m[key] = b_n
        for key in cfb_abbr_lookup_keys(b) | {b, b_n}:
            m[key] = a_n
    return m


def _get_json(url: str) -> dict[str, Any]:
    try:
        from curl_cffi.requests import Session as CurlSession

        resp = CurlSession(impersonate="chrome131").get(url, headers=_HEADERS, timeout=45)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))


def fetch_cfb_opp_map(dates: list[str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for i, day in enumerate(dates):
        ds = str(day or "").strip()[:10].replace("-", "")
        if len(ds) != 8:
            continue
        if i:
            time.sleep(0.08)
        try:
            payload = _get_json(CFB_SCOREBOARD.format(dates=ds))
        except Exception as exc:
            print(f"[CFB opp] scoreboard {ds} failed: {exc}")
            continue
        merged.update(expand_opp_map(parse_scoreboard_pairs(payload)))
    return merged


def fill_cfb_opp_from_map(df: pd.DataFrame, opp_map: dict[str, str]) -> pd.DataFrame:
    if df.empty or not opp_map:
        return df
    out = df.copy()
    team_col = next((c for c in ("team_abbr", "pp_team", "team") if c in out.columns), None)
    if not team_col:
        return out
    opp_cols = [c for c in ("pp_opp_team", "opp_team_abbr", "opp") if c in out.columns]
    if not opp_cols:
        out["pp_opp_team"] = ""
        opp_cols = ["pp_opp_team"]

    n_fill = 0
    for idx, row in out.iterrows():
        if any(not _blank(row.get(c)) for c in opp_cols):
            continue
        team = norm_cfb_team_abbr(row.get(team_col))
        opp = opp_map.get(team) or opp_map.get(str(row.get(team_col) or "").strip().upper()) or ""
        if not opp:
            continue
        n_fill += 1
        for c in opp_cols:
            out.at[idx, c] = opp
    if n_fill:
        print(f"[CFB opp] filled opponent on {n_fill} rows from ESPN scoreboard")
    return out


def fill_cfb_opp_from_espn(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    time_col = next((c for c in ("start_time", "start") if c in df.columns), None)
    dates = dates_from_start_times(df[time_col].tolist() if time_col else [])
    if not dates:
        today = datetime.datetime.now(_ET).strftime("%Y-%m-%d")
        dates = [today]
    return fill_cfb_opp_from_map(df, fetch_cfb_opp_map(dates))
