"""Regression: duplicate group ticket_no must not steal another slip's RESULT."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_ticket_eval import _ticket_eval_money_outcome, _ticket_pays_money  # noqa: E402


def test_money_outcome_all_hit_is_win_for_power_style_group():
    gname = "WNBA 3-Leg Goblin"
    gs = ["HIT", "HIT", "HIT"]
    ticket = {
        "ticket_no": 1,
        "power_payout": 6.0,
        "flex_payout": 3.0,
        "legs": [{}, {}, {}],
        "payout": {"payout": 6.0, "sweep_payout": 6.0},
    }
    assert _ticket_pays_money(gname, gs) is True
    oc = _ticket_eval_money_outcome(gname, gs, ticket)
    assert oc.get("pending") is False
    assert oc.get("result") in ("WIN", "SWEEP")
    assert float(oc.get("actual_payout") or 0) > 0


def test_power_void_pays_as_reduced_leg_tier_not_original_scrape():
    """PrizePicks: void drops the leg; 3-leg with 1 void + 2 hits pays as 2-leg."""
    from build_ticket_eval import _effective_power_multiplier  # noqa: E402

    gname = "MLB 3-Leg Goblin"
    gs = ["HIT", "HIT", "VOID"]
    legs = [{"pick_type": "Goblin"}, {"pick_type": "Goblin"}, {"pick_type": "Goblin"}]
    banner = 6.0
    ticket = {
        "ticket_no": 1,
        "power_payout": banner,
        "flex_payout": 3.0,
        "legs": legs,
        # Original 3-leg scrape must NOT win over reduced-tier math.
        "payout": {"payout": 6.0, "min_guarantee": 6.0, "sweep_payout": 6.0},
    }
    assert _ticket_pays_money(gname, gs) is True
    expected = _effective_power_multiplier(legs, gs, banner, 3)
    assert expected is not None and expected < banner
    oc = _ticket_eval_money_outcome(gname, gs, ticket)
    assert oc.get("result") == "WIN"
    assert oc.get("effective_legs") == 2
    assert oc.get("void_dropped_legs") == 1
    assert abs(float(oc.get("actual_payout") or 0) - float(expected)) < 1e-9


def test_power_void_with_remaining_miss_is_loss_not_void_fail():
    """A miss among remaining legs loses; the void itself is not the miss."""
    gname = "MLB 3-Leg Goblin"
    gs = ["HIT", "MISS", "VOID"]
    ticket = {
        "ticket_no": 1,
        "power_payout": 6.0,
        "legs": [{"pick_type": "Goblin"}] * 3,
        "payout": {"payout": 6.0},
    }
    assert _ticket_pays_money(gname, gs) is False
    oc = _ticket_eval_money_outcome(gname, gs, ticket)
    assert oc.get("result") == "LOSS"


def test_void_below_two_legs_is_refund_not_loss():
    gname = "MLB 3-Leg Goblin"
    gs = ["HIT", "VOID", "VOID"]
    ticket = {
        "ticket_no": 1,
        "power_payout": 6.0,
        "legs": [{"pick_type": "Goblin"}] * 3,
        "payout": {"payout": 6.0},
    }
    assert _ticket_pays_money(gname, gs) is False
    oc = _ticket_eval_money_outcome(gname, gs, ticket)
    assert oc.get("result") == "VOID_LOSS"
    assert "REFUND" in str(oc.get("result_display") or "")
    assert float(oc.get("actual_payout") or 0) == 0.0


def test_no_actual_resolves_to_void_for_all_sports():
    from build_ticket_eval import _resolve_void_pending_if_injury_dnp  # noqa: E402

    for sport, player, team, prop in (
        ("MLB", "Bobby Witt Jr.", "KC", "Hits"),
        ("WNBA", "Caitlin Clark", "IND", "Points"),
        ("NBA", "LeBron James", "LAL", "Rebounds"),
        ("NBA1H", "LeBron James", "LAL", "Points"),
        ("NBA1Q", "LeBron James", "LAL", "Points"),
        ("NHL", "Connor McDavid", "EDM", "Hits"),
        ("SOCCER", "Lionel Messi", "MIA", "Shots"),
        ("TENNIS", "Carlos Alcaraz", "", "Aces"),
        ("NFL", "Patrick Mahomes", "KC", "Passing Yards"),
        ("CFB", "Caleb Williams", "USC", "Passing Yards"),
        ("CBB", "Zach Edey", "PUR", "Points"),
        ("WCBB", "Caitlin Clark", "IOWA", "Points"),
    ):
        leg = {"sport": sport, "player": player, "team": team, "prop_type": prop}
        assert (
            _resolve_void_pending_if_injury_dnp(
                "UNGRADED",
                leg,
                None,
                0.5,
                "VOID",
                "NO_ACTUAL",
                {},
            )
            == "VOID"
        ), sport


def test_power_goblin_all_hit_uses_scraped_min_not_classic_sweep():
    """3-leg Goblin Power must not grade Actual at Fantasy 6x when min lock is ~1.6x."""
    gname = "WNBA 3-Leg Goblin"
    gs = ["HIT", "HIT", "HIT"]
    ticket = {
        "ticket_no": 1,
        "power_payout": 1.76,
        "flex_payout": 0.88,
        "display_min_x": 1.6,
        "legs": [{"pick_type": "Goblin"}, {"pick_type": "Goblin"}, {"pick_type": "Goblin"}],
        "payout": {
            "payout": 1.6,
            "min_guarantee": 1.6,
            "display_min_x": 1.6,
            "sweep_payout": 6.0,
        },
    }
    oc = _ticket_eval_money_outcome(gname, gs, ticket)
    assert oc.get("result") == "WIN"
    actual = float(oc.get("actual_payout") or 0)
    assert abs(actual - 1.6) < 1e-9
    assert abs(float(oc.get("entry_10_return") or 0) - 16.0) < 1e-6


def test_power_goblin_5leg_rejects_fantasy_20x_when_min_lock_exists():
    """Long Goblin parlays must not Actual at Standard 20x when scrape/min is ~4.5x."""
    gname = "WNBA Goblin 5-Leg #1"
    gs = ["HIT"] * 5
    ticket = {
        "ticket_no": 1,
        "power_payout": 4.37,
        "flex_payout": 2.18,
        "legs": [{"pick_type": "Goblin"} for _ in range(5)],
        "payout": {
            "payout": 4.5,
            "min_guarantee": 4.5,
            "display_min_x": 20.0,  # poisoned Standard tier must not win
            "sweep_payout": 20.0,
        },
    }
    oc = _ticket_eval_money_outcome(gname, gs, ticket)
    assert oc.get("result") == "WIN"
    actual = float(oc.get("actual_payout") or 0)
    assert abs(actual - 4.5) < 1e-9
    assert abs(float(oc.get("predicted_payout") or 0) - 4.5) < 1e-9


def test_power_goblin_6leg_rejects_fantasy_37_5x():
    gname = "WNBA Goblin 6-Leg #1"
    gs = ["HIT"] * 6
    ticket = {
        "ticket_no": 1,
        "power_payout": 5.59,
        "flex_payout": 3.49,
        "legs": [{"pick_type": "Goblin"} for _ in range(6)],
        "payout": {
            "payout": 5.59,
            "min_guarantee": 5.59,
            "sweep_payout": 37.5,
            "first_place": 40.0,
        },
    }
    oc = _ticket_eval_money_outcome(gname, gs, ticket)
    assert oc.get("result") == "WIN"
    assert abs(float(oc.get("actual_payout") or 0) - 5.59) < 1e-9


def test_flex_all_hit_uses_min_guarantee_not_sweep():
    """Flex all-hit must also lock to scraped min-guarantee (site policy)."""
    gname = "WNBA 5-Leg Flex"
    gs = ["HIT"] * 5
    ticket = {
        "ticket_no": 1,
        "power_payout": 10.0,
        "flex_payout": 2.0,
        "legs": [{"pick_type": "Standard"} for _ in range(5)],
        "payout": {
            "payout": 2.15,
            "min_guarantee": 2.15,
            "display_min_x": 2.15,
            "sweep_payout": 10.0,
        },
    }
    oc = _ticket_eval_money_outcome(gname, gs, ticket)
    assert oc.get("result") == "WIN"
    assert abs(float(oc.get("actual_payout") or 0) - 2.15) < 1e-9


def test_duplicate_ticket_no_outcomes_stay_on_ticket_object():
    """Simulate map collision that used to paint ALL-HIT slips as LOSS."""
    gname = "WNBA 3-Leg Goblin"
    t_win = {
        "ticket_no": 1,
        "_group_name": gname,
        "power_payout": 6.0,
        "flex_payout": 3.0,
        "legs": [{}, {}, {}],
        "payout": {"payout": 6.0, "sweep_payout": 6.0},
        "_leg_grades_cache": ["HIT", "HIT", "HIT"],
    }
    t_loss = {
        "ticket_no": 1,
        "_group_name": gname,
        "power_payout": 6.0,
        "flex_payout": 3.0,
        "legs": [{}, {}, {}],
        "payout": {"payout": 6.0, "sweep_payout": 6.0},
        "_leg_grades_cache": ["HIT", "MISS", "MISS"],
    }
    t_win["_money_outcome"] = _ticket_eval_money_outcome(
        gname, t_win["_leg_grades_cache"], t_win
    )
    t_loss["_money_outcome"] = _ticket_eval_money_outcome(
        gname, t_loss["_leg_grades_cache"], t_loss
    )
    # Old broken key would overwrite; per-ticket storage must keep both.
    assert t_win["_money_outcome"]["result"] in ("WIN", "SWEEP")
    assert t_loss["_money_outcome"]["result"] == "LOSS"


def test_filter_drops_one_leg_strong_after_hygiene():
    from build_ticket_eval import _filter_payload_groups

    payload = {
        "date": "2026-07-13",
        "pool_mode": "goblin_only_3leg",
        "groups": [
            {
                "group_name": "STRONG Goblin HOT",
                "tickets": [
                    {
                        "ticket_no": 1,
                        "power_payout": 1.06,
                        "flex_payout": 1.06,
                        "legs": [
                            {
                                "sport": "WNBA",
                                "player": "Olivia Miles",
                                "prop_type": "Rebounds",
                                "direction": "OVER",
                                "line": 2.5,
                                "pick_type": "Goblin",
                            },
                            {
                                # Dropped: goblin/power boards disallow steals.
                                "sport": "WNBA",
                                "player": "Someone",
                                "prop_type": "Steals",
                                "direction": "OVER",
                                "line": 0.5,
                                "pick_type": "Goblin",
                            },
                        ],
                    },
                    {
                        "ticket_no": 2,
                        "power_payout": 1.5,
                        "flex_payout": 1.5,
                        "legs": [
                            {
                                "sport": "WNBA",
                                "player": "Olivia Miles",
                                "prop_type": "Rebounds",
                                "direction": "OVER",
                                "line": 2.5,
                                "pick_type": "Goblin",
                            },
                            {
                                "sport": "WNBA",
                                "player": "Allisha Gray",
                                "prop_type": "Assists",
                                "direction": "OVER",
                                "line": 1.5,
                                "pick_type": "Goblin",
                            },
                        ],
                    },
                ],
            }
        ],
    }
    out = _filter_payload_groups(payload)
    tix = (out.get("groups") or [{}])[0].get("tickets") or []
    assert len(tix) == 1
    assert len(tix[0]["legs"]) == 2


def test_coalesce_merges_duplicate_group_boards_and_renumbers():
    from build_ticket_eval import _filter_payload_groups

    payload = {
        "date": "2026-07-13",
        "pool_mode": "goblin_only_3leg",
        "groups": [
            {
                "group_name": "WNBA 3-Leg Goblin",
                "tickets": [
                    {
                        "ticket_no": 1,
                        "legs": [
                            {
                                "sport": "WNBA",
                                "player": "A",
                                "prop_type": "Assists",
                                "direction": "OVER",
                                "line": 1.5,
                                "team": "ATL",
                                "opp": "LAS",
                            },
                            {
                                "sport": "WNBA",
                                "player": "B",
                                "prop_type": "Assists",
                                "direction": "OVER",
                                "line": 2.5,
                                "team": "MIN",
                                "opp": "PHX",
                            },
                            {
                                "sport": "WNBA",
                                "player": "C",
                                "prop_type": "Assists",
                                "direction": "OVER",
                                "line": 3.5,
                                "team": "NYL",
                                "opp": "CHI",
                            },
                        ],
                    }
                ],
            },
            {
                "group_name": "WNBA 3-Leg Goblin",
                "tickets": [
                    {
                        "ticket_no": 1,
                        "legs": [
                            {
                                "sport": "WNBA",
                                "player": "D",
                                "prop_type": "Assists",
                                "direction": "OVER",
                                "line": 1.5,
                                "team": "ATL",
                                "opp": "LAS",
                            },
                            {
                                "sport": "WNBA",
                                "player": "E",
                                "prop_type": "Assists",
                                "direction": "OVER",
                                "line": 2.5,
                                "team": "MIN",
                                "opp": "PHX",
                            },
                            {
                                "sport": "WNBA",
                                "player": "F",
                                "prop_type": "Assists",
                                "direction": "OVER",
                                "line": 3.5,
                                "team": "NYL",
                                "opp": "CHI",
                            },
                        ],
                    }
                ],
            },
        ],
    }
    out = _filter_payload_groups(payload)
    groups = out.get("groups") or []
    assert len(groups) == 1
    tix = groups[0]["tickets"]
    assert len(tix) == 2
    assert [t["ticket_no"] for t in tix] == [1, 2]


def test_coalesce_duplicate_group_names_and_renumber():
    from build_ticket_eval import _filter_payload_groups

    leg = {
        "sport": "WNBA",
        "player": "A",
        "prop_type": "Assists",
        "direction": "OVER",
        "line": 2.5,
        "pick_type": "Goblin",
        "team": "ATL",
        "opp": "LAS",
    }
    leg2 = dict(leg, player="B")
    leg3 = dict(leg, player="C")
    payload = {
        "date": "2026-07-13",
        "pool_mode": "goblin_only_3leg",
        "groups": [
            {
                "group_name": "WNBA 3-Leg Goblin",
                "tickets": [
                    {"ticket_no": 1, "power_payout": 2.0, "flex_payout": 1.0, "legs": [leg, leg2, leg3]},
                ],
            },
            {
                "group_name": "WNBA 3-Leg Goblin",
                "tickets": [
                    {
                        "ticket_no": 1,
                        "power_payout": 2.1,
                        "flex_payout": 1.0,
                        "legs": [
                            dict(leg, player="D"),
                            dict(leg, player="E"),
                            dict(leg, player="F"),
                        ],
                    },
                ],
            },
        ],
    }
    out = _filter_payload_groups(payload)
    groups = out.get("groups") or []
    assert len(groups) == 1
    tix = groups[0]["tickets"]
    assert len(tix) == 2
    assert [t["ticket_no"] for t in tix] == [1, 2]
