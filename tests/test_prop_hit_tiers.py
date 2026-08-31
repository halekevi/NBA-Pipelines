"""Shooting-prop canon and list-print leftover so FGA/FT/2s are not buried."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from prop_hit_tiers import assign_tier, canon_prop  # noqa: E402
from rank_best_props_today import _print_capped, print_sport  # noqa: E402


def test_cover_need_shooting_vs_pra():
    from prop_hit_tiers import cover_need

    assert cover_need("WNBA", "Pts+Rebs+Asts") == 3.7
    assert cover_need("WNBA", "FG Attempted") == 1.1
    assert cover_need("WNBA", "3-PT Made") == 0.7
    assert cover_need("WNBA", "Steals") == 2.0
    assert canon_prop("WNBA", "FG Attempted") == "fga"
    assert canon_prop("WNBA", "FG Made") == "fgm"
    assert canon_prop("WNBA", "3-PT Attempted") == "threes_att"
    assert canon_prop("WNBA", "3-PT Made") == "threes"
    assert canon_prop("WNBA", "Two Pointers Attempted") == "fg2a"
    assert canon_prop("WNBA", "Two Pointers Made") == "fg2m"
    assert canon_prop("WNBA", "Free Throws Attempted") == "fta"
    assert canon_prop("WNBA", "Free Throws Made") == "ftm"


def test_goblin_3pa_and_fga_not_default_c():
    threes_att = assign_tier(
        sport="WNBA", pick_type="Goblin", side="OVER", prop="3-PT Attempted"
    )
    fga = assign_tier(sport="WNBA", pick_type="Goblin", side="OVER", prop="FG Attempted")
    fg2a_u = assign_tier(
        sport="WNBA", pick_type="Standard", side="UNDER", prop="Two Pointers Attempted"
    )
    assert threes_att["prop_tier"] == "A"
    assert fga["prop_tier"] == "A"
    assert fg2a_u["prop_tier"] == "C"


def test_print_capped_names_cut_props(capsys):
    rows = [
        {"player": "A", "prop": "FG Attempted", "line": 10.5, "l5_over": 5, "l5_under": 0,
         "prop_tier": "D", "badge": "Bronze", "side": "OVER", "pick_type": "Standard",
         "def": "Avg", "season_avg": 11.0, "cover": 0.5, "avg_l5": 11.0, "avg_l10": 11.0,
         "checks": {}, "miss_s": "", "matchup": "ATL vs NY"},
        {"player": "B", "prop": "Points", "line": 18.5, "l5_over": 4, "l5_under": 1,
         "prop_tier": "D", "badge": "Bronze", "side": "OVER", "pick_type": "Standard",
         "def": "Avg", "season_avg": 19.0, "cover": 0.5, "avg_l5": 19.0, "avg_l10": 19.0,
         "checks": {}, "miss_s": "", "matchup": "ATL vs NY"},
    ]
    _print_capped(rows, "OVER", 1)
    out = capsys.readouterr().out
    assert "FG Attempted" in out
    assert "1 more L5≥4 not shown" in out
    assert "Points x1" in out


def test_print_sport_shows_all_goblin_fga(capsys):
    gob = []
    for i, prop in enumerate(["Points"] * 12 + ["FG Attempted", "3-PT Attempted"]):
        gob.append(
            {
                "player": f"P{i}",
                "prop": prop,
                "line": 9.5,
                "l5_over": 5,
                "l5_under": 0,
                "prop_tier": "A" if prop != "FG Attempted" else "B",
                "badge": "Silver",
                "promo": "Silver",
                "side": "OVER",
                "pick_type": "Goblin",
                "sport": "WNBA",
                "def": "Weak",
                "season_avg": 12.0,
                "cover": 2.5,
                "avg_l5": 12.0,
                "avg_l10": 12.0,
                "checks": {},
                "miss_s": "",
                "matchup": "ATL vs NY",
            }
        )
    print_sport("WNBA", [], [], gob)
    out = capsys.readouterr().out
    assert "FG Attempted" in out
    assert "3-PT Attempted" in out
