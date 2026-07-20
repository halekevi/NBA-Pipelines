"""
Percentile-calibrated ticket EV tiers (STRONG / OK / MARGINAL / SKIP).

Fixed cuts (1.0 / 1.15 / 1.40 on payout.ev) collapse almost all slips into SKIP on
typical slates. Thresholds are computed per payload from the empirical payout.ev
distribution, with small absolute floors so tiers stay meaningful on thin slates.

STRONG is leg-count aware: percentile tiers are computed within each leg-count bucket
so long parlays are not labeled STRONG just because they rank high among all slips.
Additional gates demote STRONG→OK when p_win is too low for the leg count, when
cross-sport (default: cross-sport cannot be STRONG), when length exceeds
STRONG_MAX_LEGS (default 3 — profitability prototype), or when any leg fails
Goblin + Tier A/B + HOT streak quality checks.
"""
from __future__ import annotations

import math
import os
from collections import defaultdict
from typing import Any, Mapping, MutableMapping, Sequence

import numpy as np

# Percentile ranks for tier floors (higher EV → higher tier).
TIER_EV_PERCENTILES: dict[str, float] = {
    "strong": 85.0,
    "ok": 60.0,
    "marginal": 35.0,
}

# Legacy absolute cuts when too few tickets have payout.ev.
LEGACY_TIER_EV_THRESHOLDS: dict[str, float] = {
    "strong": 1.40,
    "ok": 1.15,
    "marginal": 1.0,
}

# Minimum EV floors after percentile calibration (per $1 stake style).
TIER_EV_MIN_STRONG: float = 0.50
TIER_EV_MIN_OK: float = 0.20
TIER_EV_MIN_MARGINAL: float = 0.0

MIN_SAMPLES_FOR_PERCENTILES: int = 8

# STRONG favors high-conviction Goblin HOT slips. Default max 3 legs (Jul 2026
# graded: ≤3 cleared ~70%+ ticket WR; 4–6 dragged the average). Override via
# PROPORACLE_STRONG_MAX_LEGS (still capped at 6 for shadow/exhaust experiments).
#
# Ticket p_win floors (independence product of capped leg probs):
#   2-leg ≥0.45  → needs ~0.67+/leg under the STRONG leg cap
#   3-leg ≥0.35  → clears ~0.72^3 (common L5/hit-rate clip) and leaves room for
#                  mild correlation; higher raw ML/L5 legs still score up to the
#                  STRONG_MAX_LEG_PROB_FOR_P_WIN ceiling (~0.76 → product ≈0.44)
# MAIN still uses the tighter 0.72 global leg cap; STRONG alone may use up to
# STRONG_MAX_LEG_PROB_FOR_P_WIN so better legs are not flattened for ranking.
STRONG_MAX_LEGS: int = max(2, min(6, int(os.getenv("PROPORACLE_STRONG_MAX_LEGS", "3"))))
STRONG_MIN_P_WIN_2LEG: float = float(os.getenv("PROPORACLE_STRONG_MIN_P_WIN_2LEG", "0.45"))
STRONG_MIN_P_WIN_3LEG: float = float(os.getenv("PROPORACLE_STRONG_MIN_P_WIN_3LEG", "0.35"))
STRONG_MIN_P_WIN_4LEG: float = float(os.getenv("PROPORACLE_STRONG_MIN_P_WIN_4LEG", "0.28"))
STRONG_MIN_P_WIN_5LEG: float = float(os.getenv("PROPORACLE_STRONG_MIN_P_WIN_5LEG", "0.18"))
STRONG_MIN_P_WIN_6LEG: float = float(os.getenv("PROPORACLE_STRONG_MIN_P_WIN_6LEG", "0.12"))
# Per-leg factor ceiling when scoring STRONG builder slips (0.76^3 ≈ 0.439).
STRONG_MAX_LEG_PROB_FOR_P_WIN: float = float(
    os.getenv("PROPORACLE_STRONG_MAX_LEG_PROB", "0.76")
)
STRONG_ALLOW_CROSS_SPORT: bool = os.getenv("PROPORACLE_STRONG_ALLOW_CROSS_SPORT", "0").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _finite_evs(evs: Sequence[float]) -> list[float]:
    out: list[float] = []
    for raw in evs:
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append(v)
    return out


def compute_ev_tier_thresholds(
    evs: Sequence[float],
    *,
    percentiles: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """
    Return strong/ok/marginal cutoffs from the EV sample.

    Falls back to LEGACY_TIER_EV_THRESHOLDS when len(evs) < MIN_SAMPLES_FOR_PERCENTILES.
    """
    pct_map = dict(TIER_EV_PERCENTILES)
    if percentiles:
        pct_map.update({str(k): float(v) for k, v in percentiles.items()})

    clean = _finite_evs(evs)
    if len(clean) < MIN_SAMPLES_FOR_PERCENTILES:
        return dict(LEGACY_TIER_EV_THRESHOLDS)

    arr = np.array(clean, dtype=float)
    return {
        "strong": float(np.percentile(arr, pct_map["strong"])),
        "ok": float(np.percentile(arr, pct_map["ok"])),
        "marginal": float(np.percentile(arr, pct_map["marginal"])),
    }


def recommendation_from_ev(
    ev: float,
    thresholds: Mapping[str, float] | None = None,
) -> str:
    """Map one payout.ev to STRONG / OK / MARGINAL / SKIP."""
    try:
        v = float(ev)
    except (TypeError, ValueError):
        return "SKIP"
    if not math.isfinite(v) or v < TIER_EV_MIN_MARGINAL:
        return "SKIP"

    th = dict(LEGACY_TIER_EV_THRESHOLDS)
    if thresholds:
        th.update({str(k): float(x) for k, x in thresholds.items()})

    strong_min = max(float(th["strong"]), TIER_EV_MIN_STRONG)
    ok_min = max(float(th["ok"]), TIER_EV_MIN_OK)
    marginal_min = max(float(th["marginal"]), TIER_EV_MIN_MARGINAL)

    if v >= strong_min:
        return "STRONG"
    if v >= ok_min:
        return "OK"
    if v >= marginal_min:
        return "MARGINAL"
    return "SKIP"


def refresh_ticket_ev_from_min_guarantee(
    pay: MutableMapping[str, Any],
    min_x: float,
    *,
    update_recommendation: bool = False,
) -> float | None:
    """
    Recompute payout.ev from the live / displayed Power min-guarantee rate.

    PrizePicks ticket scrape + write-back stores power_min_x / display_min_x.
    Power EV is defined as EV = P(all_win) * min_guarantee - 1 (not the Standard sweep).
    """
    try:
        floor = float(min_x)
        p_all = float(pay.get("p_all_win"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(floor) or floor <= 0:
        return None
    if not math.isfinite(p_all) or p_all <= 0:
        return None

    tt = str(pay.get("ticket_type") or "power").strip().lower()
    floor = round(floor, 4)
    pay["min_guarantee"] = floor
    pay["min_payout_x"] = floor
    # Primary "payout" rate for Power slips is the min guarantee (scraped board floor).
    pay["payout"] = floor
    pay["display_min_x"] = floor
    # Keep $10 entry helpers + Power sweep audit fields aligned with the locked floor
    # so UI never shows a stale 1.2–1.6x next to a 2.7x display_min_x.
    pay["entry_10_to_win_guarantee"] = round(10.0 * floor, 2)
    pay["entry_20_to_win_guarantee"] = round(20.0 * floor, 2)
    if tt != "flex":
        pay["sweep_payout"] = floor
        pay["sweep_payout_x"] = floor
        pay["entry_10_to_win_sweep"] = round(10.0 * floor, 2)

    if tt == "flex":
        try:
            first = float(
                pay.get("power_first_x")
                or pay.get("sweep_payout_x")
                or pay.get("sweep_payout")
                or floor
            )
        except (TypeError, ValueError):
            first = floor
        if not math.isfinite(first) or first <= 0:
            first = floor
        try:
            p_miss = float(pay.get("p_miss_1") or 0.0)
        except (TypeError, ValueError):
            p_miss = 0.0
        try:
            p_lose = float(pay.get("p_lose"))
        except (TypeError, ValueError):
            p_lose = max(0.0, 1.0 - p_all - p_miss)
        if not math.isfinite(p_lose):
            p_lose = max(0.0, 1.0 - p_all - p_miss)
        ev = (p_all * first) + (p_miss * floor) - p_lose
        pay["ev_formula"] = (
            f"EV = P(all)*{first:.2f} + P(miss-1)*{floor:.2f} - 1.0"
        )
    else:
        ev = (p_all * floor) - 1.0
        pay["ev_formula"] = f"EV = P(all)*{floor:.2f} - 1.0"

    ev_r = round(float(ev), 4)
    pay["ev"] = ev_r
    if update_recommendation:
        pay["recommendation"] = recommendation_from_ev(ev_r)
    return ev_r


def _iter_tickets(payload: Mapping[str, Any]):
    for g in payload.get("groups") or []:
        for t in g.get("tickets") or []:
            if isinstance(t, dict):
                yield t


def _slip_leg_count(ticket: Mapping[str, Any]) -> int:
    legs = ticket.get("legs")
    if isinstance(legs, list) and legs:
        return len(legs)
    try:
        return int(ticket.get("n_legs") or 0)
    except (TypeError, ValueError):
        return 0


def _slip_sports(ticket: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for leg in ticket.get("legs") or []:
        if not isinstance(leg, dict):
            continue
        s = str(leg.get("sport") or "").strip().upper()
        if s:
            out.add(s)
    return out


def _slip_p_win(ticket: Mapping[str, Any]) -> float | None:
    for key in ("p_win", "ticket_model_p_cash", "est_win_prob", "win_rate_score"):
        raw = ticket.get(key)
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            return v
    return None


def _ticket_allows_strong_standard_hot(ticket: Mapping[str, Any]) -> bool:
    """STRONG Mix slips may use Standard HOT A/B alongside Goblin HOT."""
    pick = str(ticket.get("strong_builder_pick") or "").strip().lower()
    if pick == "mixed":
        return True
    policy = str(ticket.get("pool_policy") or "").strip().lower()
    return policy in ("goblin_standard_mixed", "mixed", "goblin_standard")


def _leg_strong_quality_fail_reason(
    leg: Mapping[str, Any],
    *,
    allow_standard_hot: bool = False,
) -> str | None:
    """Return goblin/tier/streak when leg fails STRONG quality; None if leg passes."""
    pick_type = str(leg.get("pick_type") or "").lower()
    is_goblin = "goblin" in pick_type
    is_standard = ("standard" in pick_type) and not is_goblin
    if not is_goblin and not (allow_standard_hot and is_standard):
        return "goblin"
    tier = str(leg.get("tier") or "").upper()
    if tier not in ("A", "B"):
        return "tier"
    streak = str(leg.get("l10_streak") or "").upper()
    if streak != "HOT":
        return "streak"
    return None


def all_legs_strong_quality(
    legs: Sequence[Mapping[str, Any]],
    *,
    allow_standard_hot: bool = False,
) -> bool:
    """Every leg must be Goblin (or Standard when allowed), Tier A/B, and HOT streak."""
    if not legs:
        return False
    for leg in legs:
        if not isinstance(leg, dict):
            return False
        if _leg_strong_quality_fail_reason(leg, allow_standard_hot=allow_standard_hot):
            return False
    return True


def _track_strong_leg_quality(
    legs: Sequence[object],
    gate_stats: MutableMapping[str, int],
    *,
    allow_standard_hot: bool = False,
) -> bool:
    """Record per-leg failure counts; return True when all legs pass STRONG quality."""
    ok = True
    for leg in legs or []:
        gate_stats["legs_checked"] = gate_stats.get("legs_checked", 0) + 1
        if not isinstance(leg, dict):
            gate_stats["failed_tier"] = gate_stats.get("failed_tier", 0) + 1
            ok = False
            continue
        reason = _leg_strong_quality_fail_reason(leg, allow_standard_hot=allow_standard_hot)
        if reason:
            key = f"failed_{reason}"
            gate_stats[key] = gate_stats.get(key, 0) + 1
            ok = False
    return ok


def _demote_strong_recommendation(
    rec: str,
    ticket: Mapping[str, Any],
    *,
    gate_stats: MutableMapping[str, int] | None = None,
) -> str:
    """STRONG must be same-sport, high p_win, and all legs pass quality gates."""
    if rec != "STRONG":
        return rec
    n = _slip_leg_count(ticket)
    if n > STRONG_MAX_LEGS:
        return "OK"
    sports = _slip_sports(ticket)
    if len(sports) > 1 and not STRONG_ALLOW_CROSS_SPORT:
        return "OK"
    p_win = _slip_p_win(ticket)
    if p_win is None:
        return "OK"
    if n <= 2 and p_win < STRONG_MIN_P_WIN_2LEG:
        return "OK"
    if n == 3 and p_win < STRONG_MIN_P_WIN_3LEG:
        return "OK"
    if n == 4 and p_win < STRONG_MIN_P_WIN_4LEG:
        return "OK"
    if n == 5 and p_win < STRONG_MIN_P_WIN_5LEG:
        return "OK"
    if n >= 6 and p_win < STRONG_MIN_P_WIN_6LEG:
        return "OK"
    legs = [leg for leg in (ticket.get("legs") or []) if isinstance(leg, dict)]
    allow_std = _ticket_allows_strong_standard_hot(ticket)
    if gate_stats is not None:
        if not _track_strong_leg_quality(legs, gate_stats, allow_standard_hot=allow_std):
            return "OK"
    elif not all_legs_strong_quality(legs, allow_standard_hot=allow_std):
        return "OK"
    return rec


def log_strong_gate(payload: Mapping[str, Any], gate_stats: Mapping[str, int], *, n_strong: int) -> None:
    """Print daily STRONG gate summary for ticket build logs."""
    date = str(payload.get("date") or "unknown")[:10]
    print(
        f"[strong-gate] {date}: {n_strong} STRONG tickets "
        f"({int(gate_stats.get('legs_checked', 0))} legs checked, "
        f"{int(gate_stats.get('failed_goblin', 0))} failed goblin, "
        f"{int(gate_stats.get('failed_tier', 0))} failed tier, "
        f"{int(gate_stats.get('failed_streak', 0))} failed streak)"
    )


def collect_payload_payout_evs(payload: Mapping[str, Any]) -> list[float]:
    evs: list[float] = []
    for t in _iter_tickets(payload):
        pay = t.get("payout")
        if not isinstance(pay, dict):
            continue
        raw = pay.get("ev")
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            evs.append(v)
    return evs


def _collect_evs_by_leg_count(payload: Mapping[str, Any]) -> dict[int, list[float]]:
    by_legs: dict[int, list[float]] = defaultdict(list)
    for t in _iter_tickets(payload):
        pay = t.get("payout")
        if not isinstance(pay, dict):
            continue
        raw = pay.get("ev")
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            by_legs[_slip_leg_count(t)].append(v)
    return dict(by_legs)


def apply_slate_ev_tier_recommendations(
    payload: MutableMapping[str, Any],
    *,
    percentiles: Mapping[str, float] | None = None,
    log: bool = True,
    stratify_by_legs: bool = True,
) -> dict[str, float]:
    """
    Recompute payout.recommendation (and empirical_recommendation) for all tickets
    in a slate payload using percentile thresholds. Stores cuts on the payload.

    When stratify_by_legs is True (default), thresholds are computed separately
    per leg-count bucket so long parlays do not steal the STRONG label.
    """
    evs = collect_payload_payout_evs(payload)
    global_thresholds = compute_ev_tier_thresholds(evs, percentiles=percentiles)
    by_legs_evs = _collect_evs_by_leg_count(payload) if stratify_by_legs else {}
    thresholds_by_legs: dict[str, dict[str, float]] = {}
    for n, leg_evs in sorted(by_legs_evs.items()):
        if len(leg_evs) >= MIN_SAMPLES_FOR_PERCENTILES:
            thresholds_by_legs[str(n)] = compute_ev_tier_thresholds(leg_evs, percentiles=percentiles)
        else:
            thresholds_by_legs[str(n)] = dict(global_thresholds)

    counts = {"STRONG": 0, "OK": 0, "MARGINAL": 0, "SKIP": 0}
    demoted = 0
    gate_stats: dict[str, int] = {
        "legs_checked": 0,
        "failed_goblin": 0,
        "failed_tier": 0,
        "failed_streak": 0,
    }
    for t in _iter_tickets(payload):
        pay = t.get("payout")
        if not isinstance(pay, dict):
            continue
        raw = pay.get("ev")
        if raw is None:
            continue
        try:
            ev = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(ev):
            continue
        n = _slip_leg_count(t)
        th = thresholds_by_legs.get(str(n), global_thresholds) if stratify_by_legs else global_thresholds
        before = "STRONG" if t.get("strong_builder") else recommendation_from_ev(ev, th)
        rec = _demote_strong_recommendation(before, t, gate_stats=gate_stats)
        if before == "STRONG" and rec != "STRONG":
            demoted += 1
        pay["recommendation"] = rec
        t["empirical_recommendation"] = rec
        counts[rec] = counts.get(rec, 0) + 1

    payload["tier_ev_thresholds"] = global_thresholds
    if stratify_by_legs:
        payload["tier_ev_thresholds_by_legs"] = thresholds_by_legs
    payload["tier_ev_percentiles"] = dict(TIER_EV_PERCENTILES)
    payload["strong_tier_gates"] = {
        "max_legs": STRONG_MAX_LEGS,
        "min_p_win_2leg": STRONG_MIN_P_WIN_2LEG,
        "min_p_win_3leg": STRONG_MIN_P_WIN_3LEG,
        "min_p_win_4leg": STRONG_MIN_P_WIN_4LEG,
        "min_p_win_5leg": STRONG_MIN_P_WIN_5LEG,
        "min_p_win_6leg": STRONG_MIN_P_WIN_6LEG,
        "max_leg_prob_for_p_win": STRONG_MAX_LEG_PROB_FOR_P_WIN,
        "allow_cross_sport": STRONG_ALLOW_CROSS_SPORT,
        "require_goblin": True,
        "allow_standard_hot_on_mix": True,
        "require_tier_ab": True,
        "require_hot_streak": True,
    }
    payload["strong_gate_stats"] = dict(gate_stats)
    if percentiles:
        payload["tier_ev_percentiles"] = {**payload["tier_ev_percentiles"], **dict(percentiles)}

    if log:
        n = len(evs)
        print(
            f"[tier-ev] n={n} cuts: strong>={global_thresholds['strong']:.3f} "
            f"ok>={global_thresholds['ok']:.3f} marginal>={global_thresholds['marginal']:.3f} "
            f"| STRONG={counts['STRONG']} OK={counts['OK']} "
            f"MARGINAL={counts['MARGINAL']} SKIP={counts['SKIP']}"
            + (f" strong_demoted={demoted}" if demoted else "")
        )
        log_strong_gate(payload, gate_stats, n_strong=counts["STRONG"])
    return global_thresholds


def tier_distribution_summary(payload: Mapping[str, Any]) -> dict[str, int]:
    counts = {"STRONG": 0, "OK": 0, "MARGINAL": 0, "SKIP": 0}
    for t in _iter_tickets(payload):
        pay = t.get("payout") if isinstance(t.get("payout"), dict) else {}
        rec = str(pay.get("recommendation") or t.get("empirical_recommendation") or "SKIP").strip().upper()
        counts[rec if rec in counts else "SKIP"] = counts.get(rec if rec in counts else "SKIP", 0) + 1
    return counts
