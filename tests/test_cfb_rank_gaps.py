"""CFB rankings aliases, extra FBS roster, opponent fill from scoreboard."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "Sports" / "CFB" / "scripts"))
sys.path.insert(0, str(_REPO / "Sports" / "CFB" / "scripts" / "pipeline"))

from build_cfb_unit_rankings import EXTRA_FBS_TEAMS, merge_team_lists, missing_extra_fbs  # noqa: E402
from step3_attach_unit_rankings import _load_lookup  # noqa: E402
from utils.cfb_opp_fill import expand_opp_map, fill_cfb_opp_from_map, parse_scoreboard_pairs  # noqa: E402
from utils.cfb_playoff_metadata import cfb_abbr_lookup_keys, norm_cfb_team_abbr  # noqa: E402


def test_scar_ccar_okla_aliases():
    assert norm_cfb_team_abbr("SCAR") == "SC"
    assert norm_cfb_team_abbr("CCAR") == "CCU"
    assert norm_cfb_team_abbr("OKLA") == "OU"
    assert "SCAR" in cfb_abbr_lookup_keys("SC")
    assert "CCAR" in cfb_abbr_lookup_keys("CCU")


def test_extra_sun_belt_not_in_small_cache():
    cached = [{"team_id": "356", "team_abbr": "ILL", "team_name": "Illinois"}]
    miss = missing_extra_fbs(cached)
    abbrs = {t["team_abbr"] for t in miss}
    assert "CCU" in abbrs
    assert "ULM" in abbrs
    merged = merge_team_lists(cached, miss)
    assert len(merged) == 1 + len(miss)


def test_lookup_hits_prizepicks_abbrs(tmp_path: Path):
    csv = tmp_path / "ranks.csv"
    pd.DataFrame(
        [
            {"team_id": "1", "team_abbr": "SC", "off_pass_rank": "10", "def_pass_rank": "20"},
            {"team_id": "2", "team_abbr": "CCU", "off_pass_rank": "80", "def_pass_rank": "90"},
            {"team_id": "3", "team_abbr": "OU", "off_pass_rank": "5", "def_pass_rank": "8"},
            {"team_id": "4", "team_abbr": "TA&M", "off_pass_rank": "15", "def_pass_rank": "12"},
        ]
    ).to_csv(csv, index=False)
    lookup, n = _load_lookup(csv)
    assert n == 4
    assert lookup["SCAR"]["off_pass_rank"] == "10"
    assert lookup["CCAR"]["off_pass_rank"] == "80"
    assert lookup["OKLA"]["off_pass_rank"] == "5"
    assert lookup["TXAM"]["off_pass_rank"] == "15"


def test_espn_scoreboard_fills_one_sided_board():
    payload = {
        "events": [
            {
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": "ILL"}},
                            {"homeAway": "away", "team": {"abbreviation": "UAB"}},
                        ]
                    }
                ]
            },
            {
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"abbreviation": "OU"}},
                            {"homeAway": "away", "team": {"abbreviation": "UTEP"}},
                        ]
                    }
                ]
            },
        ]
    }
    pairs = parse_scoreboard_pairs(payload)
    opp_map = expand_opp_map(pairs)
    df = pd.DataFrame(
        [
            {"player": "Collin Dixon", "pp_team": "ILL", "pp_opp_team": "", "team_abbr": "ILL", "opp_team_abbr": ""},
            {"player": "John Mateer", "pp_team": "OKLA", "pp_opp_team": "", "team_abbr": "OKLA", "opp_team_abbr": ""},
        ]
    )
    out = fill_cfb_opp_from_map(df, opp_map)
    assert out.iloc[0]["pp_opp_team"] == "UAB"
    assert out.iloc[1]["pp_opp_team"] == "UTEP"


def test_extra_fbs_count():
    assert len(EXTRA_FBS_TEAMS) == 14
    assert {t["team_abbr"] for t in EXTRA_FBS_TEAMS} >= {"CCU", "ULM", "JMU", "APP"}
