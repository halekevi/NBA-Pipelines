"""Sofascore match-log mapping for Popular soccer markets ESPN does not fill."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Sports" / "Soccer" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts"))

from soccer_sofascore_matchlog import (  # noqa: E402
    extract_matchlog_stats,
    fill_omitted_zero_counts,
    needs_matchlog,
    pick_search_hit,
    select_recent_finished_events,
    _stale_espn_targets,
    _upsert_rows,
)
from step4_db_reader import attach_stats, get_vals_soccer  # noqa: E402


HENDRY_STATS = {
    "totalPass": 58,
    "totalClearance": 1,
    "totalTackle": 2,
    "minutesPlayed": 90,
    "totalShots": 0,
    "dribbleValueNormalized": 0.12,
}

ANTONY_STATS = {
    "totalPass": 33,
    "totalContest": 5,
    "wonContest": 2,
    "dribbleValueNormalized": 0.4,
    "minutesPlayed": 78,
}


def test_needs_matchlog_norms():
    assert needs_matchlog("passes")
    assert needs_matchlog("passes attempted")
    assert needs_matchlog("", "Attempted Dribbles")
    assert needs_matchlog("clearances")
    assert needs_matchlog("tackles")
    assert needs_matchlog("shots")
    assert needs_matchlog("shots on target")
    assert needs_matchlog("goals")
    assert not needs_matchlog("fantasy_score")
    assert needs_matchlog("saves")
    assert needs_matchlog("crosses")
    assert needs_matchlog("shots_assisted")


def test_gap_matchlog_excludes_espn_counting_stats():
    from soccer_sofascore_matchlog import needs_gap_matchlog

    assert needs_gap_matchlog("passes")
    assert needs_gap_matchlog("", "Tackles")
    assert needs_gap_matchlog("crosses")
    assert needs_gap_matchlog("shots_assisted")
    assert not needs_gap_matchlog("shots")
    assert not needs_gap_matchlog("goals")
    assert not needs_gap_matchlog("saves")


def test_extract_missing_dribble_key_is_none_not_zero():
    got = extract_matchlog_stats(HENDRY_STATS)
    assert got["pa"] == 58
    assert got["clearances"] == 1
    assert got["tk"] == 2
    assert got["dribble_attempts"] is None
    assert got["sh"] == 0
    assert "totalShots" not in got


def test_unique_targets_gap_only_skips_shots_only_players():
    from soccer_sofascore_matchlog import _unique_targets

    df = pd.DataFrame(
        [
            {"player": "A", "team": "X", "prop_norm": "shots", "prop_type": "Shots", "espn_player_id": "1", "start_time": "2026-09-01T15:00:00-04:00"},
            {"player": "B", "team": "Y", "prop_norm": "passes", "prop_type": "Passes Attempted", "espn_player_id": "2", "start_time": "2026-09-01T15:00:00-04:00", "pick_type": "Standard"},
            {"player": "B", "team": "Y", "prop_norm": "shots", "prop_type": "Shots", "espn_player_id": "2", "start_time": "2026-09-01T15:00:00-04:00", "pick_type": "Standard"},
            {"player": "C", "team": "Z", "prop_norm": "tackles", "prop_type": "Tackles", "espn_player_id": "3", "start_time": "2026-09-01T15:00:00-04:00", "pick_type": "Demon"},
        ]
    )
    gap = _unique_targets(df, gap_only=True)
    assert [t["player"] for t in gap] == ["B"]
    allp = _unique_targets(df, gap_only=False)
    assert sorted(t["player"] for t in allp) == ["A", "B", "C"]


def test_extract_crosses_and_key_passes():
    got = extract_matchlog_stats({
        "totalPass": 40,
        "totalCross": 7,
        "keyPass": 3,
    })
    assert got["crosses"] == 7
    assert got["kp"] == 3


def test_extract_total_contest_as_attempted_dribbles():
    got = extract_matchlog_stats(ANTONY_STATS)
    assert got["pa"] == 33
    assert got["dribble_attempts"] == 5
    assert got["clearances"] is None


def test_extract_explicit_dribble_attempts_wins():
    st = dict(ANTONY_STATS)
    st["dribbleAttempts"] = 4
    got = extract_matchlog_stats(st)
    assert got["dribble_attempts"] == 4


def test_extract_zero_is_kept_when_key_present():
    got = extract_matchlog_stats({"totalPass": 0, "totalClearance": 0, "dribbleAttempts": 0})
    assert got["pa"] == 0
    assert got["clearances"] == 0
    assert got["dribble_attempts"] == 0


def test_extract_empty_is_all_none():
    got = extract_matchlog_stats({})
    assert got["pa"] is None
    assert got["clearances"] is None
    assert got["dribble_attempts"] is None
    assert got["tk"] is None
    assert got["sh"] is None
    assert got["sog"] is None
    assert got["g"] is None


def test_omitted_tackle_is_zero_when_player_appeared():
    raw = extract_matchlog_stats({"totalPass": 24})
    assert raw["tk"] is None
    filled = fill_omitted_zero_counts(raw)
    assert filled["pa"] == 24
    assert filled["tk"] == 0.0
    assert filled["clearances"] == 0.0
    assert filled["sh"] == 0.0
    assert filled["dribble_attempts"] is None


def test_omitted_tackle_stays_none_without_appearance():
    filled = fill_omitted_zero_counts(extract_matchlog_stats({}))
    assert filled["tk"] is None
    assert filled["pa"] is None


def test_select_recent_finished_events_newest_before_slate():
    events = [
        {"id": 1, "startTimestamp": 1700000000, "status": {"type": "finished"}},  # old
        {"id": 2, "startTimestamp": 1755900000, "status": {"type": "finished"}},  # 2025-08-22-ish
        {"id": 3, "startTimestamp": 1756166400, "status": {"type": "notstarted"}},
        {"id": 4, "startTimestamp": 1755993600, "status": {"type": "finished"}},
    ]
    # 1755900000 = 2025-08-22 20:40 UTC; 1755993600 = 2025-08-24; 1756166400 = 2025-08-26
    got = select_recent_finished_events(events, n_games=5, before_date="2025-08-25")
    assert [e["id"] for e in got] == [4, 2, 1]


def test_select_recent_skips_slate_day_and_caps():
    events = [
        {"id": i, "startTimestamp": 1700000000 + i * 86400, "status": {"type": "finished"}}
        for i in range(10)
    ]
    got = select_recent_finished_events(events, n_games=3, before_date="2023-12-01")
    assert [e["id"] for e in got] == [9, 8, 7]


def test_pick_search_hit_prefers_team():
    results = [
        {
            "type": "player",
            "entity": {
                "id": 1,
                "name": "Antony",
                "team": {"name": "Manchester United"},
                "sport": {"slug": "football"},
            },
        },
        {
            "type": "player",
            "entity": {
                "id": 958380,
                "name": "Antony",
                "team": {"name": "Real Betis"},
                "sport": {"slug": "football"},
            },
        },
    ]
    hit = pick_search_hit(results, "Antony", "BETIS")
    assert hit is not None
    assert hit["id"] == 958380


def test_sofa_upsert_fills_pa_leaves_shots_null():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    n = _upsert_rows(
        con,
        [
            {
                "game_date": "2026-08-22",
                "event_id": "sofa_15327739",
                "league": "Saudi Pro League",
                "home_team": "Al-Ettifaq",
                "away_team": "Al-Nassr",
                "player": "Jack Hendry",
                "team": "ETTIFAQ",
                "espn_player_id": "207454",
                "pa": 58,
                "tk": 2,
                "clearances": 1,
                "dribble_attempts": None,
            }
        ],
    )
    assert n == 1
    row = con.execute(
        "SELECT pa, clearances, dribble_attempts, sh, sog, g, minutes_played "
        "FROM soccer WHERE espn_player_id = '207454'"
    ).fetchone()
    assert row[0] == 58
    assert row[1] == 1
    assert row[2] is None
    assert row[3] is None
    assert row[4] is None
    assert row[5] is None
    assert row[6] is None
    vals = get_vals_soccer(con, "207454", "passes", n=5, player_name="Jack Hendry")
    assert vals == [58.0]


def test_extract_total_shots_and_sot():
    got = extract_matchlog_stats(
        {
            "totalShots": 4,
            "onTargetScoringAttempt": 2,
            "goals": 0,
            "goalAssist": 1,
            "totalPass": 21,
        }
    )
    assert got["sh"] == 4
    assert got["sog"] == 2
    assert got["g"] == 0
    assert got["a"] == 1
    assert got["pa"] == 21


def test_get_vals_soccer_dedupes_same_date_espn_over_sofa():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    con.execute(
        "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, sh) "
        "VALUES ('2026-08-21', '401877008', 'Brian', 'AME', '144325', 4)"
    )
    con.execute(
        "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, sh) "
        "VALUES ('2026-08-21', 'sofa_1', 'Brian', 'AME', '144325', 9)"
    )
    con.execute(
        "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, sh) "
        "VALUES ('2026-08-16', 'sofa_2', 'Brian', 'AME', '144325', 3)"
    )
    vals = get_vals_soccer(con, "144325", "shots", n=5, player_name="Brian")
    assert vals == [4.0, 3.0]


def test_get_vals_soccer_tackles_count_omitted_zeros():
    """PP Last 5 keeps 0-tackle appearances; do not skip to older non-zero games."""
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    rows = [
        ("2026-08-29", "sofa_1", 3.0, 38.0),
        ("2026-08-22", "sofa_2", 6.0, 20.0),
        ("2026-08-15", "sofa_3", None, 24.0),
        ("2026-08-08", "sofa_4", None, 26.0),
        ("2026-05-02", "sofa_5", 2.0, 19.0),
    ]
    for gd, eid, tk, pa in rows:
        con.execute(
            "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, tk, pa) "
            "VALUES (?, ?, 'Conor McGrandles', 'LINCOLN', '1', ?, ?)",
            (gd, eid, tk, pa),
        )
    con.execute(
        "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, sh, tk) "
        "VALUES ('2026-08-15', '401000', 'Conor McGrandles', 'LINCOLN', '1', 0, NULL)"
    )
    vals = get_vals_soccer(con, "1", "tackles", n=5, player_name="Conor McGrandles")
    assert vals == [3.0, 6.0, 0.0, 0.0, 2.0]


def test_get_vals_soccer_passes_count_omitted_zero():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    rows = [
        ("2026-08-29", 33.0, 0.0),
        ("2026-08-22", 34.0, 0.0),
        ("2026-05-02", 5.0, 0.0),
        ("2026-04-21", None, 0.0),
        ("2026-04-18", 34.0, 0.0),
    ]
    for i, (gd, pa, sh) in enumerate(rows, start=1):
        con.execute(
            "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, pa, sh) "
            "VALUES (?, ?, 'Marlon Pack', 'PORTSMOUTH', '2', ?, ?)",
            (gd, f"sofa_{i}", pa, sh),
        )
    vals = get_vals_soccer(con, "2", "passes", n=5, player_name="Marlon Pack")
    assert vals == [33.0, 34.0, 5.0, 0.0, 34.0]


def test_get_vals_soccer_team_skips_international_namesake():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    con.execute(
        "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, sh) "
        "VALUES ('2026-07-03', '760499', 'Mohamed Toure', 'AUS', '9', 2)"
    )
    vals = get_vals_soccer(
        con, "9", "shots", n=5, player_name="Mohamed Touré", team="NORWICH"
    )
    assert vals == []


def test_pick_search_hit_max_vs_maxime():
    results = [
        {
            "type": "player",
            "entity": {
                "id": 825543,
                "name": "Maxime Crocombe",
                "team": {"name": "Millwall"},
                "sport": {"slug": "football"},
            },
        }
    ]
    hit = pick_search_hit(results, "Max Crocombe", "MILLWALL")
    assert hit is not None
    assert hit["id"] == 825543


def test_espn_omitted_saves_count_as_zero_on_appearance():
    """Championship 0-save games on Sofascore omit sv; appearance still counts as 0."""
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    rows = [
        ("2026-08-29", "sofa_1", 2.0, None),
        ("2026-08-25", "sofa_2", 1.0, 0.0),
        ("2026-08-22", "sofa_3", None, 0.0),
        ("2026-08-15", "sofa_4", None, 0.0),
        ("2026-08-08", "sofa_5", None, 0.0),
    ]
    for gd, eid, sv, sh in rows:
        con.execute(
            "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, sv, sh) "
            "VALUES (?, ?, 'Max Crocombe', 'MIL', '168747', ?, ?)",
            (gd, eid, sv, sh),
        )
    vals = get_vals_soccer(
        con, "168747", "saves", n=5, player_name="Max Crocombe", team="MILLWALL"
    )
    assert vals == [2.0, 1.0, 0.0, 0.0, 0.0]


def test_stale_espn_targets_short_club_tape():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            player TEXT NOT NULL,
            team TEXT
        )
        """
    )
    con.execute(
        "INSERT INTO soccer VALUES ('2026-08-25', 'Max Crocombe', 'MIL')"
    )
    con.execute(
        "INSERT INTO soccer VALUES ('2026-06-21', 'Max Crocombe', 'NZL')"
    )
    slate = pd.DataFrame(
        [
            {
                "player": "Max Crocombe",
                "team": "MILLWALL",
                "prop_norm": "saves",
                "prop_type": "Goalie Saves",
                "pick_type": "Standard",
                "espn_player_id": "168747",
                "game_date": "2026-09-02",
            }
        ]
    )
    got = _stale_espn_targets(slate, con)
    assert [t["player"] for t in got] == ["Max Crocombe"]


def test_get_vals_soccer_espn_id_does_not_steal_other_player_tape():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    for i, sv in enumerate((3, 3, 3, 6, 3), start=1):
        con.execute(
            "INSERT INTO soccer (game_date, event_id, player, team, espn_player_id, sv) "
            "VALUES (?, ?, 'Sam Tickle', 'WIGAN', '999', ?)",
            (f"2026-08-{10+i:02d}", f"sofa_{i}", sv),
        )
    vals = get_vals_soccer(con, "999", "saves", n=5, player_name="Bradley Collins")
    assert vals == []
    vals = get_vals_soccer(con, "999", "saves", n=5, player_name="Sam Tickle")
    assert vals == [3.0, 6.0, 3.0, 3.0, 3.0]


def test_attach_stats_last5_over_from_sofa_rows():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    rows = []
    for i, pa in enumerate((58, 51, 47, 62, 55), start=1):
        rows.append(
            {
                "game_date": f"2026-08-{10 + i:02d}",
                "event_id": f"sofa_{1000 + i}",
                "player": "Jack Hendry",
                "team": "ETTIFAQ",
                "espn_player_id": "207454",
                "pa": pa,
                "tk": None,
                "clearances": 1,
                "dribble_attempts": None,
            }
        )
    _upsert_rows(con, rows)
    slate = pd.DataFrame(
        [
            {
                "player": "Jack Hendry",
                "team": "ETTIFAQ",
                "espn_player_id": "207454",
                "prop_norm": "passes",
                "line": "48.5",
            }
        ]
    )
    out, counts = attach_stats(slate, "soccer", con, id_col="espn_player_id", n=10)
    assert int(out.loc[0, "last5_over"]) >= 4
    assert counts["OK"] == 1


def test_attach_stats_name_fallback_when_espn_id_blank():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    _upsert_rows(
        con,
        [
            {
                "game_date": f"2026-08-{20 + i:02d}",
                "event_id": f"sofa_{i}",
                "player": "Jack Hendry",
                "team": "ETTIFAQ",
                "espn_player_id": None,
                "pa": 50 + i,
                "tk": None,
                "clearances": 5,
                "dribble_attempts": None,
            }
            for i in range(5)
        ],
    )
    slate = pd.DataFrame(
        [
            {
                "player": "Jack Hendry",
                "team": "ETTIFAQ",
                "espn_player_id": "",
                "prop_norm": "passes",
                "line": "48.5",
            }
        ]
    )
    out, counts = attach_stats(slate, "soccer", con, id_col="espn_player_id", n=10)
    assert counts["NO_ID"] == 0
    assert counts["OK"] == 1
    assert int(out.loc[0, "last5_over"]) == 5


def test_attach_stats_accented_name_without_espn_id():
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE soccer (
            game_date TEXT NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            player TEXT NOT NULL,
            team TEXT,
            espn_player_id TEXT,
            sh REAL, sog REAL, g REAL, a REAL,
            sv REAL, pa REAL, kp REAL, tk REAL,
            fc REAL, yc REAL, minutes_played REAL,
            clearances REAL, dribble_attempts REAL,
            PRIMARY KEY (event_id, player, team)
        )
        """
    )
    _upsert_rows(
        con,
        [
            {
                "game_date": f"2026-08-{18 + i:02d}",
                "event_id": f"sofa_m{i}",
                "player": "Álvaro Medrán",
                "team": "ETTIFAQ",
                "espn_player_id": None,
                "pa": 50 + i,
                "tk": None,
                "clearances": None,
                "dribble_attempts": None,
            }
            for i in range(5)
        ],
    )
    slate = pd.DataFrame(
        [
            {
                "player": "Álvaro Medrán",
                "team": "ETTIFAQ",
                "espn_player_id": "",
                "prop_norm": "passes",
                "line": "44.5",
            }
        ]
    )
    out, counts = attach_stats(slate, "soccer", con, id_col="espn_player_id", n=10)
    assert counts["OK"] == 1
    assert int(out.loc[0, "last5_over"]) == 5
