"""Smoke tests for daily MAIN MLB construction hit-rate monitor."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import daily_main_mlb_construction_check as mon  # noqa: E402


def test_gap_helper():
    assert mon._gap(57.1, 57.1) == 0.0
    assert mon._gap(61.3, 57.1) == 4.2
    assert mon._gap(None, 57.1) is None


def test_mlb_touching():
    assert mon._mlb_touching([{"sport": "WNBA"}]) is False
    assert mon._mlb_touching([{"sport": "MLB"}, {"sport": "WNBA"}]) is True
