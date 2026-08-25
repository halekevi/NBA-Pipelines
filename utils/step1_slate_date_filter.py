"""Same-day ET slate filter for PrizePicks step1 fetchers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

_ET = ZoneInfo("America/New_York")


def no_props_log_line(sport_label: str, fetch_date: str) -> str:
    return (
        f"[{sport_label} step1] No props for {fetch_date} — "
        "board may be tomorrow's slate or off-season"
    )


def eastern_today_ymd() -> str:
    return datetime.now(_ET).date().isoformat()


def add_calendar_days(ymd: str, days: int = 1) -> str:
    raw = str(ymd or "").strip()[:10]
    try:
        return (date.fromisoformat(raw) + timedelta(days=int(days))).isoformat()
    except ValueError:
        return ""


def should_preserve_append_output(out_path: str | Path, append: bool) -> bool:
    """True when --append should keep an existing non-empty step1 CSV unchanged."""
    if not append:
        return False
    path = Path(out_path)
    if not path.is_file():
        return False
    try:
        existing = pd.read_csv(path, encoding="utf-8-sig")
        return len(existing) > 0
    except Exception:
        return False


def stamp_board_asof(df: pd.DataFrame, board_date: str | None = None) -> pd.DataFrame:
    """Tag fetch calendar vs tip-day so a gameday rebuild can compare Standard lines.

    ``board_date`` / ``line_asof`` = when PrizePicks was pulled (Eastern today unless
    overridden). ``game_date`` stays the ET tip-day from start_time.
    """
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if out.empty and "board_date" not in out.columns:
        out["board_date"] = pd.Series(dtype="string")
        out["line_asof"] = pd.Series(dtype="string")
        return out
    bd = str(board_date or eastern_today_ymd()).strip()[:10]
    out["board_date"] = bd
    out["line_asof"] = bd
    return out


def apply_game_date_filter(
    df: pd.DataFrame,
    target_date: str,
    tz_name: str,
    allow_nearest_future: bool,
    *,
    start_time_col: str = "start_time",
    include_tomorrow: bool = False,
    board_date: str | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """
    Filter props to fetch_date (ET calendar) unless allow_nearest_future is set.

    - allow_nearest_future False: keep rows where date(start_time) == target_date
      (and target_date+1 when include_tomorrow).
    - allow_nearest_future True: skip date filter (full API board; game_date column set).
    Always stamps board_date / line_asof (fetch calendar) vs game_date (tip-day).
    """
    target_date = str(target_date or "").strip()[:10]
    bd = str(board_date or eastern_today_ymd()).strip()[:10]
    keep_dates = {d for d in (target_date,) if d}
    if include_tomorrow and target_date:
        nxt = add_calendar_days(target_date, 1)
        if nxt:
            keep_dates.add(nxt)

    if df is None or len(df) == 0:
        out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        if isinstance(out, pd.DataFrame) and "game_date" not in out.columns:
            out["game_date"] = ""
        return stamp_board_asof(out, bd), None

    tz = ZoneInfo(str(tz_name or "America/New_York"))
    col = start_time_col if start_time_col in df.columns else "start_time"
    if col not in df.columns:
        out = df.copy()
        out["game_date"] = ""
        out = stamp_board_asof(out, bd)
        if allow_nearest_future:
            return out, None
        return out.head(0).copy(), None

    ts = pd.to_datetime(df[col], errors="coerce", utc=True)
    out = df.copy()
    out["game_date"] = ts.dt.tz_convert(tz).dt.date.astype("string").fillna("")
    out = stamp_board_asof(out, bd)

    if allow_nearest_future:
        return out, None

    kept = out.loc[out["game_date"].isin(keep_dates)].copy()
    return kept, None
