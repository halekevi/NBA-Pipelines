"""Ticket fingerprint used for Placed checkboxes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import combined_slate_tickets as m


def test_ticket_fingerprint_sorts_and_normalizes():
    legs = [
        {"player": "Jackie Young", "prop_type": "Assists", "line": 5.5, "direction": "OVER"},
        {"player": "A'ja Wilson", "prop_type": "Points", "line": 22.5, "direction": "LOWER"},
    ]
    fp = m._ticket_fingerprint(legs)
    assert "a'ja wilson|points|22.5|UNDER" in fp
    assert "jackie young|assists|5.5|OVER" in fp
    assert fp == ";".join(sorted(fp.split(";")))


def test_group_is_goblin70_from_name_and_track():
    assert m._group_is_goblin70({"group_name": "X-Sport Goblin-70 Power 3"}, "X-Sport Goblin-70 Power 3")
    assert m._group_is_goblin70({"group_name": "NFL Power 3"}, "NFL Power 3")
    assert m._group_is_goblin70(
        {"group_name": "WNBA Power 3", "tickets": [{"ticket_track": "goblin70"}]},
        "WNBA Power 3",
    )
    assert not m._group_is_goblin70(
        {"group_name": "MLB Core Power 2 #3", "tickets": [{"ticket_track": "graded_main"}]},
        "MLB Core Power 2 #3",
    )


def test_tickets_html_keeps_goblin70_visible_when_skip():
    payload = {
        "date": "2026-08-28",
        "generated_at": "2026-08-28 14:41:26 UTC",
        "groups": [
            {
                "group_name": "X-Sport Goblin-70 Power 3",
                "n_legs": 3,
                "power_payout": 2.0,
                "tickets": [
                    {
                        "ticket_id": "g70-1",
                        "ticket_no": 1,
                        "ticket_track": "goblin70",
                        "est_win_prob": 0.34,
                        "ev_power": -0.11,
                        "payout": {"recommendation": "SKIP", "ev": -0.11, "p_all_win": 0.34},
                        "legs": [
                            {
                                "sport": "MLB",
                                "player": "Zach Neto",
                                "prop_type": "Total Bases",
                                "pick_type": "Goblin",
                                "direction": "OVER",
                                "line": 0.5,
                            }
                        ],
                    }
                ],
            },
            {
                "group_name": "MLB Core Power 2 #3",
                "n_legs": 2,
                "power_payout": 1.8,
                "tickets": [
                    {
                        "ticket_id": "core-1",
                        "ticket_no": 1,
                        "ticket_track": "graded_main",
                        "est_win_prob": 0.52,
                        "ev_power": 0.37,
                        "payout": {"recommendation": "OK", "ev": 0.37, "p_all_win": 0.52},
                        "legs": [
                            {
                                "sport": "MLB",
                                "player": "Lawrence Butler",
                                "prop_type": "Hits+Runs+RBIs",
                                "pick_type": "Goblin",
                                "direction": "OVER",
                                "line": 0.5,
                            }
                        ],
                    }
                ],
            },
        ],
    }
    html, _title = m.render_tickets_body_html(payload)
    assert 'data-track="goblin70"' in html
    assert "function isGoblin70" in html
    assert "if(hideSkip && !isGoblin70(g))" in html
    assert "if(isGoblin70(group)) return true;" in html


def test_tickets_render_does_not_import_mixer():
    import sys

    sys.modules.pop("utils.tickets_render", None)
    sys.modules.pop("combined_slate_tickets", None)
    sys.modules.pop("scripts.combined_slate_tickets", None)
    import utils.tickets_render as tr

    assert "combined_slate_tickets" not in sys.modules
    html, title = tr.render_tickets_body_html(
        {
            "date": "2026-08-31",
            "generated_at": "2026-08-31 19:00:00 UTC",
            "mode": "goblin70+graded_main",
            "groups": [],
        }
    )
    assert "PROP" in html
    assert "Tickets" in title
