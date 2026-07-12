"""Live CDP captures must feed /payout/ladder Goblin composition rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import collect_payout_data as cpd  # noqa: E402


def test_sync_captures_to_ladder_live(tmp_path, monkeypatch):
    monkeypatch.setattr(cpd, "PAYOUT_LADDER_LIVE_CDP_PATH", tmp_path / "payout_ladder_live_cdp.json")
    captured = [
        {
            "status": "ok",
            "ticket_id": "d|STRONG|1",
            "n_legs": 2,
            "power_min_x": 2.6,
            "legs": [
                {"player": "A", "prop_type": "Ast", "pick_type": "Goblin", "line_distance": 1.0, "sport": "WNBA"},
                {"player": "B", "prop_type": "Reb", "pick_type": "Goblin", "line_distance": 1.5, "sport": "WNBA"},
            ],
        },
        {
            "status": "ok",
            "ticket_id": "d|STRONG|1",
            "n_legs": 2,
            "power_min_x": 2.8,
            "legs": [
                {"player": "A", "prop_type": "Ast", "pick_type": "Goblin", "line_distance": 1.0, "sport": "WNBA"},
                {"player": "C", "prop_type": "Reb", "pick_type": "Goblin", "line_distance": 2.0, "sport": "WNBA"},
            ],
        },
    ]
    out = cpd.sync_captures_to_payout_ladder_live(captured, date_str="2026-07-12")
    assert len(out["rows"]) == 2
    assert out["rows"][0]["leg_composition"] == "0S+2G+0D"
    assert out["rows"][0]["source"] == "live_cdp"
    assert float(out["rows"][0]["power_payout_x"]) == 2.6

    # Re-sync same date replaces rows for that date only.
    cpd.sync_captures_to_payout_ladder_live(captured[:1], date_str="2026-07-12")
    data = json.loads((tmp_path / "payout_ladder_live_cdp.json").read_text(encoding="utf-8"))
    assert len(data["rows"]) == 1
