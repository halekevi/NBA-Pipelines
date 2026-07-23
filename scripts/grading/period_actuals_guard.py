"""
Guardrails so period props (NBA1H/1Q, WNBA1H/1Q) never grade against full-game actuals.

Period CSVs come from fetch_nba_period_actuals.py (--segment 1H|1Q; --sport WNBA for WNBA).
Expected filenames:
  actuals_nba1h_YYYY-MM-DD.csv
  actuals_nba1q_YYYY-MM-DD.csv
  actuals_wnba1h_YYYY-MM-DD.csv
  actuals_wnba1q_YYYY-MM-DD.csv
"""

from __future__ import annotations

import re
from pathlib import Path

# Sport label -> canonical token used in filenames (actuals_<token>_DATE.csv).
PERIOD_SPORT_MARKERS: dict[str, str] = {
    "NBA1H": "nba1h",
    "NBA1Q": "nba1q",
    "WNBA1H": "wnba1h",
    "WNBA1Q": "wnba1q",
}

# Check longer WNBA tokens before NBA — "wnba1h" contains the substring "nba1h".
_PERIOD_DETECT_ORDER: tuple[tuple[str, str], ...] = (
    ("WNBA1H", "wnba1h"),
    ("WNBA1Q", "wnba1q"),
    ("NBA1H", "nba1h"),
    ("NBA1Q", "nba1q"),
)


def _path_blob(*paths: str | Path | None) -> str:
    return " ".join(str(p or "").replace("\\", "/").lower() for p in paths)


def _has_token(blob: str, token: str) -> bool:
    """True when *token* appears as an actuals_/graded_/path segment, not a substring of wnba*."""
    t = token.lower()
    patterns = (
        f"actuals_{t}_",
        f"actuals_{t}.",
        f"graded_{t}_",
        f"/{t}/",
        f"_{t}_",
        f"_{t}.",
    )
    return any(p in blob for p in patterns)


def period_sport_from_path(*paths: str | Path | None) -> str | None:
    """Infer NBA1H/NBA1Q/WNBA1H/WNBA1Q from slate/actuals/output path names."""
    blob = _path_blob(*paths)
    for sport, marker in _PERIOD_DETECT_ORDER:
        if _has_token(blob, marker):
            return sport
    return None


def assert_period_actuals_path(sport: str, actuals_path: str | Path) -> Path:
    """
    Hard-fail if *actuals_path* is missing the period marker or looks like full-game actuals.

    Raises RuntimeError on mismatch. Returns the resolved Path on success.
    """
    sport_u = (sport or "").strip().upper()
    if sport_u not in PERIOD_SPORT_MARKERS:
        raise ValueError(f"assert_period_actuals_path: not a period sport: {sport!r}")

    path = Path(str(actuals_path))
    name = path.name
    name_l = name.lower()
    marker = PERIOD_SPORT_MARKERS[sport_u]

    if not _has_token(name_l, marker):
        seg = "1H" if sport_u.endswith("1H") else "1Q"
        wnba_flag = " --sport WNBA" if sport_u.startswith("WNBA") else ""
        raise RuntimeError(
            f"{sport_u} grading requires period actuals "
            f"(filename must look like actuals_{marker}_YYYY-MM-DD.csv). "
            f"Got: {name}. Fetch with: "
            f"py -3 scripts/fetch_nba_period_actuals.py{wnba_flag} "
            f"--date YYYY-MM-DD --segment {seg} "
            f"--output outputs/YYYY-MM-DD/actuals_{marker}_YYYY-MM-DD.csv"
        )

    # Bare full-game stems (never valid for period sports).
    if sport_u.startswith("WNBA") and re.fullmatch(
        r"actuals_wnba_\d{4}-\d{2}-\d{2}\.csv", name_l
    ):
        raise RuntimeError(
            f"{sport_u} must not use full-game WNBA actuals. Refusing: {name}"
        )
    if sport_u.startswith("NBA") and not sport_u.startswith("WNBA") and re.fullmatch(
        r"actuals_nba_\d{4}-\d{2}-\d{2}\.csv", name_l
    ):
        raise RuntimeError(
            f"{sport_u} must not use full-game NBA actuals. Refusing: {name}"
        )

    return path


def assert_actuals_for_inferred_period(
    actuals_path: str | Path,
    *hint_paths: str | Path | None,
) -> str | None:
    """
    If slate/output/actuals hints a period sport, validate *actuals_path* for that sport.

    Returns the inferred period sport (or None when not a period grade).
    """
    sport = period_sport_from_path(actuals_path, *hint_paths)
    if not sport:
        return None
    assert_period_actuals_path(sport, actuals_path)
    return sport
