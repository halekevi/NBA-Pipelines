"""Goblin-70 ticket pool and /tickets publish payload."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO))

from build_goblin70_tickets import (  # noqa: E402
    playable_tickets,
    to_web_payload,
)
from utils.ticket_70_pool import (  # noqa: E402
    goblin_70_eligible,
    nflp_std_over_eligible,
    nflp_ticket_eligible,
)


def _gob(**kwargs) -> dict:
    row = {
        "sport": "WNBA",
        "player": "Ezi Magbegor",
        "prop": "Rebounds",
        "side": "OVER",
        "line": 5.5,
        "pick_type": "Goblin",
        "l5_over": 5,
        "cover": 2.4,
        "def": "Weak",
        "prop_tier": "A",
    }
    row.update(kwargs)
    return row


def test_cover_floor_blocks_wnba_under_2():
    assert not goblin_70_eligible(_gob(cover=1.1))
    assert goblin_70_eligible(_gob(prop="Points", cover=4.3, l5_over=4))


def test_nflp_ticket_gate():
    kicker = {
        "sport": "NFL",
        "player": "Andres Borregales",
        "prop": "FG Made",
        "side": "OVER",
        "pick_type": "Goblin",
        "league": "NFLP",
        "starter_policy": "plays",
        "l5_over": 5,
        "checks": {"D": False},
    }
    assert nflp_ticket_eligible(kicker)
    sit = dict(kicker, prop="Rush Yards", starter_policy="sit")
    assert not nflp_ticket_eligible(sit)
    backup = dict(
        kicker,
        player="Shane Buechele",
        prop="Pass Yards",
        starter_policy="backup",
        l5_over=1,
        checks={"D": True},
    )
    assert nflp_ticket_eligible(backup)
    assert not nflp_ticket_eligible(dict(backup, checks={"D": False}))
    std_backup = dict(
        backup,
        pick_type="Standard",
        checks={"D": True},
    )
    assert nflp_std_over_eligible(std_backup)
    assert not nflp_std_over_eligible(dict(std_backup, checks={"D": False}))


def test_shadow_and_demon_off_tickets():
    assert not goblin_70_eligible(
        _gob(sport="TENNIS", prop="Aces", cover=3.0, l5_over=5)
    )
    assert not goblin_70_eligible(
        _gob(sport="SOCCER", prop="Shots On Target", cover=1.5, l5_over=5)
    )
    assert not goblin_70_eligible(
        _gob(sport="MLB", prop="Singles", cover=1.2, l5_over=5)
    )
    assert not goblin_70_eligible(_gob(pick_type="Demon", cover=4.0))
    assert not goblin_70_eligible(_gob(pick_type="Standard", cover=4.0))


def test_l5_and_mlb_floor():
    assert not goblin_70_eligible(_gob(l5_over=3, cover=4.0))
    assert goblin_70_eligible(
        _gob(
            sport="MLB",
            player="MacKenzie Gore",
            prop="Pitcher Strikeouts",
            cover=1.0,
            l5_over=4,
        )
    )
    assert not goblin_70_eligible(
        _gob(
            sport="MLB",
            player="MacKenzie Gore",
            prop="Pitcher Strikeouts",
            cover=0.9,
            l5_over=5,
        )
    )


def test_web_payload_drops_standard_and_uses_n_correct():
    payload = {
        "date": "2026-08-26",
        "payout_note": "N-correct / To Win only.",
        "pool": {"goblin_70": 1},
        "tickets": [
            {
                "id": "P3-1",
                "family": "goblin",
                "product": "Power",
                "n_legs": 3,
                "mean_leg_p": 0.763,
                "sweep_pct": 44.4,
                "cash_pct": 44.4,
                "ev_n_correct": 0.887,
                "n_correct": {3: 2.0},
                "payout_note": "0S+3G Power 3-correct 2x (live slip; N-correct / To Win)",
                "legs": [
                    {
                        "sport": "MLB",
                        "player": "MacKenzie Gore",
                        "prop": "Pitcher Strikeouts",
                        "side": "OVER",
                        "line": 3.5,
                        "pick_type": "Goblin",
                        "l5": 5,
                        "cover": 2.9,
                        "d": "Below Avg",
                        "tier": "S",
                        "matchup": "TEX vs CWS",
                        "team": "TEX",
                        "p": 0.763,
                    },
                    {
                        "sport": "TENNIS",
                        "player": "Toby Samuel",
                        "prop": "Total Games",
                        "side": "OVER",
                        "line": 17.5,
                        "pick_type": "Goblin",
                        "l5": 5,
                        "cover": 7.1,
                        "tier": "A",
                        "matchup": "TOBY SAMUEL vs BILLY HARRIS (ATP / HARD)",
                        "p": 0.763,
                    },
                    {
                        "sport": "WNBA",
                        "player": "Jade Melbourne",
                        "prop": "Points",
                        "side": "OVER",
                        "line": 7.5,
                        "pick_type": "Goblin",
                        "l5": 5,
                        "cover": 6.5,
                        "tier": "A",
                        "matchup": "SEA vs TOR",
                        "team": "SEA",
                        "p": 0.763,
                    },
                ],
            },
            {
                "id": "SF3-1",
                "family": "standard",
                "product": "Flex",
                "n_legs": 3,
                "mean_leg_p": 0.65,
                "sweep_pct": 28.0,
                "cash_pct": 72.0,
                "ev_n_correct": 1.18,
                "n_correct": {3: 2.25, 2: 1.25},
                "legs": [
                    {
                        "sport": "MLB",
                        "player": "Brady House",
                        "prop": "Hits+Runs+RBIs",
                        "side": "UNDER",
                        "line": 1.5,
                        "pick_type": "Standard",
                        "p": 0.66,
                    }
                ],
            },
        ],
    }
    assert len(playable_tickets(payload)) == 1
    web = to_web_payload(payload)
    assert web["allow_standard"] is False
    assert web["ticket_track"] == "goblin70"
    slips = [t for g in web["groups"] for t in g["tickets"]]
    assert len(slips) == 1
    slip = slips[0]
    legs = slip["legs"]
    assert all(leg["pick_type"] == "Goblin" for leg in legs)
    assert all(leg["direction"] == "OVER" for leg in legs)
    pay = slip["payout"]
    assert pay["min_guarantee"] == 2.0
    assert pay["sweep_payout_x"] == 2.0
    assert pay["audit_all_hit_x"] == 2.0
    assert pay["n_correct"][3] == 2.0
    assert "1st" not in str(pay.get("payout_note") or "").lower()


def test_named_wnba_and_nfl_groups_are_playable():
    payload = {
        "date": "2026-08-27",
        "pool": {"goblin_70": 2, "nflp_goblin": 2},
        "tickets": [
            {
                "id": "WNB3-1",
                "family": "goblin",
                "product": "Power",
                "n_legs": 2,
                "web_group": "WNBA Goblin-70 Power 2",
                "mean_leg_p": 0.763,
                "sweep_pct": 58.2,
                "cash_pct": 58.2,
                "ev_n_correct": 1.28,
                "n_correct": {2: 2.2},
                "payout_note": "0S+2G Power median 2.2x",
                "legs": [
                    {
                        "sport": "WNBA",
                        "player": "Shakira Austin",
                        "prop": "Points",
                        "side": "OVER",
                        "line": 11.5,
                        "pick_type": "Goblin",
                        "p": 0.763,
                    },
                    {
                        "sport": "WNBA",
                        "player": "Kiki Iriafen",
                        "prop": "Pts+Rebs+Asts",
                        "side": "OVER",
                        "line": 19.5,
                        "pick_type": "Goblin",
                        "p": 0.763,
                    },
                ],
            },
            {
                "id": "NFL2-1",
                "family": "nflp",
                "product": "Power",
                "n_legs": 2,
                "web_group": "NFL Power 2",
                "mean_leg_p": 0.70,
                "sweep_pct": 49.0,
                "cash_pct": 49.0,
                "ev_n_correct": 1.08,
                "n_correct": {2: 2.2},
                "payout_note": "0S+2G Power median 2.2x",
                "legs": [
                    {
                        "sport": "NFL",
                        "player": "Andres Borregales",
                        "prop": "Kicking Points",
                        "side": "OVER",
                        "line": 6.5,
                        "pick_type": "Goblin",
                        "p": 0.70,
                    },
                    {
                        "sport": "NFL",
                        "player": "Shane Buechele",
                        "prop": "Pass Yards",
                        "side": "OVER",
                        "line": 149.5,
                        "pick_type": "Goblin",
                        "p": 0.62,
                    },
                ],
            },
        ],
    }
    assert len(playable_tickets(payload)) == 2
    web = to_web_payload(payload)
    names = {g["group_name"] for g in web["groups"]}
    assert "WNBA Goblin-70 Power 2" in names
    assert "NFL Power 2" in names
    sports = {
        leg["sport"]
        for g in web["groups"]
        for t in g["tickets"]
        for leg in t["legs"]
    }
    assert "WNBA" in sports
    assert "NFL" in sports


def test_goblin_power3_n_correct_is_live_2x():
    from build_goblin70_tickets import PAY, ticket_math

    assert PAY[("goblin", 3, "Power")]["n_correct"][3] == 2.0
    math = ticket_math(
        [{"p": 0.763}, {"p": 0.763}, {"p": 0.763}],
        "Power",
        "goblin",
    )
    assert math["n_correct"][3] == 2.0
    assert abs(math["ev_n_correct"] - (0.763 ** 3) * 2.0) < 0.001


def test_goblin70_web_leg_splits_hr_and_ml():
    from build_goblin70_tickets import _leg_to_web

    web = _leg_to_web(
        {
            "player": "Gerrit Cole",
            "sport": "MLB",
            "prop": "Pitcher Strikeouts",
            "side": "OVER",
            "line": 3.5,
            "p": 0.763,
            "l5": 5,
            "cover": 3.6,
            "ml_prob": 0.92,
            "hit_rate": 1.0,
            "standard_line": 5.5,
        },
        ticket_id="t1",
        date="2026-08-27",
    )
    assert web["hit_rate"] == 1.0
    assert web["ml_prob"] == 0.92
    assert web["hit_rate"] != web["ml_prob"]
    assert web["best_cross_book"] == "PP"
    assert web["best_cross_line"] == 3.5
    assert web["cross_edge_vs_pp"] == 0.0
    assert web["standard_line"] == 5.5


def test_merge_keeps_goblin70_and_graded_main():
    from build_goblin70_tickets import is_g70_group, merge_web_payload

    g70 = {
        "date": "2026-08-27",
        "ticket_track": "goblin70",
        "mode": "goblin70",
        "groups": [
            {
                "group_name": "X-Sport Goblin-70 Power 3",
                "tickets": [{"ticket_track": "goblin70", "ticket_id": "g70-1"}],
            }
        ],
    }
    main = {
        "date": "2026-08-27",
        "ticket_track": "graded_main",
        "filters": {"min_hit_rate": 0.72},
        "groups": [
            {
                "group_name": "X-Sport Goblin-70 Power 3",
                "tickets": [{"ticket_track": "goblin70"}],
            },
            {
                "group_name": "STRONG 3-Leg",
                "tickets": [{"ticket_track": "graded_main", "ticket_id": "main-1"}],
            },
            {
                "group_name": "MLB 2-Leg Goblin OVER",
                "tickets": [{"ticket_track": "graded_main", "ticket_id": "main-2"}],
            },
        ],
    }
    mixer = [g for g in main["groups"] if not is_g70_group(g)]
    merged = merge_web_payload(g70, main, mixer)
    names = [g["group_name"] for g in merged["groups"]]
    assert names[0] == "X-Sport Goblin-70 Power 3"
    assert "STRONG 3-Leg" in names
    assert "MLB 2-Leg Goblin OVER" in names
    assert names.count("X-Sport Goblin-70 Power 3") == 1
    assert merged["mode"] == "goblin70+graded_main"
    assert merged["tracks"] == ["goblin70", "graded_main"]


def test_union_mixer_keeps_live_core_and_pool_tennis():
    from build_goblin70_tickets import union_mixer_groups

    live = [
        {"group_name": "STRONG 3-Leg", "tickets": [{"ticket_id": "s1"}]},
        {"group_name": "MLB Core Power 2 #3", "tickets": [{"ticket_id": "m1"}]},
    ]
    pool = [
        {"group_name": "TENNIS Core Power 2 #1", "tickets": [{"ticket_id": "t1"}]},
        {"group_name": "STRONG 3-Leg", "tickets": [{"ticket_id": "stale"}]},
    ]
    names = [g["group_name"] for g in union_mixer_groups(live, pool)]
    assert names == [
        "STRONG 3-Leg",
        "MLB Core Power 2 #3",
        "TENNIS Core Power 2 #1",
    ]
    by_name = {g["group_name"]: g for g in union_mixer_groups(live, pool)}
    assert by_name["STRONG 3-Leg"]["tickets"][0]["ticket_id"] == "s1"


def test_patch_mixer_updates_line_and_keeps_unmatched():
    from build_goblin70_tickets import patch_mixer_groups

    groups = [
        {
            "group_name": "STRONG 3-Leg",
            "tickets": [
                {
                    "ticket_id": "keep-line-move",
                    "legs": [
                        {
                            "sport": "WNBA",
                            "player": "Kiki Iriafen",
                            "prop_type": "Pts+Rebs",
                            "pick_type": "Goblin",
                            "direction": "OVER",
                            "line": 19.5,
                        },
                        {
                            "sport": "MLB",
                            "player": "Gerrit Cole",
                            "prop_type": "Pitcher Strikeouts",
                            "pick_type": "Goblin",
                            "direction": "OVER",
                            "line": 3.5,
                        },
                    ],
                },
                {
                    "ticket_id": "keep-missing-prop",
                    "legs": [
                        {
                            "sport": "WNBA",
                            "player": "Gone Player",
                            "prop_type": "Points",
                            "pick_type": "Goblin",
                            "direction": "OVER",
                            "line": 10.5,
                        }
                    ],
                },
            ],
        }
    ]
    board = [
        {
            "sport": "WNBA",
            "player": "Kiki Iriafen",
            "prop": "Pts+Rebs",
            "pick_type": "Goblin",
            "side": "OVER",
            "line": 18.5,
            "cover": 7.8,
            "l5_over": 5,
        },
        {
            "sport": "MLB",
            "player": "Gerrit Cole",
            "prop": "Pitcher Strikeouts",
            "pick_type": "Goblin",
            "side": "OVER",
            "line": 3.5,
            "cover": 3.6,
            "l5_over": 5,
        },
    ]
    out, stats = patch_mixer_groups(groups, board)
    assert stats["updated"] == 1
    assert stats["dropped"] == 0
    ids = [t["ticket_id"] for t in out[0]["tickets"]]
    assert ids == ["keep-line-move", "keep-missing-prop"]
    legs = out[0]["tickets"][0]["legs"]
    assert legs[0]["line"] == 18.5
    assert legs[1]["line"] == 3.5


def test_patch_mixer_keeps_leg_when_sport_not_fetched():
    from build_goblin70_tickets import patch_mixer_groups

    groups = [
        {
            "group_name": "TENNIS 2-Leg Goblin OVER",
            "tickets": [
                {
                    "ticket_id": "tennis-1",
                    "legs": [
                        {
                            "sport": "TENNIS",
                            "player": "Qinwen Zheng",
                            "prop_type": "Total Games",
                            "pick_type": "Goblin",
                            "direction": "OVER",
                            "line": 18.5,
                        }
                    ],
                }
            ],
        }
    ]
    board = [
        {
            "sport": "MLB",
            "player": "Gerrit Cole",
            "prop": "Pitcher Strikeouts",
            "pick_type": "Goblin",
            "side": "OVER",
            "line": 3.5,
        }
    ]
    out, stats = patch_mixer_groups(groups, board)
    assert stats["dropped"] == 0
    assert stats["unchanged"] == 1
    assert out[0]["tickets"][0]["legs"][0]["line"] == 18.5
