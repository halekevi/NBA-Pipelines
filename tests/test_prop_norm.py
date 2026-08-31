"""Canonical prop keys and hit-rate window selection."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from prop_hit_tiers import assign_tier, cover_need  # noqa: E402
from utils.prop_norm import canon_prop, display_prop, preferred_hr  # noqa: E402


def test_wnba_board_aliases():
    cases = {
        "Points": "points",
        "Rebounds": "rebounds",
        "Assists": "assists",
        "Pts+Rebs+Asts": "pra",
        "Pts+Rebs": "pts+reb",
        "Pts+Asts": "pts+ast",
        "Rebs+Asts": "reb+ast",
        "3-PT Made": "threes",
        "3-PT Attempted": "threes_att",
        "FG Attempted": "fga",
        "FG Made": "fgm",
        "Free Throws Made": "ftm",
        "Free Throws Attempted": "fta",
        "Two Pointers Made": "fg2m",
        "Two Pointers Attempted": "fg2a",
        "2pts Made": "fg2m",
        "2 pts made": "fg2m",
        "2PA": "fg2a",
        "2pts Attempted": "fg2a",
        "3pts Made": "threes",
        "Threes Made": "threes",
        "3PA": "threes_att",
        "pa": "pts+ast",
        "pr": "pts+reb",
        "ra": "reb+ast",
        "Offensive Rebounds": "oreb",
        "Defensive Rebounds": "dreb",
        "Blks+Stls": "stocks",
        "Blocked Shots": "blocks",
        "Turnovers": "turnovers",
        "Steals": "steals",
        "Points (Combo)": "points_combo",
        "points_combo": "points_combo",
        "Quarters with 3+ Points": "quarters_3plus",
        "Quarters with 4+ Points": "quarters_4plus",
        "Quarters with 5+ Points": "quarters_5plus",
        "Fantasy Score": "fantasy",
        "fg3m": "threes",
        "fga": "fga",
    }
    for label, want in cases.items():
        assert canon_prop("WNBA", label) == want, (label, canon_prop("WNBA", label))


def test_mlb_soccer_tennis_aliases():
    assert canon_prop("MLB", "Pitcher Strikeouts") == "pitcher_ks"
    assert canon_prop("MLB", "pitcher_ks") == "pitcher_ks"
    assert canon_prop("MLB", "Hits Allowed") == "hits_allowed"
    assert canon_prop("MLB", "hits_allowed") == "hits_allowed"
    assert canon_prop("MLB", "Pitcher Strikeouts (Combo)") == "strikeouts_combo"
    assert canon_prop("MLB", "Hits+Runs+RBIs") == "hits+runs+rbis"
    assert canon_prop("MLB", "H+R+RBI") == "hits+runs+rbis"
    assert canon_prop("MLB", "Earned Runs Allowed") == "earned_runs"
    assert canon_prop("MLB", "1st Inning Runs Allowed") == "first_inning_runs"
    assert canon_prop("Soccer", "Shots On Target") == "sog"
    assert canon_prop("Soccer", "Player Shots on Target") == "sog"
    assert canon_prop("Soccer", "Player Shots") == "shots"
    assert canon_prop("Soccer", "Goal + Assist") == "goal_assist"
    assert canon_prop("Soccer", "Passes Attempted") == "passes"
    assert canon_prop("Soccer", "Shots Attempted") == "shots"
    assert canon_prop("Soccer", "Goals + Assists") == "goal_assist"
    assert canon_prop("Soccer", "Fouls Committed") == "fouls"
    assert canon_prop("Soccer", "Player Fouls Committed") == "fouls"
    assert canon_prop("Soccer", "Player Fouls Won") == "fouls_drawn"
    assert canon_prop("Soccer", "Goalkeeper Saves") == "saves"
    assert canon_prop("Soccer", "Goalie Saves") == "saves"
    assert canon_prop("Soccer", "Goalie Saves (Combo)") == "saves_combo"
    assert canon_prop("Soccer", "Goals Allowed") == "goals_allowed"
    assert canon_prop("Soccer", "Goals Allowed (Combo)") == "goals_allowed_combo"
    assert canon_prop("Soccer", "Tackles") == "tackles"
    assert canon_prop("Soccer", "Clearances") == "clearances"
    assert canon_prop("Soccer", "Attempted Dribbles") == "attempted_dribbles"
    assert canon_prop("Soccer", "Shots Assisted") == "shots_assisted"
    assert canon_prop("Soccer", "Crosses") == "crosses"
    assert canon_prop("Soccer", "Goals Allowed in First 30 Minutes") == "goals_allowed_first30"
    assert canon_prop("CBB", "3-PT Made") == "threes"
    assert canon_prop("CBB", "fg3m") == "threes"
    assert canon_prop("CBB", "pa") == "pts+ast"
    assert canon_prop("CBB", "pr") == "pts+reb"
    assert canon_prop("CBB", "ra") == "reb+ast"
    assert canon_prop("CBB", "stl") == "steals"
    assert canon_prop("Tennis", "Total Games Won") == "games_won"
    assert canon_prop("Tennis", "Player Total Games Won") == "games_won"
    assert canon_prop("Tennis", "Player Games Won") == "games_won"
    assert canon_prop("Tennis", "Games Played") == "match_total_games"
    assert canon_prop("Tennis", "Games Won") == "games_won"
    assert canon_prop("Tennis", "Tiebreakers Played") == "total_tie_breaks"
    assert canon_prop("Tennis", "1st Set Games Played") == "match_total_games_set1"
    assert canon_prop("Golf", "Round Strokes") == "strokes"
    assert canon_prop("PGA", "Birdies or Better") == "birdies_or_better"
    assert canon_prop("Tennis", "Total Games") == "match_total_games"
    assert canon_prop("Tennis", "total games") == "match_total_games"
    assert canon_prop("Tennis", "1st Set Total Games") == "match_total_games_set1"
    assert canon_prop("Tennis", "1st Set Total Games Won") == "games_won_set1"
    assert canon_prop("Tennis", "1st Set Aces") == "aces_set1"
    assert canon_prop("NHL", "Shots on Goal") == "sog"
    assert canon_prop("NHL", "Time On Ice") == "toi"
    assert canon_prop("CBB", "3-PT Made") == "threes"
    assert canon_prop("NFL", "rec_tds") == "receiving_tds"


def test_display_and_hr_window():
    assert display_prop("fga") == "FG Attempted"
    assert display_prop("threes") == "3-PT Made"
    assert display_prop("threes_att") == "3-PT Attempted"
    assert display_prop("fg2a") == "Two Pointers Attempted"
    assert display_prop("saves_combo") == "Goalie Saves (Combo)"
    assert display_prop("points_combo") == "Points (Combo)"
    use = preferred_hr(n=100, hits=50, listed_n=50, listed_hits=35)
    assert use["window"] == "listed"
    assert use["hr"] == 0.7
    use_all = preferred_hr(n=100, hits=50, listed_n=10, listed_hits=8)
    assert use_all["window"] == "all"
    assert use_all["hr"] == 0.5


def test_mlb_s_tier_on_canon_and_board_labels():
    for prop in ("Pitcher Strikeouts", "pitcher_ks"):
        info = assign_tier(sport="MLB", pick_type="Goblin", side="OVER", prop=prop)
        assert info["prop_tier"] == "S", (prop, info)
    hits_allowed = assign_tier(
        sport="MLB", pick_type="Goblin", side="OVER", prop="Hits Allowed"
    )
    assert hits_allowed["prop_tier"] == "B"
    era = assign_tier(
        sport="MLB", pick_type="Goblin", side="OVER", prop="Earned Runs Allowed"
    )
    assert era["prop_tier"] == "C"
    outs = assign_tier(
        sport="MLB", pick_type="Goblin", side="OVER", prop="pitching_outs"
    )
    assert outs["prop_tier"] == "A"
    assert cover_need("MLB", "Hits Allowed") == 1.1
    assert cover_need("MLB", "hits_allowed") == 1.1


def test_tiers_follow_canon():
    gob = assign_tier(sport="Tennis", pick_type="Goblin", side="OVER", prop="Total Games")
    assert gob["prop_tier"] == "A"
    combo = assign_tier(sport="WNBA", pick_type="Standard", side="OVER", prop="Points (Combo)")
    assert combo["prop_tier"] == "B"
    already = assign_tier(sport="WNBA", pick_type="Standard", side="OVER", prop="points_combo")
    assert already["prop_tier"] == "B"
    assert cover_need("Tennis", "Total Games") == 4.3
    assert cover_need("WNBA", "FG Attempted") == 1.1
