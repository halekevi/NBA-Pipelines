"""CFB time-of-possession / run-heavy clock script.

Run-heavy teams hold the ball longer, leave the opponent fewer snaps, and
throw less. Pass/rec overs shrink; rush overs for that team's RB inflate;
the opponent's skill overs (pass/rec/rush) shrink because they get the ball
less.

Rush rate is rush_att / (rush_att + pass_att). TOP minutes come from ESPN
possessionTimeSeconds when rankings were rebuilt; otherwise rush rate +
plays/g is the proxy.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Rush-attempt share. ~0.50 is a typical FBS mix.
RUN_HEAVY = 0.58
RUN_LEAN = 0.54
PASS_LEAN = 0.46
PASS_HEAVY = 0.38

# Plays/g: low = they chew clock (or go 3-and-out). Rankings already rank
# fewest plays as rank 1. ~65–70 is slow; 75+ is a track meet.
SLOW_PLAYS = 64.0


def rush_rate(rush_att: Any, pass_att: Any) -> float | None:
    ra = pd.to_numeric(rush_att, errors="coerce")
    pa = pd.to_numeric(pass_att, errors="coerce")
    if pd.isna(ra) and pd.isna(pa):
        return None
    ra_f = float(ra) if pd.notna(ra) else 0.0
    pa_f = float(pa) if pd.notna(pa) else 0.0
    tot = ra_f + pa_f
    if tot <= 0:
        return None
    return ra_f / tot


def top_minutes(top_sec_pg: Any) -> float | None:
    sec = pd.to_numeric(top_sec_pg, errors="coerce")
    if pd.isna(sec):
        return None
    return float(sec) / 60.0


def clock_tier(
    rate: float | None,
    *,
    plays_pg: Any = None,
    top_min: float | None = None,
) -> str:
    """Own-offense script label."""
    if rate is None:
        return ""
    if rate >= RUN_HEAVY:
        label = "Run-heavy clock"
    elif rate >= RUN_LEAN:
        label = "Run-lean"
    elif rate <= PASS_HEAVY:
        label = "Pass-heavy"
    elif rate <= PASS_LEAN:
        label = "Pass-lean"
    else:
        label = "Balanced"
    plays = pd.to_numeric(plays_pg, errors="coerce")
    if pd.notna(plays) and float(plays) <= SLOW_PLAYS and rate >= RUN_LEAN:
        label = "Run-heavy clock"
    if top_min is not None and top_min >= 32.0 and rate >= RUN_LEAN:
        label = "Run-heavy clock"
    return label


def _is_clock_kill(tier: str) -> bool:
    return tier == "Run-heavy clock"


def clock_script_multiplier(
    prop: str,
    direction: str,
    *,
    team_rush_rate: float | None,
    opp_rush_rate: float | None,
    team_plays_pg: Any = None,
    opp_plays_pg: Any = None,
    team_top_min: float | None = None,
    opp_top_min: float | None = None,
) -> tuple[float, str]:
    """Adjust rank score for clock / run-pass mix. Caps 0.85–1.15."""
    prop_n = str(prop or "").strip().lower().replace(" ", "_")
    side = str(direction or "").strip().upper()
    if side not in {"OVER", "UNDER"}:
        return 1.0, ""

    team_tier = clock_tier(
        team_rush_rate, plays_pg=team_plays_pg, top_min=team_top_min
    )
    opp_tier = clock_tier(opp_rush_rate, plays_pg=opp_plays_pg, top_min=opp_top_min)
    own_kill = _is_clock_kill(team_tier)
    opp_kill = _is_clock_kill(opp_tier)
    own_pass = team_tier == "Pass-heavy"
    notes: list[str] = []
    mult = 1.0

    pass_like = any(
        k in prop_n
        for k in (
            "pass_yd",
            "pass_td",
            "rec_yd",
            "receiving",
            "reception",
            "rec_td",
            "longest_rec",
        )
    )
    rush_like = any(k in prop_n for k in ("rush_yd", "rush_td", "rushing", "longest_rush"))

    if own_kill:
        notes.append(f"own {team_tier}")
    elif team_tier:
        notes.append(f"own {team_tier}")
    if opp_kill:
        notes.append(f"opp {opp_tier}")

    if pass_like:
        if own_kill and side == "OVER":
            mult *= 0.90
        elif own_kill and side == "UNDER":
            mult *= 1.08
        elif own_pass and side == "OVER":
            mult *= 1.04
        elif own_pass and side == "UNDER":
            mult *= 0.96
        if opp_kill and side == "OVER":
            mult *= 0.93  # they hold the ball → you snap less
        elif opp_kill and side == "UNDER":
            mult *= 1.05
    elif rush_like:
        if own_kill and side == "OVER":
            mult *= 1.06
        elif own_kill and side == "UNDER":
            mult *= 0.94
        if opp_kill and side == "OVER":
            mult *= 0.95  # fewer of your possessions
        elif opp_kill and side == "UNDER":
            mult *= 1.04

    if not notes or abs(mult - 1.0) < 0.005:
        return 1.0, " / ".join(notes)
    return max(0.85, min(1.15, round(mult, 3))), " / ".join(notes)


def enrich_rankings_clock(df: pd.DataFrame) -> pd.DataFrame:
    """Add rush rate / TOP minutes / clock tier onto a unit-rankings frame."""
    out = df.copy()
    ra = out["off_rush_att_pg"] if "off_rush_att_pg" in out.columns else None
    pa = out["off_pass_att_pg"] if "off_pass_att_pg" in out.columns else None
    if ra is not None and pa is not None:
        rates = [
            rush_rate(r, p) for r, p in zip(ra.tolist(), pa.tolist())
        ]
        out["off_rush_rate"] = rates
    if "off_top_sec_pg" in out.columns:
        out["off_top_min_pg"] = [
            top_minutes(x) for x in out["off_top_sec_pg"].tolist()
        ]
    elif "off_top_min_pg" not in out.columns:
        out["off_top_min_pg"] = pd.NA
    plays = out["off_plays_pg"] if "off_plays_pg" in out.columns else pd.Series([None] * len(out))
    tops = out["off_top_min_pg"] if "off_top_min_pg" in out.columns else pd.Series([None] * len(out))
    rates = out["off_rush_rate"] if "off_rush_rate" in out.columns else pd.Series([None] * len(out))
    out["off_clock_tier"] = [
        clock_tier(
            rates.iloc[i] if i < len(rates) else None,
            plays_pg=plays.iloc[i] if i < len(plays) else None,
            top_min=(
                None
                if i >= len(tops) or pd.isna(tops.iloc[i])
                else float(tops.iloc[i])
            ),
        )
        for i in range(len(out))
    ]
    return out
