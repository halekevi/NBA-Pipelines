"""
Shared Tennis helpers: ESPN rankings, scoreboard parsing, name keys, prop norms.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json"}

URL_ATP_RANK = "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/rankings"
URL_WTA_RANK = "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/rankings"
URL_ATP_BOARD = "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard"
URL_WTA_BOARD = "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"


def athlete_statistics_url(tour: str, athlete_id: str) -> str:
    t = "atp" if str(tour).upper() == "ATP" else "wta"
    return f"https://site.api.espn.com/apis/site/v2/sports/tennis/{t}/athletes/{athlete_id}/statistics"


def fetch_athlete_statistics(tour: str, athlete_id: str) -> dict[str, Any]:
    if not str(athlete_id).strip():
        return {}
    try:
        return fetch_json(athlete_statistics_url(tour, athlete_id))
    except Exception:
        return {}


def _flatten_espn_stat_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for split in payload.get("splits") or []:
        for cat in split.get("categories") or []:
            for st in cat.get("stats") or []:
                if isinstance(st, dict):
                    out.append(st)
    return out


def parse_tennis_season_stats(payload: dict[str, Any]) -> dict[str, float | None]:
    """
    Best-effort parse of ESPN tennis athlete statistics JSON.
    Returns floats or None when missing.
    """
    stats = _flatten_espn_stat_dicts(payload)
    if not stats and isinstance(payload.get("statistics"), list):
        stats = [x for x in payload["statistics"] if isinstance(x, dict)]

    def find_val(*needles: str) -> float | None:
        for st in stats:
            raw = str(st.get("name") or st.get("displayName") or st.get("abbreviation") or "").lower()
            raw = re.sub(r"[^a-z0-9]+", "", raw)
            for nd in needles:
                n2 = re.sub(r"[^a-z0-9]+", "", nd.lower())
                if n2 and n2 in raw:
                    try:
                        return float(st.get("value"))
                    except (TypeError, ValueError):
                        return None
        return None

    return {
        "aces_per_match": find_val("aces", "acepermatch", "avgaces"),
        "double_faults_per_match": find_val("doublefault", "doublefaults", "df"),
        "first_serve_pct": find_val("firstserve", "1stsrvpct", "firstservepercent"),
        "games_won_per_match": find_val("games", "gameswon"),
        "sets_won_per_match": find_val("sets", "setswon"),
        "win_pct": find_val("wins", "winpercent", "matchwin"),
    }


def norm_key(s: str) -> str:
    if not s or (isinstance(s, float) and str(s) == "nan"):
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t.lower().strip())
    t = re.sub(r"[^a-z0-9 ]+", "", t)
    return t


def norm_key_candidates(s: str) -> list[str]:
    """Primary key plus given/family flip (ESPN often uses Family Given)."""
    k = norm_key(s)
    if not k:
        return []
    out = [k]
    parts = k.split()
    if len(parts) >= 2:
        flipped = parts[-1] + " " + " ".join(parts[:-1])
        if flipped not in out:
            out.append(flipped)
    return out


# Alias for Sackmann / step4 history (same normalization as ESPN rankings).
_norm_key = norm_key

_TENNIS_ROOT = Path(__file__).resolve().parent.parent
_SACKMANN_DIR = _TENNIS_ROOT / "data" / "sackmann"
_SACKMANN_MAX_AGE_DAYS = 1.0
# Player L5 is stale if newest Sackmann match is older than this vs the slate date.
SACKMANN_PLAYER_STALE_DAYS = 14
_SACKMANN_SET_RE = re.compile(r"(\d+)\s*-\s*(\d+)(?:\(\d+\))?")
_ROUND_ORDER = {
    "F": 8,
    "BR": 7,
    "SF": 6,
    "QF": 5,
    "R16": 4,
    "R32": 3,
    "R64": 2,
    "R128": 1,
    "RR": 3,
    "Q3": 0,
    "Q2": 0,
    "Q1": 0,
}

_SACKMANN_PROP_MAP: dict[str, tuple[str, ...]] = {
    "aces": ("aces",),
    "double_faults": ("double_faults",),
    "games_won": ("games_won",),
    "sets_won": ("sets_won",),
    "match_total_games": ("match_total_games",),
    # Match-level markets (same value on both player rows for a given match).
    "total_sets": ("total_sets",),
    "total_tie_breaks": ("total_tie_breaks",),
    "break_points_won": ("break_points_won",),
}


def fetch_json(url: str, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def parse_rankings_payload(data: dict[str, Any], tour: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in data.get("rankings") or []:
        for row in block.get("ranks") or []:
            ath = row.get("athlete") or {}
            aid = str(ath.get("id") or "").strip()
            name = str(ath.get("displayName") or ath.get("fullName") or "").strip()
            if not aid or not name:
                continue
            out.append(
                {
                    "espn_athlete_id": aid,
                    "player": name,
                    "tour": tour.upper(),
                    "rank": int(row.get("current") or 999),
                    "points": float(row.get("points") or 0.0),
                    "player_key": norm_key(name),
                }
            )
    return out


def load_or_refresh_rankings(cache_path: Path, *, max_age_hours: int = 8) -> list[dict[str, Any]]:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.is_file():
        try:
            age = datetime.now(timezone.utc).timestamp() - cache_path.stat().st_mtime
            if age < max_age_hours * 3600:
                return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    rows: list[dict[str, Any]] = []
    try:
        rows.extend(parse_rankings_payload(fetch_json(URL_ATP_RANK), "ATP"))
    except Exception:
        pass
    try:
        rows.extend(parse_rankings_payload(fetch_json(URL_WTA_RANK), "WTA"))
    except Exception:
        pass
    cache_path.write_text(json.dumps(rows, indent=0), encoding="utf-8")
    return rows


def _games_from_linescores(comp: dict[str, Any]) -> float:
    ls = comp.get("linescores") or []
    return float(sum(float(x.get("value") or 0) for x in ls))


def _stat_from_competitor(comp: dict[str, Any], *needles: str) -> float | None:
    for st in comp.get("statistics") or []:
        name = str(st.get("name") or st.get("displayName") or st.get("abbreviation") or "").lower()
        name = re.sub(r"[^a-z0-9]+", "", name)
        for nd in needles:
            n2 = re.sub(r"[^a-z0-9]+", "", nd.lower())
            if n2 and n2 in name:
                try:
                    return float(st.get("value"))
                except (TypeError, ValueError):
                    return None
    return None


def _sets_won_from_linescores(comp: dict[str, Any], other: dict[str, Any] | None) -> float:
    ls = comp.get("linescores") or []
    if not ls or not other:
        return 0.0
    ols = other.get("linescores") or []
    won = 0
    for i, cur in enumerate(ls):
        try:
            gv = float(cur.get("value") or 0)
            ov = float(ols[i].get("value") or 0) if i < len(ols) else 0.0
            if gv > ov:
                won += 1
        except (TypeError, ValueError, IndexError):
            continue
    return float(won)


def _tiebreaks_from_linescores(comp: dict[str, Any], other: dict[str, Any] | None) -> float:
    """Count completed sets that finished 7-6 / 6-7 (standard set tiebreak)."""
    ls = comp.get("linescores") or []
    ols = (other or {}).get("linescores") or []
    n = 0
    for i, cur in enumerate(ls):
        try:
            gv = int(float(cur.get("value") or 0))
            ov = int(float(ols[i].get("value") or 0)) if i < len(ols) else 0
        except (TypeError, ValueError, IndexError):
            continue
        if (gv == 7 and ov == 6) or (gv == 6 and ov == 7):
            n += 1
    return float(n)


def _comp_status_final(comp: dict[str, Any]) -> bool:
    st = (comp.get("status") or {}).get("type") or {}
    return str(st.get("name") or "").upper() == "STATUS_FINAL"


def iter_scoreboard_matches(tour: str, date_ymd: str | None = None) -> Iterator[dict[str, Any]]:
    url = URL_ATP_BOARD if tour.upper() == "ATP" else URL_WTA_BOARD
    ymd = str(date_ymd or "").strip().replace("-", "")
    if len(ymd) == 8 and ymd.isdigit():
        url = f"{url}?dates={ymd}"
    try:
        data = fetch_json(url)
    except Exception:
        return
    for ev in data.get("events") or []:
        for grp in ev.get("groupings") or []:
            for comp in grp.get("competitions") or []:
                if not _comp_status_final(comp):
                    continue
                comps = comp.get("competitors") or []
                if len(comps) < 2:
                    continue
                dt = str(comp.get("date") or comp.get("startDate") or "")[:19]
                match_total = sum(_games_from_linescores(c) for c in comps)
                for i, c in enumerate(comps):
                    ath = c.get("athlete") or {}
                    aid = str(ath.get("id") or c.get("id") or "").strip()
                    nm = str(ath.get("displayName") or "").strip()
                    if not aid or not nm:
                        continue
                    other_c = comps[1 - i] if len(comps) == 2 else None
                    gw = _games_from_linescores(c)
                    aces = _stat_from_competitor(c, "aces", "ace")
                    dbl = _stat_from_competitor(c, "doublefault", "doublefaults", "double faults")
                    sw = _sets_won_from_linescores(c, other_c)
                    opp_sw = _sets_won_from_linescores(other_c, c) if other_c is not None else 0.0
                    total_sets = float(sw + opp_sw) if (sw or opp_sw) else float(
                        max(len(c.get("linescores") or []), len((other_c or {}).get("linescores") or []))
                    )
                    tb = _tiebreaks_from_linescores(c, other_c)
                    bp = _stat_from_competitor(
                        c,
                        "breakpoints won",
                        "break pointswon",
                        "breakpointsWon",
                        "bp won",
                        "breakswon",
                    )
                    opp = ""
                    if other_c is not None:
                        a2 = other_c.get("athlete") or {}
                        opp = str(a2.get("displayName") or "").strip()
                    yield {
                        "espn_athlete_id": aid,
                        "player": nm,
                        "player_key": norm_key(nm),
                        "tour": tour.upper(),
                        "match_date_utc": dt,
                        "games_won": gw,
                        "match_total_games": float(match_total),
                        "opponent": opp,
                        "aces": float(aces) if aces is not None else None,
                        "double_faults": float(dbl) if dbl is not None else None,
                        "sets_won": float(sw),
                        "total_sets": float(total_sets),
                        "total_tie_breaks": float(tb),
                        "break_points_won": float(bp) if bp is not None else None,
                    }


def build_player_stats_index(
    target: str,
    *,
    days_back: int = 2,
    days_forward: int = 1,
) -> dict[str, dict[str, Any]]:
    """
    Map normalized player_key -> match stat dict for ESPN scoreboard finals
    on ``target`` ± day window (used by fetch_tennis_actuals / grader helpers).
    """
    from datetime import date as _date, timedelta as _td

    anchor = _date.fromisoformat(str(target).strip()[:10])
    valid_dates = {
        (anchor + _td(days=offset)).isoformat()
        for offset in range(-max(0, int(days_back)), max(0, int(days_forward)) + 1)
    }
    by_player: dict[str, dict[str, Any]] = {}
    for tour in ("ATP", "WTA"):
        for m in iter_scoreboard_matches(tour):
            dt = str(m.get("match_date_utc") or "")[:10]
            if dt not in valid_dates:
                continue
            pk = norm_key(str(m.get("player") or ""))
            if not pk:
                continue
            prev = by_player.get(pk)
            if prev and str(prev.get("match_date_utc") or "")[:10] >= dt:
                continue
            by_player[pk] = {
                "player": str(m.get("player") or pk),
                "match_date_utc": dt,
                "games_won": float(m.get("games_won") or 0),
                "match_total_games": float(m.get("match_total_games") or 0),
                "aces": float(m.get("aces") or 0),
                "double_faults": float(m.get("double_faults") or 0),
                "sets_won": float(m.get("sets_won") or 0),
                "total_sets": float(m.get("total_sets") or 0),
                "total_tie_breaks": float(m.get("total_tie_breaks") or 0),
                "break_points_won": (
                    float(m["break_points_won"])
                    if m.get("break_points_won") is not None
                    else None
                ),
            }
    return by_player


def refresh_match_games_cache(
    cache_path: Path,
    tours: tuple[str, ...] = ("ATP", "WTA"),
    *,
    days_back: int = 80,
) -> dict[str, list[dict[str, Any]]]:
    """Map espn_athlete_id -> list of recent match dicts (newest first).

    Walks dated ESPN scoreboards so L5 is not limited to today's board.
    """
    by_id: dict[str, list[dict[str, Any]]] = load_match_games_cache(cache_path)
    seen: set[tuple[str, str]] = set()
    for aid, rows in by_id.items():
        for m in rows:
            seen.add((str(aid), str(m.get("match_date_utc") or "")))
    today = date.today()
    n_days = max(1, int(days_back))
    for offset in range(n_days + 1):
        ymd = (today - timedelta(days=offset)).strftime("%Y%m%d")
        for tour in tours:
            try:
                matches = list(iter_scoreboard_matches(tour, ymd))
            except Exception:
                continue
            for m in matches:
                aid = str(m.get("espn_athlete_id") or "")
                key = (aid, str(m.get("match_date_utc") or ""))
                if not aid or key in seen:
                    continue
                seen.add(key)
                by_id.setdefault(aid, []).append(m)
        if offset and offset % 15 == 0:
            print(f"  [ESPN tennis] scoreboard walk {offset}/{n_days} days")
    for aid in by_id:
        by_id[aid].sort(key=lambda x: str(x.get("match_date_utc") or ""), reverse=True)
        by_id[aid] = by_id[aid][:24]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(by_id, indent=0), encoding="utf-8")
    return by_id


def load_match_games_cache(cache_path: Path) -> dict[str, list[dict[str, Any]]]:
    if not cache_path.is_file():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_athlete_id(player_name: str, rankings: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (espn_id, tour) or ('','')."""
    pk = norm_key(player_name)
    if not pk:
        return "", ""
    best = ""
    best_tour = ""
    best_len = -1
    for r in rankings:
        rk = r.get("player_key") or ""
        if not rk:
            continue
        if pk == rk:
            return str(r["espn_athlete_id"]), str(r.get("tour") or "")
        if pk in rk or rk in pk:
            ln = len(rk)
            if ln > best_len:
                best_len = ln
                best = str(r["espn_athlete_id"])
                best_tour = str(r.get("tour") or "")
    return best, best_tour


def resolve_opp_rank(opp_name: str, rankings: list[dict[str, Any]]) -> float | None:
    """ATP/WTA rank for a named opponent. Unknown names return None (not a fake 75)."""
    if not str(opp_name or "").strip() or str(opp_name).upper() in ("UNKNOWN_OPP", "UNK"):
        return None
    pk = norm_key(opp_name)
    for r in rankings:
        if r.get("player_key") == pk:
            try:
                return float(r.get("rank"))
            except (TypeError, ValueError):
                return None
    best: float | None = None
    for r in rankings:
        rk = r.get("player_key") or ""
        if pk and rk and (pk in rk or rk in pk):
            try:
                v = float(r.get("rank"))
            except (TypeError, ValueError):
                continue
            best = v if best is None else min(best, v)
    return best


def fill_opponent_rank_from_slate_players(df: pd.DataFrame) -> pd.DataFrame:
    """Fill opponent_rank from the opponent's player_atp_rank on this slate.

    Pipeline placeholder 75 is treated as missing. Named UNKNOWN_OPP stays empty.
    """
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()

    def _rk(v):
        try:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            n = int(float(v))
            if n <= 0 or n >= 900:
                return None
            return n
        except Exception:
            return None

    def _name(v) -> str:
        s = str(v or "").strip().upper()
        return "" if s in ("", "NAN", "NONE", "NULL", "UNKNOWN_OPP", "UNK") else s

    name_rank: dict[str, int] = {}
    if "player" in out.columns and "player_atp_rank" in out.columns:
        for _, r in out.iterrows():
            n = _name(r.get("player"))
            rk = _rk(r.get("player_atp_rank"))
            if n and rk:
                name_rank[n] = rk
    ocol = "opp_team" if "opp_team" in out.columns else ("opp" if "opp" in out.columns else None)
    filled = []
    for _, r in out.iterrows():
        opp = _name(r.get(ocol) if ocol else "")
        rk = name_rank.get(opp)
        if rk is None and opp:
            for n, v in name_rank.items():
                if opp in n or n in opp:
                    rk = v
                    break
        existing = _rk(r.get("opponent_rank"))
        if existing == 75:
            existing = None
        filled.append(rk if rk is not None else existing)
    out["opponent_rank"] = filled
    return out


PROP_NORM_MAP = {
    "aces": "aces",
    "ace": "aces",
    "doublefaults": "double_faults",
    "double faults": "double_faults",
    "double fault": "double_faults",
    "break point": "break_points_won",
    "break points won": "break_points_won",
    "breakpoints won": "break_points_won",
    "games won": "games_won",
    "total games": "match_total_games",
    "match total games": "match_total_games",
    "match games": "match_total_games",
    "sets won": "sets_won",
    "set won": "sets_won",
    # PrizePicks board labels (match-level).
    "total sets": "total_sets",
    "total set": "total_sets",
    "total tie breaks": "total_tie_breaks",
    "total tie break": "total_tie_breaks",
    "tie breaks": "total_tie_breaks",
    "tie break": "total_tie_breaks",
}


def norm_tennis_prop(raw: str) -> str:
    if not raw or (isinstance(raw, float) and str(raw) == "nan"):
        return ""
    s = str(raw).lower().strip()
    s2 = re.sub(r"[^a-z0-9 ]+", "", s.replace("-", " "))
    s2 = re.sub(r"\s+", " ", s2).strip()
    if s2 in PROP_NORM_MAP:
        return PROP_NORM_MAP[s2]
    # Prefer specific phrases before fuzzy substring matches.
    if "tie" in s2 and "break" in s2:
        return "total_tie_breaks"
    if "break" in s2 and "point" in s2:
        return "break_points_won"
    if "total" in s2 and "set" in s2:
        return "total_sets"
    for k, v in PROP_NORM_MAP.items():
        if k in s2:
            return v
    if "game" in s2 and "won" in s2:
        return "games_won"
    if "total" in s2 and "game" in s2:
        return "match_total_games"
    if "set" in s2 and "won" in s2:
        return "sets_won"
    return s2.replace(" ", "_")[:48]


def history_value_key(prop_norm: str) -> str | None:
    if prop_norm in (
        "games_won",
        "match_total_games",
        "aces",
        "double_faults",
        "sets_won",
        "total_sets",
        "total_tie_breaks",
        "break_points_won",
    ):
        return prop_norm
    return None


# Posted BO3 lines never live in slam territory. Above these, keep BO5 history.
_BO3_LINE_MAX = {
    "match_total_games": 31.5,
    "games_won": 19.5,
    "sets_won": 2.5,
    "total_sets": 2.5,
}


def _to_float(val: object) -> float | None:
    if val is None or val == "":
        return None
    try:
        fv = float(val)
    except (TypeError, ValueError):
        return None
    if fv != fv:
        return None
    return fv


def line_expects_best_of_three(prop_norm: str, line: object) -> bool:
    """True when the posted PrizePicks line is a best-of-3 market."""
    cap = _BO3_LINE_MAX.get(str(prop_norm or "").strip())
    if cap is None:
        return False
    lv = _to_float(line)
    if lv is None:
        return True
    return lv <= cap


def match_is_best_of_five(rec: dict[str, Any] | None) -> bool:
    """Detect slam / best-of-5 matches that must not project a BO3 line."""
    if not isinstance(rec, dict):
        return False
    ts = _to_float(rec.get("total_sets"))
    if ts is not None and ts >= 4:
        return True
    mtg = _to_float(rec.get("match_total_games"))
    if mtg is not None and mtg >= 40:
        return True
    gw = _to_float(rec.get("games_won"))
    # BO3 winner tops out around 21 (7-6 7-6 7-6).
    if gw is not None and gw >= 24:
        return True
    return False


def history_value_fits_posted_line(
    rec: dict[str, Any] | None,
    prop_norm: str,
    line: object,
    *,
    value: object = None,
) -> bool:
    """Drop BO5 / slam results when the live line is best-of-3."""
    if not line_expects_best_of_three(prop_norm, line):
        return True
    if match_is_best_of_five(rec):
        return False
    fv = _to_float(value)
    if fv is None:
        return True
    key = str(prop_norm or "").strip()
    if key == "match_total_games" and fv >= 40:
        return False
    if key == "games_won" and fv >= 24:
        return False
    if key in ("total_sets", "sets_won") and fv >= 4:
        return False
    return True


def collect_history_values(
    records: list[dict[str, Any]],
    prop_norm: str,
    last_n: int = 10,
    *,
    line: object = None,
) -> list[float]:
    """Newest-first history for prop_norm, skipping format-mismatched matches."""
    vals: list[float] = []
    want = max(1, int(last_n))
    for rec in records:
        if len(vals) >= want:
            break
        if not isinstance(rec, dict):
            continue
        raw = rec.get(prop_norm)
        fv = _to_float(raw)
        if fv is None:
            continue
        if not history_value_fits_posted_line(rec, prop_norm, line, value=fv):
            continue
        vals.append(fv)
    return vals


def apply_format_matched_stat_g(df: pd.DataFrame, n: int = 10) -> int:
    """
    Drop flattened stat_g values that look like best-of-5 when the posted line is BO3.
    Rebuilds stat_last5_avg / stat_last10_avg. Returns how many rows changed.
    """
    gcols = [f"stat_g{i}" for i in range(1, n + 1) if f"stat_g{i}" in df.columns]
    if not gcols:
        return 0
    line_col = "line" if "line" in df.columns else ("line_score" if "line_score" in df.columns else "")
    prop_col = "prop_norm" if "prop_norm" in df.columns else ""
    if not line_col or not prop_col:
        return 0
    changed = 0
    nan = float("nan")
    for idx in df.index:
        prop_norm = str(df.at[idx, prop_col] or "")
        line = df.at[idx, line_col]
        if not line_expects_best_of_three(prop_norm, line):
            continue
        kept: list[float] = []
        old: list[float | None] = []
        for c in gcols:
            fv = _to_float(df.at[idx, c])
            old.append(fv)
            if fv is None:
                continue
            if history_value_fits_posted_line(None, prop_norm, line, value=fv):
                kept.append(fv)
        new: list[float | None] = list(kept) + [None] * (len(gcols) - len(kept))
        if old == new:
            continue
        changed += 1
        for j, c in enumerate(gcols):
            df.at[idx, c] = nan if new[j] is None else new[j]
    if changed:
        sub = df[gcols].apply(pd.to_numeric, errors="coerce")
        df["stat_last5_avg"] = sub.iloc[:, :5].mean(axis=1)
        df["stat_last10_avg"] = sub.mean(axis=1)
        if "stat_season_avg" in df.columns:
            df["stat_season_avg"] = df["stat_last10_avg"]
    return changed


def _sackmann_file_stale(path: Path) -> bool:
    if not path.is_file():
        return True
    age_days = (time.time() - path.stat().st_mtime) / 86400.0
    return age_days > _SACKMANN_MAX_AGE_DAYS


def ensure_sackmann_matches(*, force_fetch: bool = False) -> pd.DataFrame:
    """
    Load combined ATP+WTA Sackmann matches; refresh via fetch_sackmann_data.py if stale.
    """
    combined_atp = _SACKMANN_DIR / "atp_matches_combined.csv"
    if force_fetch or _sackmann_file_stale(combined_atp):
        fetch_script = Path(__file__).resolve().parent / "fetch_sackmann_data.py"
        if fetch_script.is_file():
            cmd = [sys.executable, str(fetch_script)]
            if force_fetch:
                cmd.append("--force")
            subprocess.run(cmd, cwd=str(_TENNIS_ROOT.parents[1]), check=False)
    frames: list[pd.DataFrame] = []
    for name in ("atp_matches_combined.csv", "wta_matches_combined.csv"):
        p = _SACKMANN_DIR / name
        if not p.is_file():
            continue
        try:
            frames.append(pd.read_csv(p, low_memory=False))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _parse_score(score: str, is_winner: bool) -> dict[str, float | None]:
    """Parse Sackmann score string -> games_won, sets_won, match_total_games."""
    both = _parse_score_both_sides(score)
    if not both:
        return {"games_won": None, "sets_won": None, "match_total_games": None}
    side = both["winner"] if is_winner else both["loser"]
    return {
        "games_won": side["games_won"],
        "sets_won": side["sets_won"],
        "match_total_games": both["match_total_games"],
    }


def _parse_score_both_sides(score: str) -> dict[str, Any] | None:
    s = str(score or "").strip()
    if not s:
        return None
    low = s.lower()
    if low in {"w/o", "wo", "ret", "retired", "def", "default", "walkover"}:
        return None
    sets = _SACKMANN_SET_RE.findall(s)
    if not sets:
        return None
    w_games = l_games = w_sets = l_sets = 0
    total = 0
    tiebreaks = 0
    for a, b in sets:
        try:
            wi, li = int(a), int(b)
        except ValueError:
            continue
        total += wi + li
        w_games += wi
        l_games += li
        if wi > li:
            w_sets += 1
        elif li > wi:
            l_sets += 1
        # Standard set TB finishes 7-6 / 6-7 (optional (n) already stripped by regex).
        if (wi == 7 and li == 6) or (wi == 6 and li == 7):
            tiebreaks += 1
    if total <= 0:
        return None
    total_sets = float(w_sets + l_sets)
    return {
        "match_total_games": float(total),
        "total_sets": total_sets,
        "total_tie_breaks": float(tiebreaks),
        "winner": {"games_won": float(w_games), "sets_won": float(w_sets)},
        "loser": {"games_won": float(l_games), "sets_won": float(l_sets)},
    }


def build_sackmann_player_index(matches: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """
    Pre-index Sackmann matches by norm_key(player), newest tourney_date first.
    Each entry holds per-match stats used for stat_g1..g10.
    """
    if matches is None or matches.empty:
        return {}
    need = {"winner_name", "loser_name", "tourney_date", "score", "w_ace", "l_ace", "w_df", "l_df"}
    if not need.issubset(set(matches.columns)):
        return {}
    has_bp = {"w_bpSaved", "w_bpFaced", "l_bpSaved", "l_bpFaced"}.issubset(set(matches.columns))

    index: dict[str, list[dict[str, Any]]] = {}

    def _append(pk: str, rec: dict[str, Any]) -> None:
        if pk:
            index.setdefault(pk, []).append(rec)

    def _f(row: Any, col: str) -> float:
        try:
            return float(row.get(col))
        except (TypeError, ValueError):
            return float("nan")

    for _, rd in matches.iterrows():
        w_name = str(rd.get("winner_name") or "")
        l_name = str(rd.get("loser_name") or "")
        tourney_date = str(rd.get("tourney_date") or "")
        score = str(rd.get("score") or "")
        try:
            match_num = int(float(rd.get("match_num")))
        except (TypeError, ValueError):
            match_num = 0
        rnd = str(rd.get("round") or "").strip().upper()
        parsed = _parse_score_both_sides(score)
        mtg = parsed["match_total_games"] if parsed else None
        total_sets = parsed["total_sets"] if parsed else None
        total_tb = parsed["total_tie_breaks"] if parsed else None
        w_side = parsed["winner"] if parsed else {}
        l_side = parsed["loser"] if parsed else {}
        w_ace = _f(rd, "w_ace")
        l_ace = _f(rd, "l_ace")
        w_df = _f(rd, "w_df")
        l_df = _f(rd, "l_df")

        # Breaks converted = opponent break points faced - saved.
        w_bp = l_bp = float("nan")
        if has_bp:
            try:
                w_bp = float(rd.get("l_bpFaced")) - float(rd.get("l_bpSaved"))
            except (TypeError, ValueError):
                w_bp = float("nan")
            try:
                l_bp = float(rd.get("w_bpFaced")) - float(rd.get("w_bpSaved"))
            except (TypeError, ValueError):
                l_bp = float("nan")

        rec_base = {
            "date": tourney_date,
            "match_num": match_num,
            "round": rnd,
            "match_total_games": mtg,
            "total_sets": total_sets,
            "total_tie_breaks": total_tb,
        }
        _append(
            norm_key(w_name),
            {
                **rec_base,
                "aces": w_ace,
                "double_faults": w_df,
                "games_won": w_side.get("games_won"),
                "sets_won": w_side.get("sets_won"),
                "break_points_won": w_bp,
            },
        )
        _append(
            norm_key(l_name),
            {
                **rec_base,
                "aces": l_ace,
                "double_faults": l_df,
                "games_won": l_side.get("games_won"),
                "sets_won": l_side.get("sets_won"),
                "break_points_won": l_bp,
            },
        )

    for pk in index:
        index[pk].sort(
            key=lambda x: (
                str(x.get("date") or ""),
                int(x.get("match_num") or 0),
                _ROUND_ORDER.get(str(x.get("round") or "").upper(), 0),
            ),
            reverse=True,
        )
    return index


def build_sackmann_player_log(
    matches: pd.DataFrame,
    player_norm: str,
    prop_norm: str,
    last_n: int = 20,
    *,
    player_index: dict[str, list[dict[str, Any]]] | None = None,
    line: object = None,
) -> list[float]:
    """
    Return up to last_n float values for prop_norm from Sackmann matches, newest first.
    """
    if prop_norm not in _SACKMANN_PROP_MAP:
        return []
    pk = (player_norm or "").strip()
    if not pk:
        return []
    if player_index is None:
        player_index = build_sackmann_player_index(matches)
    rows = player_index.get(pk) or []
    return collect_history_values(rows, prop_norm, last_n, line=line)


def parse_sackmann_tourney_date(val: object) -> date | None:
    digits = "".join(ch for ch in str(val or "") if ch.isdigit())[:8]
    if len(digits) != 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def sackmann_coverage_end(matches: pd.DataFrame) -> date | None:
    if matches is None or matches.empty or "tourney_date" not in matches.columns:
        return None
    newest: date | None = None
    for val in matches["tourney_date"].tolist():
        parsed = parse_sackmann_tourney_date(val)
        if parsed and (newest is None or parsed > newest):
            newest = parsed
    return newest


def sackmann_player_fresh(
    player_index: dict[str, list[dict[str, Any]]],
    player_norm: str,
    slate: date,
    *,
    max_age_days: int = SACKMANN_PLAYER_STALE_DAYS,
) -> bool:
    rows = player_index.get((player_norm or "").strip()) or []
    if not rows:
        return False
    newest = parse_sackmann_tourney_date(rows[0].get("date"))
    if newest is None:
        return False
    return (slate - newest).days <= max(1, int(max_age_days))
