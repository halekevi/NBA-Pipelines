"""
Flask blueprint: /api/hot-players and /api/player-consistency
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

consistency_bp = Blueprint("consistency", __name__)

# Response cache for /api/hot-players (avoid re-parsing multi-MB slate every hit).
_HOT_PLAYERS_TTL_SEC = 300.0
# Overall graded hit rate required to appear on the Hot Players board.
HOT_PLAYERS_MIN_HIT_RATE = 0.70
_hot_players_resp_cache: dict = {"key": None, "payload": None, "expires": 0.0}
_slate_pairs_cache: dict = {"mtime": -1.0, "names": set(), "pairs": set()}


def _eastern_today_ymd() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York")).date().strftime("%Y-%m-%d")
    except Exception:
        return str(date.today())

def _repo_root() -> Path:
    """Repo root whether loaded as ui_runner.routes or routes (cwd = ui_runner)."""
    here = Path(__file__).resolve()
    if here.parent.name == "routes" and here.parent.parent.name == "ui_runner":
        return here.parents[2]
    if here.parent.name == "routes":
        return here.parents[1]
    return here.parents[2]


REPO_ROOT = _repo_root()
_CACHE_CANDIDATES = (
    REPO_ROOT / "data" / "cache" / "player_consistency.json",
    Path(__file__).resolve().parents[1] / "data" / "player_consistency.json",
)


def _cache_path() -> Path:
    """Use the newest on-disk cache (avoids stale data/cache shadowing ui_runner/data on deploy)."""
    existing = [p for p in _CACHE_CANDIDATES if p.is_file()]
    if not existing:
        return _CACHE_CANDIDATES[0]
    return max(existing, key=lambda p: p.stat().st_mtime)

_cache: dict | None = None
_cache_mtime: float = 0.0


def load_consistency_cache(*, force_reload: bool = False) -> dict:
    global _cache, _cache_mtime
    path = _cache_path()
    try:
        mtime = path.stat().st_mtime
        if force_reload or _cache is None or mtime != _cache_mtime:
            with open(path, encoding="utf-8") as f:
                _cache = json.load(f)
            _cache_mtime = mtime
    except FileNotFoundError:
        _cache = {"players": [], "generated_at": None}
        _cache_mtime = 0.0
    except (json.JSONDecodeError, OSError):
        _cache = {"players": [], "generated_at": None}
        _cache_mtime = 0.0
    return _cache


def _resolve_display_prop(player: dict) -> dict | None:
    """Best (prop, direction) slice for Hot Player cards — never rely on client-only logic."""
    bp = player.get("display_prop")
    if isinstance(bp, dict) and bp.get("prop_type"):
        return bp
    bp = player.get("best_prop")
    if isinstance(bp, dict) and bp.get("prop_type"):
        return bp
    for alt in player.get("best_props") or []:
        if isinstance(alt, dict) and alt.get("prop_type"):
            return alt
    return None


def _enrich_hot_player(player: dict) -> dict:
    out = dict(player)
    dp = _resolve_display_prop(out)
    out["display_prop"] = dp
    return out


def _player_direction(p: dict) -> str:
    best = p.get("best_prop")
    if isinstance(best, dict) and best.get("direction"):
        return str(best["direction"]).upper().strip()
    return str(p.get("direction", "")).upper().strip()


def _filter_players(
    players: list[dict],
    sport: str | None,
    tier: str | None,
    today_only: bool,
    limit: int,
    direction: str | None,
) -> list[dict]:
    out = players
    if sport:
        out = [p for p in out if str(p.get("sport", "")).upper() == sport.upper()]
    if tier:
        out = [p for p in out if p.get("tier") == tier.lower()]
    if today_only:
        out = [p for p in out if p.get("on_today_slate")]
    if direction:
        d = direction.upper()
        out = [p for p in out if _player_direction(p) == d]
    return out[:limit]


@consistency_bp.route("/api/player-consistency")
def player_consistency():
    sport = request.args.get("sport")
    tier = request.args.get("tier")
    today_only = request.args.get("today_only", "0") == "1"
    direction = request.args.get("direction")
    limit = min(int(request.args.get("limit", 50)), 100)
    sort_key = request.args.get("sort", "hit_rate")

    data = load_consistency_cache()
    players = list(data.get("players", []))
    players = _filter_players(players, sport, tier, today_only, 9999, direction)

    if sort_key == "balance_score":
        players = sorted(
            [p for p in players if p.get("balance_score") is not None],
            key=lambda p: (-float(p["balance_score"]), -float(p.get("hit_rate", 0))),
        )
    elif sort_key == "total":
        players = sorted(players, key=lambda p: -int(p.get("total", 0)))
    else:
        players = sorted(players, key=lambda p: (-float(p.get("hit_rate", 0)), -int(p.get("total", 0))))

    players = players[:limit]
    for i, p in enumerate(players, 1):
        p["rank"] = i

    return jsonify(
        {
            "generated_at": data.get("generated_at"),
            "filters": {
                "sport": sport,
                "tier": tier,
                "today_only": today_only,
                "direction": direction,
                "sort": sort_key,
                "limit": limit,
            },
            "count": len(players),
            "players": players,
        }
    )


def _load_live_today_slate() -> tuple[set[str], set[tuple[str, str]]]:
    """Reload slate_latest with strict ET game_date (no stale fallback)."""
    import sys

    root = REPO_ROOT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from scripts.build_player_consistency_ui import load_today_slate

        return load_today_slate()
    except Exception:
        return set(), set()


def _load_live_today_slate_cached() -> tuple[set[str], set[tuple[str, str]]]:
    """Cache slate name/pair sets by slate_latest.json mtime."""
    slate_path = REPO_ROOT / "ui_runner" / "templates" / "slate_latest.json"
    try:
        mtime = slate_path.stat().st_mtime if slate_path.is_file() else 0.0
    except OSError:
        mtime = 0.0
    if mtime == _slate_pairs_cache["mtime"] and _slate_pairs_cache["mtime"] >= 0:
        return _slate_pairs_cache["names"], _slate_pairs_cache["pairs"]
    names, pairs = _load_live_today_slate()
    _slate_pairs_cache["mtime"] = mtime
    _slate_pairs_cache["names"] = names
    _slate_pairs_cache["pairs"] = pairs
    return names, pairs


def _player_on_live_slate(p: dict, slate_pairs: set[tuple[str, str]]) -> bool:
    if not slate_pairs:
        return False
    name = str(p.get("player") or "").strip().lower()
    sport = str(p.get("sport") or "").upper().strip()
    return bool(name and sport and (name, sport) in slate_pairs)


@consistency_bp.route("/api/hot-players")
def hot_players():
    sport = request.args.get("sport")
    limit = min(int(request.args.get("limit", 5)), 20)

    path = _cache_path()
    try:
        cons_mtime = path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        cons_mtime = 0.0
    slate_path = REPO_ROOT / "ui_runner" / "templates" / "slate_latest.json"
    try:
        slate_mtime = slate_path.stat().st_mtime if slate_path.is_file() else 0.0
    except OSError:
        slate_mtime = 0.0

    cache_key = (cons_mtime, slate_mtime, sport or "", limit, _eastern_today_ymd())
    now = time.time()
    if (
        _hot_players_resp_cache["key"] == cache_key
        and _hot_players_resp_cache["payload"] is not None
        and now < float(_hot_players_resp_cache["expires"])
    ):
        return jsonify(_hot_players_resp_cache["payload"])

    data = load_consistency_cache(force_reload=False)
    players = data.get("players", [])

    _slate_names, slate_pairs = _load_live_today_slate_cached()
    today = [
        p
        for p in players
        if p.get("tier") in ("high", "medium") and _player_on_live_slate(p, slate_pairs)
    ]

    if sport:
        today = [p for p in today if str(p.get("sport", "")).upper() == sport.upper()]

    by_sport: dict[str, list] = {}
    for p in sorted(today, key=lambda x: -float(x.get("hit_rate", 0))):
        if float(p.get("hit_rate") or 0) < HOT_PLAYERS_MIN_HIT_RATE:
            continue
        s = str(p.get("sport", "?"))
        if s not in by_sport:
            by_sport[s] = []
        if len(by_sport[s]) < limit:
            by_sport[s].append(_enrich_hot_player(p))

    payload = {
        "date": _eastern_today_ymd(),
        "generated_at": data.get("generated_at"),
        "cache_path": str(_cache_path()),
        "sports": by_sport,
        "total_featured": sum(len(v) for v in by_sport.values()),
    }
    _hot_players_resp_cache["key"] = cache_key
    _hot_players_resp_cache["payload"] = payload
    _hot_players_resp_cache["expires"] = now + _HOT_PLAYERS_TTL_SEC
    return jsonify(payload)


@consistency_bp.route("/api/hot-players/track-record")
def hot_players_track_record():
    """Rolling Hot Players leg grades (snapshot day -> next-day graded_props)."""
    path = REPO_ROOT / "data" / "hot_players" / "track_record.json"
    ui_path = REPO_ROOT / "ui_runner" / "data" / "hot_players_track_record.json"
    for candidate in (path, ui_path):
        if candidate.is_file():
            try:
                return jsonify(json.loads(candidate.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                break
    return jsonify(
        {
            "updated_at": None,
            "days_tracked": 0,
            "aggregate": {},
            "aggregate_hit_rate": None,
            "recent": [],
            "latest_graded_date": None,
        }
    )


@consistency_bp.route("/api/consistency-leaders")
def consistency_leaders():
    """Season-window line-class consistency leaders (GOB / STD / UND)."""
    candidates = (
        REPO_ROOT / "data" / "slate_consistency" / "consistency_leaders_latest.json",
        REPO_ROOT / "ui_runner" / "data" / "consistency_leaders_latest.json",
        REPO_ROOT / "ui_runner" / "templates" / "consistency_leaders_latest.json",
        Path(__file__).resolve().parents[1] / "data" / "consistency_leaders_latest.json",
    )
    for path in candidates:
        if path.is_file():
            try:
                return jsonify(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    return jsonify(
        {
            "generated_at": None,
            "leaders": [],
            "match_index": [],
            "sports": {},
            "note": "consistency_leaders_latest.json not found",
        }
    )
