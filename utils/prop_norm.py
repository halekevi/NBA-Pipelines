"""Canonical PrizePicks prop keys for hit-rate comparison.

One market = one key. Board labels, pipeline prop_norm, and graded_props
aliases all fold here before HR is grouped or looked up.

Hit-rate windows (same cell):
  all              — every HIT/MISS, no L5/L10 gate
  listed           — directional L5 >= 4
  l5eq5            — directional L5 == 5
  l5ge4_l10ge8     — L5 >= 4 and L10 >= 8
  l5eq5_l10ge8     — L5 == 5 and L10 >= 8
  l5ge4_l10eq10    — L5 >= 4 and L10 == 10
  l5eq5_l10eq10    — L5 == 5 and L10 == 10
  D                — opponent def aligned (OVER Weak|Below Avg; UNDER Elite|Above Avg;
                     Avg/unknown fail; MLB hitter Ks invert)
  Joints also exist as L5/L10 cuts ∩ D.

When comparing categories, use ``preferred_hr()``: listed if n>=40, else
all if n>=40, else listed if n>=15, else all. Never mix Goblin with
Standard or OVER with UNDER. Combos are not mixed with singles.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_COMBO_RE = re.compile(r"\(combo\)\s*$", re.I)
_SPACE_RE = re.compile(r"\s+")

# fold(label) -> canon. Sport-specific maps win over GLOBAL.
GLOBAL_FOLD: dict[str, str] = {
    "points": "points",
    "pts": "points",
    "rebounds": "rebounds",
    "reb": "rebounds",
    "assists": "assists",
    "ast": "assists",
    "steals": "steals",
    "stl": "steals",
    "blocks": "blocks",
    "blk": "blocks",
    "blockedshots": "blocks",
    "turnovers": "turnovers",
    "tov": "turnovers",
    "to": "turnovers",
    "pra": "pra",
    "ptsrebsasts": "pra",
    "pointsreboundsassists": "pra",
    "ptsreb": "pts+reb",
    "ptsrebs": "pts+reb",
    "pointsrebounds": "pts+reb",
    "ptsast": "pts+ast",
    "ptsasts": "pts+ast",
    "pointsassists": "pts+ast",
    "rebast": "reb+ast",
    "reboundsassists": "reb+ast",
    "rebsasts": "reb+ast",
    "stocks": "stocks",
    "blksstls": "stocks",
    "fgm": "fgm",
    "fgmade": "fgm",
    "fieldgoalsmade": "fgm",
    "fga": "fga",
    "fgattempted": "fga",
    "fieldgoalsattempted": "fga",
    "threes": "threes",
    "fg3m": "threes",
    "3ptmade": "threes",
    "3ptfgmade": "threes",
    "threepointersmade": "threes",
    "threepointermade": "threes",
    "3pointersmade": "threes",
    "3pointermade": "threes",
    "3pm": "threes",
    "3ptsmade": "threes",
    "threesmade": "threes",
    "threesatt": "threes_att",
    "fg3a": "threes_att",
    "3ptattempted": "threes_att",
    "3ptfgattempted": "threes_att",
    "threepointersattempted": "threes_att",
    "3pointersattempted": "threes_att",
    "3pa": "threes_att",
    "3ptsattempted": "threes_att",
    "threesattempted": "threes_att",
    "fg2m": "fg2m",
    "2ptmade": "fg2m",
    "2ptfgmade": "fg2m",
    "twopointersmade": "fg2m",
    "twopointermade": "fg2m",
    "2pm": "fg2m",
    "2ptsmade": "fg2m",
    "twoptsmade": "fg2m",
    "2pointsmade": "fg2m",
    "twopointsmade": "fg2m",
    "fg2a": "fg2a",
    "2ptattempted": "fg2a",
    "2ptfgattempted": "fg2a",
    "twopointersattempted": "fg2a",
    "twopointerattempted": "fg2a",
    "2pa": "fg2a",
    "2ptsattempted": "fg2a",
    "twoptsattempted": "fg2a",
    "2pointsattempted": "fg2a",
    "twopointsattempted": "fg2a",
    "pa": "pts+ast",
    "pr": "pts+reb",
    "ra": "reb+ast",
    "ftm": "ftm",
    "ftmade": "ftm",
    "freethrowsmade": "ftm",
    "fta": "fta",
    "ftattempted": "fta",
    "freethrowsattempted": "fta",
    "oreb": "oreb",
    "offensiverebounds": "oreb",
    "offensiverebound": "oreb",
    "dreb": "dreb",
    "defensiverebounds": "dreb",
    "defensiverebound": "dreb",
    "pf": "pf",
    "personalfouls": "pf",
    "minutes": "minutes",
    "min": "minutes",
    "doubledouble": "double_double",
    "tripledouble": "triple_double",
    "quarterswith3points": "quarters_3plus",
    "quarterswith4points": "quarters_4plus",
    "quarterswith5points": "quarters_5plus",
    "fantasy": "fantasy",
    "fantasyscore": "fantasy",
    "sog": "sog",
    "shotsongoal": "sog",
    "shotsontarget": "sog",
    "shotontarget": "sog",
    "sot": "sog",
    "playershotsontarget": "sog",
    "saves": "saves",
    "goaliesaves": "saves",
    "goalkeepersaves": "saves",
    "gksaves": "saves",
    "keepersaves": "saves",
}

MLB_FOLD: dict[str, str] = {
    "hits": "hits",
    "totalbases": "total_bases",
    "homeruns": "home_runs",
    "hr": "home_runs",
    "rbi": "rbis",
    "rbis": "rbis",
    "runs": "runs",
    "walks": "walks",
    "stolenbases": "stolen_bases",
    "hitterstrikeouts": "hitter_ks",
    "hitterks": "hitter_ks",
    "hitterstrikeout": "hitter_ks",
    "hitsrunsrbi": "hits+runs+rbis",
    "hitsrunsrbis": "hits+runs+rbis",
    "hrrbi": "hits+runs+rbis",
    "singles": "singles",
    "doubles": "doubles",
    "triples": "triples",
    "plateappearances": "plate_appearances",
    "pitchesseen": "pitches_seen",
    "ballscounted": "balls_counted",
    "strikescounted": "strikes_counted",
    "pitcherstrikeouts": "pitcher_ks",
    "pitcherks": "pitcher_ks",
    "strikeouts": "pitcher_ks",
    "ks": "pitcher_ks",
    "pitchingouts": "pitching_outs",
    "hitsallowed": "hits_allowed",
    "earnedruns": "earned_runs",
    "earnedrunsallowed": "earned_runs",
    "walksallowed": "walks_allowed",
    "inningspitched": "innings_pitched",
    "pitchesthrown": "pitches_thrown",
    "battersfaced": "batters_faced",
    "ballsthrown": "balls_thrown",
    "strikesthrown": "strikes_thrown",
    "pitchesthrown95mph": "pitches_thrown_95",
    "1stinningrunsallowed": "first_inning_runs",
    "firstinningrunsallowed": "first_inning_runs",
    "1stinningwalksallowed": "first_inning_walks",
    "firstinningwalksallowed": "first_inning_walks",
    "pitcherstrikeoutstotalbases": "strikeouts_total_bases",
}

SOCCER_FOLD: dict[str, str] = {
    "shots": "shots",
    "shotsattempted": "shots",
    "shotattempted": "shots",
    "playershots": "shots",
    "goals": "goals",
    "assists": "assists",
    "playerassists": "assists",
    "goalassist": "goal_assist",
    "goalsassists": "goal_assist",
    "goalsplusassists": "goal_assist",
    "goalassists": "goal_assist",
    "fouls": "fouls",
    "foulscommitted": "fouls",
    "playerfoulscommitted": "fouls",
    "foulsdrawn": "fouls_drawn",
    "playerfoulswon": "fouls_drawn",
    "foulswon": "fouls_drawn",
    "cards": "cards",
    "yellowcards": "cards",
    "offsides": "offsides",
    "playeroffsides": "offsides",
    "tackles": "tackles",
    "playertackles": "tackles",
    "passes": "passes",
    "passesattempted": "passes",
    "passattempts": "passes",
    "passattempted": "passes",
    "clearances": "clearances",
    "attempteddribbles": "attempted_dribbles",
    "dribbles": "attempted_dribbles",
    "dribbleattempts": "attempted_dribbles",
    "shotsassisted": "shots_assisted",
    "keypasses": "shots_assisted",
    "crosses": "crosses",
    "tackleswon": "tackles",
    "goalsallowed": "goals_allowed",
    "goalsconceded": "goals_allowed",
    "goalsallowedcombo": "goals_allowed_combo",
    "goaliesavescombo": "saves_combo",
    "savescombo": "saves_combo",
    "goalsallowedinfirst30minutes": "goals_allowed_first30",
    "goalsallowedfirst30": "goals_allowed_first30",
    "first30minutesgoalsallowed": "goals_allowed_first30",
    "outfieldfantasyscore": "fantasy",
    "goaliefantasyscore": "fantasy",
}

TENNIS_FOLD: dict[str, str] = {
    "aces": "aces",
    "ace": "aces",
    "doublefaults": "double_faults",
    "doublefault": "double_faults",
    "gameswon": "games_won",
    "totalgameswon": "games_won",
    "playertotalgameswon": "games_won",
    "playergameswon": "games_won",
    "totalgames": "match_total_games",
    "matchtotalgames": "match_total_games",
    "gamesplayed": "match_total_games",
    "playertotalgames": "match_total_games",
    "setswon": "sets_won",
    "totalsets": "total_sets",
    "setsplayed": "total_sets",
    "totaltiebreaks": "total_tie_breaks",
    "tiebreaks": "total_tie_breaks",
    "tiebreakersplayed": "total_tie_breaks",
    "tiebreakerplayed": "total_tie_breaks",
    "tiebreaksplayed": "total_tie_breaks",
    "breakpointswon": "break_points_won",
    "1stsettotalgameswon": "games_won_set1",
    "firstsettotalgameswon": "games_won_set1",
    "1stsetgameswon": "games_won_set1",
    "firstsetgameswon": "games_won_set1",
    "1stsettotalgames": "match_total_games_set1",
    "firstsettotalgames": "match_total_games_set1",
    "1stsetgamesplayed": "match_total_games_set1",
    "firstsetgamesplayed": "match_total_games_set1",
    "1stsetaces": "aces_set1",
    "firstsetaces": "aces_set1",
}

GOLF_FOLD: dict[str, str] = {
    "strokes": "strokes",
    "roundstrokes": "strokes",
    "birdiesorbetter": "birdies_or_better",
    "bogeysorworse": "bogeys_or_worse",
    "greensinregulation": "gir",
    "gir": "gir",
    "fairwayshit": "fairways_hit",
    "fairways": "fairways_hit",
    "tourneyfinishingposition": "finish_pos",
    "tournamentfinishingposition": "finish_pos",
    "finishingposition": "finish_pos",
}

NHL_FOLD: dict[str, str] = {
    "points": "points",
    "pts": "points",
    "goals": "goals",
    "assists": "assists",
    "sog": "sog",
    "shotsongoal": "sog",
    "hits": "hits",
    "blockedshots": "blocked_shots",
    "blocks": "blocked_shots",
    "pim": "pim",
    "plusminus": "plus_minus",
    "powerplaypoints": "pp_points",
    "pppoints": "pp_points",
    "faceoffswon": "faceoffs_won",
    "timeonice": "toi",
    "toi": "toi",
    "saves": "saves",
    "goaliesaves": "saves",
    "goalsallowed": "goals_allowed",
}

NFL_FOLD: dict[str, str] = {
    "receivingyards": "receiving_yards",
    "recyds": "receiving_yards",
    "rectds": "receiving_tds",
    "receivingtds": "receiving_tds",
    "rushingyards": "rushing_yards",
    "rushyds": "rushing_yards",
    "rushtds": "rushing_tds",
    "rushingtds": "rushing_tds",
    "passingyards": "passing_yards",
    "passyds": "passing_yards",
    "passingtds": "passing_tds",
    "passtds": "passing_tds",
    "sacks": "sacks",
    "receptions": "receptions",
    "rec": "receptions",
    "tackles": "tackles",
    "tacklesast": "tackles",
    "solotackles": "solo_tackles",
    "int": "interceptions",
    "interceptions": "interceptions",
    "passints": "interceptions",
    "playertouchdowns": "player_tds",
    "anytimetd": "player_tds",
    "fgmade": "fg_made",
    "patmade": "pat_made",
    "passrushyds": "pass_rush_yds",
    "rushrecyds": "rush_rec_yds",
    "passrushtds": "pass_rush_tds",
    "100recyardgames": "season_100_rec",
    "100rushyardgames": "season_100_rush",
    "300passyardgames": "season_300_pass",
    "400passyardgames": "season_400_pass",
    "puntsinside20": "punts_inside_20",
    "50yardfgmade": "fg_50plus",
    "regularseasongamesstarted": "games_started",
}

CFB_FOLD: dict[str, str] = {
    "passyards": "pass_yds",
    "passingyards": "pass_yds",
    "passyds": "pass_yds",
    "rushyards": "rush_yds",
    "rushingyards": "rush_yds",
    "recyards": "rec_yds",
    "receivingyards": "rec_yds",
    "passtds": "pass_td",
    "passingtds": "pass_td",
    "rushtds": "rush_td",
    "rectds": "rec_td",
    "receptions": "rec",
    "interceptions": "int",
    "passattempts": "pass_att",
    "completions": "pass_cmp",
    "kickingpoints": "kick_pts",
    "fgmade": "fg_made",
    "patmade": "pat_made",
    "playertouchdowns": "player_td",
    "sacks": "sacks",
    "tackles": "tackles",
    "tacklesforloss": "tfl",
    "passrushyds": "pass_rush_yds",
    "rushrecyds": "rush_rec_yds",
    "targets": "rec_tgt",
    "rushattempts": "rush_att",
}

SPORT_FOLD: dict[str, dict[str, str]] = {
    "MLB": MLB_FOLD,
    "SOCCER": SOCCER_FOLD,
    "TENNIS": TENNIS_FOLD,
    "NHL": NHL_FOLD,
    "NFL": NFL_FOLD,
    "NFLP": NFL_FOLD,
    "CFB": CFB_FOLD,
    "GOLF": GOLF_FOLD,
    "PGA": GOLF_FOLD,
}

BASKETBALL = frozenset({
    "WNBA", "NBA", "CBB", "WCBB",
    "WNBA1H", "WNBA1Q", "WNBA2H", "WNBA4Q",
    "NBA1H", "NBA1Q",
})

# Human labels for reports / list print.
DISPLAY: dict[str, str] = {
    "points": "Points",
    "rebounds": "Rebounds",
    "assists": "Assists",
    "steals": "Steals",
    "blocks": "Blocked Shots",
    "turnovers": "Turnovers",
    "pra": "Pts+Rebs+Asts",
    "pts+reb": "Pts+Rebs",
    "pts+ast": "Pts+Asts",
    "reb+ast": "Rebs+Asts",
    "stocks": "Blks+Stls",
    "fgm": "FG Made",
    "fga": "FG Attempted",
    "threes": "3-PT Made",
    "threes_att": "3-PT Attempted",
    "fg2m": "Two Pointers Made",
    "fg2a": "Two Pointers Attempted",
    "ftm": "Free Throws Made",
    "fta": "Free Throws Attempted",
    "oreb": "Offensive Rebounds",
    "dreb": "Defensive Rebounds",
    "quarters_3plus": "Quarters with 3+ Points",
    "quarters_4plus": "Quarters with 4+ Points",
    "quarters_5plus": "Quarters with 5+ Points",
    "sog": "Shots On Target",
    "saves": "Goalie Saves",
    "saves_combo": "Goalie Saves (Combo)",
    "points_combo": "Points (Combo)",
    "goal_assist": "Goal + Assist",
    "passes": "Passes Attempted",
    "tackles": "Tackles",
    "clearances": "Clearances",
    "attempted_dribbles": "Attempted Dribbles",
    "shots_assisted": "Shots Assisted",
    "crosses": "Crosses",
    "fouls": "Fouls",
    "fouls_drawn": "Fouls Drawn",
    "goals": "Goals",
    "goals_allowed": "Goals Allowed",
    "goals_allowed_combo": "Goals Allowed (Combo)",
    "goals_allowed_first30": "Goals Allowed in First 30 Minutes",
    "offsides": "Offsides",
    "shots": "Shots",
    "games_won": "Total Games Won",
    "match_total_games": "Total Games",
    "pitcher_ks": "Pitcher Strikeouts",
    "hitter_ks": "Hitter Strikeouts",
    "hits+runs+rbis": "Hits+Runs+RBIs",
    "total_bases": "Total Bases",
    "earned_runs": "Earned Runs Allowed",
    "first_inning_runs": "1st Inning Runs Allowed",
    "first_inning_walks": "1st Inning Walks Allowed",
    "strikeouts_combo": "Pitcher Strikeouts (Combo)",
}


def fold(text: object) -> str:
    s = str(text or "").strip().lower().replace("&", "and")
    s = s.replace("+", "").replace("-", "")
    return re.sub(r"[^a-z0-9]+", "", s)


def _sport_key(sport: object) -> str:
    s = str(sport or "").strip().upper()
    if s == "SOC":
        return "SOCCER"
    if s == "PGA":
        return "GOLF"
    return s


def _lookup(sport: str, folded: str) -> str | None:
    if sport in BASKETBALL and folded in GLOBAL_FOLD:
        return GLOBAL_FOLD[folded]
    table = SPORT_FOLD.get(sport)
    if table and folded in table:
        return table[folded]
    if folded in GLOBAL_FOLD:
        return GLOBAL_FOLD[folded]
    return None


def _known_canon_keys() -> frozenset[str]:
    keys = set(DISPLAY)
    keys.update(GLOBAL_FOLD.values())
    for table in SPORT_FOLD.values():
        keys.update(table.values())
    return frozenset(keys)


_KNOWN_CANON = _known_canon_keys()


def canon_prop(sport: object, prop: object) -> str:
    """One key per market. Combo and 1st-set stay distinct from the full-game single."""
    raw = _SPACE_RE.sub(" ", str(prop or "").strip())
    if not raw:
        return ""
    if raw in _KNOWN_CANON:
        return raw
    # Already-canon combo keys (points_combo) must not re-fold to pointscombo.
    if raw.endswith("_combo"):
        inner = raw[: -len("_combo")]
        sport_k = _sport_key(sport)
        if inner in _KNOWN_CANON or _lookup(sport_k, fold(inner)) is not None:
            return raw
    sport_k = _sport_key(sport)
    combo = bool(_COMBO_RE.search(raw))
    base = _COMBO_RE.sub("", raw).strip()
    folded = fold(base)
    if not folded:
        return ""

    hit = _lookup(sport_k, folded)
    if hit is None and sport_k == "MLB":
        if "hitter" in folded and "strike" in folded:
            hit = "hitter_ks"
        elif "pitcher" in folded and "strike" in folded:
            hit = "pitcher_ks"
    if hit is None:
        hit = folded

    if combo:
        if hit == "pitcher_ks":
            return "strikeouts_combo"
        if hit.endswith("_combo"):
            return hit
        return f"{hit}_combo"
    return hit


def display_prop(canon: object) -> str:
    c = str(canon or "").strip()
    if c.endswith("_combo"):
        inner = display_prop(c[: -len("_combo")])
        return f"{inner} (Combo)"
    return DISPLAY.get(c, c.replace("_", " ").title())


def preferred_hr(
    *,
    n: int = 0,
    hits: int = 0,
    listed_n: int = 0,
    listed_hits: int = 0,
) -> dict[str, Any]:
    """Pick the HR window used when comparing categories.

    listed (L5>=4) wins at n>=40 because that is the list/ticket gate.
    """
    n = int(n or 0)
    hits = int(hits or 0)
    listed_n = int(listed_n or 0)
    listed_hits = int(listed_hits or 0)
    if listed_n >= 40:
        window, hn, hh = "listed", listed_n, listed_hits
    elif n >= 40:
        window, hn, hh = "all", n, hits
    elif listed_n >= 15:
        window, hn, hh = "listed_thin", listed_n, listed_hits
    else:
        window, hn, hh = "all_thin", n, hits
    hr = round(hh / hn, 4) if hn else None
    return {"window": window, "n": hn, "hits": hh, "hr": hr}


def hr_lookup_key(sport: object, prop: object) -> str:
    """Alnum fold of canon — use as dict key when joining reports."""
    return fold(canon_prop(sport, prop))


def apply_canon_row(sport: object, prop: object, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    c = canon_prop(sport, prop)
    out = {"prop_canon": c, "prop_display": display_prop(c), "prop_fold": fold(c)}
    if extra:
        out.update(dict(extra))
    return out
