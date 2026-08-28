"""Ticket seed tiers: L5=5+D → L5=4+D → L5>=4 no-D."""
from __future__ import annotations

import pandas as pd
from utils.best_props_pool import (
    SEED_TIER_L5_4_D,
    SEED_TIER_L5_5_D,
    SEED_TIER_L5_NO_D,
    _seed_tier,
    annotate_best_props_pool,
    prefer_best_props_seed,
)


def test_seed_tier_ordering():
    assert _seed_tier(5, True) == SEED_TIER_L5_5_D
    assert _seed_tier(4, True) == SEED_TIER_L5_4_D
    assert _seed_tier(5, False) == SEED_TIER_L5_NO_D
    assert _seed_tier(4, False) == SEED_TIER_L5_NO_D
    assert _seed_tier(3, True) == 99


def _row(**kw):
    base = {
        "sport": "MLB",
        "player": "A",
        "prop_type": "Hits",
        "pick_type": "Goblin",
        "direction": "OVER",
        "model_dir": "OVER",
        "line": 0.5,
        "season_avg": 1.5,
        "l5_over": 4,
        "l5_under": 1,
        "def_tier": "Weak",
        "opponent_def_rank": 20,
        "OVERALL_DEF_RANK": 20,
    }
    base.update(kw)
    return base


def test_prefer_seed_orders_l5_5_d_first():
    df = pd.DataFrame(
        [
            _row(player="NoD4", l5_over=4, def_tier="Elite", opponent_def_rank=2, OVERALL_DEF_RANK=2),
            _row(player="D4", l5_over=4, def_tier="Weak", opponent_def_rank=25, OVERALL_DEF_RANK=25),
            _row(player="D5", l5_over=5, def_tier="Weak", opponent_def_rank=28, OVERALL_DEF_RANK=28),
            _row(player="NoD5", l5_over=5, def_tier="Avg", opponent_def_rank=15, OVERALL_DEF_RANK=15),
        ]
    )
    # Expand n_teams signal
    df["OVERALL_DEF_RANK"] = [2, 25, 28, 15]
    out = prefer_best_props_seed(df, prefer_gold_silver=False, min_preferred=1)
    assert list(out["player"])[:3] == ["D5", "D4", "NoD5"] or list(out["player"])[0] == "D5"
    ann = annotate_best_props_pool(df)
    tiers = dict(zip(ann["player"], ann["best_props_seed_tier"]))
    assert tiers["D5"] == SEED_TIER_L5_5_D
    assert tiers["D4"] == SEED_TIER_L5_4_D
    assert tiers["NoD5"] == SEED_TIER_L5_NO_D
    assert tiers["NoD4"] == SEED_TIER_L5_NO_D
