"""Ticket-leg pools: Goblin 70% engine vs Standard Flex allowlist.

Goblin tickets (measured ~73.4%): OVER only, directional L5 >= 4, sport cover
floor (WNBA/Tennis >= 2, MLB/Soccer >= 1), no Demons, no shadow.

Standard stays off those slips. Flex-only fill uses a short allowlist until a
cell independently clears ~70% with n >= 40.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import prop_hit_tiers as T  # noqa: E402

ACTIVE = T.ACTIVE
TIER_RANK = T.TIER_RANK
canon_prop = T.canon_prop
cover_clears_floor = T.cover_clears_floor
is_shadow = T.is_shadow
norm_sport = T.norm_sport

# Historical hit rates used as ticket p, not board hit_rate.
P_GOBLIN_COVER = 0.734
P_GOBLIN_SA = 0.774
P_GOBLIN_L5EQ5 = 0.763
P_WNBA_STEALS_UNDER = 0.727
P_WNBA_ASSISTS_UNDER = 0.631
P_MLB_HRRBI_UNDER_L5EQ5 = 0.660
P_WNBA_COMBO_OVER = 0.644

PITCHER_PROPS = frozenset(
    {
        "pitcher_ks",
        "hits allowed",
        "walks allowed",
        "earned runs allowed",
        "pitches thrown",
        "pitching outs",
    }
)
WNBA_COMBO_OVER = frozenset({"pra", "pts+ast", "points (combo)"})
HRRBI = frozenset({"hits+runs+rbis", "h+r+rbi"})

STD_KIND_ORDER = (
    "wnba_steals_under",
    "wnba_combo_over",
    "wnba_assists_under",
    "mlb_hrrbi_under_l5eq5",
)


def _pick(r: dict[str, Any]) -> str:
    return str(r.get("pick_type") or "").strip()


def _side(r: dict[str, Any]) -> str:
    return str(r.get("side") or "").strip().upper()


def _sport(r: dict[str, Any]) -> str:
    return norm_sport(str(r.get("sport") or ""))


def _prop(r: dict[str, Any]) -> str:
    return canon_prop(_sport(r), str(r.get("prop") or ""))


def _l5(r: dict[str, Any]) -> float | None:
    side = _side(r)
    v = r.get("l5_over") if side == "OVER" else r.get("l5_under")
    if v is None:
        v = r.get("l5")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def directional_l5(r: dict[str, Any]) -> float | None:
    return _l5(r)


def skip_combo_player(r: dict[str, Any]) -> bool:
    return "+" in str(r.get("player") or "")


def skip_era_half(r: dict[str, Any]) -> bool:
    prop = str(r.get("prop") or "").lower()
    if "earned run" not in prop:
        return False
    try:
        return float(r.get("line") or 99) <= 0.5
    except (TypeError, ValueError):
        return False


def nflp_ticket_eligible(r: dict[str, Any]) -> bool:
    """NFLP week-3 Goblin OVER for a separate /tickets group (not the 70% book).

    Kickers: L5 >= 4. Backup skill: D pass. Sit/cameo skill overs stay off.
    """
    if _pick(r) != "Goblin" or _side(r) != "OVER":
        return False
    if _sport(r) != "NFL":
        return False
    from utils.nflp_playing_time import is_nflp, nflp_list_eligible, policy_from_row

    if not is_nflp(r.get("league")):
        return False
    d_ok = bool((r.get("checks") or {}).get("D") is True)
    policy = str(r.get("starter_policy") or "") or policy_from_row(r)
    return nflp_list_eligible(
        policy=policy,
        side="OVER",
        pick_type="Goblin",
        d_ok=d_ok,
        l5_over=r.get("l5_over"),
        l5_under=r.get("l5_under"),
    )


def nflp_std_over_eligible(r: dict[str, Any]) -> bool:
    """NFLP Standard OVER for a separate /tickets group when Goblins are absent."""
    if _pick(r) != "Standard" or _side(r) != "OVER":
        return False
    if _sport(r) != "NFL":
        return False
    from utils.nflp_playing_time import is_nflp, nflp_list_eligible, policy_from_row

    if not is_nflp(r.get("league")):
        return False
    d_ok = bool((r.get("checks") or {}).get("D") is True)
    policy = str(r.get("starter_policy") or "") or policy_from_row(r)
    return nflp_list_eligible(
        policy=policy,
        side="OVER",
        pick_type="Standard",
        d_ok=d_ok,
        l5_over=r.get("l5_over"),
        l5_under=r.get("l5_under"),
    )


def nflp_ticket_p(r: dict[str, Any]) -> float:
    from utils.nflp_playing_time import POLICY_PLAYS

    if str(r.get("starter_policy") or "") == POLICY_PLAYS:
        return 0.70
    return 0.62


def goblin_70_eligible(r: dict[str, Any]) -> bool:
    """Hard ticket gate for the 70% Goblin book."""
    if _pick(r) != "Goblin" or _side(r) != "OVER":
        return False
    sport = _sport(r)
    if sport not in ACTIVE:
        return False
    if skip_combo_player(r) or skip_era_half(r):
        return False
    l5 = _l5(r)
    if l5 is None or l5 < 4:
        return False
    if is_shadow(sport, "Goblin OVER", _prop(r)):
        return False
    return cover_clears_floor(sport, r.get("cover"), "OVER")


def goblin_ticket_p(r: dict[str, Any]) -> float:
    l5 = _l5(r) or 0
    tier = str(r.get("prop_tier") or "")
    if l5 >= 5:
        return P_GOBLIN_L5EQ5
    if tier in {"S", "A"}:
        return P_GOBLIN_SA
    return P_GOBLIN_COVER


def standard_flex_kind(r: dict[str, Any]) -> str | None:
    """Allowlist for Flex-only Standard fill. None = do not ticket."""
    if _pick(r) != "Standard":
        return None
    sport = _sport(r)
    if sport not in ACTIVE:
        return None
    if skip_combo_player(r):
        return None
    side = _side(r)
    prop = _prop(r)
    book = f"Standard {side}"
    if is_shadow(sport, book, prop):
        return None
    l5 = _l5(r)
    if l5 is None:
        return None
    if sport == "WNBA" and side == "UNDER" and prop == "steals" and l5 >= 4:
        return "wnba_steals_under"
    if sport == "WNBA" and side == "OVER" and prop in WNBA_COMBO_OVER and l5 >= 4:
        return "wnba_combo_over"
    if sport == "WNBA" and side == "UNDER" and prop == "assists" and l5 >= 4:
        return "wnba_assists_under"
    if sport == "MLB" and side == "UNDER" and prop in HRRBI and l5 == 5:
        return "mlb_hrrbi_under_l5eq5"
    return None


def standard_ticket_p(kind: str) -> float:
    return {
        "wnba_steals_under": P_WNBA_STEALS_UNDER,
        "wnba_combo_over": P_WNBA_COMBO_OVER,
        "wnba_assists_under": P_WNBA_ASSISTS_UNDER,
        "mlb_hrrbi_under_l5eq5": P_MLB_HRRBI_UNDER_L5EQ5,
    }.get(kind, 0.54)


def is_pitcher_prop(r: dict[str, Any]) -> bool:
    return _prop(r) in PITCHER_PROPS


def goblin_sort_key(r: dict[str, Any]) -> tuple:
    tier = str(r.get("prop_tier") or "")
    l5 = int(_l5(r) or 0)
    cover = r.get("cover")
    try:
        cov = -float(cover)
    except (TypeError, ValueError):
        cov = 0.0
    promo = str(r.get("promo") or r.get("badge") or "")
    promo_rank = {"Diamond": 0, "Platinum": 1, "Gold": 2, "Silver": 3, "Bronze": 4}.get(
        promo, 9
    )
    return (
        TIER_RANK.get(tier, 9),
        0 if l5 >= 5 else 1,
        promo_rank,
        cov,
        str(r.get("player") or ""),
    )


def standard_sort_key(r: dict[str, Any]) -> tuple:
    kind = r.get("std_kind") or standard_flex_kind(r) or ""
    try:
        ki = STD_KIND_ORDER.index(kind)
    except ValueError:
        ki = 99
    l5 = int(_l5(r) or 0)
    return (ki, -l5, str(r.get("player") or ""))
