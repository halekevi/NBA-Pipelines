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
