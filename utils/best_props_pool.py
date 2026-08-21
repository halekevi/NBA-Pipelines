"""Best-props style L5 / cover-Δ / D badge pool for ticket seeding.

Mirrors scripts/rank_best_props_today.py badge recipe:
  Hard gate: directional L5 >= 4; Std OVER/UNDER + Goblin OVER only.
  Badge: Gold/Silver/Bronze from L5, Cover, Delta, Dir, D, Rank checks.

Ticket seed priority (L5-first with D as the main add-on gate):
  0) L5 == 5 and agreeing def direction
  1) L5 == 4 and agreeing def direction
  2) L5 >= 4 without congruent def (L5=5 no-D before L5=4 no-D)

Within each tier: higher L5, then cover magnitude. Preferred pool expands
tier-by-tier until min_preferred legs are available.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

WEAK = {"weak", "easy", "easiest"}
ELITE = {"elite", "hard", "hardest", "tough"}
WEAK_ALIGN = WEAK | {"below avg", "below average"}
ELITE_ALIGN = ELITE | {"above avg", "above average", "solid"}
SKIP_PROPS = {"fantasy score", "fantasy"}
_ATP_ELITE_MAX = 10
_ATP_ABOVE_AVG_MAX = 25
_ATP_AVG_MAX = 50
_ATP_BELOW_AVG_MAX = 100
_UNKNOWN_OPP = {"unknown_opp", "unk", "unknown", ""}
DELTA_FLOOR = 0.50
DELTA_PCT = 0.15
BADGE_ORDER = {"Gold": 0, "Silver": 1, "Bronze": 2, "": 3}
# Seed tiers: L5=5+D → L5=4+D → L5>=4 without D
SEED_TIER_L5_5_D = 0
SEED_TIER_L5_4_D = 1
SEED_TIER_L5_NO_D = 2
SEED_TIER_LABELS = {
    SEED_TIER_L5_5_D: "L5=5+D",
    SEED_TIER_L5_4_D: "L5=4+D",
    SEED_TIER_L5_NO_D: "L5>=4 no-D",
}
MIN_PREFERRED_LEGS = 8


def _pick(v: object) -> str:
    s = str(v or "").strip().lower()
    if "dem" in s:
        return "Demon"
    if "gob" in s:
        return "Goblin"
    if "std" in s or s == "standard":
        return "Standard"
    return str(v or "").strip() or "Unknown"


def _dir(r: dict | pd.Series) -> str:
    for c in ("final_bet_direction", "bet_direction", "direction", "over_under", "model_dir"):
        s = str(r.get(c) or "").strip().upper()
        if s in ("OVER", "HIGHER"):
            return "OVER"
        if s in ("UNDER", "LOWER"):
            return "UNDER"
    return ""


def _model_dir(r: dict | pd.Series) -> str:
    s = str(r.get("model_dir") or "").strip().upper()
    return s if s in ("OVER", "UNDER") else ""


def _num(v: object) -> int | None:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if str(v).strip() in ("", "nan", "None"):
            return None
        return int(float(v))
    except Exception:
        return None


def _flt(v: object) -> float | None:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if str(v).strip() in ("", "nan", "None"):
            return None
        return float(v)
    except Exception:
        return None


def _clean(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("", "nan", "none") else s


def _delta_need(line: float) -> float:
    return max(DELTA_FLOOR, abs(line) * DELTA_PCT)


def _atp_tier_from_rank(rank: object) -> str:
    v = _num(rank)
    if v is None or v <= 0:
        return ""
    if v <= _ATP_ELITE_MAX:
        return "Elite"
    if v <= _ATP_ABOVE_AVG_MAX:
        return "Above Avg"
    if v <= _ATP_AVG_MAX:
        return "Avg"
    if v <= _ATP_BELOW_AVG_MAX:
        return "Below Avg"
    return "Weak"


def _opp_name(r: dict | pd.Series) -> str:
    return _clean(r.get("opp_team") or r.get("opp") or "").lower()


def _def_rank(r: dict | pd.Series) -> float | None:
    sport = str(r.get("sport") or "").strip().upper()
    if sport == "TENNIS":
        if _opp_name(r) in _UNKNOWN_OPP:
            return None
        v = _num(r.get("opponent_rank")) or _num(r.get("opponent_def_rank"))
        return float(v) if v is not None and v > 0 else None
    for c in ("OVERALL_DEF_RANK", "stat_def_rank", "def_rank", "opponent_def_rank"):
        v = _num(r.get(c))
        if v is not None and v > 0:
            return float(v)
    return None


def _n_teams(df: pd.DataFrame) -> int | None:
    for c in ("OVERALL_DEF_RANK", "stat_def_rank", "def_rank"):
        if c not in df.columns:
            continue
        m = pd.to_numeric(df[c], errors="coerce").max()
        if pd.notna(m) and float(m) >= 5:
            return int(m)
    return None


def _def_tier(r: dict | pd.Series) -> str:
    sport = str(r.get("sport") or "").strip().upper()
    if sport == "TENNIS":
        return _atp_tier_from_rank(_def_rank(r))
    raw = (
        _clean(r.get("stat_def_tier"))
        or _clean(r.get("DEF_TIER"))
        or _clean(r.get("def_tier"))
        or _clean(r.get("opp_def_tier"))
    )
    low = raw.lower()
    if low in {"n/a", "na", "none"}:
        return ""
    if low in WEAK or "easy" in low:
        return "Weak"
    if "below" in low:
        return "Below Avg"
    if low in ELITE or "hard" in low or "elite" in low:
        return "Elite"
    if "above" in low:
        return "Above Avg"
    return raw


def _over_d_ok(sport: str, tier: str) -> bool:
    if sport in ("WNBA", "MLB"):
        return tier == "Weak"
    if sport in ("SOCCER", "TENNIS", "SOC"):
        return tier in ("Weak", "Below Avg")
    return False


def _under_d_ok(sport: str, tier: str) -> bool:
    if sport in ("WNBA", "MLB"):
        return tier == "Elite"
    if sport in ("SOCCER", "TENNIS", "SOC"):
        return tier in ("Elite", "Above Avg")
    return False


def _prop_avg(r: dict | pd.Series) -> float | None:
    seas = _flt(r.get("stat_season_avg")) or _flt(r.get("season_avg"))
    if seas is not None:
        return seas
    vals = []
    for i in range(1, 21):
        v = _flt(r.get(f"stat_g{i}"))
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _l5(r: dict | pd.Series, over: bool) -> int | None:
    if over:
        return _num(r.get("l5_over")) or _num(r.get("last5_over"))
    return _num(r.get("l5_under")) or _num(r.get("last5_under"))


def _l10(r: dict | pd.Series, over: bool) -> int | None:
    if over:
        return _num(r.get("l10_over"))
    return _num(r.get("l10_under"))


def _badge(rec: dict[str, Any], n_teams: int | None) -> dict[str, Any]:
    side = rec.get("side") or ""
    over = side == "OVER"
    l5 = rec["l5_over"] if over else rec["l5_under"]
    cover = rec.get("cover")
    line = rec.get("line") if isinstance(rec.get("line"), (int, float)) else _flt(rec.get("line"))
    tier = rec.get("def") or ""
    rank = rec.get("def_rank")
    model = rec.get("model_dir") or ""
    sport = str(rec.get("sport") or "").strip().upper()

    checks: dict[str, bool | None] = {}
    checks["L5"] = None if l5 is None else l5 >= 4
    if cover is None:
        checks["Cover"] = None
    elif over:
        checks["Cover"] = cover > 0
    elif side == "UNDER":
        checks["Cover"] = cover < 0
    else:
        checks["Cover"] = None

    if cover is None or line is None:
        checks["Delta"] = None
    else:
        need = _delta_need(float(line))
        checks["Delta"] = cover >= need if over else cover <= -need

    if not model:
        checks["Dir"] = None
    elif rec.get("pick_type") == "Goblin":
        checks["Dir"] = model == "OVER"
    else:
        checks["Dir"] = model == side

    skip_matchup = not tier and rank is None
    if skip_matchup:
        checks["D"] = False
        checks["Rank"] = None
    else:
        if not tier:
            checks["D"] = False
        elif over:
            checks["D"] = _over_d_ok(sport, tier)
        elif side == "UNDER":
            checks["D"] = _under_d_ok(sport, tier)
        else:
            checks["D"] = False
        if rank is None:
            checks["Rank"] = None
        elif sport == "TENNIS":
            checks["Rank"] = rank > _ATP_AVG_MAX if over else rank <= _ATP_ABOVE_AVG_MAX
        elif not n_teams:
            checks["Rank"] = None
        elif over:
            checks["Rank"] = rank >= int(math.ceil(0.5 * n_teams))
        else:
            checks["Rank"] = rank <= int(math.floor(0.4 * n_teams))

    applicable = {k: v for k, v in checks.items() if v is not None}
    misses = [k for k, v in applicable.items() if v is False]
    if len(applicable) < 4:
        badge = ""
    elif not misses:
        badge = "Gold"
    elif len(misses) == 1:
        badge = "Silver"
    elif len(misses) == 2:
        badge = "Bronze"
    else:
        badge = ""
    return {
        "checks": checks,
        "misses": misses,
        "badge": badge,
        "miss_s": ", ".join(misses) if misses else "",
        "d_ok": bool(checks.get("D") is True),
    }


def _seed_tier(l5: int | None, d_ok: bool) -> int:
    """L5=5+D → L5=4+D → L5>=4 without congruent D."""
    if l5 is None or l5 < 4:
        return 99
    if l5 >= 5 and d_ok:
        return SEED_TIER_L5_5_D
    if l5 == 4 and d_ok:
        return SEED_TIER_L5_4_D
    return SEED_TIER_L5_NO_D


def row_to_best_props_rec(r: dict | pd.Series, n_teams: int | None = None) -> dict[str, Any] | None:
    """Build a best-props rec for one slate/ticket row, or None if not list-eligible."""
    prop = str(r.get("prop_type") or r.get("prop") or "").strip()
    if prop.lower() in SKIP_PROPS:
        return None
    pick_type = _pick(r.get("pick_type"))
    if pick_type == "Demon":
        return None
    side = _dir(r)
    if pick_type == "Goblin" and side != "OVER":
        return None
    if pick_type == "Standard" and side not in ("OVER", "UNDER"):
        return None
    if pick_type not in ("Standard", "Goblin"):
        return None

    line = _flt(r.get("line"))
    avg = _prop_avg(r)
    cover = None if avg is None or line is None else avg - line
    l5o = _l5(r, True)
    l5u = _l5(r, False)
    if side == "OVER" and (l5o is None or l5o < 4):
        return None
    if side == "UNDER" and (l5u is None or l5u < 4):
        return None

    l5_dir = l5o if side == "OVER" else l5u
    rec: dict[str, Any] = {
        "sport": str(r.get("sport") or "").strip().upper(),
        "player": str(r.get("player") or "").strip(),
        "prop": prop,
        "line": r.get("line") if line is None else line,
        "pick_type": pick_type,
        "side": side,
        "model_dir": _model_dir(r),
        "l5_over": l5o,
        "l5_under": l5u,
        "l10_over": _l10(r, True),
        "l10_under": _l10(r, False),
        "season_avg": None if avg is None else round(avg, 2),
        "cover": None if cover is None else round(cover, 2),
        "def": _def_tier(r),
        "def_rank": _def_rank(r),
    }
    rec.update(_badge(rec, n_teams))
    if not rec.get("badge"):
        return None
    rec["seed_tier"] = _seed_tier(l5_dir, bool(rec.get("d_ok")))
    rec["l5_dir"] = l5_dir
    return rec


def annotate_best_props_pool(df: pd.DataFrame) -> pd.DataFrame:
    """Annotate dataframe with best_props_* columns; drop non-eligible rows."""
    if df is None or df.empty:
        return df.iloc[0:0].copy() if df is not None else pd.DataFrame()
    n_teams = _n_teams(df)
    badges: list[str] = []
    covers: list[float | None] = []
    l5_dir: list[int | None] = []
    miss_s: list[str] = []
    seed_tiers: list[int] = []
    d_oks: list[bool] = []
    keep_idx: list[Any] = []
    for idx in df.index:
        row = df.loc[idx]
        rec = row_to_best_props_rec(row, n_teams)
        if rec is None:
            continue
        keep_idx.append(idx)
        badges.append(str(rec.get("badge") or ""))
        covers.append(rec.get("cover"))
        l5_dir.append(rec.get("l5_dir"))
        miss_s.append(str(rec.get("miss_s") or ""))
        seed_tiers.append(int(rec.get("seed_tier", 99)))
        d_oks.append(bool(rec.get("d_ok")))
    if not keep_idx:
        return df.iloc[0:0].copy()
    out = df.loc[keep_idx].copy()
    out["best_props_badge"] = badges
    out["best_props_cover"] = covers
    out["best_props_l5"] = l5_dir
    out["best_props_misses"] = miss_s
    out["best_props_seed_tier"] = seed_tiers
    out["best_props_d_ok"] = d_oks
    # Within no-D tier, still prefer L5=5 over L5=4 via _bp_l5.
    l5_keys = [(-(x or 0)) for x in l5_dir]
    cover_keys: list[float] = []
    for i, c in enumerate(covers):
        side = _dir(out.iloc[i])
        if c is None:
            cover_keys.append(0.0)
        elif side == "OVER":
            cover_keys.append(-float(c))
        else:
            cover_keys.append(float(c))
    badge_ords = [BADGE_ORDER.get(b, 3) for b in badges]
    out = out.assign(
        _bp_seed=seed_tiers,
        _bp_l5=l5_keys,
        _bp_cover=cover_keys,
        _bp_badge_ord=badge_ords,
    )
    out = out.sort_values(
        ["_bp_seed", "_bp_l5", "_bp_badge_ord", "_bp_cover"],
        ascending=[True, True, True, True],
    )
    return out.drop(columns=["_bp_seed", "_bp_l5", "_bp_cover", "_bp_badge_ord"], errors="ignore")


def prefer_best_props_seed(
    df: pd.DataFrame,
    *,
    prefer_gold_silver: bool = True,
    min_preferred: int = MIN_PREFERRED_LEGS,
) -> pd.DataFrame:
    """Reorder ticket pool: L5=5+D → L5=4+D → L5>=4 no-D.

    Expands seed tiers until ``min_preferred`` legs are available. Bronze badge
    legs may still appear inside those tiers; ``prefer_gold_silver`` drops
    Bronze only after the tiered pool is chosen and Gold+Silver alone is thick
    enough.
    """
    if df is None or df.empty:
        return df.iloc[0:0].copy() if df is not None else pd.DataFrame()
    annotated = annotate_best_props_pool(df)
    if annotated.empty:
        # No L5≥4 badge legs — keep original order rather than emptying the pool.
        return df

    tier_col = "best_props_seed_tier"
    chosen = annotated.iloc[0:0].copy()
    for tier in (SEED_TIER_L5_5_D, SEED_TIER_L5_4_D, SEED_TIER_L5_NO_D):
        part = annotated[annotated[tier_col] == tier]
        if part.empty:
            continue
        chosen = pd.concat([chosen, part], ignore_index=True)
        if len(chosen) >= int(min_preferred):
            break
    if chosen.empty:
        chosen = annotated

    if prefer_gold_silver:
        pref = chosen[chosen["best_props_badge"].isin(["Gold", "Silver"])]
        if len(pref) >= int(min_preferred):
            return pref.reset_index(drop=True)
    return chosen.reset_index(drop=True)


def sort_ticket_seed_pool(df: pd.DataFrame) -> pd.DataFrame:
    """Keep L5/D seed tiers ahead of rank_score when sorting ticket candidates."""
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    cols: list[str] = []
    asc: list[bool] = []
    if "best_props_seed_tier" in out.columns:
        out["_seed_tier_sort"] = pd.to_numeric(out["best_props_seed_tier"], errors="coerce").fillna(99)
        cols.append("_seed_tier_sort")
        asc.append(True)
    if "best_props_l5" in out.columns:
        out["_l5_sort"] = pd.to_numeric(out["best_props_l5"], errors="coerce").fillna(0)
        cols.append("_l5_sort")
        asc.append(False)
    if "rank_score" in out.columns:
        cols.append("rank_score")
        asc.append(False)
    if not cols:
        return out
    out = out.sort_values(cols, ascending=asc, na_position="last")
    return out.drop(columns=["_seed_tier_sort", "_l5_sort"], errors="ignore").reset_index(drop=True)
