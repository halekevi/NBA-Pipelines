import pandas as pd
from utils.matchup_edge.player_ranks import (
    assign_league_ranks,
    assign_team_ranks,
    format_category_rank_label,
    stamp_player_ranks,
)


def test_assign_league_and_team_ranks():
    df = pd.DataFrame(
        [
            {"PLAYER_NORM": "aja wilson", "season_avg": 9.5},
            {"PLAYER_NORM": "jackie young", "season_avg": 4.2},
            {"PLAYER_NORM": "bench player", "season_avg": 1.1},
        ]
    )
    league = assign_league_ranks(df)
    assert league["aja wilson"]["league_rank"] == 1
    assert league["jackie young"]["league_rank"] == 2
    assert league["bench player"]["league_n"] == 3

    team = assign_team_ranks(df)
    assert team["aja wilson"]["rank_on_team"] == 1
    assert team["aja wilson"]["leader_slice"] == "top"
    assert team["bench player"]["rank_on_team"] == 3


def test_category_rank_label():
    lbl = format_category_rank_label(
        {"league_rank": 1, "rank_on_team": 1},
        opp_def_rank=3,
        cat_short="reb",
    )
    assert lbl == "L#1 · T1 · vs #3 reb D"


def test_stamp_player_ranks():
    rec = {"player": "A'ja Wilson"}
    stamp_player_ranks(
        rec,
        league={"league_rank": 3, "league_n": 140, "league_rank_label": "L#3"},
        team={"rank_on_team": 1, "leader_slice": "top", "team_rank_label": "T1"},
        opp_def_rank=5,
        cat_short="reb",
    )
    assert rec["league_rank"] == 3
    assert rec["rank_on_team"] == 1
    assert "L#3" in rec["category_rank_label"]
    assert "T1" in rec["category_rank_label"]
    assert "vs #5 reb D" in rec["category_rank_label"]
