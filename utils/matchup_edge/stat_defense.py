"""Prop-category defense for Matchup Edge panels.

Maps Matchup Edge category ids → prop-defense lookups, and maps HARD/EASY
tiers onto the Elite / Above Avg / Avg / Below Avg / Weak labels the UI uses.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# Matchup Edge category id → prop label understood by *_prop_defense.lookup_stat_defense
CAT_ID_TO_PROP: dict[str, str] = {
    "pts": "Points",
    "reb": "Rebounds",
    "ast": "Assists",
    "fg3m": "3-PT Made",
    "stl": "Steals",
    "blk": "Blocked Shots",
    "stocks": "Blks+Stls",
    "bs": "Blks+Stls",
    "pra": "Pts+Rebs+Asts",
    "pr": "Pts+Rebs",
    "pa": "Pts+Asts",
    "ra": "Rebs+Asts",
    "fgm": "FG Made",
    "fga": "FG Attempted",
    "ftm": "Free Throws Made",
    "fta": "Free Throws Attempted",
    "tov": "Turnovers",
    # Soccer / other common ids (best-effort; lookup returns empty if unsupported)
    "shots": "Shots",
    "sog": "Shots On Target",
    "goals": "Goals",
}

# Prop-defense tier → Matchup Edge display tier (CSS: Elite / Weak / …)
_TIER_DISPLAY: dict[str, str] = {
    "HARD": "Elite",
    "HARD_MID": "Above Avg",
    "MID": "Avg",
    "EASY_MID": "Below Avg",
    "EASY": "Weak",
    "ELITE": "Elite",
    "ABOVE_AVG": "Above Avg",
    "ABOVE AVG": "Above Avg",
    "AVG": "Avg",
    "AVERAGE": "Avg",
    "BELOW_AVG": "Below Avg",
    "BELOW AVG": "Below Avg",
    "WEAK": "Weak",
}


def display_tier_from_stat(tier_raw: object) -> str:
    t = str(tier_raw or "").strip().upper().replace("-", "_")
    if not t:
        return ""
    if t in _TIER_DISPLAY:
        return _TIER_DISPLAY[t]
    spaced = t.replace("_", " ")
    if spaced in _TIER_DISPLAY:
        return _TIER_DISPLAY[spaced]
    # Already a Matchup Edge label
    pretty = str(tier_raw or "").strip()
    if pretty.lower() in ("elite", "above avg", "avg", "below avg", "weak"):
        return pretty if pretty[0].isupper() else pretty.title().replace("Avg", "Avg")
    return pretty


def prop_label_for_cat(cat_id: object, cat_label: object = "") -> str:
    cid = str(cat_id or "").strip().lower()
    if cid in CAT_ID_TO_PROP:
        return CAT_ID_TO_PROP[cid]
    label = str(cat_label or "").strip()
    if label:
        # Normalize common Matchup Edge labels
        low = label.lower()
        aliases = {
            "points": "Points",
            "rebounds": "Rebounds",
            "assists": "Assists",
            "3-pointers made": "3-PT Made",
            "3-pointers": "3-PT Made",
            "steals": "Steals",
            "blocks": "Blocked Shots",
            "stocks (stl+blk)": "Blks+Stls",
            "stocks": "Blks+Stls",
            "pts+reb+ast": "Pts+Rebs+Asts",
            "pts+rebs+asts": "Pts+Rebs+Asts",
        }
        if low in aliases:
            return aliases[low]
        return label
    return ""


def _lookup_fn_for_sport(sport: str) -> Optional[Callable[..., dict]]:
    sp = str(sport or "").strip().lower()
    try:
        if sp == "wnba":
            from utils.wnba_prop_defense import lookup_stat_defense

            return lookup_stat_defense
        if sp in ("nba", "nba1h", "nba1q"):
            from utils.nba_prop_defense import lookup_stat_defense

            return lookup_stat_defense
        if sp == "mlb":
            from utils.mlb_prop_defense import lookup_stat_defense

            return lookup_stat_defense
        if sp == "nhl":
            from utils.nhl_prop_defense import lookup_stat_defense

            return lookup_stat_defense
        if sp in ("soccer", "soc"):
            from utils.soccer_prop_defense import lookup_stat_defense

            return lookup_stat_defense
        if sp in ("nfl", "cfb"):
            from utils.football_prop_defense import lookup_stat_defense as _fb

            return lambda opp, prop, **kw: _fb(sp, opp, prop, **kw)
        if sp in ("cbb", "wcbb"):
            from utils.cbb_prop_defense import lookup_stat_defense as _cbb

            return lambda opp, prop, **kw: _cbb(sp, opp, prop, **kw)
    except Exception:
        return None
    return None


def resolve_category_defense(
    *,
    sport: str,
    opponent: object,
    cat_id: object,
    cat_label: object = "",
    overall_rank: object = None,
    overall_tier: object = "",
) -> dict[str, Any]:
    """
    Prefer prop-specific opp defense for this category; fall back to overall.

    Returns keys used on Matchup Edge opponent blocks:
      def_rank, def_tier, overall_def_rank, overall_def_tier,
      stat_def_category, stat_def_rank, stat_def_tier
    """
    overall_tier_s = str(overall_tier or "")
    try:
        overall_rank_i = int(overall_rank) if overall_rank is not None and str(overall_rank) != "" else None
    except (TypeError, ValueError):
        overall_rank_i = None

    out: dict[str, Any] = {
        "def_rank": overall_rank_i,
        "def_tier": overall_tier_s,
        "overall_def_rank": overall_rank_i,
        "overall_def_tier": overall_tier_s,
        "stat_def_category": "",
        "stat_def_rank": None,
        "stat_def_tier": "",
    }

    prop = prop_label_for_cat(cat_id, cat_label)
    fn = _lookup_fn_for_sport(sport)
    if not fn or not prop:
        return out

    try:
        info = fn(opponent, prop) or {}
    except Exception:
        return out

    rank = info.get("stat_def_rank")
    if rank is None:
        return out

    try:
        rank_i = int(rank)
    except (TypeError, ValueError):
        return out

    raw = str(info.get("stat_def_tier_raw") or info.get("stat_def_tier") or "")
    display = display_tier_from_stat(raw) or overall_tier_s
    out.update(
        {
            "def_rank": rank_i,
            "def_tier": display,
            "stat_def_category": str(info.get("stat_def_category") or ""),
            "stat_def_rank": rank_i,
            "stat_def_tier": str(info.get("stat_def_tier") or raw),
        }
    )
    return out
