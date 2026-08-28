"""ESPN boxscore cache: SQLite first, CSV is backfill only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from scripts.espn_boxscore_cache import (
    load_boxscore_cache,
    save_boxscore_cache,
    sport_key_from_espn_league,
    upsert_rows,
)


def _patch_open_db(monkeypatch, con: sqlite3.Connection) -> None:
    monkeypatch.setattr("scripts.espn_boxscore_cache.open_db", lambda db_path=None: con)


def test_sport_key_from_espn_league():
    assert sport_key_from_espn_league("nfl") == "nfl"
    assert sport_key_from_espn_league("college-football") == "cfb"
    assert sport_key_from_espn_league("mens-college-basketball") == "cbb"
    assert sport_key_from_espn_league("womens-college-basketball") == "wcbb"


def test_load_skips_csv_when_db_has_rows(tmp_path: Path, monkeypatch):
    con = sqlite3.connect(":memory:")
    _patch_open_db(monkeypatch, con)
    upsert_rows(
        con,
        "cfb",
        [
            {"event_id": "1", "espn_athlete_id": "a", "game_date": "2026-08-01", "PASS_YDS": 200},
            {"event_id": "2", "espn_athlete_id": "b", "game_date": "2026-08-02", "PASS_YDS": 100},
        ],
    )
    csv = tmp_path / "cfb_boxscore_cache.csv"
    pd.DataFrame(
        [{"event_id": "csv-only", "espn_athlete_id": "x", "PASS_YDS": 1}]
    ).to_csv(csv, index=False)

    rows, source = load_boxscore_cache("cfb", str(csv), min_db_rows=1)
    assert source == "db"
    assert len(rows) == 2
    assert {r["event_id"] for r in rows} == {"1", "2"}


def test_save_db_source_does_not_rewrite_csv(tmp_path: Path, monkeypatch):
    con = sqlite3.connect(":memory:")
    _patch_open_db(monkeypatch, con)
    csv = tmp_path / "cbb_boxscore_cache.csv"
    csv.write_text("event_id,espn_athlete_id\nkeep-me,1\n", encoding="utf-8")

    save_boxscore_cache(
        "cbb",
        [{"event_id": "9", "espn_athlete_id": "z", "PTS": 10, "game_date": "2026-01-01"}],
        str(csv),
        "db",
    )
    assert "keep-me" in csv.read_text(encoding="utf-8")
    rows, source = load_boxscore_cache("cbb", str(csv), min_db_rows=1)
    assert source == "db"
    assert len(rows) == 1
    assert rows[0]["event_id"] == "9"


def test_csv_backfill_when_db_empty(tmp_path: Path, monkeypatch):
    con = sqlite3.connect(":memory:")
    _patch_open_db(monkeypatch, con)
    csv = tmp_path / "nfl_boxscore_cache.csv"
    pd.DataFrame(
        [{"event_id": "e1", "espn_athlete_id": "p1", "game_date": "2026-08-20", "RUSH_YDS": 55}]
    ).to_csv(csv, index=False)

    rows, source = load_boxscore_cache("nfl", str(csv), min_db_rows=200)
    assert source == "csv"
    assert len(rows) == 1
    assert rows[0]["event_id"] == "e1"
    rows2, source2 = load_boxscore_cache("nfl", str(csv), min_db_rows=1)
    assert source2 == "db"
    assert len(rows2) == 1
