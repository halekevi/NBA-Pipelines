"""CFB ESPN team-stat parse + national ranks."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "Sports" / "CFB" / "scripts"))

from build_cfb_unit_rankings import add_conference_ranks, add_national_ranks, parse_team_unit_stats  # noqa: E402


def _block(name: str, **stats) -> dict:
    return {"name": name, "stats": [{"name": k, "value": v} for k, v in stats.items()]}


def test_parse_team_unit_stats_rates_and_allowed():
    payload = {
        "results": {
            "requestedSeason": {"year": 2025},
            "stats": {
                "categories": [
                    _block(
                        "passing",
                        netPassingYardsPerGame=250.0,
                        passingTouchdowns=24.0,
                        interceptions=12.0,
                        sacks=36.0,
                        passingAttempts=400.0,
                        teamGamesPlayed=12.0,
                    ),
                    _block(
                        "rushing",
                        rushingYardsPerGame=150.0,
                        rushingTouchdowns=18.0,
                        rushingAttempts=400.0,
                        totalOffensivePlays=800.0,
                    ),
                    _block("receiving", receivingYardsPerGame=250.0, receivingTouchdowns=20.0),
                    _block(
                        "kicking",
                        fieldGoalsMade=18.0,
                        extraPointsMade=36.0,
                        totalKickingPoints=90.0,
                    ),
                    _block("scoring", totalPointsPerGame=28.0, totalTouchdowns=42.0),
                    _block("defensive", sacks=30.0, totalTackles=720.0, tacklesForLoss=72.0),
                    _block("defensiveInterceptions", interceptions=15.0),
                    _block("general", gamesPlayed=12.0),
                    _block("miscellaneous", possessionTimeSeconds=18000.0),
                ]
            },
            "opponent": [
                _block(
                    "passing",
                    netPassingYardsPerGame=180.0,
                    passingTouchdowns=12.0,
                ),
                _block("rushing", rushingYardsPerGame=100.0, rushingTouchdowns=8.0),
                _block("receiving", receivingTouchdowns=10.0),
                _block(
                    "scoring",
                    totalPointsPerGame=18.0,
                    totalTouchdowns=20.0,
                    fieldGoals=12.0,
                    kickExtraPoints=20.0,
                ),
            ],
        }
    }
    row = parse_team_unit_stats(payload)
    assert row["season"] == 2025
    assert row["games"] == 12.0
    assert row["off_pass_ypg"] == 250.0
    assert row["off_pass_td_pg"] == 2.0
    assert row["off_int_pg"] == 1.0
    assert row["off_pass_att_pg"] == 400.0 / 12.0
    assert row["off_rush_att_pg"] == 400.0 / 12.0
    assert abs(float(row["off_rush_rate"]) - 0.5) < 1e-9
    assert row["off_top_sec_pg"] == 1500.0
    assert row["off_fg_pg"] == 1.5
    assert row["off_pat_pg"] == 3.0
    assert row["def_pass_ypg_allowed"] == 180.0
    assert row["def_pass_td_pg_allowed"] == 1.0
    assert row["def_fg_pg_allowed"] == 1.0
    assert row["def_pat_pg_allowed"] == 20.0 / 12.0
    assert row["def_kick_pts_pg_allowed"] == (3 * 12 + 20) / 12.0
    assert row["def_int_forced_pg"] == 15.0 / 12.0
    assert row["def_sacks_pg"] == 2.5
    assert row["def_tackles_pg"] == 60.0
    assert row["def_tfl_pg"] == 6.0


def test_add_conference_ranks_within_league():
    df = pd.DataFrame(
        {
            "conference_id": ["1", "1", "2", "2"],
            "conference_name": ["Big Ten", "Big Ten", "SEC", "SEC"],
            "off_pass_ypg": [300.0, 100.0, 250.0, 200.0],
            "def_pass_ypg_allowed": [100.0, 300.0, 150.0, 250.0],
        }
    )
    out = add_conference_ranks(df)
    assert int(out.loc[0, "conference_size"]) == 2
    assert int(out.loc[0, "off_pass_rank_conf"]) == 1
    assert int(out.loc[1, "off_pass_rank_conf"]) == 2
    assert int(out.loc[2, "off_pass_rank_conf"]) == 1
    assert int(out.loc[3, "off_pass_rank_conf"]) == 2
    assert int(out.loc[0, "def_pass_rank_conf"]) == 1
    assert int(out.loc[1, "def_pass_rank_conf"]) == 2
    df = pd.DataFrame(
        {
            "off_pass_ypg": [300.0, 100.0],
            "def_pass_ypg_allowed": [100.0, 300.0],
            "def_sacks_pg": [4.0, 1.0],
            "off_int_pg": [0.5, 2.0],
        }
    )
    out = add_national_ranks(df)
    assert int(out.loc[0, "off_pass_rank"]) == 1
    assert int(out.loc[1, "off_pass_rank"]) == 2
    assert int(out.loc[0, "def_pass_rank"]) == 1
    assert int(out.loc[1, "def_pass_rank"]) == 2
    assert int(out.loc[0, "def_sacks_rank"]) == 1
    assert int(out.loc[1, "def_sacks_rank"]) == 2
    assert int(out.loc[0, "off_int_rank"]) == 1
    assert int(out.loc[1, "off_int_rank"]) == 2
