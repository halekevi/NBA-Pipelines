#!/usr/bin/env python3
"""POSTPONED is a distinct result from VOID but settles like VOID for tickets."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from grading.leg_grade_utils import leg_grade_for_ticket_eval  # noqa: E402


def test_postponed_result_settles_as_void():
    assert (
        leg_grade_for_ticket_eval(None, 10.5, "OVER", "POSTPONED", "POSTPONED · NY @ DAL")
        == "VOID"
    )
    assert (
        leg_grade_for_ticket_eval(None, 10.5, "OVER", "VOID", "POSTPONED · NY @ DAL")
        == "VOID"
    )


def test_pending_no_actual_stays_ungraded():
    assert leg_grade_for_ticket_eval(None, 10.5, "UNDER", "VOID", "NO_ACTUAL") == "UNGRADED"
