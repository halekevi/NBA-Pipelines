"""N-correct lookup: slip pin, same-day CDP, mix_by_delta, fallback."""
from __future__ import annotations

import json
from pathlib import Path

from utils.n_correct_payout import (
    goblin_delta_sig,
    resolve_n_correct,
)


def test_override_beats_fallback(tmp_path: Path):
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    payload = {
        "date": "2026-08-27",
        "entries": [
            {
                "n_legs": 3,
                "n_s": 0,
                "n_g": 3,
                "product": "Power",
                "n_correct": {"3": 2.0},
                "note": "slip pin 2x",
            }
        ],
    }
    (reports / "payout_overrides_2026-08-27.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    legs = [
        {"pick_type": "Goblin", "line": 3.5, "standard_line": 5.5, "p": 0.76},
        {"pick_type": "Goblin", "line": 2.5, "standard_line": 5.0, "p": 0.76},
        {"pick_type": "Goblin", "line": 1.5, "standard_line": 3.5, "p": 0.76},
    ]
    got = resolve_n_correct(legs, "Power", "goblin", date="2026-08-27", repo=tmp_path)
    assert got["n_correct"][3] == 2.0
    assert got["payout_source"] == "n_correct_live"
    other = resolve_n_correct(legs, "Power", "goblin", date="2026-08-26", repo=tmp_path)
    assert other["payout_source"] == "n_correct_median"
    assert other["n_correct"][3] == 2.0


def test_same_day_cdp_matches_delta(tmp_path: Path):
    live = tmp_path / "ui_runner" / "data"
    live.mkdir(parents=True)
    (live / "payout_ladder_live_cdp.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "date": "2026-08-27",
                        "n_legs": "3",
                        "leg_composition": "0S+3G+0D",
                        "goblin_deltas": ["2", "2.5", "2"],
                        "power_payout_x": "2.0",
                        "source": "live_cdp",
                        "ticket_id": "z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    legs = [
        {"pick_type": "Goblin", "line": 3.5, "standard_line": 5.5, "p": 0.76},
        {"pick_type": "Goblin", "line": 2.5, "standard_line": 5.0, "p": 0.76},
        {"pick_type": "Goblin", "line": 1.5, "standard_line": 3.5, "p": 0.76},
    ]
    assert goblin_delta_sig(legs) == "2+2+2.5"
    got = resolve_n_correct(legs, "Power", "goblin", date="2026-08-27", repo=tmp_path)
    assert got["n_correct"][3] == 2.0
    assert got["payout_source"] == "n_correct_live"


def test_mix_by_delta_when_no_pin(tmp_path: Path):
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    (reports / "predicted_payout_tables_latest.json").write_text(
        json.dumps(
            {
                "mix_by_delta": [
                    {
                        "n_legs": 3,
                        "n_s": 0,
                        "n_g": 3,
                        "composition": "0S+3G",
                        "goblin_delta_sig": "2+2+2.5",
                        "power_x": 2.1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    legs = [
        {"pick_type": "Goblin", "line": 3.5, "standard_line": 5.5, "p": 0.76},
        {"pick_type": "Goblin", "line": 2.5, "standard_line": 5.0, "p": 0.76},
        {"pick_type": "Goblin", "line": 1.5, "standard_line": 3.5, "p": 0.76},
    ]
    got = resolve_n_correct(legs, "Power", "goblin", date="2026-08-20", repo=tmp_path)
    assert got["n_correct"][3] == 2.1
    assert got["payout_source"] == "n_correct_delta"
