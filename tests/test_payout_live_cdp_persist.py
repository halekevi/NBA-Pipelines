"""Regression: live_cdp floors must survive empty re-scrape + board-avg attach."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import collect_payout_data as cpd  # noqa: E402
import combined_slate_tickets as cst  # noqa: E402


def _ticket(tid: str, min_x: float, source: str, *, line: float = 1.5) -> dict:
    return {
        "ticket_id": tid,
        "n_legs": 2,
        "legs": [
            {
                "player": "A Player",
                "prop_type": "Assists",
                "direction": "OVER",
                "line": line,
                "pick_type": "Goblin",
            },
            {
                "player": "B Player",
                "prop_type": "Rebounds",
                "direction": "OVER",
                "line": line + 1,
                "pick_type": "Goblin",
            },
        ],
        "payout": {
            "power_min_x": min_x if source == "live_cdp" else None,
            "display_min_x": min_x,
            "payout_source": source,
            "min_payout_x": 5.0,
            "model_min_payout_x": 5.0,
        },
        "display_min_x": min_x,
    }


def _payload(date: str, tickets: list[dict]) -> dict:
    return {
        "date": date,
        "generated_at": "2026-07-12 00:00:00 UTC",
        "groups": [{"name": "STRONG Goblin HOT", "tickets": tickets}],
    }


def test_attach_does_not_downgrade_live_cdp():
    t = _ticket("d|STRONG|1", 2.6, "live_cdp")
    # Simulate missing power_min_x (only display + source)
    t["payout"]["power_min_x"] = None
    out = cst.attach_display_min_x(t)
    assert out["payout"]["payout_source"] == "live_cdp"
    assert float(out["payout"]["display_min_x"]) == 2.6
    assert float(out["payout"]["power_min_x"]) == 2.6


def test_empty_capture_does_not_wipe_prior_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(cpd, "ROOT", tmp_path)
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    date = "2026-07-12"
    prior = {
        "date": date,
        "by_ticket_id": {
            "d|STRONG|1": {
                "power_min_x": 2.6,
                "display_min_x": 2.6,
                "payout_source": "live_cdp",
            }
        },
        "by_leg_sig": {},
    }
    (reports / f"payout_patch_{date}.json").write_text(
        json.dumps(prior), encoding="utf-8"
    )
    tickets_path = tmp_path / "tickets.json"
    payload = _payload(date, [_ticket("d|STRONG|1", 2.6, "live_cdp")])
    tickets_path.write_text(json.dumps(payload), encoding="utf-8")

    # 0-ok capture (all failed) must keep prior floors
    failed = [
        {
            "ticket_id": "d|STRONG|1",
            "status": "failed",
            "power_min_x": None,
            "legs": payload["groups"][0]["tickets"][0]["legs"],
        }
    ]
    result = cpd.write_payout_patch_and_apply_to_tickets(
        tickets_path=tickets_path,
        captured=failed,
        date_str=date,
    )
    patch = json.loads((reports / f"payout_patch_{date}.json").read_text(encoding="utf-8"))
    assert "d|STRONG|1" in patch["by_ticket_id"]
    assert float(patch["by_ticket_id"]["d|STRONG|1"]["power_min_x"]) == 2.6
    assert result["n_patched"] + result["n_kept_live"] >= 1

    data = json.loads(tickets_path.read_text(encoding="utf-8"))
    pay = data["groups"][0]["tickets"][0]["payout"]
    assert pay["payout_source"] == "live_cdp"
    assert float(pay["display_min_x"]) == 2.6


def test_preserve_and_upsert_heal_empty_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(cst, "REPO_ROOT", str(tmp_path))
    (tmp_path / "data" / "reports").mkdir(parents=True)
    date = "2026-07-12"
    live = _payload(date, [_ticket("d|STRONG|1", 2.8, "live_cdp")])
    # Fresh rebuild: board avg, but same legs/id
    rebuilt = _payload(
        date,
        [_ticket("d|STRONG|1", 2.2, "mix_grid_average")],
    )
    n = cst.preserve_live_cdp_onto_payload(rebuilt, live)
    assert n == 1
    assert rebuilt["groups"][0]["tickets"][0]["payout"]["payout_source"] == "live_cdp"
    assert float(rebuilt["groups"][0]["tickets"][0]["payout"]["display_min_x"]) == 2.8

    n_ids = cst.upsert_payout_patch_from_payload(rebuilt)
    assert n_ids == 1
    patch = json.loads(
        (tmp_path / "data" / "reports" / f"payout_patch_{date}.json").read_text(
            encoding="utf-8"
        )
    )
    assert float(patch["by_ticket_id"]["d|STRONG|1"]["power_min_x"]) == 2.8

    # Empty upsert must not wipe
    empty = _payload(date, [_ticket("d|STRONG|2", 2.2, "mix_grid_average")])
    cst.upsert_payout_patch_from_payload(empty)
    patch2 = json.loads(
        (tmp_path / "data" / "reports" / f"payout_patch_{date}.json").read_text(
            encoding="utf-8"
        )
    )
    assert "d|STRONG|1" in patch2["by_ticket_id"]
