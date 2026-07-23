#!/usr/bin/env python3
"""PrizePicks league IDs for the WNBA board family.

Verified 2026-07-22 via CDP attach to app.prizepicks.com + GET /leagues
(Sports/WNBA/step1_fetch_prizepicks.py --print-leagues --cdp ...).

Full-game WNBA remains league_id=3. Period boards are separate tabs/ids.
"""

from __future__ import annotations

# Full game
WNBA = "3"

# Period boards (MVP focus: 1H + 1Q)
WNBA1H = "193"
WNBA1Q = "308"

# Also present on /leagues (not wired in MVP refresh yet)
WNBA2H = "194"
WNBA4Q = "195"

# Sport tag -> league_id for period refresh / step1
PERIOD_LEAGUE_IDS: dict[str, str] = {
    "wnba1h": WNBA1H,
    "wnba1q": WNBA1Q,
    # Ready when needed:
    "wnba2h": WNBA2H,
    "wnba4q": WNBA4Q,
}

SPORT_TAG_BY_LEAGUE_ID: dict[str, str] = {
    WNBA: "WNBA",
    WNBA1H: "WNBA1H",
    WNBA1Q: "WNBA1Q",
    WNBA2H: "WNBA2H",
    WNBA4Q: "WNBA4Q",
}
