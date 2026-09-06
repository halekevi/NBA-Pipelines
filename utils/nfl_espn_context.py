"""ESPN NFL helpers: schedule pairing, weather, injuries, depth charts.

Used by NFL step2 (Opp fill), step4c (depth), step4d (injuries), and step6b
(weather + game context). All network calls are best-effort — callers keep
going with empty dicts on failure.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

NFL_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
NFL_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
NFL_TEAMS = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
NFL_DEPTH = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/depthcharts"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

NFL_TEAM_ALIASES = {
    "WAS": "WSH",
    "WSH": "WSH",
    "LA": "LAR",
    "JAC": "JAX",
    "JAX": "JAX",
    "LAR": "LAR",
    "LVR": "LV",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
}

NFL_TEAM_DISPLAY_TO_ABBR = {
    "arizona cardinals": "ARI",
    "atlanta falcons": "ATL",
    "baltimore ravens": "BAL",
    "buffalo bills": "BUF",
    "carolina panthers": "CAR",
    "chicago bears": "CHI",
    "cincinnati bengals": "CIN",
    "cleveland browns": "CLE",
    "dallas cowboys": "DAL",
    "denver broncos": "DEN",
    "detroit lions": "DET",
    "green bay packers": "GB",
    "houston texans": "HOU",
    "indianapolis colts": "IND",
    "jacksonville jaguars": "JAX",
    "kansas city chiefs": "KC",
    "las vegas raiders": "LV",
    "los angeles chargers": "LAC",
    "los angeles rams": "LAR",
    "miami dolphins": "MIA",
    "minnesota vikings": "MIN",
    "new england patriots": "NE",
    "new orleans saints": "NO",
    "new york giants": "NYG",
    "new york jets": "NYJ",
    "philadelphia eagles": "PHI",
    "pittsburgh steelers": "PIT",
    "san francisco 49ers": "SF",
    "seattle seahawks": "SEA",
    "tampa bay buccaneers": "TB",
    "tennessee titans": "TEN",
    "washington commanders": "WSH",
}

# Odds API keyword fragments (unique enough to match full names).
ODDS_TEAM_KEYWORDS = {
    "ARI": "Arizona",
    "ATL": "Atlanta",
    "BAL": "Baltimore",
    "BUF": "Buffalo",
    "CAR": "Carolina",
    "CHI": "Chicago",
    "CIN": "Cincinnati",
    "CLE": "Cleveland",
    "DAL": "Dallas",
    "DEN": "Denver",
    "DET": "Detroit",
    "GB": "Green Bay",
    "HOU": "Houston",
    "IND": "Indianapolis",
    "JAX": "Jacksonville",
    "JAC": "Jacksonville",
    "KC": "Kansas City",
    "LV": "Las Vegas",
    "LAC": "Chargers",
    "LAR": "Rams",
    "LA": "Rams",
    "MIA": "Miami",
    "MIN": "Minnesota",
    "NE": "New England",
    "NO": "New Orleans",
    "NYG": "Giants",
    "NYJ": "Jets",
    "PHI": "Philadelphia",
    "PIT": "Pittsburgh",
    "SF": "San Francisco",
    "SEA": "Seattle",
    "TB": "Tampa",
    "TEN": "Tennessee",
    "WSH": "Washington",
    "WAS": "Washington",
}

BLOWOUT_THRESHOLD = 7.5
LOW_TOTAL_THRESH = 40.0
HIGH_TOTAL_THRESH = 48.0
WIND_PASS_MPH = 15.0
WIND_HIGH_MPH = 20.0


def canon_nfl_abbr(raw: object) -> str:
    s = str(raw or "").strip().upper()
    if not s or s in {"NAN", "NONE", "NAT", "<NA>"}:
        return ""
    if "/" in s:
        return ""
    return NFL_TEAM_ALIASES.get(s, s)


def _get_json(url: str, *, params: dict | None = None, timeout: float = 25.0) -> dict:
    last_exc: Exception | None = None
    try:
        from curl_cffi.requests import Session as CurlSession

        s = CurlSession(impersonate="chrome131")
        r = s.get(url, params=params or {}, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        last_exc = exc
    r = requests.get(url, headers=HEADERS, params=params or {}, timeout=timeout)
    try:
        r.raise_for_status()
    except Exception:
        if last_exc:
            raise last_exc
        raise
    data = r.json()
    return data if isinstance(data, dict) else {}


def iso_to_et_date(iso: str) -> str:
    s = str(iso or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return s[:10] if len(s) >= 10 else ""


def parse_espn_nfl_events(scoreboard: dict) -> list[dict[str, Any]]:
    """Flatten ESPN scoreboard events into home/away/venue/weather rows."""
    out: list[dict[str, Any]] = []
    for ev in scoreboard.get("events") or []:
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get("id") or "").strip()
        comps = ev.get("competitions") or []
        if not comps or not isinstance(comps[0], dict):
            continue
        comp = comps[0]
        home = away = ""
        for c in comp.get("competitors") or []:
            if not isinstance(c, dict):
                continue
            abbr = canon_nfl_abbr((c.get("team") or {}).get("abbreviation"))
            if not abbr:
                continue
            if str(c.get("homeAway") or "").lower() == "home":
                home = abbr
            else:
                away = abbr
        if not home or not away:
            continue
        venue = comp.get("venue") or {}
        indoor = bool(venue.get("indoor"))
        addr = venue.get("address") or {}
        wx = comp.get("weather") or {}
        wind_raw = wx.get("gust") or wx.get("windSpeed") or wx.get("wind")
        try:
            wind_espn = float(wind_raw) if wind_raw not in (None, "") else None
        except (TypeError, ValueError):
            wind_espn = None
        try:
            temp_espn = float(wx.get("temperature")) if wx.get("temperature") not in (None, "") else None
        except (TypeError, ValueError):
            temp_espn = None
        out.append(
            {
                "event_id": eid,
                "home": home,
                "away": away,
                "kickoff": str(comp.get("date") or ev.get("date") or ""),
                "indoor": indoor,
                "venue_name": str(venue.get("fullName") or venue.get("name") or ""),
                "lat": venue.get("latitude") or addr.get("latitude"),
                "lon": venue.get("longitude") or addr.get("longitude"),
                "condition": str(wx.get("displayValue") or wx.get("conditionId") or ""),
                "temp_f_espn": temp_espn,
                "wind_mph_espn": wind_espn,
            }
        )
    return out


def fetch_espn_nfl_scoreboard(date_iso: str) -> list[dict[str, Any]]:
    ds = str(date_iso or "").strip()[:10].replace("-", "")
    if len(ds) != 8:
        return []
    try:
        payload = _get_json(NFL_SCOREBOARD, params={"dates": ds, "limit": "100"})
    except Exception as exc:
        print(f"[NFL espn] scoreboard {ds} failed: {exc}")
        return []
    return parse_espn_nfl_events(payload)


def espn_nfl_opp_map_for_dates(dates: list[str]) -> dict[str, str]:
    """team abbr -> opponent abbr from ESPN scoreboards (both directions)."""
    pair: dict[str, str] = {}
    seen: set[str] = set()
    for d in dates:
        key = str(d or "").strip()[:10]
        if not key or key in seen:
            continue
        seen.add(key)
        for ev in fetch_espn_nfl_scoreboard(key):
            h, a = ev["home"], ev["away"]
            pair[h] = a
            pair[a] = h
        time.sleep(0.08)
    return pair


def weather_flag(*, indoor: bool, wind_mph: float | None, precip_mm: float | None, condition: str = "") -> str:
    if indoor:
        return "dome"
    cond = str(condition or "").strip().lower()
    if precip_mm is not None and precip_mm >= 0.5:
        return "precip"
    if any(w in cond for w in ("rain", "snow", "storm", "shower")):
        return "precip"
    if wind_mph is None:
        return "unknown"
    if wind_mph >= WIND_HIGH_MPH:
        return "high_wind"
    if wind_mph >= WIND_PASS_MPH:
        return "wind"
    return "calm"


def _open_meteo_hour(lat: float, lon: float, kickoff_iso: str) -> dict[str, float | None]:
    try:
        dt = datetime.fromisoformat(str(kickoff_iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return {"temp_f": None, "wind_mph": None, "precip_mm": None}
    hour = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation,wind_speed_10m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
        "timezone": "UTC",
        "start_hour": hour,
        "end_hour": hour,
    }
    try:
        data = _get_json(OPEN_METEO, params=params, timeout=20.0)
    except Exception as exc:
        print(f"[NFL espn] Open-Meteo failed: {exc}")
        return {"temp_f": None, "wind_mph": None, "precip_mm": None}
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if hour not in times:
        idx = 0
    else:
        idx = times.index(hour)

    def _at(key: str) -> float | None:
        vals = hourly.get(key) or []
        if idx >= len(vals) or vals[idx] is None:
            return None
        try:
            return float(vals[idx])
        except (TypeError, ValueError):
            return None

    return {"temp_f": _at("temperature_2m"), "wind_mph": _at("wind_speed_10m"), "precip_mm": _at("precipitation")}


def attach_weather_details(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill wind/temp from Open-Meteo when the stadium is outdoor."""
    out = []
    for ev in events:
        rec = dict(ev)
        indoor = bool(rec.get("indoor"))
        wind = rec.get("wind_mph_espn")
        temp = rec.get("temp_f_espn")
        precip = None
        if not indoor:
            try:
                lat = float(rec.get("lat"))
                lon = float(rec.get("lon"))
            except (TypeError, ValueError):
                lat = lon = None
            if lat is not None and lon is not None and rec.get("kickoff"):
                om = _open_meteo_hour(lat, lon, str(rec["kickoff"]))
                wind = om.get("wind_mph") if om.get("wind_mph") is not None else wind
                temp = om.get("temp_f") if om.get("temp_f") is not None else temp
                precip = om.get("precip_mm")
                time.sleep(0.05)
        rec["wind_mph"] = wind
        rec["temp_f"] = temp
        rec["precip_mm"] = precip
        rec["weather_flag"] = weather_flag(
            indoor=indoor,
            wind_mph=float(wind) if wind is not None else None,
            precip_mm=float(precip) if precip is not None else None,
            condition=str(rec.get("condition") or ""),
        )
        out.append(rec)
    return out


def weather_lookup_by_team(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """team abbr -> weather/script row (home and away both keyed)."""
    lookup: dict[str, dict[str, Any]] = {}
    for ev in events:
        for team, opp, is_home in (
            (ev["home"], ev["away"], True),
            (ev["away"], ev["home"], False),
        ):
            lookup[team] = {**ev, "team": team, "opp": opp, "is_home": is_home}
    return lookup


def pace_tier(game_total: object) -> str:
    try:
        gt = float(game_total)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if gt != gt:
        return "UNKNOWN"
    if gt >= HIGH_TOTAL_THRESH:
        return "HIGH"
    if gt >= LOW_TOTAL_THRESH:
        return "NORMAL"
    return "LOW"


def game_context_score(
    *,
    axis: str,
    wind_mph: float | None,
    weather_flag_val: str,
    blowout: bool,
    low_total: bool,
    spread: float | None,
) -> float:
    """Small signed adjustment: negative = harder for overs / volume."""
    score = 0.0
    wf = str(weather_flag_val or "").lower()
    if axis in {"pass", "rec"}:
        if wind_mph is not None and wind_mph >= WIND_HIGH_MPH:
            score -= 0.12
        elif wind_mph is not None and wind_mph >= WIND_PASS_MPH:
            score -= 0.08
        elif wf in {"wind", "high_wind"}:
            score -= 0.08
        if wf == "precip":
            score -= 0.05
        if blowout:
            score -= 0.05
        if low_total:
            score -= 0.05
    elif axis == "rush":
        if blowout and spread is not None and spread <= -BLOWOUT_THRESHOLD:
            score += 0.03
        elif blowout:
            score -= 0.04
        if wf == "precip":
            score += 0.02
    elif axis == "kick":
        if wf in {"wind", "high_wind", "precip"}:
            score -= 0.08
    return round(score, 3)


def fetch_nfl_injuries() -> list[dict[str, Any]]:
    try:
        payload = _get_json(NFL_INJURIES, timeout=28.0)
    except Exception as exc:
        print(f"[NFL espn] injuries feed failed: {exc}")
        return []
    rows: list[dict[str, Any]] = []
    for block in payload.get("injuries") or []:
        if not isinstance(block, dict):
            continue
        display = str(block.get("displayName") or "").strip().lower()
        team_obj = block.get("team") or {}
        abbr = canon_nfl_abbr(team_obj.get("abbreviation")) or NFL_TEAM_DISPLAY_TO_ABBR.get(display, "")
        if not abbr:
            continue
        for inj in block.get("injuries") or []:
            if not isinstance(inj, dict):
                continue
            ath = inj.get("athlete") or {}
            name = str(ath.get("displayName") or ath.get("fullName") or "").strip()
            if not name:
                continue
            typ = inj.get("type") or {}
            status = str(inj.get("status") or "").strip()
            type_ab = str(typ.get("abbreviation") or "").strip().upper()
            if status.upper() in {"ACTIVE", "A"} or type_ab in {"A", "ACTIVE"}:
                continue
            rows.append(
                {
                    "team": abbr,
                    "player": name,
                    "injury_status": status,
                    "injury_type": str(typ.get("abbreviation") or "").strip(),
                    "injury_type_desc": str(typ.get("description") or "").strip(),
                    "injury_detail": str(inj.get("shortComment") or "").strip(),
                    "espn_athlete_id": str(ath.get("id") or "").strip(),
                }
            )
    return rows


def fetch_nfl_team_list() -> list[dict[str, str]]:
    try:
        payload = _get_json(NFL_TEAMS, params={"limit": "50"})
    except Exception as exc:
        print(f"[NFL espn] teams list failed: {exc}")
        return []
    out: list[dict[str, str]] = []
    for ent in (payload.get("sports") or [{}])[0].get("leagues", [{}])[0].get("teams", []) or []:
        t = (ent or {}).get("team") or {}
        tid = str(t.get("id") or "").strip()
        abbr = canon_nfl_abbr(t.get("abbreviation"))
        if tid and abbr:
            out.append({"team_id": tid, "team_abbr": abbr, "name": str(t.get("displayName") or "")})
    return out


def _depth_slot(pos: str, rank: int) -> str:
    p = str(pos or "").strip().upper()
    if not p:
        p = "UNK"
    return f"{p}{int(rank)}" if rank > 0 else p


def expected_snaps_from_slot(slot: str) -> str:
    s = str(slot or "").strip().upper()
    if s in {"QB1", "RB1", "WR1", "WR2", "TE1", "FB1", "K1", "PK1"}:
        return "starter"
    if s in {"QB2", "RB2", "WR3", "TE2"}:
        return "rotation"
    if s:
        return "reserve"
    return ""


def parse_depth_chart_payload(payload: dict, team_abbr: str) -> list[dict[str, Any]]:
    """Parse ESPN site v2 depthcharts (`depthchart` list, positions dict)."""
    import re

    rows: list[dict[str, Any]] = []
    items = payload.get("depthchart") or payload.get("items") or payload.get("depthcharts") or []
    if isinstance(payload.get("athletes"), list) and not items:
        items = [payload]
    for chart in items:
        if not isinstance(chart, dict):
            continue
        positions = chart.get("positions") or {}
        if isinstance(positions, dict):
            pos_items = list(positions.items())
        elif isinstance(positions, list):
            pos_items = [(str(p.get("abbreviation") or ""), p) for p in positions if isinstance(p, dict)]
        else:
            continue
        for pos_key, pos in pos_items:
            if not isinstance(pos, dict):
                continue
            meta = pos.get("position") if isinstance(pos.get("position"), dict) else {}
            pos_ab = str(meta.get("abbreviation") or pos.get("abbreviation") or pos_key or "").strip().upper()
            m = re.match(r"^([A-Z]+)(\d+)$", str(pos_key or "").strip().upper())
            key_rank = int(m.group(2)) if m else 0
            if m and not meta:
                pos_ab = m.group(1)
            athletes = pos.get("athletes") or []
            for i, ath in enumerate(athletes):
                if not isinstance(ath, dict):
                    continue
                inner = ath.get("athlete") if isinstance(ath.get("athlete"), dict) else ath
                name = str(
                    inner.get("displayName")
                    or inner.get("fullName")
                    or inner.get("name")
                    or ""
                ).strip()
                try:
                    rank = int(ath.get("rank") or inner.get("rank") or 0)
                except (TypeError, ValueError):
                    rank = 0
                if rank <= 0:
                    rank = key_rank or (i + 1)
                if not name:
                    continue
                slot = _depth_slot(pos_ab, rank)
                rows.append(
                    {
                        "team": team_abbr,
                        "player": name,
                        "espn_athlete_id": str(inner.get("id") or ath.get("id") or "").strip(),
                        "position": pos_ab,
                        "depth_rank": rank,
                        "depth_slot": slot,
                        "expected_snaps": expected_snaps_from_slot(slot),
                        "chart": str(chart.get("name") or ""),
                    }
                )
    return rows


def fetch_team_depth_chart(team_id: str, team_abbr: str) -> list[dict[str, Any]]:
    try:
        payload = _get_json(NFL_DEPTH.format(team_id=team_id), timeout=25.0)
    except Exception as exc:
        print(f"[NFL espn] depth chart {team_abbr} failed: {exc}")
        return []
    return parse_depth_chart_payload(payload, team_abbr)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
