"""
Cross-sport L5 recency policy (Jul 10–19 2026 as-of rebuild + Aug 2026 soccer grades
+ Aug 8 2026 graded confirmation).

Findings:
- L5 >= 4 lifts Goblins / most Std OVER across sports (stable default bar).
- Aug 8 graded: L5>=4 ~58.6% decided vs ~25% board; Goblin L5>=4 ~67%; L5=5/5 ~70%.
- L5 == 5 adds more lift for WNBA / Tennis Goblin; hurts MLB Standard OVER.
- Basketball-family Standard prop gates clear at L5 >= 4 (WNBA evidence).
- Soccer Standard gates also clear at L5 >= 4 (graded ~99k props: +42pp overall;
  Shots +41pp, Saves +34pp). Passes/tackles/clearances stay ticket-banned.
- Other clear-eligible sports still require perfect L5 = 5.
- MLB Standard OVER at L5 = 5 is avoided / penalized (45% → ~33% HR).
"""

from __future__ import annotations

from typing import Any

# Preferred directional L5 hit-count floor (0–5).
L5_GE4_MIN: float = 4.0
L5_PERFECT: float = 5.0
L5_COLD_MAX: float = 2.0

# Soft scoring (used by utils.prop_signal_score for every sport).
L5_GE4_BOOST: float = 0.08
L5_PERFECT_EXTRA_BOOST: float = 0.06
L5_COLD_PENALTY: float = -0.05
# Strong enough to push MLB Std OVER L5=5 below GE4 peers in sort.
MLB_STD_OVER_PERFECT_L5_PENALTY: float = -0.15

# Clear Standard prop×direction ledger gates at L5 >= 4.
L5_GE4_GATE_CLEAR_SPORTS: frozenset[str] = frozenset(
    {
        "WNBA",
        "NBA",
        "NBA1H",
        "NBA1Q",
        "CBB",
        "WCBB",
        "SOCCER",
        "SOC",
    }
)

# Non-basketball / non-soccer: clear only on perfect L5 = 5 (pending denser graded evidence).
L5_PERFECT_ONLY_GATE_CLEAR_SPORTS: frozenset[str] = frozenset(
    {
        "NFL",
        "CFB",
        "NHL",
        "TENNIS",
        "GOLF",
    }
)

# Union — any sport that may clear Standard gates via L5 recency.
L5_PERFECT_GATE_CLEAR_SPORTS: frozenset[str] = (
    L5_GE4_GATE_CLEAR_SPORTS | L5_PERFECT_ONLY_GATE_CLEAR_SPORTS
)

# Extra L5=5 scoring bump is skipped here (as-of study: MLB Std OVER 45% → 33%).
L5_PERFECT_BOOST_SKIP_SPORTS: frozenset[str] = frozenset({"MLB"})


def _norm_sport(sport: object) -> str:
    return str(sport or "").strip().upper()


def _norm_pick(pick: object) -> str:
    return str(pick or "").strip().lower()


def _norm_direction(direction: object) -> str:
    return str(direction or "").strip().upper()


def is_standard_pick(pick: object) -> bool:
    p = _norm_pick(pick)
    return "standard" in p and "goblin" not in p and "demon" not in p


def l5_gate_clear_min_hits(sport: object) -> float | None:
    """
    Minimum directional L5 hits to clear a Standard prop×direction ledger gate.

    Returns None when the sport never clears via L5 (MLB, …).
    """
    sport_u = _norm_sport(sport)
    if sport_u in L5_GE4_GATE_CLEAR_SPORTS:
        return L5_GE4_MIN
    if sport_u in L5_PERFECT_ONLY_GATE_CLEAR_SPORTS:
        return L5_PERFECT
    return None


def l5_perfect_gate_clear_sport(sport: object) -> bool:
    """True when this sport can clear Standard gates via L5 (at its sport threshold)."""
    return l5_gate_clear_min_hits(sport) is not None


def l5_clears_standard_prop_gate(sport: object, hits: float | None) -> bool:
    """True when directional L5 hits meet the sport's Standard gate-clear floor."""
    if hits is None:
        return False
    mn = l5_gate_clear_min_hits(sport)
    if mn is None:
        return False
    try:
        return float(hits) >= float(mn) - 1e-9
    except (TypeError, ValueError):
        return False


def l5_perfect_score_boost_allowed(
    sport: object,
    pick_type: object | None = None,
    direction: object | None = None,
) -> bool:
    """
    True when L5=5/5 may receive the extra soft score bump.

    MLB Standards are excluded (perfect L5 hurt Std OVER in as-of rebuild).
    Goblin/Demon on MLB still allowed.
    """
    sport_u = _norm_sport(sport)
    if sport_u not in L5_PERFECT_BOOST_SKIP_SPORTS:
        return True
    if pick_type is None:
        return False
    return not is_standard_pick(pick_type)


def mlb_standard_over_perfect_l5(
    sport: object,
    pick_type: object | None,
    direction: object | None,
    hits: float | None,
) -> bool:
    """True for MLB Standard OVER with directional L5 == 5 (negative lift in study)."""
    if _norm_sport(sport) != "MLB":
        return False
    if not is_standard_pick(pick_type):
        return False
    if _norm_direction(direction) != "OVER":
        return False
    if hits is None:
        return False
    try:
        return float(hits) >= L5_PERFECT - 1e-9
    except (TypeError, ValueError):
        return False


def directional_l5_is_ge4(hits: float | None) -> bool:
    if hits is None:
        return False
    try:
        return float(hits) >= L5_GE4_MIN - 1e-9
    except (TypeError, ValueError):
        return False


def directional_l5_is_perfect(hits: float | None) -> bool:
    if hits is None:
        return False
    try:
        return float(hits) >= L5_PERFECT - 1e-9
    except (TypeError, ValueError):
        return False


def row_l5_perfect_boost_ok(row: dict[str, Any] | Any) -> bool:
    if hasattr(row, "get"):
        return l5_perfect_score_boost_allowed(
            row.get("sport"),
            row.get("pick_type") or row.get("pick"),
            row.get("direction") or row.get("bet_direction") or row.get("over_under"),
        )
    return l5_perfect_score_boost_allowed(
        getattr(row, "sport", None),
        getattr(row, "pick_type", None),
        getattr(row, "direction", None),
    )
