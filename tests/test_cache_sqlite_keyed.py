"""Keyed SQLite cache loads skip full ESPN CSV dumps."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_MLB_SCRIPTS = _ROOT / "Sports" / "MLB" / "scripts"
if str(_MLB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MLB_SCRIPTS))

from scripts.db_utils import ensure_mlb_schema, ensure_wnba_schema, upsert_rows

_WNBA_STEP4 = _ROOT / "Sports" / "WNBA" / "step4_fetch_player_stats.py"
_spec = importlib.util.spec_from_file_location("wnba_step4_cache", _WNBA_STEP4)
assert _spec and _spec.loader
_wnba = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wnba)

_MLB_STEP4 = _MLB_SCRIPTS / "step4_attach_player_stats_mlb.py"
_mspec = importlib.util.spec_from_file_location("mlb_step4_cache", _MLB_STEP4)
assert _mspec and _mspec.loader
_mlb = importlib.util.module_from_spec(_mspec)
_mspec.loader.exec_module(_mlb)

_STEP3 = _ROOT / "Sports" / "WNBA" / "step3_attach_defense.py"
_s3 = importlib.util.spec_from_file_location("wnba_step3_defense", _STEP3)
assert _s3 and _s3.loader
_wnba_step3 = importlib.util.module_from_spec(_s3)
_s3.loader.exec_module(_wnba_step3)
_wnba_boxscore_days = _wnba_step3._wnba_boxscore_days


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA journal_mode=WAL;")
    return con


def test_wnba_load_skips_csv_when_db_has_rows(tmp_path: Path):
    con = _mem_con()
    ensure_wnba_schema(con)
    upsert_rows(
        con,
        "wnba",
        [
            {
                "game_date": "2026-08-01",
                "event_id": "e1",
                "league": "WNBA",
                "player": "A'ja Wilson",
                "team": "LV",
                "espn_athlete_id": "1",
                "minutes": 32.0,
                "pts": 22.0,
                "season": "2026",
            },
            {
                "game_date": "2025-06-01",
                "event_id": "old",
                "league": "WNBA",
                "player": "Old Row",
                "team": "NY",
                "espn_athlete_id": "9",
                "minutes": 10.0,
                "pts": 2.0,
                "season": "2025",
            },
        ],
    )
    csv = tmp_path / "wnba_espn_cache.csv"
    pd.DataFrame({"PLAYER_NAME": ["CSV SHOULD NOT LOAD"], "event_id": ["x"]}).to_csv(csv, index=False)
    df = _wnba.load_wnba_cache(csv, con, since_date="2026-01-01", min_db_rows=1)
    assert list(df["PLAYER_NAME"]) == ["A'ja Wilson"]
    assert _wnba._WNBA_CACHE_SOURCE == "db"


def test_mlb_load_keyed_player_ids(tmp_path: Path):
    con = _mem_con()
    ensure_mlb_schema(con)
    ts = "2026-08-01T00:00:00Z"
    upsert_rows(
        con,
        "mlb_gamelog",
        [
            {
                "mlb_player_id": "111",
                "season": "2026",
                "game_date": "2026-08-01",
                "game_id": "g1",
                "player_type": "hitter",
                "prop_norm": "hits",
                "stat_value": 2.0,
                "team_id": "119",
                "opp_team_id": "147",
                "updated_at": ts,
            },
            {
                "mlb_player_id": "222",
                "season": "2026",
                "game_date": "2026-08-01",
                "game_id": "g2",
                "player_type": "hitter",
                "prop_norm": "hits",
                "stat_value": 1.0,
                "team_id": "147",
                "opp_team_id": "119",
                "updated_at": ts,
            },
        ],
    )
    csv = tmp_path / "mlb_stats_cache.csv"
    pd.DataFrame({"MLB_PLAYER_ID": ["999"], "PROP_NORM": ["hits"]}).to_csv(csv, index=False)
    df = _mlb.load_cache(csv, con, player_ids=["111"], seasons=["2026"], min_db_rows=1)
    assert set(df["MLB_PLAYER_ID"]) == {"111"}
    assert _mlb._MLB_CACHE_SOURCE == "db"


def test_wnba_boxscore_days_uses_sqlite(tmp_path: Path, monkeypatch):
    con = _mem_con()
    ensure_wnba_schema(con)
    upsert_rows(
        con,
        "wnba",
        [
            {
                "game_date": "2026-08-20",
                "event_id": "e9",
                "league": "WNBA",
                "player": "P",
                "team": "SEA",
                "espn_athlete_id": "1",
                "minutes": 20.0,
                "pts": 10.0,
                "season": "2026",
            },
            {
                "game_date": "2026-08-20",
                "event_id": "e9",
                "league": "WNBA",
                "player": "Q",
                "team": "MIN",
                "espn_athlete_id": "2",
                "minutes": 20.0,
                "pts": 8.0,
                "season": "2026",
            },
        ],
    )
    monkeypatch.setattr("scripts.db_utils.open_db", lambda path=None: con)
    out = _wnba_boxscore_days({"2026-08-20"}, tmp_path / "missing.csv")
    assert out is not None
    assert set(out["TEAM"]) == {"SEA", "MIN"}
