"""Unit tests for verify_ticket_payout_rates helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_ticket_payout_rates as v  # noqa: E402


def test_parse_delta_blob_handles_char_sploded_and_joined():
    assert v._parse_delta_blob("1+1.5") == [1.0, 1.5]
    assert v._parse_delta_blob("1,2") == [1.0, 2.0]
    assert v._parse_delta_blob(["1", ",", "1"]) == [1.0, 1.0]
    assert v._parse_delta_blob([1.5, 2.0]) == [1.5, 2.0]
    assert v._parse_delta_blob("") == []


def test_ticket_recipe_goblin_delta_from_standard_line():
    ticket = {
        "legs": [
            {"pick_type": "Standard", "line": 20.5},
            {
                "pick_type": "Goblin",
                "line": 18.5,
                "standard_line": 20.5,
            },
        ]
    }
    recipe = v.ticket_recipe(ticket)
    assert recipe["composition"] == "1S+1G+0D"
    assert recipe["goblin_delta_sig"] == "2"
    assert recipe["missing_goblin_delta"] == 0


def test_audit_flags_missing_live_and_outstanding_extrapolated():
    tickets = [
        {
            "ticket_id": "t1",
            "group_name": "MAIN",
            "strong_builder": False,
            "n_legs": 2,
            "composition": "1S+1G+0D",
            "n_standard": 1,
            "n_goblin": 1,
            "n_demon": 0,
            "goblin_delta_sig": "1.5",
            "demon_delta_sig": "—",
            "missing_goblin_delta": 0,
            "payout_source": "mix_grid_average",
            "display_min_x": 2.4,
            "has_live_cdp": False,
        },
        {
            "ticket_id": "t2",
            "group_name": "STRONG",
            "strong_builder": True,
            "n_legs": 2,
            "composition": "2S+0G+0D",
            "n_standard": 2,
            "n_goblin": 0,
            "n_demon": 0,
            "goblin_delta_sig": "—",
            "demon_delta_sig": "—",
            "missing_goblin_delta": 0,
            "payout_source": "live_cdp",
            "display_min_x": 3.0,
            "has_live_cdp": True,
        },
    ]
    live_index = {(2, "2S+0G+0D", "—"): [3.0]}
    rate_index = {
        (2, "1S+1G+0D", "1.5"): {
            "source": "extrapolated",
            "status": "extrapolated",
            "power_min_x": 2.5,
        },
        (2, "2S+0G+0D", "—"): {
            "source": "live_cdp",
            "status": "observed",
            "power_min_x": 3.0,
        },
    }
    audit = v.audit_tickets(tickets, live_index, rate_index)
    assert audit["n_missing_live_cdp"] == 1
    assert audit["missing_live_cdp"][0]["ticket_id"] == "t1"
    assert audit["n_outstanding_rates"] >= 1
    assert any(r["ticket_id"] == "t1" for r in audit["outstanding_rates"])


def test_load_ticket_rows_reads_groups(tmp_path: Path):
    path = tmp_path / "tickets.json"
    path.write_text(
        json.dumps(
            {
                "date": "2026-07-13",
                "groups": [
                    {
                        "group_name": "STRONG Goblin HOT",
                        "tickets": [
                            {
                                "ticket_id": "abc",
                                "strong_builder": True,
                                "payout": {
                                    "payout_source": "live_cdp",
                                    "display_min_x": 4.0,
                                    "power_min_x": 4.0,
                                },
                                "legs": [
                                    {
                                        "player": "A",
                                        "prop_type": "Points",
                                        "pick_type": "Goblin",
                                        "line": 18.5,
                                        "standard_line": 20.5,
                                    },
                                    {
                                        "player": "B",
                                        "prop_type": "Assists",
                                        "pick_type": "Goblin",
                                        "line": 4.5,
                                        "standard_line": 5.5,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rows = v.load_ticket_rows(path)
    assert len(rows) == 1
    assert rows[0]["has_live_cdp"] is True
    assert rows[0]["composition"] == "0S+2G+0D"
    assert rows[0]["goblin_delta_sig"] == "1+2"
