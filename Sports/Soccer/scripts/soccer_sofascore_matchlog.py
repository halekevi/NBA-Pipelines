"""Sofascore match-log fill for Popular soccer markets ESPN under-covers.

ESPN player boxscores leave `pa` / `clearances` / `dribble_attempts` (and usually
`tk`) NULL, and often only the latest league game for shots/SOT/goals. Sofascore
lineups have `totalPass`, `totalClearance`, `totalTackle`, take-on attempts
(`dribbleAttempts` or Opta `totalContest`), plus `totalShots` / SOT / goals.

Rows are stored as `event_id=sofa_{id}`. Shot columns are filled when Sofascore
has them so L5 can match PrizePicks (Leagues Cup + league mix). Same-date ESPN
rows still win in `get_vals_soccer`. Missing dribble keys stay None (never 0).
"""
from __future__ import annotations

import json
import random
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote

import pandas as pd

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "cache" / "sofascore_matchlog.json"
SOFA_SEARCH = "https://www.sofascore.com/api/v1/search/all?q={q}"
SOFA_EVENTS = "https://www.sofascore.com/api/v1/player/{pid}/events/last/{page}"
SOFA_LINEUPS = "https://www.sofascore.com/api/v1/event/{eid}/lineups"
SOFA_HEADERS = {
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}
# ESPN boxscores leave these NULL; Sofascore is the L5 source.
GAP_NORMS = frozenset({
    "passes", "passes attempted", "pa",
    "clearances",
    "attempted_dribbles", "attempted dribbles", "dribbles",
    "tackles", "tk",
    "crosses",
    "shots assisted", "shots_assisted",
})
MATCHLOG_NORMS = GAP_NORMS | frozenset({
    "shots", "sh",
    "shots on target", "shots_on_target", "sog", "sot",
    "goals", "g",
    "assists", "a",
    "goal+assist", "goal_assist",
    "saves", "goalie saves", "goalkeeper saves", "sv",
    "fouls", "fc",
})
_GAP_COMPACT = frozenset({
    "passes", "passesattempted", "pa", "clearances",
    "attempteddribbles", "dribbles", "tackles", "tk",
    "crosses", "shotsassisted",
})
_TEAM_NOISE = frozenset({"fc", "cf", "afc", "sc", "club", "al", "de", "the", "united", "city", "real"})
_tls = threading.local()


def _norm(s: str) -> str:
    text = unicodedata.normalize("NFKD", str(s or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def player_cache_key(name: str, team: str) -> str:
    return f"{_norm(name)}|{_norm(team)}"


def _prop_tokens(prop_norm: str, prop_type: str = "") -> list[str]:
    out = []
    for raw in (prop_norm, prop_type):
        p = str(raw or "").lower().strip()
        if p:
            out.append(p)
            out.append(p.replace("-", "").replace("_", "").replace(" ", ""))
    return out


def needs_matchlog(prop_norm: str, prop_type: str = "") -> bool:
    for p in _prop_tokens(prop_norm, prop_type):
        if p in MATCHLOG_NORMS or p.replace("-", "").replace("_", "").replace(" ", "") in {
            "passes", "passesattempted", "pa", "clearances",
            "attempteddribbles", "dribbles", "tackles", "tk",
            "shots", "sh", "shotsontarget", "sog", "sot",
            "goals", "g", "assists", "a", "goalassist",
            "shotsassisted", "saves", "goaliesaves", "goalkeepersaves", "sv",
            "fouls", "fc", "crosses",
        }:
            return True
    return False


def needs_gap_matchlog(prop_norm: str, prop_type: str = "") -> bool:
    """True for ESPN-null PrizePicks markets (passes/tackles/clearances/dribbles/crosses/shots assisted)."""
    for p in _prop_tokens(prop_norm, prop_type):
        if p in GAP_NORMS:
            return True
        if p.replace("-", "").replace("_", "").replace(" ", "") in _GAP_COMPACT:
            return True
    return False


def _num_if_present(st: dict, *keys: str) -> Optional[float]:
    for key in keys:
        if key not in st or st[key] is None:
            continue
        try:
            return float(st[key])
        except (TypeError, ValueError):
            continue
    return None


def extract_matchlog_stats(statistics: Optional[dict]) -> Dict[str, Optional[float]]:
    """Map Sofascore lineup statistics → DB columns. Absent keys stay None."""
    st = statistics or {}
    pa = _num_if_present(st, "totalPass", "totalPasses")
    clearances = _num_if_present(st, "totalClearance", "totalClearances")
    tk = _num_if_present(st, "totalTackle", "totalTackles")

    drb = None
    if "dribbleAttempts" in st and st["dribbleAttempts"] is not None:
        drb = _num_if_present(st, "dribbleAttempts")
    elif "dribbles" in st and st["dribbles"] is not None:
        drb = _num_if_present(st, "dribbles")
    elif "successfulDribbles" in st or "unsuccessfulDribbles" in st:
        succ = st.get("successfulDribbles")
        uns = st.get("unsuccessfulDribbles")
        if succ is not None or uns is not None:
            try:
                drb = float(succ or 0) + float(uns or 0)
            except (TypeError, ValueError):
                drb = None
    elif "totalContest" in st and st["totalContest"] is not None:
        # Opta take-on attempts (FBref Att); Sofascore often omits dribbleAttempts.
        drb = _num_if_present(st, "totalContest")

    sh = _num_if_present(st, "totalShots", "shots")
    sog = _num_if_present(st, "onTargetScoringAttempt", "shotsOnTarget", "shotOnTarget")
    g = _num_if_present(st, "goals", "goal")
    a = _num_if_present(st, "goalAssist", "assists")
    kp = _num_if_present(st, "keyPass", "keyPasses")
    sv = _num_if_present(st, "saves", "goalkeeperSaves")
    if sv is None:
        sv_in = _num_if_present(st, "savedShotsFromInsideTheBox")
        sv_out = _num_if_present(st, "savedShotsFromOutsideTheBox")
        if sv_in is not None or sv_out is not None:
            sv = float(sv_in or 0) + float(sv_out or 0)
    fc = _num_if_present(st, "fouls", "foulsCommitted")
    crosses = _num_if_present(st, "totalCross", "totalCrosses", "crosses")

    return {
        "pa": pa,
        "clearances": clearances,
        "dribble_attempts": drb,
        "tk": tk,
        "sh": sh,
        "sog": sog,
        "g": g,
        "a": a,
        "kp": kp,
        "sv": sv,
        "fc": fc,
        "crosses": crosses,
    }


def _team_matches(hint: str, sofa_name: str) -> bool:
    h = _norm(hint)
    n = _norm(sofa_name)
    if not h or not n:
        return False
    if h in n or n in h:
        return True
    ht = [t for t in h.split() if t not in _TEAM_NOISE]
    nt = n.split()
    if not ht:
        return False
    return all(any(t == x or t in x or x in t for x in nt) for t in ht)


def pick_search_hit(results: Iterable[dict], name: str, team_hint: str = "") -> Optional[dict]:
    """Pick a football player entity from Sofascore search results."""
    name_n = _norm(name)
    if not name_n:
        return None
    scored: List[tuple] = []
    for item in results or []:
        if str(item.get("type") or "") != "player":
            continue
        ent = item.get("entity") or {}
        sport = ent.get("sport") or {}
        slug = str(sport.get("slug") or sport.get("name") or "").lower()
        if slug and slug not in ("football", "soccer"):
            continue
        ename = _norm(ent.get("name"))
        if not ename:
            continue
        ntoks = [t for t in name_n.split() if len(t) > 1]
        etoks = ename.split()
        score = 0
        if ename == name_n:
            score += 10
        elif name_n in ename or ename in name_n:
            score += 7
        else:
            overlap = sum(1 for t in ntoks if t in etoks)
            if ntoks and overlap == len(ntoks):
                score += 8
            elif overlap:
                score += overlap
        # PrizePicks "Max Crocombe" vs Sofascore "Maxime Crocombe"
        if score < 6 and ntoks and etoks and ntoks[-1] == etoks[-1]:
            nf, ef = ntoks[0], etoks[0]
            if nf == ef or (
                len(nf) >= 3 and len(ef) >= 3 and (nf.startswith(ef) or ef.startswith(nf))
            ):
                score = 8
        if score < 6:
            continue
        sofa_team = str((ent.get("team") or {}).get("name") or "")
        if team_hint and _team_matches(team_hint, sofa_team):
            score += 5
        scored.append((score, -len(ename), str(ent.get("id") or ""), ent))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][3]


def _event_date(ev: dict) -> str:
    ts = ev.get("startTimestamp")
    if ts:
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            pass
    for key in ("startDate", "formatedStartDate"):
        raw = str(ev.get(key) or "")
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            return raw[:10]
    return ""


def select_recent_finished_events(
    events: Iterable[dict], n_games: int, before_date: str = ""
) -> List[dict]:
    """Newest finished games strictly before `before_date` (slate day).

    Sofascore `/events/last/0` is chronological oldest-first, newest at the
    end of the page. Taking the first N without sorting yields January leftovers.
    """
    cutoff = str(before_date or "").strip()[:10]
    picked: List[dict] = []
    seen = set()
    for ev in events or []:
        if str((ev.get("status") or {}).get("type") or "") != "finished":
            continue
        eid = ev.get("id")
        if eid is None or eid in seen:
            continue
        gd = _event_date(ev)
        if len(gd) < 10:
            continue
        if cutoff and gd >= cutoff:
            continue
        seen.add(eid)
        picked.append(ev)
    picked.sort(key=lambda e: (int(e.get("startTimestamp") or 0), _event_date(e)), reverse=True)
    return picked[: max(0, int(n_games))]


_APPEARANCE_KEYS = (
    "pa", "sh", "sog", "g", "a", "sv", "fc", "tk",
)
# Sofascore drops these keys at 0; PrizePicks Last 5 still shows 0.
_OMITTED_ZERO_KEYS = (
    "tk", "clearances", "crosses", "kp",
    "pa", "sh", "sog", "sv",
)


def _has_matchlog_values(stats: dict) -> bool:
    return any(
        stats.get(k) is not None
        for k in (
            "pa", "clearances", "dribble_attempts", "tk", "crosses",
            "sh", "sog", "g", "a", "kp", "sv", "fc",
        )
    )


def fill_omitted_zero_counts(stats: dict) -> dict:
    """If the player appeared, treat missing tackle/clearance/cross/key-pass as 0.

    Sofascore lineup JSON omits ``totalTackle`` (etc.) at zero. Skipping those
    rows made L5 jump to older non-zero games, so Goblin 0.5 looked like 5/5
    while PrizePicks Last 5 was 2/5 vs 1.5.
    """
    out = dict(stats or {})
    appeared = any(out.get(k) is not None for k in _APPEARANCE_KEYS)
    if not appeared:
        return out
    for key in _OMITTED_ZERO_KEYS:
        if out.get(key) is None:
            out[key] = 0.0
    return out


_SOCCER_GAP_COLS = (
    ("clearances", "REAL"),
    ("dribble_attempts", "REAL"),
    ("crosses", "REAL"),
)


def ensure_soccer_gap_columns(con) -> None:
    """Add Sofascore-only columns on older soccer tables (live DB often lacks them)."""
    have = {str(r[1]).lower() for r in con.execute("PRAGMA table_info(soccer)").fetchall()}
    with con:
        for col, typ in _SOCCER_GAP_COLS:
            if col not in have:
                con.execute(f"ALTER TABLE soccer ADD COLUMN {col} {typ}")


def _make_session():
    from utils.prizepicks_http import curl_impersonate, ensure_chrome131

    ensure_chrome131()
    from curl_cffi.requests import Session as CurlSession

    session = CurlSession(impersonate=curl_impersonate())
    session.headers.update(SOFA_HEADERS)
    return session


def _session():
    if not getattr(_tls, "session", None):
        _tls.session = _make_session()
    return _tls.session


def _get_json(url: str, retries: int = 3) -> Optional[dict]:
    session = _session()
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            time.sleep(0.12 + random.uniform(0, 0.18))
            resp = session.get(url, timeout=20)
            if resp.status_code in (403, 429):
                time.sleep(1.5 * attempt)
                last_err = f"HTTP {resp.status_code}"
                continue
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                if resp.status_code in (404,):
                    return None
                continue
            data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception as exc:
            last_err = str(exc)
            time.sleep(0.4 * attempt)
    if last_err:
        return None
    return None


def _search_player(name: str, team: str) -> Optional[dict]:
    queries = []
    team_n = str(team or "").strip()
    if team_n:
        queries.append(f"{name} {team_n}")
    queries.append(name)
    parts = [p for p in str(name or "").split() if p]
    if len(parts) >= 2:
        queries.append(parts[-1])
    seen = set()
    for q in queries:
        q = str(q or "").strip()
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        data = _get_json(SOFA_SEARCH.format(q=quote(q)))
        if not data:
            continue
        hit = pick_search_hit(data.get("results") or [], name, team_n)
        if hit and hit.get("id"):
            return hit
    return None


def _finished_events(pid: int, n_games: int, before_date: str = "") -> List[dict]:
    raw: List[dict] = []
    for page in (0, 1):
        data = _get_json(SOFA_EVENTS.format(pid=pid, page=page))
        raw.extend((data or {}).get("events") or [])
    return select_recent_finished_events(raw, n_games, before_date=before_date)


def _player_lineup_stats(event: dict, sofa_id: int) -> Optional[dict]:
    eid = event.get("id")
    if eid is None:
        return None
    data = _get_json(SOFA_LINEUPS.format(eid=eid))
    if not data:
        return {"missing": True}
    sid = str(sofa_id)
    for side in ("home", "away"):
        for entry in ((data.get(side) or {}).get("players") or []):
            player = entry.get("player") or {}
            if str(player.get("id")) != sid:
                continue
            stats = extract_matchlog_stats(entry.get("statistics") or {})
            home = str((event.get("homeTeam") or {}).get("name") or "")
            away = str((event.get("awayTeam") or {}).get("name") or "")
            league = str(
                ((event.get("tournament") or {}).get("uniqueTournament") or {}).get("name")
                or (event.get("tournament") or {}).get("name")
                or ""
            )
            team_name = home if side == "home" else away
            return {
                "event_id": str(eid),
                "game_date": _event_date(event),
                "home": home,
                "away": away,
                "league": league,
                "team_name": team_name,
                **stats,
            }
    return {"missing": True}


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "players": {}, "player_stats": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "players": {}, "player_stats": {}}
    if not isinstance(data, dict):
        return {"version": 1, "players": {}, "player_stats": {}}
    data.setdefault("players", {})
    data.setdefault("player_stats", {})
    return data


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _upsert_rows(con, rows: List[dict]) -> int:
    if not rows:
        return 0
    ensure_soccer_gap_columns(con)
    sql = """
        INSERT OR REPLACE INTO soccer (
            game_date, event_id, league, home_team, away_team,
            player, team, espn_player_id,
            pa, tk, clearances, dribble_attempts, crosses,
            sh, sog, g, a, kp, sv, fc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    data = [
        (
            r.get("game_date"),
            r.get("event_id"),
            r.get("league") or "sofascore",
            r.get("home_team") or "",
            r.get("away_team") or "",
            r.get("player"),
            r.get("team") or "",
            r.get("espn_player_id") or "",
            r.get("pa"),
            r.get("tk"),
            r.get("clearances"),
            r.get("dribble_attempts"),
            r.get("crosses"),
            r.get("sh"),
            r.get("sog"),
            r.get("g"),
            r.get("a"),
            r.get("kp"),
            r.get("sv"),
            r.get("fc"),
        )
        for r in rows
    ]
    with con:
        con.executemany(sql, data)
    return len(rows)


def _is_combo(player: str, espn_id: str) -> bool:
    return "+" in str(player or "") or "|" in str(espn_id or "")


def _row_game_date(row) -> str:
    for col in ("game_date", "game_start", "start_time", "start"):
        raw = str(row.get(col) or "").strip()
        if not raw:
            continue
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.notna(ts):
            return ts.strftime("%Y-%m-%d")
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            return raw[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _unique_targets(slate: pd.DataFrame, *, gap_only: bool = True) -> List[dict]:
    by_key: Dict[tuple, dict] = {}
    pred = needs_gap_matchlog if gap_only else needs_matchlog
    for _, row in slate.iterrows():
        if not pred(str(row.get("prop_norm") or ""), str(row.get("prop_type") or "")):
            continue
        # Demons are not on the best-props list; skip them so gap fill stays bounded.
        pick = str(row.get("pick_type") or "").lower()
        if gap_only and "dem" in pick:
            continue
        player = str(row.get("player") or "").strip()
        team = str(row.get("team") or "").strip()
        espn_id = str(
            row.get("espn_player_id") or row.get("espn_id") or row.get("ESPN_PLAYER_ID") or ""
        ).strip()
        if espn_id.endswith(".0") and espn_id[:-2].isdigit():
            espn_id = espn_id[:-2]
        if not player or _is_combo(player, espn_id):
            continue
        key = (player.lower(), team.lower(), espn_id)
        gd = _row_game_date(row)
        rec = by_key.get(key)
        if rec:
            if gd and (not rec.get("before_date") or gd < rec["before_date"]):
                rec["before_date"] = gd
            continue
        by_key[key] = {"player": player, "team": team, "espn_id": espn_id, "before_date": gd}
    return list(by_key.values())


def _club_like(hint: str, db_team: str) -> bool:
    """Same club if codes match or one contains the other (MILLWALL vs MIL)."""
    import re

    h = re.sub(r"[^A-Z0-9]", "", str(hint or "").upper())
    d = re.sub(r"[^A-Z0-9]", "", str(db_team or "").upper())
    if not h or not d:
        return True
    if h == d:
        return True
    if len(h) >= 3 and len(d) >= 3 and (h in d or d in h):
        return True
    return False


def _player_newest_game_date(con, player: str, team: str = "") -> str:
    name = str(player or "").strip()
    if not name:
        return ""
    try:
        rows = con.execute(
            "SELECT game_date, team FROM soccer WHERE lower(player) = ? "
            "ORDER BY game_date DESC",
            (name.lower(),),
        ).fetchall()
    except Exception:
        return ""
    hint = str(team or "").strip()
    for row in rows:
        gd = str(row[0] or "")[:10]
        if not gd:
            continue
        if hint and not _club_like(hint, str(row[1] or "")):
            continue
        return gd
    return ""


def _player_club_game_count(con, player: str, team: str = "", *, limit: int = 5) -> int:
    name = str(player or "").strip()
    if not name:
        return 0
    try:
        rows = con.execute(
            "SELECT game_date, team FROM soccer WHERE lower(player) = ? "
            "ORDER BY game_date DESC",
            (name.lower(),),
        ).fetchall()
    except Exception:
        return 0
    hint = str(team or "").strip()
    seen: set[str] = set()
    for row in rows:
        gd = str(row[0] or "")[:10]
        if not gd or gd in seen:
            continue
        if hint and not _club_like(hint, str(row[1] or "")):
            continue
        seen.add(gd)
        if len(seen) >= int(limit):
            return len(seen)
    return len(seen)


def _stale_espn_targets(slate: pd.DataFrame, con, *, max_age_days: int = 4) -> List[dict]:
    """ESPN counting markets whose club tape is shorter or older than PP Last 5.

    Gap-only fill skips shots/saves/goals. Championship keepers often have one
    ESPN row plus internationals; L5 then looks like 1/5 instead of PP's 5/5.
    """
    from datetime import datetime as dt

    by_key: Dict[tuple, dict] = {}
    for _, row in slate.iterrows():
        pn = str(row.get("prop_norm") or "")
        pt = str(row.get("prop_type") or "")
        if not needs_matchlog(pn, pt) or needs_gap_matchlog(pn, pt):
            continue
        pick = str(row.get("pick_type") or "").lower()
        if "dem" in pick:
            continue
        if "standard" not in pick and "goblin" not in pick:
            continue
        player = str(row.get("player") or "").strip()
        team = str(row.get("team") or "").strip()
        espn_id = str(
            row.get("espn_player_id") or row.get("espn_id") or row.get("ESPN_PLAYER_ID") or ""
        ).strip()
        if espn_id.endswith(".0") and espn_id[:-2].isdigit():
            espn_id = espn_id[:-2]
        if not player or _is_combo(player, espn_id):
            continue
        key = (player.lower(), team.lower(), espn_id)
        if key in by_key:
            continue
        slate_day = _row_game_date(row)
        newest = _player_newest_game_date(con, player, team)
        club_n = _player_club_game_count(con, player, team, limit=5)
        is_saves = "save" in pn or "save" in pt.lower()
        # Short club tapes are common for Championship GKs (1 ESPN row + NT).
        # Missing shooters are not stale-ESPN — refetching them hangs the slate.
        stale = bool(is_saves and club_n < 5)
        if not stale and slate_day and newest:
            try:
                delta = (
                    dt.strptime(slate_day[:10], "%Y-%m-%d")
                    - dt.strptime(newest[:10], "%Y-%m-%d")
                ).days
                stale = delta >= int(max_age_days)
            except ValueError:
                stale = True
        if stale:
            by_key[key] = {
                "player": player,
                "team": team,
                "espn_id": espn_id,
                "before_date": slate_day,
            }
    return list(by_key.values())


def _fetch_one(target: dict, cache: dict, n_games: int) -> dict:
    player = target["player"]
    team = target["team"]
    pkey = player_cache_key(player, team)
    cached = (cache.get("players") or {}).get(pkey) or {}
    sofa_id = cached.get("sofa_id")
    sofa_name = cached.get("sofa_name") or player
    sofa_team = str(cached.get("sofa_team") or "")
    if not sofa_id:
        hit = _search_player(player, team)
        if not hit:
            return {"player": player, "team": team, "error": "no_sofascore_id", "rows": []}
        sofa_id = hit.get("id")
        sofa_name = str(hit.get("name") or player)
        sofa_team = str((hit.get("team") or {}).get("name") or "")
    try:
        sofa_id_int = int(sofa_id)
    except (TypeError, ValueError):
        return {"player": player, "team": team, "error": "bad_sofascore_id", "rows": []}

    cached_stats = ((cache.get("player_stats") or {}).get(str(sofa_id_int)) or {})
    events = _finished_events(sofa_id_int, n_games, before_date=str(target.get("before_date") or ""))
    event_payloads: Dict[str, dict] = {}
    rows = []
    for ev in events:
        eid = str(ev.get("id"))
        payload = cached_stats.get(eid)
        # Old cache rows omit shot keys; refetch so L5 can use totalShots.
        if isinstance(payload, dict) and not payload.get("missing") and "sh" not in payload:
            payload = None
        if not payload:
            payload = _player_lineup_stats(ev, sofa_id_int) or {"missing": True}
        event_payloads[eid] = payload
        if payload.get("missing"):
            continue
        stats = {
            "pa": payload.get("pa"),
            "clearances": payload.get("clearances"),
            "dribble_attempts": payload.get("dribble_attempts"),
            "tk": payload.get("tk"),
            "crosses": payload.get("crosses"),
            "sh": payload.get("sh"),
            "sog": payload.get("sog"),
            "g": payload.get("g"),
            "a": payload.get("a"),
            "kp": payload.get("kp"),
            "sv": payload.get("sv"),
            "fc": payload.get("fc"),
        }
        stats = fill_omitted_zero_counts(stats)
        if not _has_matchlog_values(stats):
            continue
        gd = str(payload.get("game_date") or _event_date(ev) or "")
        if len(gd) < 10:
            continue
        rows.append({
            "game_date": gd[:10],
            "event_id": f"sofa_{eid}",
            "league": payload.get("league") or "sofascore",
            "home_team": payload.get("home") or "",
            "away_team": payload.get("away") or "",
            "player": player,
            "team": team,
            "espn_player_id": target.get("espn_id") or None,
            **stats,
        })
    return {
        "player": player,
        "team": team,
        "pkey": pkey,
        "sofa_id": sofa_id_int,
        "sofa_name": sofa_name,
        "sofa_team": sofa_team,
        "event_payloads": event_payloads,
        "rows": rows,
        "error": None,
    }


def enrich_slate_matchlog(
    con,
    slate: pd.DataFrame,
    *,
    workers: int = 6,
    n_games: int = 10,
    cache_path: Optional[Path] = None,
    gap_only: bool = True,
    stale_espn_only: bool = False,
) -> int:
    """Fetch Sofascore match logs for ESPN-null PrizePicks markets and upsert.

    Default ``gap_only=True`` limits targets to passes/tackles/clearances/
    dribbles/crosses/shots-assisted so a full shots slate does not hang.
    ``stale_espn_only=True`` fetches Standard shots/saves/goals whose DB last
    game is older than PP Last 5 (missing this week's appearances).
    """
    ensure_soccer_gap_columns(con)
    if stale_espn_only:
        targets = _stale_espn_targets(slate, con)
    else:
        targets = _unique_targets(slate, gap_only=gap_only)
        if gap_only:
            extra = _stale_espn_targets(slate, con)
            if extra:
                have = {
                    (t["player"].lower(), t["team"].lower(), t.get("espn_id") or "")
                    for t in targets
                }
                for t in extra:
                    key = (t["player"].lower(), t["team"].lower(), t.get("espn_id") or "")
                    if key not in have:
                        targets.append(t)
                        have.add(key)
                print(f"[matchlog] +{len(extra)} stale ESPN last-5 players (shots/saves/goals)")
    if not targets:
        print("[matchlog] no Popular-market rows — skip")
        return 0
    try:
        _make_session()
    except ImportError:
        print("[matchlog] curl_cffi not installed — skip Sofascore fill")
        return 0

    path = Path(cache_path) if cache_path else CACHE_PATH
    cache = _load_cache(path)
    print(
        f"[matchlog] {len(targets)} players need Sofascore L5 "
        f"({'stale ESPN Last 5' if stale_espn_only else ('gap markets' if gap_only else 'all matchlog props')})"
    )

    results = []
    workers = max(1, int(workers or 1))
    if workers == 1:
        for tgt in targets:
            results.append(_fetch_one(tgt, cache, n_games))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_fetch_one, tgt, cache, n_games) for tgt in targets]
            for fut in as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    results.append({"player": "?", "error": str(exc), "rows": []})

    all_rows: List[dict] = []
    misses = []
    for res in results:
        if res.get("error"):
            misses.append(f"{res.get('player')} ({res.get('team') or '?'}: {res.get('error')})")
            continue
        sofa_id = res.get("sofa_id")
        if sofa_id:
            cache["players"][res["pkey"]] = {
                "sofa_id": sofa_id,
                "sofa_name": res.get("sofa_name"),
                "sofa_team": res.get("sofa_team") or "",
            }
            bucket = cache["player_stats"].setdefault(str(sofa_id), {})
            bucket.update(res.get("event_payloads") or {})
        all_rows.extend(res.get("rows") or [])

    n_up = _upsert_rows(con, all_rows)
    try:
        _save_cache(path, cache)
    except Exception as exc:
        print(f"[matchlog] cache save failed: {exc}")
    if misses:
        preview = "; ".join(misses[:8])
        extra = f" (+{len(misses) - 8} more)" if len(misses) > 8 else ""
        print(f"[matchlog] unresolved {len(misses)}: {preview}{extra}")
    print(f"[matchlog] upserted {n_up} Sofascore rows")
    return n_up
