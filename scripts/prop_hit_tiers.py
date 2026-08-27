"""Prop-family hit-rate tiers (S–D) associated with Diamond→Bronze badges.

Prop tier = which market (sport × book × prop) historically hits.
Badge / promo = this play's six checks (Diamond = Gold + L10≥8 + season HR>70%).

They stack, they do not replace each other:
  sort S → A → B → C → D → W, then Diamond → Bronze inside the tier.
  Promotions can raise a B/C cell into A/S when the measured gate passes.
  Shadow cells stay listed and tagged; they sort as W.
"""
from __future__ import annotations

import re

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
    "MLB": "MLB",
    "SOCCER": "Soccer",
    "TENNIS": "Tennis",
    "NBA": "NBA",
    "NFL": "NFL",
    "NFLP": "NFL",
    "CFB": "CFB",
    "CBB": "CBB",
    "WCBB": "WCBB",
    "NHL": "NHL",
}
GOBLIN_FLOOR = {"WNBA": 2.0, "MLB": 1.0, "Tennis": 2.0, "Soccer": 1.0}
ACTIVE = frozenset({"WNBA", "MLB", "Soccer", "Tennis"})

S_KEYS = frozenset(
    {
        ("MLB", "Goblin OVER", "walks allowed"),
        ("MLB", "Goblin OVER", "hits allowed"),
        ("MLB", "Goblin OVER", "pitcher_ks"),
        ("MLB", "Goblin OVER", "earned runs allowed"),
        ("MLB", "Goblin OVER", "pitches thrown"),
    }
)
A_KEYS = frozenset(
    {
        ("MLB", "Goblin OVER", "pitching outs"),
        ("WNBA", "Goblin OVER", "pts+reb"),
        ("WNBA", "Goblin OVER", "points"),
        ("WNBA", "Goblin OVER", "assists"),
        ("WNBA", "Goblin OVER", "rebounds"),
        ("WNBA", "Goblin OVER", "threes"),
        ("WNBA", "Goblin OVER", "pra"),
        ("WNBA", "Goblin OVER", "pts+ast"),
        ("Tennis", "Goblin OVER", "total games"),
        ("Tennis", "Goblin OVER", "games_won"),
        ("Soccer", "Goblin OVER", "saves"),
    }
)
B_KEYS = frozenset(
    {
        ("WNBA", "Goblin OVER", "reb+ast"),
        ("MLB", "Goblin OVER", "hits+runs+rbis"),
        ("MLB", "Goblin OVER", "h+r+rbi"),
        ("WNBA", "Standard OVER", "points (combo)"),
        ("WNBA", "Standard OVER", "pra"),
    }
)
C_KEYS = frozenset(
    {
        ("MLB", "Goblin OVER", "hitter_ks"),
        ("MLB", "Goblin OVER", "hits"),
        ("MLB", "Goblin OVER", "total_bases"),
        ("WNBA", "Standard OVER", "pts+ast"),
        ("Tennis", "Standard OVER", "total games"),
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
    p = re.sub(r"\s+", " ", str(prop or "").strip().lower())
    p = p.replace("points + rebounds + assists", "pra")
    p = p.replace("pts+rebs+asts", "pra").replace("pts + rebs + asts", "pra")
    p = p.replace("points + rebounds", "pts+reb").replace("pts+rebs", "pts+reb")
    p = p.replace("points + assists", "pts+ast").replace("pts+asts", "pts+ast")
    p = p.replace("rebounds + assists", "reb+ast").replace("rebs+asts", "reb+ast")
    p = p.replace("blocked shots", "blocks")
    aliases = {
        "pts": "points",
        "reb": "rebounds",
        "ast": "assists",
        "fg made": "fgm",
        "3-pt made": "threes",
        "3pt made": "threes",
        "three pointers made": "threes",
        "shots on goal": "sog",
        "shot on target": "sog",
        "shots on target": "sog",
        "goalie saves": "saves",
        "goalkeeper saves": "saves",
        "pitcher strikeouts": "pitcher_ks",
        "hitter strikeouts": "hitter_ks",
        "hitter strikeout": "hitter_ks",
        "total bases": "total_bases",
        "hits+runs+rbi": "hits+runs+rbis",
        "hits + runs + rbis": "hits+runs+rbis",
        "hits + runs + rbi": "hits+runs+rbis",
        "h+r+rbi": "hits+runs+rbis",
        "total games won": "games_won",
        "games won": "games_won",
        "aces": "aces",
        "double faults": "double_faults",
        "double_faults": "double_faults",
    }
    out = aliases.get(p, p)
    if "hitter" in out and "strike" in out:
        return "hitter_ks"
    if "pitcher" in out and "strike" in out:
        return "pitcher_ks"
    if sport == "MLB" and out in ("strikeouts", "ks", "k's"):
        return "strikeouts"
    return out


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


def cover_clears_floor(sport: str, cover, side: str = "OVER") -> bool:
    if cover is None:
        return False
    try:
        c = float(cover)
    except (TypeError, ValueError):
        return False
    need = GOBLIN_FLOOR.get(sport, 1.0)
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
            and cover_clears_floor(sport_n, cover, side)
        ):
            tier, promoted, reason = "A", True, "reb+ast cover >=2"
        elif (
            sport_n == "MLB"
            and book == "Goblin OVER"
            and prop_n == "total_bases"
            and d_ok
            and cover_clears_floor(sport_n, cover, side)
        ):
            tier, promoted, reason = "A", True, "TB cover + D"
        elif (
            sport_n == "MLB"
            and book == "Goblin OVER"
            and prop_n == "hitter_ks"
            and cover_clears_floor(sport_n, cover, side)
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
