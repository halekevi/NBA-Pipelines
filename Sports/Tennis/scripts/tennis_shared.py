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
import urllib.parse
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
URL_ESPN_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"

# ESPN only publishes top ~150; confirmed athletes outside that band map to Weak for D gates.
UNRANKED_OUTSIDE_TOP150 = 250
ATP_ELITE_MAX = 10
ATP_ABOVE_AVG_MAX = 25
ATP_AVG_MAX = 50
ATP_BELOW_AVG_MAX = 100


def atp_wta_def_tier(rank: object) -> str:
    """Map individual opponent ATP/WTA rank to Elite→Weak. Blank if unknown."""
    try:
        v = float(rank)
    except (TypeError, ValueError):
        return ""
    if v != v or v <= 0:
        return ""
    if v <= ATP_ELITE_MAX:
        return "Elite"
    if v <= ATP_ABOVE_AVG_MAX:
        return "Above Avg"
    if v <= ATP_AVG_MAX:
        return "Avg"
    if v <= ATP_BELOW_AVG_MAX:
        return "Below Avg"
    return "Weak"


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


def is_doubles_pair(name: str) -> bool:
    """PrizePicks combined prop: 'Bolelli S / Vavassori A'."""
    return " / " in str(name or "")


def split_pair(name: str) -> tuple[str, str]:
    parts = [p.strip() for p in str(name or "").split(" / ", 1)]
    return (parts[0], parts[1]) if len(parts) == 2 else ("", "")


def norm_pair_key(name: str) -> str:
    """Stable key for a doubles pair regardless of name order."""
    if not is_doubles_pair(name):
        return norm_key(name)
    a, b = split_pair(name)
    keys = sorted(k for k in (norm_key(a), norm_key(b)) if k)
    return " / ".join(keys)


def infer_doubles_opponent(player_name: str, description: str) -> str:
    """
    PrizePicks doubles combines store the opposing pair in projection ``description``
    (e.g. player 'Bolelli S / Vavassori A', description 'Pavlasek A / Rikl P').
    """
    if not is_doubles_pair(player_name):
        return ""
    desc = str(description or "").strip()
    if not desc or norm_key(desc) == norm_key(player_name):
        return ""
    return desc


def resolve_tour_for_player_or_pair(name: str, rankings: list[dict[str, Any]]) -> str:
    if is_doubles_pair(name):
        for part in split_pair(name):
            _eid, tour = resolve_athlete_id(part, rankings)
            if tour:
                return tour
        return "ATP"
    _eid, tour = resolve_athlete_id(name, rankings)
    return tour or "ATP"


def resolve_opp_rank_pair(opp_name: str, rankings: list[dict[str, Any]]) -> float | None:
    """Best singles rank among players in an opponent pair (strongest opponent)."""
    if not str(opp_name or "").strip() or str(opp_name).upper() in ("UNKNOWN_OPP", "UNK"):
        return None
    if is_doubles_pair(opp_name):
        ranks: list[float] = []
        for part in split_pair(opp_name):
            r = resolve_opp_rank(part, rankings)
            if r is not None:
                ranks.append(r)
        return min(ranks) if ranks else None
    return resolve_opp_rank(opp_name, rankings)


def load_opp_rank_cache(cache_path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = cache_path or _OPP_RANK_CACHE
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_opp_rank_cache(cache: dict[str, dict[str, Any]], cache_path: Path | None = None) -> None:
    path = cache_path or _OPP_RANK_CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _rank_by_espn_id(espn_id: str, rankings: list[dict[str, Any]]) -> float | None:
    aid = str(espn_id or "").strip()
    if not aid:
        return None
    for r in rankings:
        if str(r.get("espn_athlete_id") or "") == aid:
            try:
                return float(r.get("rank"))
            except (TypeError, ValueError):
                return None
    return None


def search_espn_tennis_athlete(name: str) -> dict[str, Any] | None:
    """Resolve a PP-style or full name to ESPN athlete id + tour via search API."""
    query = str(name or "").strip()
    if not query:
        return None
    last, initial = _pp_abbrev_tokens(query)
    qlist = [query.replace("/", " ").strip()]
    parts = qlist[0].split()
    if len(parts) >= 2:
        flipped = parts[-1] + " " + " ".join(parts[:-1])
        if norm_key(flipped) != norm_key(qlist[0]):
            qlist.append(flipped)
    best: dict[str, Any] | None = None
    best_score = -1
    q_cands = set(norm_key_candidates(query))
    q_pk = norm_key(query)
    q_parts = q_pk.split()
    q_lasts = {c.split()[-1] for c in q_cands if c.split()}
    q_firsts = {c.split()[0] for c in q_cands if c.split()}
    is_abbrev = bool(initial) and bool(last) and last != q_pk
    seen_urls: set[str] = set()
    for search_q in qlist:
        url_q = search_q
        sq_last, _sq_init = _pp_abbrev_tokens(search_q)
        if sq_last and len(sq_last) >= 3 and sq_last != norm_key(search_q):
            url_q = sq_last.title()
        url = f"{URL_ESPN_SEARCH}?query={urllib.parse.quote(url_q)}&limit=8&type=player&sport=tennis"
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            data = fetch_json(url)
        except Exception:
            continue
        for item in data.get("items") or []:
            if str(item.get("sport") or "").lower() != "tennis":
                continue
            display = str(item.get("displayName") or "").strip()
            if not display:
                continue
            pk = norm_key(display)
            d_parts = pk.split()
            d_last_tok = d_parts[-1] if d_parts else ""
            score = 0
            if pk in q_cands:
                score += 10
            elif is_abbrev:
                if last != d_last_tok and last not in d_parts:
                    continue
                score += 4
                if initial and d_parts and d_parts[0][:1] == initial:
                    score += 2
            elif len(q_parts) >= 2:
                if d_last_tok not in q_lasts:
                    continue
                score += 4
                if d_parts and d_parts[0] in q_firsts:
                    score += 3
                elif d_parts and d_parts[0][:1] in {f[:1] for f in q_firsts if f}:
                    score += 1
            elif last and last in d_parts:
                score += 4
            if score > best_score:
                best_score = score
                tour = str(item.get("league") or item.get("defaultLeagueSlug") or "ATP").upper()
                if tour not in ("ATP", "WTA"):
                    tour = "ATP"
                best = {
                    "espn_athlete_id": str(item.get("id") or ""),
                    "player": display,
                    "tour": tour,
                    "player_key": pk,
                }
        if best_score >= 10:
            break
    return best if best_score >= 2 else None


def hydrate_rankings_for_names(
    names: list[str],
    rankings: list[dict[str, Any]],
    *,
    cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Ensure every named opponent has a rank entry (top-150 cache, opp cache, or ESPN search).
    Athletes confirmed on ESPN but outside the published top 150 get UNRANKED_OUTSIDE_TOP150 (Weak).
    """
    out = list(rankings)
    by_id = {str(r.get("espn_athlete_id") or ""): r for r in out if r.get("espn_athlete_id")}
    by_pk = {str(r.get("player_key") or ""): r for r in out if r.get("player_key")}
    cache = load_opp_rank_cache(cache_path)
    added = 0
    searched = 0

    def _append_entry(entry: dict[str, Any]) -> None:
        nonlocal added
        aid = str(entry.get("espn_athlete_id") or "")
        pk = str(entry.get("player_key") or "")
        if aid and aid in by_id:
            return
        if pk and pk in by_pk:
            return
        out.append(entry)
        if aid:
            by_id[aid] = entry
        if pk:
            by_pk[pk] = entry
        added += 1

    todo: list[str] = []
    for raw in names:
        s = str(raw or "").strip()
        if not s or s.upper() in ("UNKNOWN_OPP", "UNK", "NAN"):
            continue
        if is_doubles_pair(s):
            todo.extend(split_pair(s))
        else:
            todo.append(s)

    seen: set[str] = set()
    for name in todo:
        pk = norm_key(name)
        if not pk or pk in seen:
            continue
        seen.add(pk)
        if resolve_opp_rank(name, out) is not None:
            continue
        cached = cache.get(pk) or cache.get(name)
        if isinstance(cached, dict) and cached.get("espn_athlete_id"):
            cached_aid = str(cached.get("espn_athlete_id") or "").strip()
            cands = set(norm_key_candidates(name)) | {pk}
            existing = by_id.get(cached_aid)
            exist_pk = str((existing or {}).get("player_key") or "")
            # Old substring maps stored Ann Li's id under Hazelitt / Mandlik / Alice.
            if existing and exist_pk and exist_pk not in cands:
                cached = None
            else:
                rank = cached.get("rank")
                try:
                    rank_f = float(rank) if rank is not None else UNRANKED_OUTSIDE_TOP150
                except (TypeError, ValueError):
                    rank_f = UNRANKED_OUTSIDE_TOP150
                _append_entry(
                    {
                        "espn_athlete_id": cached_aid,
                        "player": str(cached.get("player") or name),
                        "tour": str(cached.get("tour") or "ATP").upper(),
                        "rank": rank_f,
                        "points": 0.0,
                        "player_key": str(cached.get("player_key") or pk),
                        "rank_source": str(cached.get("rank_source") or "cache"),
                    }
                )
                continue

        searched += 1
        hit = search_espn_tennis_athlete(name)
        if not hit:
            continue
        aid = str(hit.get("espn_athlete_id") or "")
        existing = _rank_by_espn_id(aid, out)
        rank_f = existing if existing is not None else float(UNRANKED_OUTSIDE_TOP150)
        source = "espn_top150" if existing is not None else "espn_search_unranked"
        entry = {
            "espn_athlete_id": aid,
            "player": str(hit.get("player") or name),
            "tour": str(hit.get("tour") or "ATP").upper(),
            "rank": rank_f,
            "points": 0.0,
            "player_key": pk,
            "rank_source": source,
        }
        _append_entry(entry)
        cache[pk] = entry
        time.sleep(0.15)

    if added:
        save_opp_rank_cache(cache, cache_path)
        print(f"  [Tennis] hydrated opponent ranks: +{added} (searched {searched})")
    return out


def collect_slate_opponent_names(df: pd.DataFrame) -> list[str]:
    names: list[str] = []
    for col in ("opp_team", "opp", "player"):
        if col not in df.columns:
            continue
        for v in df[col].astype(str).tolist():
            s = str(v or "").strip()
            if s and s.upper() not in ("UNKNOWN_OPP", "UNK", "NAN", "NONE"):
                names.append(s)
    return names


def hydrate_rankings_from_slate(
    df: pd.DataFrame,
    rankings: list[dict[str, Any]],
    *,
    cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return rankings
    return hydrate_rankings_for_names(collect_slate_opponent_names(df), rankings, cache_path=cache_path)


def fill_doubles_opponents_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Backfill ``opp_team`` for doubles rows from pp_description/description or
    sibling pair on the same ``pp_game_id``.
    """
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    if "opp_team" not in out.columns:
        out["opp_team"] = ""

    player_col = "player" if "player" in out.columns else "player_name"
    desc_col = "pp_description" if "pp_description" in out.columns else "description"

    def _blank(v) -> bool:
        s = str(v or "").strip()
        return s.lower() in ("", "nan", "none", "null")

    for idx, row in out.iterrows():
        if not _blank(row.get("opp_team")):
            continue
        player = str(row.get(player_col) or "")
        if not is_doubles_pair(player):
            continue
        desc = str(row.get(desc_col) or "")
        opp = infer_doubles_opponent(player, desc)
        if opp:
            out.at[idx, "opp_team"] = opp

    if "pp_game_id" in out.columns and "team" in out.columns:
        blank = out["opp_team"].map(_blank)
        if blank.any():
            game_team_map = (
                out.loc[:, ["pp_game_id", "team"]]
                .astype(str)
                .assign(team=lambda x: x["team"].str.strip(), pp_game_id=lambda x: x["pp_game_id"].str.strip())
                .groupby("pp_game_id")["team"]
                .apply(
                    lambda s: sorted({t for t in s.tolist() if t and t.lower() not in ("nan", "none", "null")})
                )
                .to_dict()
            )
            for idx, row in out.loc[blank].iterrows():
                player = str(row.get(player_col) or "")
                if not is_doubles_pair(player):
                    continue
                gid = str(row.get("pp_game_id", "")).strip()
                team = str(row.get("team", "")).strip()
                teams = game_team_map.get(gid, [])
                if len(teams) == 2 and team in teams:
                    out.at[idx, "opp_team"] = teams[0] if teams[1] == team else teams[1]

    return out


# Alias for Sackmann / step4 history (same normalization as ESPN rankings).
_norm_key = norm_key

_TENNIS_ROOT = Path(__file__).resolve().parent.parent
_SACKMANN_DIR = _TENNIS_ROOT / "data" / "sackmann"
_DOUBLES_OPP_CACHE = _TENNIS_ROOT / "cache" / "tennis_doubles_opp_cache.json"
_OPP_RANK_CACHE = _TENNIS_ROOT / "cache" / "tennis_opp_rank_cache.json"
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


_QUAL_ROUND_ABBR = {
    "Q1",
    "Q2",
    "Q3",
    "Q1ST",
    "Q2ND",
    "Q3RD",
    "QUAL",
}
_QUAL_ROUND_IDS = {"11", "12", "13", "14"}


def normalize_espn_athlete_id(v: object) -> str:
    """CSV float ids ('3562.0') must match cache keys ('3562')."""
    s = str(v or "").strip()
    if not s or s.lower() in {"nan", "none"}:
        return ""
    try:
        f = float(s)
        if f == int(f) and f > 0:
            return str(int(f))
    except (TypeError, ValueError):
        pass
    return s


def match_is_incomplete(rec: dict[str, Any] | None) -> bool:
    """PrizePicks last-5 skips retirements and walkovers."""
    if not isinstance(rec, dict):
        return False
    score = str(rec.get("score") or "").upper()
    if any(tok in score for tok in ("RET", "W/O", "WALKOVER", " DEF", "DEFAULT")):
        return True
    if score.strip() in {"WO", "DEF"}:
        return True
    return False


_LOW_LEVEL_TOURN = re.compile(
    r"(?:\bITF\b|\bW(?:15|25|35|50|75|100)\b)",
    re.I,
)


def match_is_low_level(rec: dict[str, Any] | None) -> bool:
    """ITF / WTA 15–100 only. ATP Challenger is on PrizePicks last-5.

    Skipping CH made Jacob Fearnley Total Games look 5/5; PP is 3/5 after
    Quebec City 17-17-22.
    """
    if not isinstance(rec, dict):
        return False
    level = str(rec.get("level") or "").strip().upper()
    if level in {"S", "ITF", "F"}:
        return True
    blob = " ".join(
        str(rec.get(k) or "")
        for k in ("tourn", "tournament", "event", "event_name", "name")
    )
    return bool(_LOW_LEVEL_TOURN.search(blob))


def match_is_qualifying(rec: dict[str, Any] | None) -> bool:
    """PrizePicks tennis last-5 skips qualifying; keep main-draw matches only."""
    if not isinstance(rec, dict):
        return False
    if rec.get("is_qualifying"):
        return True
    for key in ("round", "round_name", "round_abbr", "grouping", "match_type", "type"):
        s = str(rec.get(key) or "").strip()
        if not s:
            continue
        if s.upper() in _QUAL_ROUND_ABBR or "qualif" in s.lower():
            return True
    rid = str(rec.get("round_id") or "").strip()
    if rid in _QUAL_ROUND_IDS:
        return True
    return False


def match_is_doubles_event(rec: dict[str, Any] | None) -> bool:
    if not isinstance(rec, dict):
        return False
    if rec.get("is_doubles_match"):
        return True
    blob = " ".join(
        str(rec.get(k) or "") for k in ("match_type", "grouping", "type", "round")
    ).lower()
    return "double" in blob


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
                    nm = str(ath.get("displayName") or "").strip()
                    if not nm:
                        continue
                    aid = str(ath.get("id") or "").strip()
                    if not aid:
                        cid = str(c.get("id") or "").strip()
                        if cid.isdigit():
                            aid = cid
                    if not aid:
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
                    rnd = comp.get("round") if isinstance(comp.get("round"), dict) else {}
                    round_name = str(rnd.get("displayName") or rnd.get("abbreviation") or "").strip()
                    round_id = str(rnd.get("id") or "").strip()
                    grouping_slug = str((grp.get("grouping") or {}).get("slug") or "").lower()
                    type_slug = str(
                        ((comp.get("type") or {}) if isinstance(comp.get("type"), dict) else {}).get("slug") or ""
                    ).lower()
                    yield {
                        "espn_athlete_id": aid,
                        "player": nm,
                        "player_key": norm_key(nm),
                        "tour": tour.upper(),
                        "match_date_utc": dt,
                        "competition_id": str(comp.get("id") or "").strip(),
                        "games_won": gw,
                        "match_total_games": float(match_total),
                        "opponent": opp,
                        "aces": float(aces) if aces is not None else None,
                        "double_faults": float(dbl) if dbl is not None else None,
                        "sets_won": float(sw),
                        "total_sets": float(total_sets),
                        "total_tie_breaks": float(tb),
                        "break_points_won": float(bp) if bp is not None else None,
                        "round": round_name,
                        "round_id": round_id,
                        "is_qualifying": match_is_qualifying(
                            {
                                "round": round_name,
                                "round_id": round_id,
                                "grouping": grouping_slug,
                                "match_type": type_slug,
                            }
                        ),
                        "match_type": type_slug or grouping_slug,
                        "is_doubles_match": match_is_doubles_event(
                            {"match_type": type_slug or grouping_slug}
                        ),
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
            def _sf(key: str) -> float | None:
                v = m.get(key)
                if v is None or v == "":
                    return None
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    return None
                if f != f:
                    return None
                return f

            by_player[pk] = {
                "player": str(m.get("player") or pk),
                "match_date_utc": dt,
                "games_won": _sf("games_won") or 0.0,
                "match_total_games": _sf("match_total_games") or 0.0,
                "aces": _sf("aces"),
                "double_faults": _sf("double_faults"),
                "sets_won": _sf("sets_won") or 0.0,
                "total_sets": _sf("total_sets") or 0.0,
                "total_tie_breaks": _sf("total_tie_breaks") or 0.0,
                "break_points_won": _sf("break_points_won"),
            }
    if by_player:
        grouped: dict[str, dict[str, dict[str, Any]]] = {}
        for pk, st in by_player.items():
            grouped.setdefault(str(st.get("match_date_utc") or "")[:10], {})[pk] = st
        sidx: dict[str, list[dict[str, Any]]] | None = None
        for ds, subset in grouped.items():
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                continue
            if sidx is None:
                sidx = build_sackmann_player_index(ensure_sackmann_matches())
            fill_missing_serve_from_sackmann(subset, d, player_index=sidx)
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
    by_id: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
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
                cid = str(m.get("competition_id") or "").strip()
                key = (aid, cid or f"{m.get('match_date_utc')}|{m.get('opponent')}")
                if not aid or key in seen:
                    continue
                seen.add(key)
                by_id.setdefault(aid, []).append(m)
                pk = str(m.get("player_key") or "").strip()
                if pk:
                    by_id.setdefault(f"pk:{pk}", []).append(m)
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
    for cand in norm_key_candidates(player_name):
        for r in rankings:
            if (r.get("player_key") or "") == cand:
                return str(r["espn_athlete_id"]), str(r.get("tour") or "")
    eid, tour = _resolve_pp_abbrev_athlete_id(player_name, rankings)
    if eid:
        return eid, tour
    return "", ""


def resolve_or_search_athlete_id(
    player_name: str,
    rankings: list[dict[str, Any]],
) -> tuple[str, str]:
    """Rankings / abbrev first; ESPN search for anyone outside the top 150."""
    eid, tour = resolve_athlete_id(player_name, rankings)
    if eid:
        return eid, tour
    hit = search_espn_tennis_athlete(player_name)
    if not hit:
        return "", tour
    return str(hit.get("espn_athlete_id") or ""), str(hit.get("tour") or tour or "")


def _pp_abbrev_tokens(name: str) -> tuple[str, str]:
    """PrizePicks 'Last F' / 'Last Fi' -> (last_name_key, first_initial)."""
    parts = [p for p in re.split(r"\s+", str(name or "").strip()) if p]
    if len(parts) >= 2 and len(parts[-1]) <= 2:
        return norm_key(" ".join(parts[:-1])), parts[-1][0].lower()
    return norm_key(name), ""


def _resolve_pp_abbrev_athlete_id(player_name: str, rankings: list[dict[str, Any]]) -> tuple[str, str]:
    """Match PP abbreviated labels ('Ram R') to ESPN full names ('Rajeev Ram').

    Full names are not handled here. Substring last-name matching used to map
    Jordyn Hazelitt / Alice Tubello / Elizabeth Mandlik onto Ann Li because
    the letters ``li`` appear inside those names.
    """
    parts = [p for p in re.split(r"\s+", str(player_name or "").strip()) if p]
    if not (len(parts) >= 2 and len(parts[-1]) <= 2):
        return "", ""
    last, initial = _pp_abbrev_tokens(player_name)
    if not last:
        return "", ""
    best = ""
    best_tour = ""
    best_score = -1
    for r in rankings:
        rk = str(r.get("player_key") or "")
        display = str(r.get("player") or "")
        for key in (rk, norm_key(display)):
            if not key:
                continue
            words = key.split()
            if not words:
                continue
            rk_last = words[-1]
            rk_init = words[0][0] if words[0] else ""
            if last != rk_last:
                continue
            score = 3
            if initial and initial == rk_init:
                score += 2
            elif initial:
                continue
            if score > best_score:
                best_score = score
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
    _eid, _t = _resolve_pp_abbrev_athlete_id(opp_name, rankings)
    if _eid:
        for r in rankings:
            if str(r.get("espn_athlete_id")) == _eid:
                try:
                    return float(r.get("rank"))
                except (TypeError, ValueError):
                    return None
    return None


def load_doubles_opp_cache(cache_path: Path | None = None) -> dict[str, dict[str, str]]:
    """Load projection_id / pair_key -> {pp_description, opp_team} for doubles combines."""
    path = cache_path or _DOUBLES_OPP_CACHE
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for k, v in raw.items():
        if not isinstance(v, dict):
            continue
        desc = str(v.get("pp_description") or v.get("description") or "").strip()
        opp = str(v.get("opp_team") or "").strip()
        if desc or opp:
            out[str(k)] = {"pp_description": desc, "opp_team": opp}
    return out


def save_doubles_opp_cache(cache: dict[str, dict[str, str]], cache_path: Path | None = None) -> None:
    path = cache_path or _DOUBLES_OPP_CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def update_doubles_opp_cache_from_df(
    df: pd.DataFrame,
    cache: dict[str, dict[str, str]] | None = None,
    *,
    cache_path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Merge doubles rows with filled opp_team into the persistent cache."""
    store = dict(cache or load_doubles_opp_cache(cache_path))
    if df is None or getattr(df, "empty", True):
        return store
    player_col = "player" if "player" in df.columns else "player_name"
    pid_col = "projection_id" if "projection_id" in df.columns else "pp_projection_id"

    def _blank(v) -> bool:
        s = str(v or "").strip()
        return s.lower() in ("", "nan", "none", "null")

    for _, row in df.iterrows():
        player = str(row.get(player_col) or "")
        if not is_doubles_pair(player):
            continue
        opp = str(row.get("opp_team") or "").strip()
        desc = str(row.get("pp_description") or row.get("description") or "").strip()
        if _blank(opp) and _blank(desc):
            continue
        rec = {"pp_description": desc or opp, "opp_team": opp or desc}
        pid = str(row.get(pid_col) or "").strip()
        if pid:
            store[pid] = rec
        pk = norm_pair_key(player)
        if pk:
            store[f"pair:{pk}"] = rec
    save_doubles_opp_cache(store, cache_path)
    return store


def apply_doubles_opp_cache(df: pd.DataFrame, cache: dict[str, dict[str, str]] | None = None) -> tuple[pd.DataFrame, int]:
    """Apply cached PP descriptions / opponents to doubles rows missing opp_team."""
    if df is None or getattr(df, "empty", True):
        return df, 0
    store = cache if cache is not None else load_doubles_opp_cache()
    if not store:
        return df, 0
    out = df.copy()
    if "pp_description" not in out.columns:
        out["pp_description"] = ""
    if "opp_team" not in out.columns:
        out["opp_team"] = ""
    player_col = "player" if "player" in out.columns else "player_name"
    pid_col = "projection_id" if "projection_id" in out.columns else "pp_projection_id"
    patched = 0

    def _blank(v) -> bool:
        s = str(v or "").strip()
        return s.lower() in ("", "nan", "none", "null")

    for idx, row in out.iterrows():
        if not _blank(row.get("opp_team")):
            continue
        player = str(row.get(player_col) or "")
        if not is_doubles_pair(player):
            continue
        pid = str(row.get(pid_col) or "").strip()
        rec = store.get(pid) or store.get(f"pair:{norm_pair_key(player)}") or {}
        desc = str(rec.get("pp_description") or "").strip()
        opp = str(rec.get("opp_team") or "").strip()
        if not desc and not opp:
            continue
        if desc:
            out.at[idx, "pp_description"] = desc
        if opp:
            out.at[idx, "opp_team"] = opp
        elif desc:
            out.at[idx, "opp_team"] = infer_doubles_opponent(player, desc)
        patched += 1
    return out, patched


def merge_doubles_fields_into_step1(step1_path: Path, df: pd.DataFrame) -> int:
    """Write pp_description / opp_team from processed doubles rows back into step1 CSV."""
    if not step1_path.is_file() or df is None or df.empty:
        return 0
    player_col = "player" if "player" in df.columns else "player_name"
    pid_col = "projection_id" if "projection_id" in df.columns else "pp_projection_id"
    patch: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        if not is_doubles_pair(str(row.get(player_col) or "")):
            continue
        pid = str(row.get(pid_col) or "").strip()
        opp = str(row.get("opp_team") or "").strip()
        desc = str(row.get("pp_description") or "").strip()
        if pid and (opp or desc):
            patch[pid] = {
                "opp_team": opp,
                "pp_description": desc or opp,
                "is_doubles": "1",
            }
    if not patch:
        return 0
    s1 = pd.read_csv(step1_path, dtype=str, encoding="utf-8-sig").fillna("")
    if "pp_description" not in s1.columns:
        s1["pp_description"] = ""
    if "is_doubles" not in s1.columns:
        s1["is_doubles"] = s1.get("player", s1.get("player_name", "")).astype(str).map(
            lambda s: "1" if is_doubles_pair(s) else "0"
        )
    pid_s1 = "projection_id" if "projection_id" in s1.columns else "pp_projection_id"
    updated = 0
    for idx, row in s1.iterrows():
        pid = str(row.get(pid_s1) or "").strip()
        if pid not in patch:
            continue
        rec = patch[pid]
        s1.at[idx, "opp_team"] = rec["opp_team"]
        s1.at[idx, "pp_description"] = rec["pp_description"]
        s1.at[idx, "is_doubles"] = rec["is_doubles"]
        updated += 1
    if updated:
        s1.to_csv(step1_path, index=False, encoding="utf-8-sig")
    return updated


def backfill_pp_descriptions_from_api(
    df: pd.DataFrame,
    *,
    league_id: str = "5",
    skip_api: bool = False,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    """Patch doubles rows missing ``pp_description`` / ``opp_team`` from cache then live PP."""
    if df is None or getattr(df, "empty", True):
        return df
    player_col = "player" if "player" in df.columns else "player_name"

    def _blank_series(col: str) -> pd.Series:
        return df.get(col, pd.Series([""] * len(df))).astype(str).str.strip().str.lower().isin(
            ["", "nan", "none", "null"]
        )

    need_mask = df[player_col].astype(str).map(is_doubles_pair) & _blank_series("opp_team")
    if not need_mask.any():
        return df
    out = df.copy()
    if "pp_description" not in out.columns:
        out["pp_description"] = ""

    cache = load_doubles_opp_cache(cache_path)
    out, from_cache = apply_doubles_opp_cache(out, cache)
    if from_cache:
        print(f"  [Tennis step2] doubles opp cache hit: {from_cache}/{int(need_mask.sum())}")

    still_need = out[player_col].astype(str).map(is_doubles_pair) & out["opp_team"].astype(str).str.strip().isin(
        ["", "nan", "none"]
    )
    if skip_api or not still_need.any():
        update_doubles_opp_cache_from_df(out, cache, cache_path=cache_path)
        return out

    try:
        repo = Path(__file__).resolve().parents[3]
        nba_scripts = repo / "Sports" / "NBA" / "scripts"
        if str(nba_scripts) not in sys.path:
            sys.path.insert(0, str(nba_scripts))
        import step1_fetch_prizepicks_api as nba  # noqa: WPS433

        data, _included = nba.fetch_projections(
            league_id=str(league_id),
            per_page=250,
            max_pages=2,
            fail_fast=True,
        )
        desc_by_pid: dict[str, str] = {}
        for d in data:
            pid = str(d.get("id") or "").strip()
            attrs = d.get("attributes") or {}
            desc = str(attrs.get("description") or "").strip()
            if pid and desc:
                desc_by_pid[pid] = desc
        pid_col = "projection_id" if "projection_id" in out.columns else "pp_projection_id"
        patched = 0
        for idx, row in out.loc[still_need].iterrows():
            pid = str(row.get(pid_col) or "").strip()
            desc = desc_by_pid.get(pid, "")
            if not desc:
                continue
            out.at[idx, "pp_description"] = desc
            opp = infer_doubles_opponent(str(row.get(player_col) or ""), desc)
            if opp:
                out.at[idx, "opp_team"] = opp
                patched += 1
        if patched:
            print(f"  [Tennis step2] PP API patched doubles opp_team: {patched}/{int(still_need.sum())}")
    except Exception as e:
        print(f"  [Tennis step2] WARN: could not backfill PP descriptions ({type(e).__name__}: {e})")

    update_doubles_opp_cache_from_df(out, cache, cache_path=cache_path)
    return out


def backfill_opp_team_from_game_players(df: pd.DataFrame) -> pd.DataFrame:
    """Infer blank opp_team from the other singles player sharing pp_game_id.

    PrizePicks tennis rows often omit opp_team until late; team/player usually
    carries the athlete name, so a 2-player game map recovers the matchup.
    """
    if df is None or getattr(df, "empty", True):
        return df
    if "opp_team" not in df.columns or "pp_game_id" not in df.columns:
        return df
    out = df.copy()
    opp_blank = out["opp_team"].astype(str).str.strip().isin(["", "nan", "None", "null"])
    if not bool(opp_blank.any()):
        return out

    label_col = "player" if "player" in out.columns else ("team" if "team" in out.columns else None)
    if not label_col:
        return out

    def _label(v: object) -> str:
        s = str(v or "").strip()
        return "" if s.lower() in ("", "nan", "none", "null") else s

    game_map: dict[str, list[str]] = (
        out.loc[:, ["pp_game_id", label_col]]
        .assign(
            pp_game_id=lambda x: x["pp_game_id"].astype(str).str.strip(),
            _lab=lambda x: x[label_col].map(_label),
        )
        .groupby("pp_game_id")["_lab"]
        .apply(lambda s: sorted({t.upper() for t in s.tolist() if t}))
        .to_dict()
    )

    inferred: list[str] = []
    for _, r in out.loc[opp_blank, ["pp_game_id", label_col]].iterrows():
        gid = str(r.get("pp_game_id", "")).strip()
        mine = _label(r.get(label_col)).upper()
        others = game_map.get(gid, [])
        if len(others) == 2 and mine in others:
            inferred.append(others[0] if others[1] == mine else others[1])
        else:
            inferred.append("")
    out.loc[opp_blank, "opp_team"] = inferred
    still_blank = out["opp_team"].astype(str).str.strip().isin(["", "nan", "None", "null"])
    out.loc[still_blank, "opp_team"] = "UNKNOWN_OPP"
    return out


def fill_opponent_rank_from_slate_players(df: pd.DataFrame) -> pd.DataFrame:
    """Fill opponent_rank from the opponent's player_atp_rank on this slate (ATP/WTA).

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

    def _lookup_opp_rank(opp: str) -> int | None:
        if not opp:
            return None
        rk = name_rank.get(opp)
        if rk is not None:
            return rk
        for n, v in name_rank.items():
            if opp in n or n in opp:
                return v
        if is_doubles_pair(opp):
            parts = [_name(p) for p in split_pair(opp)]
            part_ranks = [name_rank.get(p) for p in parts if p]
            part_ranks = [r for r in part_ranks if r is not None]
            if part_ranks:
                return min(part_ranks)
            for n, v in name_rank.items():
                if any(p and (p in n or n in p) for p in parts):
                    return v
        return None

    filled = []
    for _, r in out.iterrows():
        opp = _name(r.get(ocol) if ocol else "")
        rk = _lookup_opp_rank(opp)
        existing = _rk(r.get("opponent_rank"))
        if existing == 75:
            existing = None
        filled.append(rk if rk is not None else existing)
    out["opponent_rank"] = filled
    return out


def ensure_opponent_atp_wta_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Backfill opp_team from the match, then set opponent_rank to ATP/WTA rank."""
    if df is None or getattr(df, "empty", True):
        return df
    out = backfill_opp_team_from_game_players(df)
    return fill_opponent_rank_from_slate_players(out)


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
    """Keep history that matches the posted format (BO3 line vs BO5 line)."""
    key = str(prop_norm or "").strip()
    fv = _to_float(value)
    if line_expects_best_of_three(prop_norm, line):
        if match_is_best_of_five(rec):
            return False
        if fv is None:
            return True
        if key == "match_total_games" and fv >= 40:
            return False
        if key == "games_won" and fv >= 24:
            return False
        if key in ("total_sets", "sets_won") and fv >= 4:
            return False
        return True
    if key not in _BO3_LINE_MAX:
        return True
    # Posted line is BO5. Drop 2-set / 3-set tape (Tiafoe 40.5 vs Cincy 19–30).
    if isinstance(rec, dict) and not match_is_best_of_five(rec):
        ts = _to_float(rec.get("total_sets"))
        if ts is not None and ts <= 3:
            return False
        mtg = _to_float(rec.get("match_total_games"))
        if key == "match_total_games" and mtg is not None and mtg < 32:
            return False
        gw = _to_float(rec.get("games_won"))
        if key == "games_won" and gw is not None and gw < 16:
            return False
    if fv is None:
        return True
    if key == "match_total_games" and fv < 32:
        return False
    if key == "games_won" and fv < 16:
        return False
    if key == "total_sets" and fv <= 2:
        return False
    return True


def tennis_bo5_graded_on_bo3_tape(row: object) -> bool:
    """True when a BO5 games/sets line is being graded on BO3 last-5 tape.

    List-side veto so PrizePicks last-5 (Cincy BO3 19–30) cannot Gold a
    US Open Total Games under at 40.5. Fail closed when the line is BO5
    and no last-5 game is slam-sized.
    """
    if row is None:
        return False
    get = row.get if hasattr(row, "get") else None
    if get is None:
        return False
    prop = str(get("prop_norm") or "").strip()
    if not prop:
        prop = norm_tennis_prop(str(get("prop_type") or get("prop") or get("Prop") or ""))
    if prop not in _BO3_LINE_MAX:
        return False
    line = get("line")
    if line is None or line == "":
        line = get("Line")
    if line_expects_best_of_three(prop, line):
        return False
    vals: list[float] = []
    for i in range(1, 6):
        fv = _to_float(get(f"stat_g{i}"))
        if fv is not None:
            vals.append(fv)
    avg = _to_float(get("stat_last5_avg"))
    if avg is None and vals:
        avg = sum(vals) / len(vals)
    if prop == "match_total_games":
        if any(v >= 32 for v in vals):
            return False
        if avg is not None and avg >= 32:
            return False
        return True
    if prop == "games_won":
        if any(v >= 16 for v in vals):
            return False
        if avg is not None and avg >= 16:
            return False
        return True
    if prop in ("total_sets", "sets_won"):
        if any(v >= 4 for v in vals):
            return False
        return True
    return False


def collect_history_values(
    records: list[dict[str, Any]],
    prop_norm: str,
    last_n: int = 10,
    *,
    line: object = None,
    skip_qualifying: bool = True,
    skip_doubles: bool = True,
) -> list[float]:
    """Newest-first history for prop_norm, skipping format-mismatched matches.

    PrizePicks tennis last-5 is main-draw singles. Qualifying and doubles
    matches are dropped so L5 matches the site (Stoiana O20.0 is 4/1, not 5/0).
    """
    vals: list[float] = []
    want = max(1, int(last_n))
    for rec in records:
        if len(vals) >= want:
            break
        if not isinstance(rec, dict):
            continue
        if skip_qualifying and match_is_qualifying(rec):
            continue
        if skip_doubles and match_is_doubles_event(rec):
            continue
        if match_is_incomplete(rec):
            continue
        if match_is_low_level(rec):
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
    Drop flattened stat_g values that do not match the posted format
    (BO5 tape on a BO3 line, or BO3 tape on a BO5 line).
    Rebuilds stat_last5_avg / stat_last10_avg. Returns how many rows changed.
    """
    gcols = [f"stat_g{i}" for i in range(1, n + 1) if f"stat_g{i}" in df.columns]
    if not gcols:
        return 0
    line_col = "line" if "line" in df.columns else ("line_score" if "line_score" in df.columns else "")
    prop_col = "prop_norm" if "prop_norm" in df.columns else ("prop_type" if "prop_type" in df.columns else "")
    if not line_col or not prop_col:
        return 0
    changed = 0
    nan = float("nan")
    for idx in df.index:
        raw_prop = str(df.at[idx, prop_col] or "")
        prop_norm = raw_prop if prop_col == "prop_norm" else norm_tennis_prop(raw_prop)
        line = df.at[idx, line_col]
        if str(prop_norm or "").strip() not in _BO3_LINE_MAX:
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


def ta_player_side_from_score(score: str, wl: object) -> dict[str, Any] | None:
    """Pick THIS player's games/sets from a Tennis Abstract score + W/L.

    TA mixes player-first strings (``4-6 6-3 3-6`` with ``L``) and winner-first
    strings (``6-2 6-3`` with ``L``). Always taking the first number in each set
    inflates games-won on every winner-first loss. Use set counts vs W/L:

    - Win: the side with more sets (first numbers when they won the match).
    - Loss: the side with fewer sets (second numbers when the score is winner-first).

    RET / W/O / default scores keep match totals when parseable but leave
    games_won / sets_won empty — do not guess from a partial score.
    """
    parsed = _parse_score_both_sides(score)
    if not parsed:
        return None
    out: dict[str, Any] = {
        "match_total_games": parsed["match_total_games"],
        "total_sets": parsed["total_sets"],
        "total_tie_breaks": parsed["total_tie_breaks"],
        "games_won": None,
        "sets_won": None,
    }
    score_u = str(score or "").upper()
    if any(tok in score_u for tok in ("RET", "W/O", "WALKOVER", " DEF", "DEFAULT")):
        return out
    first = parsed["winner"]
    second = parsed["loser"]
    fs = float(first.get("sets_won") or 0)
    ss = float(second.get("sets_won") or 0)
    flag = str(wl or "").strip().upper()
    if flag == "W":
        side = first if fs >= ss else second
    elif flag == "L":
        if fs < ss:
            side = first
        elif fs > ss:
            side = second
        else:
            return out
    else:
        side = first
    out["games_won"] = side.get("games_won")
    out["sets_won"] = side.get("sets_won")
    return out


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
        match_minutes = _f(rd, "minutes")

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
            "minutes": match_minutes if match_minutes == match_minutes else None,
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


def _sackmann_finite(v: object) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def lookup_sackmann_match(
    player_index: dict[str, list[dict[str, Any]]],
    player: str,
    slate: date,
    *,
    games_won_hint: float | None = None,
    window_before: int = 18,
    window_after: int = 2,
) -> dict[str, Any] | None:
    """Best Sackmann row for a player on/near a slate date.

    ``tourney_date`` is the event start, so the window is wide. Prefer a row
    whose games_won matches a sibling ESPN games-won actual when provided.
    Serve stats may be a true 0; missing Sackmann values stay None (never
    coerced to 0.0).
    """
    if not player_index or not player:
        return None
    lo = slate - timedelta(days=int(window_before))
    hi = slate + timedelta(days=int(window_after))
    cands: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()
    for pk in norm_key_candidates(player):
        for rec in player_index.get(pk) or []:
            dt = parse_sackmann_tourney_date(rec.get("date"))
            if dt is None or dt < lo or dt > hi:
                continue
            key = (
                str(rec.get("date") or ""),
                rec.get("match_num"),
                rec.get("round"),
                rec.get("games_won"),
            )
            if key in seen:
                continue
            seen.add(key)
            cands.append(rec)
    if not cands:
        return None
    hint = _sackmann_finite(games_won_hint)
    if hint is not None and hint > 0:
        close = []
        for rec in cands:
            gw = _sackmann_finite(rec.get("games_won"))
            if gw is not None and abs(gw - hint) <= 1.5:
                close.append(rec)
        if close:
            cands = close
    with_serve = [
        r
        for r in cands
        if _sackmann_finite(r.get("aces")) is not None
        or _sackmann_finite(r.get("double_faults")) is not None
    ]
    pool = with_serve or cands

    def _sort_key(r: dict[str, Any]) -> tuple[int, int]:
        dt = parse_sackmann_tourney_date(r.get("date")) or date.min
        return (abs((dt - slate).days), -int(r.get("match_num") or 0))

    best = min(pool, key=_sort_key)
    out = dict(best)
    for k in ("aces", "double_faults", "games_won", "sets_won", "match_total_games"):
        out[k] = _sackmann_finite(out.get(k))
    return out


def lookup_serve_actual(
    player: str,
    slate: date,
    *,
    games_won_hint: float | None = None,
    ta_index: dict[str, list[dict[str, Any]]] | None = None,
    sack_index: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Tennis Abstract (match date) first, then Sackmann (event start)."""
    if ta_index:
        rec = lookup_sackmann_match(
            ta_index,
            player,
            slate,
            games_won_hint=games_won_hint,
            window_before=3,
            window_after=1,
        )
        if rec and (
            rec.get("aces") is not None or rec.get("double_faults") is not None
        ):
            return rec, "tennis_abstract"
    if sack_index:
        rec = lookup_sackmann_match(
            sack_index,
            player,
            slate,
            games_won_hint=games_won_hint,
            window_before=18,
            window_after=2,
        )
        if rec and (
            rec.get("aces") is not None or rec.get("double_faults") is not None
        ):
            return rec, "sackmann"
    return None, ""


def fill_missing_serve_from_sackmann(
    by_player: dict[str, dict[str, Any]],
    slate: date,
    *,
    player_index: dict[str, list[dict[str, Any]]] | None = None,
    ta_index: dict[str, list[dict[str, Any]]] | None = None,
) -> int:
    """Fill None aces/DF from Tennis Abstract, then Sackmann. Returns rows touched."""
    missing = [
        pk
        for pk, st in by_player.items()
        if st.get("aces") is None or st.get("double_faults") is None
    ]
    if not missing:
        return 0
    if player_index is None:
        player_index = build_sackmann_player_index(ensure_sackmann_matches())
    if ta_index is None:
        try:
            from tennis_ta_matchlog import load_cached_ta_player_index

            ta_index = load_cached_ta_player_index()
        except Exception:
            ta_index = {}
    filled = 0
    for pk in missing:
        st = by_player[pk]
        rec, _src = lookup_serve_actual(
            str(st.get("player") or pk),
            slate,
            games_won_hint=_sackmann_finite(st.get("games_won")),
            ta_index=ta_index,
            sack_index=player_index,
        )
        if not rec:
            continue
        changed = False
        if st.get("aces") is None and rec.get("aces") is not None:
            st["aces"] = rec["aces"]
            changed = True
        if st.get("double_faults") is None and rec.get("double_faults") is not None:
            st["double_faults"] = rec["double_faults"]
            changed = True
        if changed:
            filled += 1
    return filled


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
