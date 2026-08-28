"""Vectorized stand-ins for step7 row-wise scoring helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd


def to_num(s) -> pd.Series:
    if s is None:
        return pd.Series(dtype=float)
    if isinstance(s, pd.Series):
        return pd.to_numeric(s, errors="coerce")
    return pd.to_numeric(pd.Series(s), errors="coerce")


def pick_first_numeric(df: pd.DataFrame, *col_names: str) -> pd.Series:
    result = pd.Series(np.nan, index=df.index, dtype=float)
    for col in col_names:
        if col not in df.columns:
            continue
        v = to_num(df[col])
        result = result.where(result.notna(), v)
    return result


def blend_two_rates(hr5: pd.Series, hr10: pd.Series) -> pd.Series:
    a = to_num(hr5)
    b = to_num(hr10)
    return pd.Series(
        np.where(
            a.notna() & b.notna(),
            a * 0.50 + b * 0.50,
            np.where(a.notna(), a, np.where(b.notna(), b, np.nan)),
        ),
        index=a.index,
        dtype=float,
    )


def directional_line_hit_rate(
    df: pd.DataFrame,
    bet_dir,
    *,
    under_from_counts: bool = False,
) -> pd.Series:
    """Direction-aware blend of 5g/10g hit-rate columns (NBA/WNBA/MLB/Soccer)."""
    under = pd.Series(bet_dir, index=df.index).astype(str).str.upper().str.strip().eq("UNDER")
    hr5_over = pick_first_numeric(df, "line_hit_rate_over_ou_5", "line_hit_rate_over_5", "last5_hit_rate")
    hr10_over = pick_first_numeric(df, "line_hit_rate_over_ou_10", "line_hit_rate_over_10")
    hr5_under = pick_first_numeric(df, "line_hit_rate_under_ou_5", "line_hit_rate_under_5")
    hr10_under = pick_first_numeric(df, "line_hit_rate_under_ou_10", "line_hit_rate_under_10")
    if under_from_counts:
        l5o = to_num(df["last5_over"]) if "last5_over" in df.columns else pd.Series(np.nan, index=df.index)
        l5u = to_num(df["last5_under"]) if "last5_under" in df.columns else pd.Series(np.nan, index=df.index)
        denom = (l5o + l5u).replace(0, np.nan)
        derived = l5u / denom
        hr5_under = hr5_under.where(hr5_under.notna(), derived)
    hr5 = pd.Series(np.where(under, hr5_under, hr5_over), index=df.index, dtype=float)
    hr10 = pd.Series(np.where(under, hr10_under, hr10_over), index=df.index, dtype=float)
    return blend_two_rates(hr5, hr10)


def over_only_line_hit_rate(df: pd.DataFrame) -> pd.Series:
    hr5 = pick_first_numeric(df, "line_hit_rate_over_ou_5", "line_hit_rate_over_5", "last5_hit_rate")
    hr10 = pick_first_numeric(df, "line_hit_rate_over_ou_10", "line_hit_rate_over_10")
    return blend_two_rates(hr5, hr10)


def edge_transform_series(edge, cap: float = 3.0, power: float = 0.85) -> pd.Series:
    x = to_num(edge)
    arr = x.to_numpy(dtype=float, copy=False)
    mag = np.minimum(np.abs(arr), cap)
    out = np.sign(arr) * (mag ** power)
    return pd.Series(out, index=x.index, dtype=float)


def first_stat_projection(df: pd.DataFrame) -> pd.Series:
    """First of last5 / last10 / season averages."""
    return pick_first_numeric(df, "stat_last5_avg", "stat_last10_avg", "stat_season_avg")


def minutes_certainty_from_tier(tier, default: float = 0.80) -> pd.Series:
    s = pd.Series(tier).astype(str).str.upper()
    mapped = s.map({"HIGH": 1.00, "MEDIUM": 0.90, "LOW": 0.75, "UNKNOWN": default})
    return pd.to_numeric(mapped, errors="coerce").fillna(default)


def def_adj_from_rank(rank, n_teams: int) -> pd.Series:
    r = to_num(rank)
    n = max(int(n_teams), 2)
    mid = (n + 1.0) / 2.0
    return ((r - mid) / mid * 0.06).fillna(0.0)


def def_rank_signal_series(rank, bet_dir, n_teams: int) -> pd.Series:
    r = to_num(rank)
    n = max(int(n_teams), 2)
    signal = (r - 1.0) / (n - 1.0) * 2.0 - 1.0
    under = pd.Series(bet_dir, index=r.index).astype(str).str.upper().str.strip().eq("UNDER")
    signed = pd.Series(np.where(under, -signal, signal), index=r.index, dtype=float)
    return signed.where(r.notna(), 0.0)


def avg_vs_line_series(
    df: pd.DataFrame,
    line,
    bet_dir,
    *,
    last5_col: str = "stat_last5_avg_num",
    last10_col: str = "stat_last10_avg_num",
    season_col: str = "stat_season_avg_num",
) -> pd.Series:
    l = to_num(line).replace(0, np.nan)
    under = pd.Series(bet_dir, index=df.index).astype(str).str.upper().str.strip().eq("UNDER")
    score = pd.Series(0.0, index=df.index, dtype=float)
    weight = pd.Series(0.0, index=df.index, dtype=float)
    for col, w in ((last5_col, 0.50), (last10_col, 0.30), (season_col, 0.20)):
        if col not in df.columns:
            continue
        v = to_num(df[col])
        raw = ((v - l) / l).clip(-1.0, 1.0)
        raw = pd.Series(np.where(under, -raw, raw), index=df.index, dtype=float)
        ok = v.notna() & l.notna()
        score = score + raw.where(ok, 0.0) * w
        weight = weight + ok.astype(float) * w
    out = score / weight.replace(0.0, np.nan)
    return out.where(weight > 0.1, 0.0).fillna(0.0)
