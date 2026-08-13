"""Attach prop-category opponent defense onto a multi-sport slate.

Ticket scoring/gates still read ``def_tier``. After attach, rows with a
category rank use that stat's tier (Elite/Weak/…) instead of overall D.
Overall labels are kept in ``overall_def_tier``.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from utils.matchup_edge.stat_defense import display_tier_from_stat


def attach_stat_defense_all_sports(df: pd.DataFrame) -> pd.DataFrame:
    """Fill stat_def_category / stat_def_rank / stat_def_tier per sport."""
    if df is None or len(df) == 0:
        return df
    if "sport" not in df.columns:
        return df
    out = df
    sports = {str(s).strip().upper() for s in out["sport"].dropna().unique()}

    def _run(label: str, fn: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
        nonlocal out
        try:
            out = fn(out)
        except Exception as exc:
            print(f"  [stat-def] {label} attach skipped: {exc}")

    if "WNBA" in sports:
        from utils.wnba_prop_defense import attach_stat_defense_columns as _wnba

        _run("WNBA", _wnba)
    if sports & {"NBA", "NBA1H", "NBA1Q"}:
        from utils.nba_prop_defense import lookup_stat_defense as _nba_lu
        from utils.prop_defense_common import attach_lookup_columns

        for sp in ("NBA", "NBA1H", "NBA1Q"):
            if sp in sports:
                _run(sp, lambda d, s=sp: attach_lookup_columns(d, sport=s, lookup_fn=_nba_lu))
    if "MLB" in sports:
        from utils.mlb_prop_defense import attach_stat_defense_columns as _mlb

        _run("MLB", _mlb)
    if "NHL" in sports:
        from utils.nhl_prop_defense import attach_stat_defense_columns as _nhl

        _run("NHL", _nhl)
    if sports & {"SOCCER", "SOC"}:
        from utils.soccer_prop_defense import attach_stat_defense_columns as _soc
        from utils.prop_defense_common import attach_lookup_columns
        from utils.soccer_prop_defense import lookup_stat_defense as _soc_lu

        if "SOCCER" in sports:
            _run("SOCCER", _soc)
        if "SOC" in sports:
            _run("SOC", lambda d: attach_lookup_columns(d, sport="SOC", lookup_fn=_soc_lu))
    if "CBB" in sports:
        from utils.cbb_prop_defense import attach_stat_defense_columns as _cbb

        _run("CBB", lambda d: _cbb(d, sport="CBB"))
    if "WCBB" in sports:
        from utils.cbb_prop_defense import attach_stat_defense_columns as _cbb

        _run("WCBB", lambda d: _cbb(d, sport="WCBB"))
    if "NFL" in sports:
        from utils.football_prop_defense import attach_stat_defense_columns as _fb

        _run("NFL", lambda d: _fb(d, sport="NFL"))
    if "CFB" in sports:
        from utils.football_prop_defense import attach_stat_defense_columns as _fb

        _run("CFB", lambda d: _fb(d, sport="CFB"))
    return out


def apply_category_def_to_ticket_tier(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer category-specific D on def_tier when a stat rank exists."""
    if df is None or len(df) == 0:
        return df
    out = df.copy()
    if "def_tier" in out.columns and "overall_def_tier" not in out.columns:
        out["overall_def_tier"] = out["def_tier"]
    elif "overall_def_tier" not in out.columns:
        out["overall_def_tier"] = ""

    if "stat_def_rank" not in out.columns:
        return out

    rank = pd.to_numeric(out["stat_def_rank"], errors="coerce")
    raw = out.get("stat_def_tier", pd.Series("", index=out.index))
    display = raw.map(display_tier_from_stat)
    use = rank.notna() & display.astype(str).str.strip().ne("")
    n = int(use.sum())
    if n == 0:
        return out
    if "def_tier" not in out.columns:
        out["def_tier"] = ""
    out.loc[use, "def_tier"] = display.loc[use]
    out["DEF_TIER"] = out["def_tier"]
    if "opponent_def_rank" in out.columns:
        out.loc[use, "opponent_def_rank"] = rank.loc[use]
    if "def_rank" in out.columns:
        out.loc[use, "def_rank"] = rank.loc[use]
    print(f"  [stat-def] category D on {n}/{len(out)} legs (def_tier = that prop's allowed-stat rank)")
    return out


def attach_and_apply_category_defense(df: pd.DataFrame) -> pd.DataFrame:
    return apply_category_def_to_ticket_tier(attach_stat_defense_all_sports(df))


def directional_l5_hits_series(df: pd.DataFrame) -> pd.Series:
    direction = df.get("direction", pd.Series("", index=df.index)).astype(str).str.upper().str.strip()
    l5o = pd.to_numeric(df.get("l5_over"), errors="coerce")
    l5u = pd.to_numeric(df.get("l5_under"), errors="coerce")
    return l5u.where(direction.eq("UNDER"), l5o)


def category_def_align_mask(df: pd.DataFrame, def_tier: pd.Series | None = None) -> pd.Series:
    """OVER vs Weak/Below Avg, UNDER vs Elite/Above Avg — after category overlay."""
    direction = df.get("direction", pd.Series("", index=df.index)).astype(str).str.upper().str.strip()
    if def_tier is None:
        from utils.defense_tiers import normalize_def_tier_label

        raw = df.get("def_tier", pd.Series("", index=df.index))
        def_tier = raw.map(lambda x: str(normalize_def_tier_label(x) or "").upper())
    over = direction.eq("OVER") & def_tier.isin(["WEAK", "BELOW AVG"])
    under = direction.eq("UNDER") & def_tier.isin(["ELITE", "ABOVE AVG"])
    return over | under
