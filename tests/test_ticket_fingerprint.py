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
