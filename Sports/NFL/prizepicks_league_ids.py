"""PrizePicks NFL board family.

Verified 2026-08-15 via partner-api.prizepicks.com/leagues
(projections_count at check: NFL=236, NFLP=49, NFLSZN=1345).
"""

from __future__ import annotations

# Single-game (regular + in-season)
NFL = "9"

# Preseason game board (live in August)
NFLP = "44"

# Season-long regular-season totals (NFLSZN tab)
NFLSZN = "163"

# Period boards (empty until regular season kickoff)
NFL1H = "35"
NFL2H = "25"
NFL1Q = "245"
NFL4Q = "152"

# Default step1 fetch: games + preseason games + latest season-long board
DEFAULT_NFL_BOARDS: dict[str, str] = {
    NFL: "NFL",
    NFLP: "NFLP",
    NFLSZN: "NFLSZN",
}

PERIOD_BOARDS: dict[str, str] = {
    NFL1H: "NFL1H",
    NFL2H: "NFL2H",
    NFL1Q: "NFL1Q",
    NFL4Q: "NFL4Q",
}

SEASON_BOARD_IDS = frozenset({NFLSZN})
