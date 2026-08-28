"""No duplicate players on a ticket — including combo arms."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_ticket_eval import _filter_payload_groups  # noqa: E402
from combined_slate_tickets import (  # noqa: E402
    _player_name_atoms,
    _ticket_players_unique,
)


def test_player_atoms_split_combo():
    assert _player_name_atoms("Carla Leite") == ["carla leite"]
    atoms = _player_name_atoms("Mike Maignan + Unai Simón")
    assert "mike maignan" in atoms
    assert "unai simon" in atoms or "unai simón" in atoms or len(atoms) == 2


def test_ticket_rejects_same_player_two_props():
    rows = [
        {"player": "Carla Leite", "prop_type": "Pts+Rebs"},
        {"player": "Carla Leite", "prop_type": "Rebs+Asts"},
        {"player": "Emily Engstler", "prop_type": "Rebounds"},
    ]
    assert _ticket_players_unique(rows) is False


def test_ticket_rejects_combo_arm_plus_solo():
    rows = [
        {"player": "Kylian Mbappé + Lamine Yamal + Lionel Messi"},
        {"player": "Mike Maignan + Unai Simón"},
        {"player": "Mike Maignan"},
    ]
    assert _ticket_players_unique(rows) is False


def test_ticket_allows_distinct_players():
    rows = [
        {"player": "Emily Engstler"},
        {"player": "Carla Leite"},
        {"player": "Allisha Gray"},
    ]
    assert _ticket_players_unique(rows) is True


def test_filter_drops_duplicate_player_tickets_from_grades():
    def leg(player: str, prop: str, line: float = 5.5) -> dict:
        return {
            "sport": "WNBA",
            "player": player,
            "prop_type": prop,
            "direction": "OVER",
            "line": line,
            "pick_type": "Goblin",
            "team": "DAL",
            "opp": "LAS",
        }

    payload = {
        "date": "2026-07-14",
        "pool_mode": "goblin_only_3leg",
        "groups": [
            {
                "group_name": "WNBA 3-Leg Goblin",
                "tickets": [
                    {
                        "ticket_no": 1,
                        "legs": [
                            leg("Emily Engstler", "Rebounds"),
                            leg("Carla Leite", "Pts+Rebs", 14.5),
                            leg("Carla Leite", "Rebs+Asts", 6.5),
                        ],
                    },
                    {
                        "ticket_no": 2,
                        "legs": [
                            leg("Emily Engstler", "Rebounds"),
                            leg("Allisha Gray", "Assists"),
                            leg("Alyssa Thomas", "Points", 12.5),
                        ],
                    },
                ],
            }
        ],
    }
    out = _filter_payload_groups(payload)
    tix = (out.get("groups") or [{}])[0].get("tickets") or []
    assert len(tix) == 1
    assert [x["player"] for x in tix[0]["legs"]] == [
        "Emily Engstler",
        "Allisha Gray",
        "Alyssa Thomas",
    ]
