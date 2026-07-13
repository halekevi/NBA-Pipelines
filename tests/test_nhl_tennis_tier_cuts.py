"""NHL/Tennis sport-specific ml_prob tier cuts."""
from __future__ import annotations

from utils.group_rank_tier import (
    SPORT_ML_PROB_CUTS,
    SPORT_STANDARD_DIRECTION_CUTS,
    _resolve_ml_prob_cuts,
    _resolve_standard_direction_cuts,
)


def test_nhl_and_tennis_have_sport_cuts():
    assert "nhl" in SPORT_ML_PROB_CUTS
    assert "tennis" in SPORT_ML_PROB_CUTS
    nhl_g = SPORT_ML_PROB_CUTS["nhl"]["goblin"]
    assert nhl_g[0] < 0.5  # compressed vs NBA default 0.71
    ten_g = SPORT_ML_PROB_CUTS["tennis"]["goblin"]
    assert ten_g[0] <= 0.65
    assert _resolve_ml_prob_cuts("nhl", "goblin") == nhl_g


def test_resolve_nhl_standard_under_uses_direction_cuts():
    cuts = _resolve_standard_direction_cuts("nhl", "UNDER")
    assert cuts == SPORT_STANDARD_DIRECTION_CUTS["nhl"]["UNDER"]
