"""Soccer combo legs stay PENDING while an arm's nation game is not in actuals."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_ticket_eval import _canon_void_note  # noqa: E402
from grading.leg_grade_utils import leg_grade_for_ticket_eval  # noqa: E402
from soccer_grader_advanced import (  # noqa: E402
    _soccer_missing_actual_reason,
    build_soccer_actuals_lookup,
    lookup_soccer_actual_combo,
)


def _lut_fra_esp_shots():
    import pandas as pd

    rows = [
        {"player": "Kylian Mbappé", "team": "FRA", "prop_type": "Shots", "actual": 3.0},
        {"player": "Lamine Yamal", "team": "ESP", "prop_type": "Shots", "actual": 0.0},
        {
            "player": "Kylian Mbappé",
            "team": "FRA",
            "prop_type": "Shots On Target",
            "actual": 0.0,
        },
        {
            "player": "Lamine Yamal",
            "team": "ESP",
            "prop_type": "Shots On Target",
            "actual": 0.0,
        },
    ]
    return build_soccer_actuals_lookup(pd.DataFrame(rows))


def test_three_nation_combo_pending_while_argentina_missing():
    lut = _lut_fra_esp_shots()
    player = "Kylian Mbappé + Lamine Yamal + Lionel Messi"
    team = "FRANCE/SPAIN/ARGENTINA"
    assert np.isnan(lookup_soccer_actual_combo(lut, player, "Shots (Combo)", team))
    assert (
        _soccer_missing_actual_reason(lut, player, "Shots (Combo)", team) == "PENDING"
    )


def test_two_player_combo_grades_when_both_nations_posted():
    lut = _lut_fra_esp_shots()
    actual = lookup_soccer_actual_combo(
        lut,
        "Lamine Yamal + Kylian Mbappé",
        "Shots (Combo)",
        "SPAIN/FRANCE",
    )
    assert actual == 3.0


def test_ticket_eval_pending_reason_stays_ungraded():
    assert (
        leg_grade_for_ticket_eval(None, 10.5, "UNDER", "PENDING", "PENDING")
        == "UNGRADED"
    )
    assert _canon_void_note({"reason": "PENDING"}) == "PENDING"
    assert _canon_void_note({"reason": "NO_DATA"}) == "NO_DATA"
    # Do not treat grader prose as a void cause.
    assert _canon_void_note({"reason": "Missed by 1.0 despite high confidence"}) == ""
