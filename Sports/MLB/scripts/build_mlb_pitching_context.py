#!/usr/bin/env python3
"""
build_mlb_pitching_context.py

Fetch MLB pitching staff (rotation depth, closer, handedness) and probable-starter
schedule from statsapi.mlb.com.

Outputs:
  Sports/MLB/data/mlb_pitching_staff.json
  Sports/MLB/data/mlb_rotation_schedule.json
  Sports/MLB/data/mlb_pitching_staff_summary.csv

Run (from Sports/MLB):
  py -3.14 scripts/build_mlb_pitching_context.py
  py -3.14 scripts/build_mlb_pitching_context.py --date 2026-07-05 --rotation-days 14
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_REPO = Path(__file__).resolve().parents[3]
_MLB = Path(__file__).resolve().parents[1]
_DATA = _MLB / "data"

STATS_API = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
SLEEP_S = 0.25
CACHE_HOURS = 6

# PrizePicks / step4b aliases (slate -> API lookup key)
PP_TO_API = {"AZ": "ARI", "OAK": "ATH", "WSN": "WSH", "WAS": "WSH", "SDP": "SD", "SFG": "SF"}
API_TO_PP = {v: k for k, v in PP_TO_API.items()}


def fetch_json(url: str, retries: int = 3) -> dict[str, Any]:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            if attempt < retries - 1:
                time.sleep(1.5**attempt)
    return {}


def _num(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if isinstance(x, float) and math.isnan(x):
            return None
        return float(x)
    s = str(x).strip()
    if not s or s.lower() in ("nan", "none", "-", ".-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _api_abbr(abbr: str) -> str:
    s = str(abbr or "").strip().upper()
    return PP_TO_API.get(s, s)


def _pp_abbr(abbr: str) -> str:
    s = str(abbr or "").strip().upper()
    return API_TO_PP.get(s, s)


def _cache_fresh(path: Path, hours: float = CACHE_HOURS) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = data.get("fetched_at")
        if not ts:
            return False
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt < timedelta(hours=hours)
    except Exception:
        return False


def _pitcher_record(person: dict) -> dict[str, Any]:
    hand = str((person.get("pitchHand") or {}).get("code") or "").upper()[:1]
    st: dict[str, Any] = {}
    for blk in person.get("stats") or []:
        for sp in blk.get("splits") or []:
            st = sp.get("stat") or {}
    gs = int(_num(st.get("gamesStarted")) or 0)
    sv = int(_num(st.get("saves")) or 0)
    return {
        "id": person.get("id"),
        "name": str(person.get("fullName") or "").strip(),
        "hand": hand if hand in ("L", "R", "S") else "",
        "era": _num(st.get("era")),
        "whip": _num(st.get("whip")),
        "games_started": gs,
        "saves": sv,
        "innings_pitched": _num(st.get("inningsPitched")),
        "strikeouts": int(_num(st.get("strikeOuts")) or 0),
    }


def fetch_team_ids() -> dict[int, str]:
    data = fetch_json(f"{STATS_API}/teams?sportId=1")
    out: dict[int, str] = {}
    for t in (data or {}).get("teams") or []:
        tid = t.get("id")
        ab = str(t.get("abbreviation") or "").strip().upper()
        if tid is not None and ab:
            out[int(tid)] = ab
    return out


def build_staff(season: int) -> dict[str, Any]:
    team_ids = fetch_team_ids()
    teams: dict[str, Any] = {}
    print(f"📡 Fetching pitching staff for {len(team_ids)} teams (season={season})...")

    hydrate = "person(pitchHand,stats(group=[pitching],type=[season],season=%d))" % season
    for tid, api_abbr in sorted(team_ids.items(), key=lambda x: x[1]):
        time.sleep(SLEEP_S)
        url = f"{STATS_API}/teams/{tid}/roster?rosterType=active&season={season}&hydrate={hydrate}"
        data = fetch_json(url)
        pitchers = [
            _pitcher_record(p["person"])
            for p in (data or {}).get("roster") or []
            if (p.get("position") or {}).get("abbreviation") == "P"
        ]
        pitchers = [p for p in pitchers if p.get("name")]
        rotation = sorted(
            [p for p in pitchers if (p.get("games_started") or 0) > 0],
            key=lambda p: (-(p.get("games_started") or 0), p.get("era") or 99),
        )[:5]
        relievers = [p for p in pitchers if (p.get("games_started") or 0) == 0]
        closer = max(pitchers, key=lambda p: (p.get("saves") or 0), default=None)
        if closer and (closer.get("saves") or 0) == 0:
            closer = None
        lhp = sum(1 for p in pitchers if p.get("hand") == "L")
        rhp = sum(1 for p in pitchers if p.get("hand") == "R")
        pp_key = api_abbr
        teams[pp_key] = {
            "api_abbrev": api_abbr,
            "closer": closer,
            "rotation": rotation,
            "reliever_count": len(relievers),
            "staff_lhp": lhp,
            "staff_rhp": rhp,
            "staff_total": len(pitchers),
        }

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "teams": teams,
    }


def build_rotation(season: int, start: str, days: int) -> dict[str, Any]:
    end_dt = datetime.strptime(start, "%Y-%m-%d").date() + timedelta(days=max(days - 1, 0))
    end = end_dt.isoformat()
    url = (
        f"{STATS_API}/schedule?sportId=1&startDate={start}&endDate={end}"
        f"&hydrate=probablePitcher(team),team"
    )
    print(f"📡 Fetching probable starters {start} → {end}...")
    time.sleep(SLEEP_S)
    data = fetch_json(url)
    by_team: dict[str, list[dict[str, Any]]] = {}
    by_date: dict[str, dict[str, Any]] = {}

    for day in (data or {}).get("dates") or []:
        gdate = str(day.get("date", ""))[:10]
        by_date.setdefault(gdate, {})
        for g in day.get("games") or []:
            for side in ("home", "away"):
                block = g.get("teams", {}).get(side) or {}
                team_obj = block.get("team") or {}
                api_abbr = str(team_obj.get("abbreviation") or "").strip().upper()
                if not api_abbr:
                    continue
                pp_key = api_abbr
                opp_side = "away" if side == "home" else "home"
                opp_abbr = str(
                    (((g.get("teams") or {}).get(opp_side) or {}).get("team") or {}).get(
                        "abbreviation", ""
                    )
                ).strip().upper()
                pp = block.get("probablePitcher") or {}
                hand = str((pp.get("pitchHand") or {}).get("code") or "").upper()[:1]
                entry = {
                    "date": gdate,
                    "game_pk": g.get("gamePk"),
                    "is_home": side == "home",
                    "opponent": str(opp_abbr).strip().upper(),
                    "starter_id": pp.get("id"),
                    "starter_name": str(pp.get("fullName") or "").strip(),
                    "starter_hand": hand if hand in ("L", "R", "S") else "",
                }
                by_team.setdefault(pp_key, []).append(entry)
                if entry["starter_name"]:
                    by_date[gdate][pp_key] = entry

    for entries in by_team.values():
        entries.sort(key=lambda e: e.get("date") or "")

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "start_date": start,
        "end_date": end,
        "by_team": by_team,
        "by_date": by_date,
    }


def staff_summary_rows(staff: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for team, block in sorted((staff.get("teams") or {}).items()):
        closer = block.get("closer") or {}
        rot = block.get("rotation") or []
        row: dict[str, Any] = {
            "TEAM_ABBREVIATION": team,
            "closer_name": closer.get("name", ""),
            "closer_hand": closer.get("hand", ""),
            "closer_era": closer.get("era"),
            "closer_saves": closer.get("saves"),
            "staff_lhp": block.get("staff_lhp"),
            "staff_rhp": block.get("staff_rhp"),
        }
        for i, sp in enumerate(rot[:5], start=1):
            row[f"sp{i}_name"] = sp.get("name", "")
            row[f"sp{i}_hand"] = sp.get("hand", "")
            row[f"sp{i}_era"] = sp.get("era")
            row[f"sp{i}_gs"] = sp.get("games_started")
        rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--date", default=None, help="Rotation window start (YYYY-MM-DD)")
    ap.add_argument("--rotation-days", type=int, default=14)
    ap.add_argument("--force", action="store_true", help="Ignore cache freshness")
    ap.add_argument("--staff-out", default=str(_DATA / "mlb_pitching_staff.json"))
    ap.add_argument("--rotation-out", default=str(_DATA / "mlb_rotation_schedule.json"))
    ap.add_argument("--summary-out", default=str(_DATA / "mlb_pitching_staff_summary.csv"))
    args = ap.parse_args()

    season = args.season or date.today().year
    start = args.date or date.today().isoformat()
    staff_path = Path(args.staff_out)
    rot_path = Path(args.rotation_out)
    summary_path = Path(args.summary_out)

    staff_path.parent.mkdir(parents=True, exist_ok=True)

    if args.force or not _cache_fresh(staff_path):
        staff = build_staff(season)
        staff_path.write_text(json.dumps(staff, indent=2), encoding="utf-8")
        print(f"✅ Staff → {staff_path}")
    else:
        staff = json.loads(staff_path.read_text(encoding="utf-8"))
        print(f"↺ Staff cache fresh → {staff_path}")

    if args.force or not _cache_fresh(rot_path):
        rotation = build_rotation(season, start, args.rotation_days)
        rot_path.write_text(json.dumps(rotation, indent=2), encoding="utf-8")
        print(f"✅ Rotation → {rot_path}")
    else:
        rotation = json.loads(rot_path.read_text(encoding="utf-8"))
        print(f"↺ Rotation cache fresh → {rot_path}")

    rows = staff_summary_rows(staff)
    pd.DataFrame(rows).to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"✅ Summary → {summary_path} ({len(rows)} teams)")

    n_probable = sum(
        1
        for day in (rotation.get("by_date") or {}).values()
        for _ in day.values()
    )
    print(f"   Probable starters in window: {n_probable}")


if __name__ == "__main__":
    main()
