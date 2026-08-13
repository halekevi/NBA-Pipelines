#!/usr/bin/env python3
"""
Build UI cache for Hot Players + Player Evaluator tabs.
Reads graded history (retrain_dataset.csv or graded_export_*.csv) and writes:
  data/cache/player_consistency.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RETRAIN_CSV = REPO_ROOT / "data" / "retrain_dataset.csv"
TRAINING_DIR = REPO_ROOT / "data" / "training"
CACHE_DIR = REPO_ROOT / "data" / "cache"
OUTPUT_PATH = CACHE_DIR / "player_consistency.json"
UI_DEPLOY_PATH = REPO_ROOT / "ui_runner" / "data" / "player_consistency.json"
CONSISTENCY_DB = CACHE_DIR / "player_consistency.db"

SPORT_ALIASES = {
    "nba": "NBA",
    "mlb": "MLB",
    "nhl": "NHL",
    "nfl": "NFL",
    "wnba": "WNBA",
    "soccer": "Soccer",
    "tennis": "Tennis",
    "cbb": "CBB",
    "cfb": "CFB",
}

SLATE_PATHS = (
    REPO_ROOT / "ui_runner" / "templates" / "slate_latest.json",
    REPO_ROOT / "mobile" / "www" / "slate_latest.json",
)

TICKETS_PATHS = (
    REPO_ROOT / "ui_runner" / "templates" / "tickets_latest.json",
    REPO_ROOT / "mobile" / "www" / "tickets_latest.json",
)

# Per-sport minimum graded props for a (prop, direction) slice to surface in UI.
_SPORT_MIN: dict[str, int | None] = {
    "NBA1H": None,  # use dynamic rule instead
    "NBA1Q": 20,
    "NBA": 20,
    "WNBA": 15,
    "MLB": 20,
    "NHL": 20,
    "SOCCER": 20,
    "TENNIS": 20,
}
_DYNAMIC_SPORTS = frozenset({"NBA1H"})
# In-season / shallow pools: never let top_n drop today's slate (WNBA was rank 51+).
_SPORT_INCLUDE_ALL = frozenset({"WNBA", "NBA1H", "NBA1Q", "MLB", "SOCCER", "TENNIS"})
TOP_BEST_PROPS = 3
# Floor for a featured (prop, direction) slice. 3 let 3/3 at 100% flood the board.
MIN_DISPLAY_PROPS = 5
_WILSON_Z = 1.64  # ~95% one-sided lower bound; shrinks tiny 100% samples.

# Volume/process props: deprioritized when ranking (weight 0.75 vs 1.0 for outcome props).
VOLUME_PROPS: frozenset[str] = frozenset(
    {
        "3-pt attempted",
        "3 pt attempted",
        "fga",
        "fg attempted",
        "fta",
        "free throws attempted",
        "shots attempted",
        "passes attempted",
        "fouls",
        "turnovers",
        "to",
        "minutes",
        "time on ice",
        "total games",
        "total games won",
        "walks allowed",
        "pitches thrown",
        "batters faced",
        "hits allowed",
        "personal fouls",
        "plus/minus",
    }
)
VOLUME_PROP_WEIGHT = 0.75
OUTCOME_PROP_WEIGHT = 1.0

# NHL graded rows often use snake_case; map to display labels used on PrizePicks cards.
NHL_PROP_DISPLAY: dict[str, str] = {
    "shots_on_goal": "Shots on Goal",
    "power_play_points": "PP Points",
    "blocked_shots": "Blocked Shots",
    "goalie_saves": "Goalie Saves",
    "goalie_fantasy_score": "Goalie Fantasy Score",
    "faceoffs_won": "Faceoffs Won",
    "time_on_ice": "Time on Ice",
    "plus/minus": "Plus/Minus",
}


def find_latest_graded_csv() -> Path | None:
    pattern = sorted(TRAINING_DIR.glob("graded_export_*.csv"), reverse=True)
    return pattern[0] if pattern else None


def _norm_name(name: str) -> str:
    return (name or "").strip().lower()


def load_graded_dataframe() -> tuple[pd.DataFrame, str]:
    if RETRAIN_CSV.is_file():
        return pd.read_csv(RETRAIN_CSV, low_memory=False), RETRAIN_CSV.name
    fallback = find_latest_graded_csv()
    if fallback is None:
        raise FileNotFoundError("No retrain_dataset.csv or graded_export_*.csv found")
    return pd.read_csv(fallback, low_memory=False), fallback.name


def _player_record(
    *,
    player: str,
    sport: str,
    total: int,
    hits: int,
    over_hits: int,
    over_total: int,
    over_rate: float | None,
    under_hits: int,
    under_total: int,
    under_rate: float | None,
    direction: str,
    card_direction: str,
    balance_score: float | None,
    tier: str,
    best_prop: dict | None,
    best_props: list[dict],
) -> dict:
    return {
        "player": str(player),
        "sport": str(sport),
        "total": int(total),
        "hits": int(hits),
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "over_hits": int(over_hits),
        "over_total": int(over_total),
        "over_rate": over_rate,
        "under_hits": int(under_hits),
        "under_total": int(under_total),
        "under_rate": under_rate,
        "direction": card_direction,
        "direction_pooled": direction,
        "tier": tier,
        "balance_score": balance_score,
        "best_prop": best_prop,
        "display_prop": best_prop,
        "best_props": best_props,
        "last_updated": str(date.today()),
    }


def _direction_and_balance(
    over_rate: float | None,
    over_total: int,
    under_rate: float | None,
    under_total: int,
) -> tuple[str, float | None]:
    direction = "BOTH"
    if over_rate is not None and under_rate is not None and over_total >= 10 and under_total >= 10:
        gap = over_rate - under_rate
        if gap > 0.10:
            direction = "OVER"
        elif gap < -0.10:
            direction = "UNDER"
    elif over_rate is not None and over_total >= 10 and (under_total < 10 or under_rate is None):
        direction = "OVER"
    elif under_rate is not None and under_total >= 10 and (over_total < 10 or over_rate is None):
        direction = "UNDER"
    if over_rate is not None and under_rate is not None and over_total >= 5 and under_total >= 5:
        balance_score = round(1 - abs(over_rate - under_rate), 4)
    else:
        balance_score = None
    return direction, balance_score


def _tier_for_total(total: int) -> str:
    if total >= 50:
        return "high"
    if total >= 25:
        return "medium"
    return "low"


def _prop_slices_from_agg(
    slice_rows: list[dict],
    sport: str,
    min_n: int,
) -> list[dict]:
    slices: list[dict] = []
    for raw in slice_rows:
        direction = str(raw.get("direction") or "").upper().strip()
        if direction not in ("OVER", "UNDER"):
            continue
        n = int(raw.get("total") or 0)
        if n < min_n:
            continue
        hits = int(raw.get("hits") or 0)
        prop_raw = str(raw.get("prop") or "")
        prop_type = normalize_prop_display(prop_raw, sport)
        weight = _prop_quality_weight(prop_type, prop_raw)
        hit_rate = round(hits / n, 4) if n else 0.0
        slices.append(
            {
                "prop_type": prop_type,
                "direction": direction,
                "hits": hits,
                "total": n,
                "hit_rate": hit_rate,
                "_sort_score": _slice_sort_score(hits, n, weight),
            }
        )
    slices.sort(
        key=lambda x: (-float(x["_sort_score"]), -int(x["total"]), x["prop_type"]),
    )
    return slices


def _compute_best_props_from_agg(
    slice_rows: list[dict],
    sport: str,
    player_total: int,
    *,
    over_hits: int = 0,
    over_total: int = 0,
    over_rate: float | None = None,
    under_hits: int = 0,
    under_total: int = 0,
    under_rate: float | None = None,
    direction: str = "BOTH",
) -> tuple[dict | None, list[dict]]:
    min_n = _min_for_sport(sport, player_total)
    strict = _prop_slices_from_agg(slice_rows, sport, min_n)
    display_min = _display_min_for(sport, player_total)
    relaxed = _prop_slices_from_agg(slice_rows, sport, display_min) if display_min < min_n else strict
    best_props = [_strip_slice(s) for s in strict[:TOP_BEST_PROPS]]
    pick = strict[0] if strict else (relaxed[0] if relaxed else None)
    best_prop = _strip_slice(pick) if pick else None
    pooled = _pooled_direction_slice(
        over_hits=over_hits,
        over_total=over_total,
        over_rate=over_rate,
        under_hits=under_hits,
        under_total=under_total,
        under_rate=under_rate,
        direction=direction,
    )
    best_prop = _finalize_display_prop(best_prop, pooled)
    return best_prop, best_props


def compute_consistency_from_db(db_path: Path, min_props: int = 10) -> list[dict]:
    """Player-level Hot Players records from player_consistency.db (all in-season sports)."""
    import sqlite3
    from collections import defaultdict

    if not db_path.is_file():
        return []
    con = None
    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT player_name, sport, prop_type, direction,
                   SUM(decided_count) AS decided, SUM(hit_count) AS hits
            FROM player_consistency
            GROUP BY player_name, sport, prop_type, direction
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if con is not None:
            con.close()

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        player = str(r["player_name"] or "").strip()
        sport = _normalize_slate_sport(str(r["sport"] or ""))
        if not player or not sport:
            continue
        grouped[(player, sport)].append(
            {
                "prop": r["prop_type"],
                "direction": r["direction"],
                "total": int(r["decided"] or 0),
                "hits": int(r["hits"] or 0),
            }
        )

    results: list[dict] = []
    for (player, sport), slice_rows in grouped.items():
        total = sum(int(s["total"]) for s in slice_rows)
        if total < min_props:
            continue
        hits = sum(int(s["hits"]) for s in slice_rows)
        over = [s for s in slice_rows if str(s["direction"]).upper() == "OVER"]
        under = [s for s in slice_rows if str(s["direction"]).upper() == "UNDER"]
        over_total = sum(int(s["total"]) for s in over)
        over_hits = sum(int(s["hits"]) for s in over)
        under_total = sum(int(s["total"]) for s in under)
        under_hits = sum(int(s["hits"]) for s in under)
        over_rate = round(over_hits / over_total, 4) if over_total else None
        under_rate = round(under_hits / under_total, 4) if under_total else None
        direction, balance_score = _direction_and_balance(
            over_rate, over_total, under_rate, under_total
        )
        tier = _tier_for_total(total)
        best_prop, best_props = _compute_best_props_from_agg(
            slice_rows,
            sport,
            total,
            over_hits=over_hits,
            over_total=over_total,
            over_rate=over_rate,
            under_hits=under_hits,
            under_total=under_total,
            under_rate=under_rate,
            direction=direction,
        )
        card_direction = (
            str(best_prop["direction"])
            if best_prop and best_prop.get("direction")
            else direction
        )
        results.append(
            _player_record(
                player=player,
                sport=sport,
                total=total,
                hits=hits,
                over_hits=over_hits,
                over_total=over_total,
                over_rate=over_rate,
                under_hits=under_hits,
                under_total=under_total,
                under_rate=under_rate,
                direction=direction,
                card_direction=card_direction,
                balance_score=balance_score,
                tier=tier,
                best_prop=best_prop,
                best_props=best_props,
            )
        )

    tier_order = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda r: (r["sport"], tier_order[r["tier"]], -r["hit_rate"]))
    return results


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
    col_map = {
        "player_name": "player",
        "name": "player",
        "pick_direction": "direction",
        "side": "direction",
        "prop_type": "prop",
        "stat_type": "prop",
        "result": "outcome",
        "grade": "outcome",
        "date": "game_date",
        "file_date": "game_date",
    }
    for src, dst in col_map.items():
        if src in df.columns and dst not in df.columns:
            df = df.rename(columns={src: dst})
    if "outcome" not in df.columns and "result" in df.columns:
        df["outcome"] = df["result"]
    if "outcome" in df.columns:
        df["outcome"] = (
            df["outcome"]
            .astype(str)
            .str.upper()
            .str.strip()
            .replace({"WIN": "HIT", "LOSS": "MISS", "LOSE": "MISS"})
        )
    elif "result_binary" in df.columns:
        df["outcome"] = df["result_binary"].map({1: "HIT", 0: "MISS", True: "HIT", False: "MISS"})
    elif "hit" in df.columns:
        df["outcome"] = df["hit"].map({1: "HIT", 0: "MISS", True: "HIT", False: "MISS"})
    return df


def normalize_prop_display(raw: str, sport: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return "Unknown"
    if sport == "NHL":
        key = s.lower().replace(" ", "_")
        if key in NHL_PROP_DISPLAY:
            return NHL_PROP_DISPLAY[key]
        if "_" in key:
            return key.replace("_", " ").title()
    if s.islower() and "_" in s:
        return s.replace("_", " ").title()
    return s


def _prop_match_key(label: str) -> str:
    return str(label or "").strip().lower().replace("_", " ").replace("-", " ")


def _is_volume_prop(prop_type: str, prop_raw: str = "") -> bool:
    for label in (prop_type, prop_raw):
        if _prop_match_key(label) in VOLUME_PROPS:
            return True
    return False


def _prop_quality_weight(prop_type: str, prop_raw: str = "") -> float:
    return VOLUME_PROP_WEIGHT if _is_volume_prop(prop_type, prop_raw) else OUTCOME_PROP_WEIGHT


def _min_for_sport(sport: str, total: int) -> int:
    sport_u = str(sport).upper()
    if sport_u in _DYNAMIC_SPORTS:
        return max(5, round(total * 0.30))
    min_val = _SPORT_MIN.get(sport_u, 20)
    return min_val if min_val is not None else 20


def _display_min_for(sport: str, player_total: int) -> int:
    """Relaxed slice floor for the card title — never as low as 3/3."""
    sport_min = _min_for_sport(sport, player_total)
    floor = MIN_DISPLAY_PROPS
    if player_total < 16:
        floor = max(4, min(MIN_DISPLAY_PROPS, max(4, player_total // 2)))
    return min(sport_min, floor)


def _wilson_lower(hits: int, n: int, z: float = _WILSON_Z) -> float:
    """Lower confidence bound so 3/3 at 100% does not outrank a real sample."""
    if n <= 0:
        return 0.0
    phat = hits / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = phat + z2 / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def _slice_sort_score(hits: int, n: int, weight: float) -> float:
    # log(n) prefers 12/18 over 3/3 at 100%; Wilson already shrinks the rate.
    return _wilson_lower(hits, n) * weight * math.log(n + 1.0)


def _pooled_direction_slice(
    *,
    over_hits: int,
    over_total: int,
    over_rate: float | None,
    under_hits: int,
    under_total: int,
    under_rate: float | None,
    direction: str,
) -> dict | None:
    """Fallback card market: all overs or all unders, not a 5/5 micro-slice."""
    d = str(direction or "").upper()
    if d == "UNDER" and under_total >= MIN_DISPLAY_PROPS and under_rate is not None:
        return {
            "prop_type": "All Unders",
            "direction": "UNDER",
            "hits": int(under_hits),
            "total": int(under_total),
            "hit_rate": float(under_rate),
        }
    if over_total >= MIN_DISPLAY_PROPS and over_rate is not None:
        return {
            "prop_type": "All Overs",
            "direction": "OVER",
            "hits": int(over_hits),
            "total": int(over_total),
            "hit_rate": float(over_rate),
        }
    if under_total >= MIN_DISPLAY_PROPS and under_rate is not None:
        return {
            "prop_type": "All Unders",
            "direction": "UNDER",
            "hits": int(under_hits),
            "total": int(under_total),
            "hit_rate": float(under_rate),
        }
    return None


def _finalize_display_prop(pick: dict | None, pooled: dict | None) -> dict | None:
    """Do not advertise 100% on n<8 (5/5, 6/6) when a real pooled sample exists."""
    if pick is None:
        return pooled
    n = int(pick.get("total") or 0)
    hr = float(pick.get("hit_rate") or 0)
    if hr >= 0.999 and n < 8 and pooled and int(pooled.get("total") or 0) > n:
        return pooled
    return pick


def _prop_slices_for_group(
    grp: pd.DataFrame,
    sport: str,
    min_n: int,
) -> list[dict]:
    if "prop" not in grp.columns:
        return []
    slices: list[dict] = []
    for (prop_raw, direction), sub in grp.groupby(["prop", "direction"], sort=False):
        direction = str(direction).upper().strip()
        if direction not in ("OVER", "UNDER"):
            continue
        n = len(sub)
        if n < min_n:
            continue
        hits = int((sub["outcome"] == "HIT").sum())
        hit_rate = round(hits / n, 4)
        prop_type = normalize_prop_display(str(prop_raw), sport)
        weight = _prop_quality_weight(prop_type, str(prop_raw))
        slices.append(
            {
                "prop_type": prop_type,
                "direction": direction,
                "hits": hits,
                "total": int(n),
                "hit_rate": hit_rate,
                "_sort_score": _slice_sort_score(hits, n, weight),
            }
        )
    slices.sort(
        key=lambda x: (-float(x["_sort_score"]), -int(x["total"]), x["prop_type"]),
    )
    return slices


def _strip_slice(s: dict) -> dict:
    return {k: v for k, v in s.items() if k != "_sort_score"}


def _compute_best_props(grp: pd.DataFrame, sport: str) -> tuple[dict | None, list[dict]]:
    player_total = len(grp)
    min_n = _min_for_sport(sport, player_total)
    strict = _prop_slices_for_group(grp, sport, min_n)
    display_min = _display_min_for(sport, player_total)
    relaxed = _prop_slices_for_group(grp, sport, display_min) if display_min < min_n else strict

    best_props = [_strip_slice(s) for s in strict[:TOP_BEST_PROPS]]
    pick = strict[0] if strict else (relaxed[0] if relaxed else None)
    best_prop = _strip_slice(pick) if pick else None
    over_grp = grp[grp["direction"] == "OVER"]
    under_grp = grp[grp["direction"] == "UNDER"]
    over_total = len(over_grp)
    over_hits = int((over_grp["outcome"] == "HIT").sum()) if over_total else 0
    under_total = len(under_grp)
    under_hits = int((under_grp["outcome"] == "HIT").sum()) if under_total else 0
    over_rate = round(over_hits / over_total, 4) if over_total else None
    under_rate = round(under_hits / under_total, 4) if under_total else None
    direction, _balance = _direction_and_balance(over_rate, over_total, under_rate, under_total)
    pooled = _pooled_direction_slice(
        over_hits=over_hits,
        over_total=over_total,
        over_rate=over_rate,
        under_hits=under_hits,
        under_total=under_total,
        under_rate=under_rate,
        direction=direction,
    )
    best_prop = _finalize_display_prop(best_prop, pooled)
    return best_prop, best_props


def compute_consistency(df: pd.DataFrame, min_props: int = 10) -> list[dict]:
    df = df.copy()
    df["sport"] = df["sport"].astype(str).str.lower().map(SPORT_ALIASES).fillna(df["sport"].astype(str).str.upper())
    df["direction"] = df["direction"].astype(str).str.upper().str.strip()
    df["outcome"] = df["outcome"].astype(str).str.upper().str.strip()
    df = df[df["outcome"].isin(["HIT", "MISS"])]

    results: list[dict] = []
    for (player, sport), grp in df.groupby(["player", "sport"], sort=False):
        total = len(grp)
        if total < min_props:
            continue

        hits = int((grp["outcome"] == "HIT").sum())
        hit_rate = round(hits / total, 4)

        over_grp = grp[grp["direction"] == "OVER"]
        under_grp = grp[grp["direction"] == "UNDER"]

        over_total = len(over_grp)
        over_hits = int((over_grp["outcome"] == "HIT").sum()) if over_total else 0
        over_rate = round(over_hits / over_total, 4) if over_total else None

        under_total = len(under_grp)
        under_hits = int((under_grp["outcome"] == "HIT").sum()) if under_total else 0
        under_rate = round(under_hits / under_total, 4) if under_total else None

        direction = "BOTH"
        if over_rate is not None and under_rate is not None and over_total >= 10 and under_total >= 10:
            gap = over_rate - under_rate
            if gap > 0.10:
                direction = "OVER"
            elif gap < -0.10:
                direction = "UNDER"
        elif over_rate is not None and over_total >= 10 and (under_total < 10 or under_rate is None):
            direction = "OVER"
        elif under_rate is not None and under_total >= 10 and (over_total < 10 or over_rate is None):
            direction = "UNDER"

        if over_rate is not None and under_rate is not None and over_total >= 5 and under_total >= 5:
            balance_score = round(1 - abs(over_rate - under_rate), 4)
        else:
            balance_score = None

        tier = "high" if total >= 50 else "medium" if total >= 25 else "low"

        best_prop, best_props = _compute_best_props(grp, str(sport))
        display_prop = best_prop
        card_direction = (
            str(best_prop["direction"])
            if best_prop and best_prop.get("direction")
            else direction
        )  # direction_pooled retained for filters when no qualifying slice

        row: dict = {
            "player": str(player),
            "sport": str(sport),
            "total": int(total),
            "hits": hits,
            "hit_rate": hit_rate,
            "over_hits": over_hits,
            "over_total": int(over_total),
            "over_rate": over_rate,
            "under_hits": under_hits,
            "under_total": int(under_total),
            "under_rate": under_rate,
            "direction": card_direction,
            "direction_pooled": direction,
            "tier": tier,
            "balance_score": balance_score,
            "best_prop": best_prop,
            "display_prop": display_prop,
            "best_props": best_props,
            "last_updated": str(date.today()),
        }
        results.append(row)

    tier_order = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda r: (r["sport"], tier_order[r["tier"]], -r["hit_rate"]))
    return results


def _normalize_slate_sport(raw: str) -> str:
    key = str(raw or "").strip().lower()
    return SPORT_ALIASES.get(key, str(raw or "").strip().upper())


def slate_pair_key(player: str, sport: str) -> tuple[str, str]:
    """Canonical (name, sport) key matching slate_latest pair sets."""
    return (_norm_name(player), _normalize_slate_sport(sport))


def _sport_level_slate_date(data: dict, sport_key: str) -> str:
    """Top-level tennis_date / soccer_date when row game_date is stale."""
    key = str(sport_key or "").strip().lower()
    field = {
        "tennis": "tennis_date",
        "soccer": "soccer_date",
    }.get(key)
    if not field:
        return ""
    return str(data.get(field) or "")[:10]


def _players_from_slate_json(
    data: dict,
    today_str: str | None = None,
) -> tuple[set[str], set[tuple[str, str]]]:
    players: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    td = str(today_str or date.today())[:10]
    sports = data.get("sports") or {}
    if not isinstance(sports, dict):
        return players, pairs
    for sport_key, rows in sports.items():
        if not isinstance(rows, list):
            continue
        sport_norm = _normalize_slate_sport(str(sport_key))
        # Tennis/soccer often keep stale per-row game_date while slate marks
        # the board day via tennis_date / soccer_date.
        sport_day = _sport_level_slate_date(data, str(sport_key))
        trust_sport_day = bool(sport_day and sport_day == td)
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not trust_sport_day:
                gd = str(row.get("game_date") or "").strip()[:10]
                if gd and gd != td:
                    continue
                if not gd:
                    gt = str(row.get("game_time") or "").strip()
                    m = re.match(r"^(\d{4}-\d{2}-\d{2})", gt)
                    if m and m.group(1) != td:
                        continue
            name = row.get("player") or row.get("player_name") or ""
            if not name:
                continue
            clean = str(name).strip()
            players.add(clean)
            row_sport = row.get("sport") or sport_key
            pairs.add(slate_pair_key(clean, str(row_sport) if row_sport else sport_norm))
    return players, pairs


def _eastern_today_ymd() -> str:
    """US Eastern calendar date for slate day gates (matches home Slate Explorer)."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York")).date().strftime("%Y-%m-%d")
    except Exception:
        return str(date.today())


def _players_from_tickets_json(
    data: dict,
    today_str: str | None = None,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Supplement slate pairs from published tickets (helps when tennis dates are stale)."""
    players: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    td = str(today_str or date.today())[:10]
    board_date = str(data.get("date") or data.get("tennis_date") or "")[:10]
    if board_date and board_date != td:
        return players, pairs

    def _add_leg(leg: dict) -> None:
        if not isinstance(leg, dict):
            return
        name = leg.get("player") or leg.get("player_name") or ""
        sport = leg.get("sport") or ""
        if not name or not sport:
            return
        clean = str(name).strip()
        players.add(clean)
        pairs.add(slate_pair_key(clean, str(sport)))

    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for ticket in group.get("tickets") or []:
            if not isinstance(ticket, dict):
                continue
            for leg in ticket.get("legs") or []:
                _add_leg(leg)
        for leg in group.get("legs") or []:
            _add_leg(leg)
    for key in ("hot_legs", "cold_legs"):
        legs = data.get(key)
        if isinstance(legs, list):
            for leg in legs:
                _add_leg(leg)
    return players, pairs


def load_today_slate() -> tuple[set[str], set[tuple[str, str]]]:
    players: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    today_str = _eastern_today_ymd()

    for path in SLATE_PATHS:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        names, slate_pairs = _players_from_slate_json(data, today_str)
        if names:
            players.update(names)
            pairs.update(slate_pairs)

    for path in TICKETS_PATHS:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        names, ticket_pairs = _players_from_tickets_json(data, today_str)
        if names:
            players.update(names)
            pairs.update(ticket_pairs)

    step8_dir = CACHE_DIR
    for sport_file in step8_dir.glob("step8_*.json"):
        try:
            data = json.loads(sport_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        picks = data if isinstance(data, list) else data.get("picks", [])
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            gd = pick.get("game_date", "") or pick.get("date", "")
            if gd and str(gd)[:10] != today_str:
                continue
            name = pick.get("player") or pick.get("player_name") or ""
            if not name:
                continue
            clean = str(name).strip()
            players.add(clean)
            pairs.add(
                slate_pair_key(
                    clean,
                    str(pick.get("sport") or sport_file.stem.replace("step8_", "")),
                )
            )

    return players, pairs


def tag_today_slate(
    records: list[dict],
    today_players: set[str],
    slate_pairs: set[tuple[str, str]] | None = None,
) -> list[dict]:
    today_norm = {_norm_name(p) for p in today_players}
    pair_set = slate_pairs or set()
    for r in records:
        pair = slate_pair_key(str(r.get("player") or ""), str(r.get("sport") or ""))
        on_pair = pair in pair_set if pair_set else False
        r["on_today_slate"] = pair[0] in today_norm or on_pair
    return records


def select_top_records(
    records: list[dict],
    top_n: int,
    slate_pairs: set[tuple[str, str]],
) -> list[dict]:
    """Keep every high/medium player (Hot Players live-filters today's slate).

    Low-tier is capped at top_n unless the sport is in-season or the player is
    on today's slate. A 5AM build with an empty slate used to drop WNBA/tennis
    entirely after a May CSV top-50 cut.
    """
    tier_order = {"high": 0, "medium": 1, "low": 2}
    sorted_recs = sorted(
        records,
        key=lambda r: (r["sport"], tier_order.get(r["tier"], 2), -float(r["hit_rate"])),
    )
    selected: list[dict] = []
    for _sport, group in groupby(sorted_recs, key=lambda r: r["sport"]):
        group_list = list(group)
        sport_u = str(_sport).upper()
        if sport_u in _SPORT_INCLUDE_ALL:
            selected.extend(group_list)
            continue

        high_med = [r for r in group_list if r.get("tier") in ("high", "medium")]
        low = [r for r in group_list if r.get("tier") not in ("high", "medium")]
        chosen = list(high_med)
        chosen_keys = {(r["player"], r["sport"]) for r in chosen}
        for r in low[:top_n]:
            key = (r["player"], r["sport"])
            if key not in chosen_keys:
                chosen.append(r)
                chosen_keys.add(key)
        for r in low[top_n:]:
            pair = slate_pair_key(str(r.get("player") or ""), str(r.get("sport") or ""))
            if pair in slate_pairs and (r["player"], r["sport"]) not in chosen_keys:
                chosen.append(r)
                chosen_keys.add((r["player"], r["sport"]))
        selected.extend(chosen)
    return selected


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build player_consistency.json for UI")
    p.add_argument("--sport", default=None)
    p.add_argument("--min-props", type=int, default=10)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--today-only", action="store_true")
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--output", default=str(OUTPUT_PATH))
    return p.parse_args()


def main() -> int:
    args = parse_args()

    records: list[dict] = []
    source_name = ""
    db_ok = CONSISTENCY_DB.is_file() and not args.days
    if db_ok:
        print(f"[consistency-ui] Computing from {CONSISTENCY_DB.name} ...")
        records = compute_consistency_from_db(CONSISTENCY_DB, min_props=args.min_props)
        source_name = CONSISTENCY_DB.name
        if args.sport:
            sport_norm = SPORT_ALIASES.get(args.sport.lower(), args.sport.upper())
            records = [
                r for r in records if str(r.get("sport", "")).upper() == sport_norm.upper()
            ]
        if not records:
            print(
                f"[consistency-ui] DB yielded 0 players — falling back to CSV",
                file=sys.stderr,
            )

    if not records:
        try:
            df, source_name = load_graded_dataframe()
        except FileNotFoundError as exc:
            print(f"[consistency-ui] ERROR: {exc}", file=sys.stderr)
            return 1

        df = normalize_columns(df)
        required = ["player", "sport", "direction", "outcome", "prop"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            print(f"[consistency-ui] ERROR: missing columns {missing}", file=sys.stderr)
            return 1

        df["prop"] = df["prop"].astype(str).str.strip()
        df = df[df["prop"].str.len() > 0]

        if args.days and "game_date" in df.columns:
            cutoff = date.today() - timedelta(days=args.days)
            df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
            df = df[df["game_date"].dt.date >= cutoff]

        if args.sport:
            sport_norm = SPORT_ALIASES.get(args.sport.lower(), args.sport.upper())
            df = df[df["sport"].astype(str).str.upper() == sport_norm.upper()]

        print(f"[consistency-ui] Computing from {source_name} ({len(df):,} rows) ...")
        records = compute_consistency(df, min_props=args.min_props)

    today_players, slate_pairs = load_today_slate()
    if today_players:
        print(
            f"[consistency-ui] Today's slate: {len(today_players)} players, "
            f"{len(slate_pairs)} (name, sport) pairs"
        )
    records = tag_today_slate(records, today_players, slate_pairs)
    top_records = select_top_records(records, args.top_n, slate_pairs)

    if args.today_only:
        top_records = [r for r in top_records if r.get("on_today_slate")]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_csv": source_name,
        "total_players": len(top_records),
        "players": top_records,
    }
    text = json.dumps(payload, indent=2)
    out_path.write_text(text, encoding="utf-8")
    print(f"[consistency-ui] Wrote {len(top_records)} players -> {out_path}")
    UI_DEPLOY_PATH.parent.mkdir(parents=True, exist_ok=True)
    UI_DEPLOY_PATH.write_text(text, encoding="utf-8")
    print(f"[consistency-ui] Mirrored deploy copy -> {UI_DEPLOY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
