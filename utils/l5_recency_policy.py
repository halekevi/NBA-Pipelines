"""
Cross-sport L5 recency policy (Jul 10–19 2026 as-of rebuild).

Findings:
- L5 >= 4 lifts Goblins / most Std OVER across sports (stable default bar).
- L5 == 5 adds more lift for WNBA / Tennis Goblin; hurts MLB Standard OVER.
- Standard prop-direction gate clear on perfect L5 is WNBA-family only until
  sport-specific evidence says otherwise.
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

# Perfect L5 clears Standard prop×direction ledger gates for these sports.
# MLB excluded (as-of: Std OVER 45% → 33% at L5=5). Soccer kept gated pending
# sport-specific Standard evidence (shots OVER ban remains hard).
L5_PERFECT_GATE_CLEAR_SPORTS: frozenset[str] = frozenset(
    {
        "WNBA",
        "NBA",
        "NBA1H",
        "NBA1Q",
        "CBB",
        "WCBB",
        "NFL",
        "CFB",
        "NHL",
        "TENNIS",
        "GOLF",
    }
)

# Extra L5=5 scoring bump is skipped here (as-of study: MLB Std OVER 45% → 33%).
L5_PERFECT_BOOST_SKIP_SPORTS: frozenset[str] = frozenset({"MLB"})


def _norm_sport(sport: object) -> str:
    return str(sport or "").strip().upper()


def _norm_pick(pick: object) -> str:
    return str(pick or "").strip().lower()


def is_standard_pick(pick: object) -> bool:
    p = _norm_pick(pick)
    return "standard" in p and "goblin" not in p and "demon" not in p


def l5_perfect_gate_clear_sport(sport: object) -> bool:
    return _norm_sport(sport) in L5_PERFECT_GATE_CLEAR_SPORTS


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
