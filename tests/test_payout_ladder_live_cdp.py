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
            "captured_at": "2026-08-27T08:05:00-04:00",
            "legs": [
                {
                    "player": "A",
                    "prop_type": "Ast",
                    "pick_type": "Goblin",
                    "line_distance": 1.0,
                    "sport": "WNBA",
                    "event_start_time": "2099-01-01T00:00:00+00:00",
                },
                {
                    "player": "B",
                    "prop_type": "Reb",
                    "pick_type": "Goblin",
                    "line_distance": 1.5,
                    "sport": "WNBA",
                    "event_start_time": "2099-01-01T00:00:00+00:00",
                },
            ],
        },
        {
            "status": "ok",
            "ticket_id": "d|STRONG|1",
            "n_legs": 2,
            "power_min_x": 2.8,
            "captured_at": "2026-08-27T16:32:00-04:00",
            "legs": [
                {
                    "player": "A",
                    "prop_type": "Ast",
                    "pick_type": "Goblin",
                    "line_distance": 1.0,
                    "sport": "WNBA",
                    "event_start_time": "2099-01-01T00:00:00+00:00",
                },
                {
                    "player": "C",
                    "prop_type": "Reb",
                    "pick_type": "Goblin",
                    "line_distance": 2.0,
                    "sport": "WNBA",
                    "event_start_time": "2099-01-01T00:00:00+00:00",
                },
            ],
        },
    ]
    import utils.bet_windows as bw

    monkeypatch.setattr(bw, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(bw, "LINE_DB", tmp_path / "missing.db")
    out = cpd.sync_captures_to_payout_ladder_live(captured, date_str="2026-07-12")
    assert len(out["rows"]) == 2
    assert out["rows"][0]["leg_composition"] == "0S+2G+0D"
    assert out["rows"][0]["source"] == "live_cdp"
    assert float(out["rows"][0]["power_payout_x"]) == 2.6
    assert out["rows"][0]["captured_at"]
    gd = out["rows"][0]["goblin_deltas"]
    if isinstance(gd, list):
        gd = ",".join(str(x) for x in gd)
    assert str(gd).replace(".0", "") in ("1,1.5", "1.5,1")

    # Re-sync a subset keeps prior same-date rows (movement history).
    cpd.sync_captures_to_payout_ladder_live(captured[:1], date_str="2026-07-12")
    data = json.loads((tmp_path / "payout_ladder_live_cdp.json").read_text(encoding="utf-8"))
    assert len(data["rows"]) == 2

    # Explicit wipe still replaces the date.
    cpd.sync_captures_to_payout_ladder_live(
        captured[:1], date_str="2026-07-12", keep_same_date=False
    )
    data = json.loads((tmp_path / "payout_ladder_live_cdp.json").read_text(encoding="utf-8"))
    assert len(data["rows"]) == 1


def test_capture_row_computes_distance_from_standard_line():
    row = cpd._capture_to_ladder_row(
        {
            "status": "ok",
            "ticket_id": "x",
            "power_min_x": 2.4,
            "legs": [
                {"player": "A", "prop_type": "Pts", "pick_type": "Goblin", "line": 16.5, "standard_line": 20.5},
                {"player": "B", "prop_type": "Reb", "pick_type": "Goblin", "line": 5.5, "standard_line": 7.5},
            ],
            "captured_at": "2026-07-12T10:30:00-04:00",
        },
        "2026-07-12",
    )
    assert row is not None
    assert row["goblin_deltas"] in ("2,4", ["2", "4"])
    assert row["captured_at"] == "2026-07-12T10:30:00-04:00"
    assert row["window"] == "10:30"
