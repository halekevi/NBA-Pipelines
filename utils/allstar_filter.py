"""Exclude All-Star / special-squad games and PrizePicks props from pipelines.

PrizePicks L5 windows are regular-season only. ESPN caches sometimes include
All-Star boxscores (e.g. WNBA Team Coop / Team Spoon), which inflate L5 Over
counts and averages vs the live board.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable, Mapping

import pandas as pd

# Explicit All-Star / Rising Stars / exhibition-squad abbreviations by sport.
# Keep franchise codes out of these sets.
ALLSTAR_TEAM_ABBREVS: dict[str, frozenset[str]] = {
    # Named All-Star squads rotate yearly (Team Coop/Spoon, Clark/Collier, …).
    "WNBA": frozenset({"COOP", "SPO", "CLA", "COL"}),
    "NBA": frozenset(
        {
            "STARS",
            "STRIPES",
            "WORLD",  # Rising Stars squads seen in ESPN cache
            "EST",
            "WST",  # classic East/West All-Star
            "LBN",
            "GIA",  # Team LeBron / Team Giannis
        }
    ),
    "MLB": frozenset({"AL", "NL"}),  # All-Star Game squads only
}

# Known ESPN All-Star Game event ids (belt-and-suspenders with team codes).
ALLSTAR_EVENT_IDS: dict[str, frozenset[str]] = {
    "WNBA": frozenset(
        {
            "401781604",  # 2025 Team Clark vs Team Collier
            "401857320",  # 2026 Team Coop vs Team Spoon
        }
    ),
    "NBA": frozenset(),
    "MLB": frozenset(),
}

# Full published All-Star Game rosters (normalized display names).
# Used to purge ASG rows even if a squad abbrev is missing/unknown.
WNBA_ALLSTAR_ROSTERS_BY_YEAR: dict[int, frozenset[str]] = {
    2025: frozenset(
        {
            "a'ja wilson",
            "aliyah boston",
            "allisha gray",
            "alyssa thomas",
            "angel reese",
            "breanna stewart",
            "brionna jones",
            "brittney sykes",
            "courtney williams",
            "gabby williams",
            "jackie young",
            "kayla mcbride",
            "kayla thornton",
            "kelsey mitchell",
            "kelsey plum",
            "kiki iriafen",
            "napheesa collier",
            "nneka ogwumike",
            "paige bueckers",
            "sabrina ionescu",
            "skylar diggins",
            "sonia citron",
        }
    ),
    2026: frozenset(
        {
            "a'ja wilson",
            "aliyah boston",
            "allisha gray",
            "angel reese",
            "breanna stewart",
            "caitlin clark",
            "courtney williams",
            "dominique malonga",
            "gabby williams",
            "jackie young",
            "jessica shepard",
            "jonquel jones",
            "kahleah copper",
            "kelsey mitchell",
            "kelsey plum",
            "kiki iriafen",
            "marina mabrey",
            "natasha howard",
            "nneka ogwumike",
            "olivia miles",
            "paige bueckers",
            "rhyne howard",
            "sonia citron",
        }
    ),
}

# Optional hard date windows (inclusive) for known All-Star game days.
# Prefer team/text/event detection; dates are a safety net for fetch skips.
ALLSTAR_DATE_WINDOWS: dict[str, tuple[tuple[str, str], ...]] = {
    "WNBA": (
        ("2025-07-19", "2025-07-20"),  # 2025 ASG (UTC/local boundary)
        ("2026-07-25", "2026-07-25"),  # 2026 ASG
    ),
    "NBA": (),
    "MLB": (),
}

_TEAM_COLUMNS: tuple[str, ...] = (
    "TEAM",
    "team",
    "team_abbr",
    "TEAM_ABBREVIATION",
    "pp_home_team",
    "pp_away_team",
    "home_team",
    "away_team",
    "opp_team",
    "team_1",
    "team_2",
)

_TEXT_COLUMNS: tuple[str, ...] = (
    "prop_type",
    "prop",
    "prop_name",
    "prop_type_norm",
    "Prop",
    "Prop Type",
    "stat_type",
    "prop_norm",
    "description",
    "game_note",
    "gameNote",
    "notes",
    "event_name",
    "name",
)


def _canon_sport(sport: object) -> str:
    s = str(sport or "").strip().upper()
    if s.startswith("WNBA"):
        return "WNBA"
    if s.startswith("NBA"):
        return "NBA"
    if s in {"MLB", "BASEBALL"}:
        return "MLB"
    return s


def _norm_team(abbr: object) -> str:
    return str(abbr or "").strip().upper()


def _norm_text(text: object) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"[\s_\-]+", " ", s)
    return s


def is_allstar_text(text: object) -> bool:
    """True when a label/note clearly marks an All-Star product."""
    s = _norm_text(text)
    if not s:
        return False
    compact = s.replace(" ", "")
    if "allstar" in compact:
        return True
    if re.search(r"\ball[\s\-]?star\b", s):
        return True
    return False


def allstar_teams_for_sport(sport: object) -> frozenset[str]:
    return ALLSTAR_TEAM_ABBREVS.get(_canon_sport(sport), frozenset())


def is_allstar_team(abbr: object, sport: object = "WNBA") -> bool:
    a = _norm_team(abbr)
    if not a:
        return False
    return a in allstar_teams_for_sport(sport)


def is_allstar_date(day: object, sport: object = "WNBA") -> bool:
    """True when ``day`` falls in a configured All-Star date window."""
    sport_u = _canon_sport(sport)
    windows = ALLSTAR_DATE_WINDOWS.get(sport_u) or ()
    if not windows:
        return False
    if isinstance(day, datetime):
        d = day.date()
    elif isinstance(day, date):
        d = day
    else:
        raw = str(day or "").strip()[:10]
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return False
    for start_s, end_s in windows:
        try:
            start = datetime.strptime(start_s, "%Y-%m-%d").date()
            end = datetime.strptime(end_s, "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d <= end:
            return True
    return False


def _norm_player(name: object) -> str:
    s = _norm_text(name)
    s = s.replace(".", "")
    return s


def is_wnba_allstar_roster_player(name: object, year: int) -> bool:
    roster = WNBA_ALLSTAR_ROSTERS_BY_YEAR.get(int(year), frozenset())
    return _norm_player(name) in roster


def allstar_event_ids_for_sport(sport: object) -> frozenset[str]:
    return ALLSTAR_EVENT_IDS.get(_canon_sport(sport), frozenset())


def is_allstar_event_id(event_id: object, sport: object = "WNBA") -> bool:
    eid = str(event_id or "").strip()
    if not eid:
        return False
    return eid in allstar_event_ids_for_sport(sport)


def is_espn_summary_allstar(summary: Mapping | None, sport: object = "WNBA") -> bool:
    """Detect All-Star from an ESPN site summary payload."""
    summary = summary or {}
    header = summary.get("header") or {}
    if is_allstar_text(header.get("gameNote")):
        return True
    if is_allstar_text(header.get("name")):
        return True
    sport_u = _canon_sport(sport)
    for comp in header.get("competitions") or []:
        if not isinstance(comp, dict):
            continue
        ctype = comp.get("type") or {}
        if isinstance(ctype, dict):
            if str(ctype.get("abbreviation") or "").strip().upper() == "ALLSTAR":
                return True
            if is_allstar_text(ctype.get("name") or ctype.get("abbreviation")):
                return True
        for note in comp.get("notes") or []:
            if isinstance(note, dict) and is_allstar_text(note.get("headline") or note.get("text")):
                return True
            if is_allstar_text(note):
                return True
        for c in comp.get("competitors") or []:
            if not isinstance(c, dict):
                continue
            team = c.get("team") or {}
            if is_allstar_team(team.get("abbreviation"), sport_u):
                return True
            loc = _norm_text(team.get("location") or team.get("displayName") or "")
            # Named draft squads are "Team Coop", "Team Clark", etc.
            if loc.startswith("team "):
                return True
    return False


def allstar_game_row_mask(df: pd.DataFrame, sport: object = "WNBA") -> pd.Series:
    """True for boxscore/cache rows that belong to an All-Star game."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    sport_u = _canon_sport(sport)
    mask = pd.Series(False, index=df.index)
    teams = allstar_teams_for_sport(sport_u)
    if teams:
        for col in _TEAM_COLUMNS:
            if col in df.columns:
                mask |= df[col].map(lambda x: _norm_team(x) in teams)

    for col in ("event_id", "EVENT_ID", "game_id"):
        if col in df.columns:
            mask |= df[col].map(lambda x: is_allstar_event_id(x, sport_u))
            break

    date_col = next((c for c in ("game_date", "GAME_DATE", "date") if c in df.columns), None)
    if date_col:
        mask |= df[date_col].map(lambda x: is_allstar_date(x, sport_u))

    # Roster × ASG-date: catch every All-Star player even if squad code drifts.
    if sport_u == "WNBA" and date_col:
        name_col = next(
            (
                c
                for c in ("PLAYER_NAME", "player", "PLAYER", "athlete", "name")
                if c in df.columns
            ),
            None,
        )
        if name_col:

            def _roster_hit(row: pd.Series) -> bool:
                raw = str(row.get(date_col) or "")[:10]
                try:
                    year = int(raw[:4])
                except ValueError:
                    return False
                if not is_allstar_date(raw, "WNBA"):
                    return False
                return is_wnba_allstar_roster_player(row.get(name_col), year)

            mask |= df.apply(_roster_hit, axis=1)

    for col in _TEXT_COLUMNS:
        if col in df.columns:
            mask |= df[col].map(is_allstar_text)
    return mask


def drop_allstar_game_rows(
    df: pd.DataFrame, sport: object = "WNBA"
) -> tuple[pd.DataFrame, int]:
    """Return (filtered_df, dropped_count) for boxscore/cache frames."""
    if df is None or df.empty:
        return df, 0
    mask = allstar_game_row_mask(df, sport=sport)
    dropped = int(mask.sum())
    if dropped == 0:
        return df, 0
    return df.loc[~mask].copy(), dropped


def allstar_prop_row_mask(df: pd.DataFrame, sport: object = "WNBA") -> pd.Series:
    """True for PrizePicks slate rows that are All-Star props/games."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    sport_u = _canon_sport(sport)
    mask = pd.Series(False, index=df.index)
    teams = allstar_teams_for_sport(sport_u)
    if teams:
        for col in _TEAM_COLUMNS:
            if col in df.columns:
                mask |= df[col].map(lambda x: _norm_team(x) in teams)
    for col in _TEXT_COLUMNS:
        if col in df.columns:
            mask |= df[col].map(is_allstar_text)
    for col in ("game_date", "GAME_DATE", "date", "start_time"):
        if col in df.columns:
            mask |= df[col].map(lambda x: is_allstar_date(str(x)[:10], sport_u))
            break
    return mask


def drop_allstar_props(
    df: pd.DataFrame, sport: object = "WNBA"
) -> tuple[pd.DataFrame, int]:
    """Return (filtered_df, dropped_count) for PrizePicks slate frames."""
    if df is None or df.empty:
        return df, 0
    mask = allstar_prop_row_mask(df, sport=sport)
    dropped = int(mask.sum())
    if dropped == 0:
        return df, 0
    return df.loc[~mask].copy(), dropped


def drop_allstar_rows(
    rows: Iterable[dict], sport: object = "WNBA"
) -> tuple[list[dict], int]:
    """Filter list-of-dict step rows (NHL step2 style)."""
    sport_u = _canon_sport(sport)
    teams = allstar_teams_for_sport(sport_u)
    kept: list[dict] = []
    dropped = 0
    for row in rows:
        hit = False
        for key in _TEAM_COLUMNS:
            if key in row and _norm_team(row.get(key)) in teams:
                hit = True
                break
        if not hit:
            for key in ("prop_type", "prop", "prop_name", "stat_type", "description"):
                if key in row and is_allstar_text(row.get(key)):
                    hit = True
                    break
        if hit:
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped
