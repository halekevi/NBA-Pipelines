"""Prop-family hit-rate tiers (S–D) associated with Diamond→Bronze badges.

Prop tier = which market (sport × book × prop) historically hits.
Badge / promo = this play's six checks (Diamond = Gold + L10≥8 + season HR>70%).

They stack, they do not replace each other:
  sort S → A → B → C → D → W, then Diamond → Bronze inside the tier.
  Promotions can raise a B/C cell into A/S when the measured gate passes.
  Shadow cells stay listed and tagged; they sort as W.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.prop_norm import canon_prop as _canon_prop
from utils.prop_norm import preferred_hr  # noqa: F401

TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "W": 5}
PROMO_RANK = {
    "Diamond": 0,
    "Platinum": 1,
    "Gold": 2,
    "Silver": 3,
    "Bronze": 4,
}
SPORT_NORM = {
    "WNBA": "WNBA",
    "WNBA1Q": "WNBA1Q",
    "WNBA1H": "WNBA1H",
    "MLB": "MLB",
    "SOCCER": "Soccer",
    "TENNIS": "Tennis",
    "NBA": "NBA",
    "NBA1Q": "NBA1Q",
    "NBA1H": "NBA1H",
    "NFL": "NFL",
    "NFLP": "NFL",
    "CFB": "CFB",
    "CBB": "CBB",
    "WCBB": "WCBB",
    "NHL": "NHL",
    "GOLF": "Golf",
    "PGA": "Golf",
}
GOBLIN_FLOOR = {
    "WNBA": 2.0,
    "NBA": 2.0,
    "CBB": 2.0,
    "WCBB": 2.0,
    "WNBA1H": 1.0,
    "NBA1H": 1.0,
    "WNBA1Q": 0.7,
    "NBA1Q": 0.7,
    "MLB": 1.0,
    "Tennis": 2.0,
    "Soccer": 1.0,
    "NHL": 0.5,
    "NFL": 1.0,
    "CFB": 1.0,
    "Golf": 1.0,
}
# Typical |last5-line| for that market (u=1). Sport-wide +2 treated PRA and
# 3s/FGA as the same gap; they are not.
_BBALL_COVER = {
    "pra": 3.7,
    "pts+reb": 3.7,
    "pts+ast": 3.7,
    "points": 3.1,
    "fantasy": 5.8,
    "rebounds": 1.3,
    "reb+ast": 1.3,
    "assists": 1.1,
    "threes": 0.7,
    "threes_att": 0.7,
    "fga": 1.1,
    "fgm": 0.75,
    "fg2a": 0.9,
    "fg2m": 0.7,
    "fta": 0.9,
    "ftm": 0.7,
}
_PERIOD_SCALE = {
    "NBA1H": 0.5,
    "WNBA1H": 0.5,
    "NBA1Q": 0.28,
    "WNBA1Q": 0.28,
}
PROP_COVER_UNIT: dict[tuple[str, str], float] = {}
for _sp in ("WNBA", "NBA", "CBB", "WCBB"):
    for _p, _u in _BBALL_COVER.items():
        PROP_COVER_UNIT[(_sp, _p)] = _u
for _sp, _scale in _PERIOD_SCALE.items():
    for _p, _u in _BBALL_COVER.items():
        PROP_COVER_UNIT[(_sp, _p)] = round(_u * _scale, 2)
PROP_COVER_UNIT.update(
    {
        ("MLB", "pitcher_ks"): 1.0,
        ("MLB", "hits_allowed"): 1.1,
        ("MLB", "walks_allowed"): 0.75,
        ("MLB", "pitching_outs"): 1.5,
        ("MLB", "h+r+rbi"): 1.1,
        ("MLB", "hits+runs+rbis"): 1.1,
        ("MLB", "total_bases"): 0.9,
        ("MLB", "hitter_ks"): 0.5,
        ("MLB", "hitter_fantasy"): 4.1,
        ("MLB", "pitcher_fantasy"): 7.8,
        ("Tennis", "games_won"): 3.3,
        ("Tennis", "match_total_games"): 4.3,
        ("Soccer", "shots"): 0.5,
        ("Soccer", "saves"): 0.9,
        ("NFL", "passing_yards"): 15.0,
        ("NFL", "rushing_yards"): 8.0,
        ("NFL", "receiving_yards"): 8.0,
        ("NFL", "receptions"): 0.8,
        ("NFL", "passing_tds"): 0.5,
        ("NFL", "rushing_tds"): 0.5,
        ("NFL", "receiving_tds"): 0.5,
        ("NFL", "player_tds"): 0.5,
        ("NFL", "fg_made"): 0.5,
        ("NFL", "pat_made"): 0.4,
        ("NFL", "sacks"): 0.5,
        ("NFL", "tackles"): 1.0,
        ("NFL", "rush_rec_yds"): 10.0,
        ("NFL", "pass_rush_yds"): 12.0,
        ("CFB", "pass_yds"): 15.0,
        ("CFB", "rush_yds"): 8.0,
        ("CFB", "rec_yds"): 8.0,
        ("CFB", "rec"): 0.8,
        ("CFB", "pass_td"): 0.5,
        ("CFB", "rush_td"): 0.5,
        ("CFB", "rec_td"): 0.5,
        ("CFB", "player_td"): 0.5,
        ("CFB", "fg_made"): 0.5,
        ("CFB", "pat_made"): 0.4,
        ("CFB", "sacks"): 0.5,
        ("CFB", "tackles"): 1.0,
        ("CFB", "rush_rec_yds"): 10.0,
        ("CFB", "pass_rush_yds"): 12.0,
        ("CFB", "kick_pts"): 1.0,
        ("NHL", "points"): 0.5,
        ("NHL", "assists"): 0.5,
        ("NHL", "sog"): 0.8,
        ("NHL", "saves"): 1.5,
        ("NHL", "goals"): 0.4,
        ("NHL", "hits"): 1.0,
        ("NHL", "blocked_shots"): 0.7,
        ("Golf", "strokes"): 1.5,
        ("Golf", "birdies_or_better"): 0.6,
        ("Golf", "bogeys_or_worse"): 0.6,
        ("Golf", "gir"): 1.0,
        ("Golf", "fairways_hit"): 1.0,
        ("Golf", "finish_pos"): 5.0,
    }
)
ACTIVE = frozenset(
    {
        "WNBA",
        "WNBA1Q",
        "WNBA1H",
        "MLB",
        "Soccer",
        "Tennis",
        "NBA",
        "NBA1Q",
        "NBA1H",
        "NHL",
        "CBB",
        "WCBB",
        "NFL",
        "CFB",
        "Golf",
    }
)

S_KEYS = frozenset(
    {
        ("MLB", "Goblin OVER", "walks_allowed"),
        ("MLB", "Goblin OVER", "pitcher_ks"),
        ("MLB", "Goblin OVER", "pitches_thrown"),
        ("NBA1Q", "Goblin OVER", "points"),
        ("NBA1Q", "Goblin OVER", "rebounds"),
        ("NBA1Q", "Goblin OVER", "assists"),
    }
)
A_KEYS = frozenset(
    {
        ("MLB", "Goblin OVER", "pitching_outs"),
        ("WNBA", "Goblin OVER", "pts+reb"),
        ("WNBA", "Goblin OVER", "points"),
        ("WNBA", "Goblin OVER", "assists"),
        ("WNBA", "Goblin OVER", "rebounds"),
        ("WNBA", "Goblin OVER", "threes"),
        ("WNBA", "Goblin OVER", "threes_att"),
        ("WNBA", "Goblin OVER", "pts+ast"),
        ("WNBA", "Goblin OVER", "fga"),
        ("WNBA", "Goblin OVER", "reb+ast"),
        ("Tennis", "Goblin OVER", "match_total_games"),
        ("Tennis", "Goblin OVER", "games_won"),
        ("Soccer", "Goblin OVER", "saves"),
        ("NBA", "Goblin OVER", "points"),
        ("NBA", "Goblin OVER", "pra"),
        ("NBA", "Goblin OVER", "pts+reb"),
        ("NBA", "Goblin OVER", "pts+ast"),
        ("NBA", "Goblin OVER", "assists"),
        ("NBA", "Goblin OVER", "threes"),
        ("NBA", "Goblin OVER", "steals"),
    }
)
B_KEYS = frozenset(
    {
        ("WNBA", "Goblin OVER", "pra"),
        ("MLB", "Goblin OVER", "hits+runs+rbis"),
        ("MLB", "Goblin OVER", "h+r+rbi"),
        ("MLB", "Goblin OVER", "hits_allowed"),
        ("WNBA", "Standard OVER", "points_combo"),
        ("WNBA", "Standard OVER", "pra"),
        ("NBA", "Goblin OVER", "rebounds"),
    }
)
C_KEYS = frozenset(
    {
        ("MLB", "Goblin OVER", "hitter_ks"),
        ("MLB", "Goblin OVER", "hits"),
        ("MLB", "Goblin OVER", "total_bases"),
        ("WNBA", "Standard OVER", "pts+ast"),
        ("WNBA", "Standard UNDER", "fg2a"),
        ("Tennis", "Standard OVER", "match_total_games"),
    }
)
SHADOW_KEYS = frozenset(
    {
        ("Tennis", "Goblin OVER", "aces"),
        ("Tennis", "Goblin OVER", "double_faults"),
        ("Tennis", "Standard UNDER", "aces"),
        ("Tennis", "Standard UNDER", "games_won"),
        ("Soccer", "Goblin OVER", "shots on target"),
        ("Soccer", "Goblin OVER", "sog"),
        ("Soccer", "Standard UNDER", "shots"),
        ("Soccer", "Standard UNDER", "shots on target"),
        ("Soccer", "Standard UNDER", "sog"),
        ("MLB", "Goblin OVER", "singles"),
        ("MLB", "Standard UNDER", "total_bases"),
        ("WNBA", "Standard OVER", "points"),
    }
)


def norm_sport(sport: str) -> str:
    raw = str(sport or "").strip()
    return SPORT_NORM.get(raw.upper(), raw)


def book_label(pick_type: str, side: str) -> str:
    pt = str(pick_type or "").strip().lower()
    d = str(side or "").strip().upper()
    if d in ("O", "OVER"):
        d = "OVER"
    elif d in ("U", "UNDER"):
        d = "UNDER"
    else:
        d = d or ""
    if "goblin" in pt:
        return f"Goblin {d}".strip()
    if "demon" in pt:
        return f"Demon {d}".strip()
    return f"Standard {d}".strip()


def canon_prop(sport: str, prop: str) -> str:
    return _canon_prop(sport, prop)


def _soccer_shadow(book: str, prop: str) -> bool:
    p = (prop or "").lower()
    if book == "Goblin OVER" and (
        "shot on" in p or p in {"sog", "shots on goal", "shots on target"}
    ):
        return True
    if book == "Standard UNDER":
        if "save" in p:
            return False
        if "shot" in p:
            return True
    return False


def is_shadow(sport: str, book: str, prop: str) -> bool:
    if (sport, book, prop) in SHADOW_KEYS:
        return True
    if sport == "Soccer" and _soccer_shadow(book, prop):
        return True
    return False


def base_tier(sport: str, book: str, prop: str) -> str:
    key = (sport, book, prop)
    if key in S_KEYS:
        return "S"
    if key in A_KEYS:
        return "A"
    if key in B_KEYS:
        return "B"
    if key in C_KEYS:
        return "C"
    if "goblin" in book.lower() and book.endswith("OVER"):
        return "C"
    return "D"


def cover_need(sport: str, prop: str = "", *, use_prop_unit: bool = True) -> float:
    """Points of play-side cover required. Per-prop u=1 when mapped, else sport floor."""
    sport_n = norm_sport(sport)
    fallback = GOBLIN_FLOOR.get(sport_n, 1.0)
    if not use_prop_unit:
        return fallback
    prop_n = canon_prop(sport_n, prop)
    return PROP_COVER_UNIT.get((sport_n, prop_n), fallback)


def cover_clears_floor(
    sport: str,
    cover,
    side: str = "OVER",
    prop: str = "",
    *,
    use_prop_unit: bool = True,
) -> bool:
    if cover is None:
        return False
    try:
        c = float(cover)
    except (TypeError, ValueError):
        return False
    need = cover_need(sport, prop, use_prop_unit=use_prop_unit)
    if str(side).upper() in ("U", "UNDER"):
        c = -c
    return c >= need


def assign_tier(
    *,
    sport: str,
    pick_type: str,
    side: str,
    prop: str,
    cover=None,
    d_ok: bool = False,
) -> dict:
    """Return base_tier, effective tier, shadow, and promotion note."""
    sport_n = norm_sport(sport)
    book = book_label(pick_type, side)
    prop_n = canon_prop(sport_n, prop)
    shadow = is_shadow(sport_n, book, prop_n)
    base = base_tier(sport_n, book, prop_n) if sport_n in ACTIVE else ""
    tier = base
    promoted = False
    reason = ""
    if sport_n in ACTIVE and not shadow:
        if (
            sport_n == "MLB"
            and book == "Goblin OVER"
            and prop_n in {"hits+runs+rbis", "h+r+rbi"}
            and d_ok
        ):
            tier, promoted, reason = "A", True, "H+R+RBI D pass"
        elif (
            sport_n == "WNBA"
            and book == "Goblin OVER"
            and prop_n == "reb+ast"
            and cover_clears_floor(sport_n, cover, side, use_prop_unit=False)
        ):
            tier, promoted, reason = "A", True, "reb+ast cover >=2"
        elif (
            sport_n == "MLB"
            and book == "Goblin OVER"
            and prop_n == "total_bases"
            and d_ok
            and cover_clears_floor(sport_n, cover, side, use_prop_unit=False)
        ):
            tier, promoted, reason = "A", True, "TB cover + D"
        elif (
            sport_n == "MLB"
            and book == "Goblin OVER"
            and prop_n == "hitter_ks"
            and cover_clears_floor(sport_n, cover, side, use_prop_unit=False)
        ):
            tier, promoted, reason = "S", True, "hitter K cover >=1"
    if shadow:
        tier = "W"
    return {
        "prop_canon": prop_n,
        "book": book,
        "prop_tier_base": base or "",
        "prop_tier": tier or "",
        "prop_shadow": shadow,
        "prop_promoted": promoted,
        "prop_promote_reason": reason,
    }


def sort_key_tier_then_badge(r: dict, *, over: bool) -> tuple:
    """Primary: S→W. Secondary: Diamond→Bronze. Then L5 / cover."""
    tier = r.get("prop_tier") or ""
    promo = r.get("promo") or r.get("badge") or ""
    l5 = (r.get("l5_over") if over else r.get("l5_under")) or 0
    cover = r.get("cover")
    if cover is None:
        cov = 0.0
    else:
        cov = -float(cover) if over else float(cover)
    l10 = (r.get("l10_over") if over else r.get("l10_under")) or 0
    return (
        TIER_RANK.get(tier, 9),
        PROMO_RANK.get(promo, 9),
        -int(l5),
        cov,
        -int(l10),
        str(r.get("player") or ""),
    )
