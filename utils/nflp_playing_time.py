"""Preseason (NFLP) playing-time gates for overs/unders.

2025 L5 / snap% describe regular-season starter volume. Week-3 preseason
does not. Use this module for list membership and ticket seeding when
League=NFLP.

Rules:
  - Kickers usually play → keep the L5 >= 4 list gate.
  - Sit / cameo (2025 HIGH snap, skill 40–70% snap, or L5 from 2025
    boxscores): do not list skill OVERs. UNDERS already on the board may stay
    (volume will not be there). Backup QBs are not cameo even at 40–70% 2025 snap.
  - Backups (no 2025 starter role, including backup QBs): list skill OVERs
    only when D passes. L5 is not required (Sunday Drew Lock path).
  - Regular-season NFL (League=NFL) is unchanged.
"""

from __future__ import annotations

from typing import Any

from utils.nfl_prop_defense import prop_def_axis, snap_pct_to_minutes_tier

NFLP_LEAGUES = frozenset({"NFLP", "NFL PRESEASON", "44"})
SIT_SNAP_PCT = 70.0
CAMEO_SNAP_PCT = 40.0
POLICY_SIT = "sit"
POLICY_CAMEO = "cameo"
POLICY_BACKUP = "backup"
POLICY_PLAYS = "plays"
POLICY_NORMAL = "normal"
SNAPS_SIT = "0-15"
SNAPS_CAMEO = "15-30"
SNAPS_FULL = "30+"


def _tok(v: object) -> str:
    if v is None:
        return ""
    try:
        if v != v:  # NaN
            return ""
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    if s.lower() in {"", "nan", "none", "nat", "<na>"}:
        return ""
    return s


def is_nflp(league: object = None, league_id: object = None) -> bool:
    lg = _tok(league).upper()
    if lg in NFLP_LEAGUES:
        return True
    lid = _tok(league_id)
    if lid == "44":
        return True
    return False


def is_kicker_prop(prop: object) -> bool:
    return prop_def_axis(prop) == "kick"


def is_qb_prop(prop: object) -> bool:
    """Pass-volume props. Week-3 backups play Q2–Q4 even if 2025 snap was 40–70%."""
    p = str(prop or "").strip().lower().replace(" ", "_")
    p = p.replace("-", "_")
    if p.startswith("passing_") or p.startswith("pass_"):
        return True
    return p in {"completions", "pass_completions", "interceptions_thrown"}


def snap_pct_value(*vals: object) -> float | None:
    for v in vals:
        if v is None:
            continue
        try:
            if v != v:
                continue
        except (TypeError, ValueError):
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x != x:
            continue
        if x <= 1.5:
            x *= 100.0
        return x
    return None


def infer_starter_policy(
    *,
    league: object = None,
    league_id: object = None,
    prop: object = None,
    snap_pct: object = None,
    l5_over: object = None,
    l5_under: object = None,
) -> str:
    """sit | cameo | backup | plays | normal."""
    if not is_nflp(league, league_id):
        return POLICY_NORMAL
    if is_kicker_prop(prop):
        return POLICY_PLAYS
    snap = snap_pct_value(snap_pct)
    if snap is not None:
        if snap >= SIT_SNAP_PCT:
            return POLICY_SIT
        # Backup QBs get the bulk of week-3 snaps. A 2025 spot start (40–70%)
        # is not tonight's cameo the way a starting RB/WR 1-series is.
        if is_qb_prop(prop):
            return POLICY_BACKUP
        if snap >= CAMEO_SNAP_PCT:
            return POLICY_CAMEO
        return POLICY_BACKUP
    try:
        lo = int(float(l5_over)) if l5_over is not None and str(l5_over) not in ("", "nan") else 0
    except (TypeError, ValueError):
        lo = 0
    try:
        lu = int(float(l5_under)) if l5_under is not None and str(l5_under) not in ("", "nan") else 0
    except (TypeError, ValueError):
        lu = 0
    # L5 from 2025 regular-season logs ⇒ they had a starter-ish role.
    if lo >= 4 or lu >= 4:
        return POLICY_SIT
    return POLICY_BACKUP


def expected_snaps_bucket(policy: str) -> str:
    return {
        POLICY_SIT: SNAPS_SIT,
        POLICY_CAMEO: SNAPS_CAMEO,
        POLICY_BACKUP: SNAPS_FULL,
        POLICY_PLAYS: SNAPS_FULL,
        POLICY_NORMAL: SNAPS_FULL,
    }.get(policy or "", SNAPS_FULL)


def minutes_tier_for_policy(policy: str, snap_pct: object = None) -> str:
    """NFLP: map tonight's expected role, not 2025 snap%."""
    if policy == POLICY_SIT:
        return "LOW"
    if policy == POLICY_CAMEO:
        return "MEDIUM"
    if policy in (POLICY_BACKUP, POLICY_PLAYS):
        return "HIGH"
    return snap_pct_to_minutes_tier(snap_pct)


def nflp_list_eligible(
    *,
    policy: str,
    side: str,
    pick_type: str = "Standard",
    d_ok: bool = False,
    l5_over: int | None = None,
    l5_under: int | None = None,
) -> bool:
    """Whether a play belongs on the NFLP best-props / ticket-seed list."""
    pt = (pick_type or "Standard").strip()
    if pt == "Demon":
        return False
    if pt == "Goblin" and side != "OVER":
        return False
    if pt not in ("Standard", "Goblin"):
        return False
    side_u = (side or "").upper()
    if policy == POLICY_PLAYS:
        l5 = l5_over if side_u == "OVER" else l5_under
        return l5 is not None and int(l5) >= 4
    if policy in (POLICY_SIT, POLICY_CAMEO):
        # 2025 volume will not show up. Do not list skill overs.
        return side_u == "UNDER" and pt == "Standard"
    # backup: D veto on overs; L5 not required.
    if side_u == "OVER":
        return bool(d_ok)
    if side_u == "UNDER":
        return bool(d_ok) or (l5_under is not None and int(l5_under) >= 4)
    return False


def d_aligned_side(def_tier: object) -> str | None:
    """OVER vs Weak|Below Avg, UNDER vs Elite|Above Avg. Avg/unknown → None."""
    t = str(def_tier or "").strip().lower().replace("_", " ")
    if t in {"weak", "below avg", "below average", "easy", "easiest"}:
        return "OVER"
    if t in {"elite", "above avg", "above average", "hard", "hardest", "tough", "solid"}:
        return "UNDER"
    return None


def policy_from_row(r: Any) -> str:
    get = r.get if hasattr(r, "get") else lambda *_a, **_k: None
    existing = _tok(get("starter_policy") or get("Starter Policy")).lower()
    if existing in {POLICY_SIT, POLICY_CAMEO, POLICY_BACKUP, POLICY_PLAYS, POLICY_NORMAL}:
        return existing
    snap = snap_pct_value(
        get("snap_pct_L3"),
        get("Snap L3"),
        get("snap_pct_season"),
        get("Snap %"),
    )
    return infer_starter_policy(
        league=get("league") or get("League"),
        league_id=get("league_id") or get("League Id"),
        prop=get("prop") or get("Prop") or get("prop_type") or get("prop_type_normalized"),
        snap_pct=snap,
        l5_over=get("l5_over") if get("l5_over") is not None else get("L5 Over"),
        l5_under=get("l5_under") if get("l5_under") is not None else get("L5 Under"),
    )


def apply_nflp_playing_time(df):
    """Write starter_policy, expected_snaps; remap minutes_tier for NFLP rows."""
    import pandas as pd

    out = df.copy()
    n = len(out)
    if n == 0:
        out["starter_policy"] = pd.Series(dtype="object")
        out["expected_snaps"] = pd.Series(dtype="object")
        return out

    def _col(*names: str):
        for nme in names:
            if nme in out.columns:
                return out[nme]
        return pd.Series([""] * n, index=out.index)

    league = _col("league", "League")
    league_id = _col("league_id")
    prop = _col("prop_type_normalized", "prop_type", "stat_type", "prop")
    snap = pd.to_numeric(_col("snap_pct_L3", "snap_pct_season", "snap_pct"), errors="coerce")
    l5o = pd.to_numeric(_col("l5_over", "last5_over"), errors="coerce")
    l5u = pd.to_numeric(_col("l5_under", "last5_under"), errors="coerce")

    policies: list[str] = []
    buckets: list[str] = []
    tiers: list[str] = []
    for i in out.index:
        pol = infer_starter_policy(
            league=league.at[i] if i in league.index else "",
            league_id=league_id.at[i] if i in league_id.index else "",
            prop=prop.at[i] if i in prop.index else "",
            snap_pct=snap.at[i] if i in snap.index else None,
            l5_over=l5o.at[i] if i in l5o.index else None,
            l5_under=l5u.at[i] if i in l5u.index else None,
        )
        policies.append(pol)
        buckets.append(expected_snaps_bucket(pol))
        snap_i = snap.at[i] if i in snap.index else None
        if is_nflp(league.at[i] if i in league.index else "", league_id.at[i] if i in league_id.index else ""):
            tiers.append(minutes_tier_for_policy(pol, snap_i))
        else:
            existing = ""
            if "minutes_tier" in out.columns:
                existing = str(out.at[i, "minutes_tier"] or "").strip()
            tiers.append(existing if existing and existing.upper() not in {"NAN", "NONE", "UNKNOWN", ""} else snap_pct_to_minutes_tier(snap_i))

    out["starter_policy"] = policies
    out["expected_snaps"] = buckets
    out["minutes_tier"] = tiers
    return out
