"""Future-sport coverage: grades JSON, tickets, S-D, cover floors."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "grading"))
sys.path.insert(0, str(ROOT))

from prop_hit_tiers import ACTIVE, assign_tier, cover_need, norm_sport  # noqa: E402
from utils.ticket_70_pool import (  # noqa: E402
    TICKET_SPORTS,
    goblin_70_eligible,
    standard_flex_kind,
    ticket_gate_passes,
)
from build_grades_html import GRADED_JSON_SPORTS  # noqa: E402
from build_ticket_eval import (  # noqa: E402
    ALLOWED_TICKET_SPORTS,
    TICKET_EVAL_SPORT_ORDER,
    _leg_match_buckets,
)


def test_nfl_cfb_wcbb_in_graded_json_export():
    keys = {k for k, _ in GRADED_JSON_SPORTS}
    labels = {lab for _, lab in GRADED_JSON_SPORTS}
    assert {"nfl", "cfb", "wcbb", "golf"} <= keys
    assert {"NFL", "CFB", "WCBB", "Golf"} <= labels


def test_period_and_football_on_ticket_sports():
    for sport in ("WNBA1Q", "WNBA1H", "NBA1Q", "NBA1H", "NFL", "CFB", "Golf", "WCBB"):
        assert sport in TICKET_SPORTS, sport
        assert norm_sport(sport) in ACTIVE or norm_sport(sport) in TICKET_SPORTS


def test_sd_pins_follow_l5eq5_catalog():
    fga = assign_tier(sport="WNBA", pick_type="Goblin", side="OVER", prop="FG Attempted")
    reb_ast = assign_tier(sport="WNBA", pick_type="Goblin", side="OVER", prop="Rebs+Asts")
    pra = assign_tier(sport="WNBA", pick_type="Goblin", side="OVER", prop="Pts+Rebs+Asts")
    assert fga["prop_tier"] == "A"
    assert reb_ast["prop_tier"] == "A"
    assert pra["prop_tier"] == "B"
    nba_pts = assign_tier(sport="NBA", pick_type="Goblin", side="OVER", prop="Points")
    nba1q_reb = assign_tier(sport="NBA1Q", pick_type="Goblin", side="OVER", prop="Rebounds")
    assert nba_pts["prop_tier"] == "A"
    assert nba1q_reb["prop_tier"] == "S"
    cfb_pass = assign_tier(sport="CFB", pick_type="Goblin", side="OVER", prop="Pass Yards")
    assert cfb_pass["prop_tier"] == "C"


def test_cover_floors_basketball_and_football():
    assert cover_need("NBA", "Pts+Rebs+Asts") == 3.7
    assert cover_need("CBB", "FG Attempted") == 1.1
    assert cover_need("NBA1Q", "Points") == 0.87
    assert cover_need("NFL", "Passing Yards") == 15.0
    assert cover_need("CFB", "Pass Yards") == 15.0
    assert cover_need("NFL", "Receptions") == 0.8


def test_wnba1q_and_cfb_clear_ticket_gate():
    q = {
        "sport": "WNBA1Q",
        "player": "A'ja Wilson",
        "prop": "Points",
        "side": "OVER",
        "pick_type": "Goblin",
        "l5_over": 5,
        "l10_over": 8,
        "cover": 1.2,
        "def": "Weak",
    }
    assert ticket_gate_passes(q)
    assert goblin_70_eligible(q)
    thin = dict(q, cover=0.2)
    assert not goblin_70_eligible(thin)


def test_ticket_eval_allows_period_golf_and_football():
    for sport in ("WNBA1Q", "WNBA1H", "GOLF", "NFL", "CFB"):
        assert sport in ALLOWED_TICKET_SPORTS, sport
        assert sport in TICKET_EVAL_SPORT_ORDER, sport
    assert _leg_match_buckets("WNBA1Q")[0] == "WNBA1Q"
    assert _leg_match_buckets("GOLF") == ["GOLF"]
    assert _leg_match_buckets("PGA") == ["GOLF"]


def test_combo_canon_keeps_sd_and_flex_kind():
    assert assign_tier(
        sport="WNBA", pick_type="Standard", side="OVER", prop="points_combo"
    )["prop_tier"] == "B"
    row = {
        "sport": "WNBA",
        "player": "A'ja Wilson",
        "prop": "points_combo",
        "side": "OVER",
        "pick_type": "Standard",
        "l5_over": 4,
        "l10_over": 8,
        "cover": 3.0,
        "def": "Weak",
    }
    assert standard_flex_kind(row) == "wnba_combo_over"


def test_sport_pure_ticket_ids_do_not_collide():
    from build_goblin70_tickets import SPORT_PURE, SPORT_TID_PREFIX

    prefixes = []
    for sport, *_ in SPORT_PURE:
        prefixes.append(
            SPORT_TID_PREFIX.get(str(sport).upper(), str(sport)[:3].upper())
        )
    assert len(prefixes) == len(set(prefixes)), prefixes
