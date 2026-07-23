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


def test_attach_pending_live_when_require_live(monkeypatch):
    monkeypatch.setenv("PROPORACLE_REQUIRE_LIVE_PAYOUT", "1")
    t = _ticket("d|STRONG|9", 2.2, "mix_grid_average")
    t["payout"]["power_min_x"] = None
    t["payout"]["payout_source"] = "mix_grid_average"
    out = cst.attach_display_min_x(t)
    assert out["payout"]["payout_source"] == "pending_live"
    assert out["payout"].get("display_min_x") is None
    assert out.get("display_min_x") is None


def test_resolve_display_skips_model_when_pending(monkeypatch):
    monkeypatch.setenv("PROPORACLE_REQUIRE_LIVE_PAYOUT", "1")
    t = {
        "power_payout": 9.0,
        "base_power_payout": 9.0,
        "payout": {"payout_source": "pending_live", "model_min_payout_x": 9.0},
    }
    assert cst._resolve_ticket_display_min_x(t["payout"], t) is None
    label, badge, _ = cst._board_payout_label(None, "pending_live")
    assert label == "—"
    assert badge == "pending"


def test_attach_mix_grid_when_require_live_off(monkeypatch):
    monkeypatch.setenv("PROPORACLE_REQUIRE_LIVE_PAYOUT", "0")
    monkeypatch.setattr(cst, "_load_live_payout_rate_card", lambda: None)
    monkeypatch.setattr(cst, "_LIVE_COMPOSITION_FLOORS", {})
    monkeypatch.setattr(cst, "_lookup_sg_delta_verified_floor", lambda _t: None)
    t = {
        "n_legs": 2,
        "legs": [
            {"pick_type": "Goblin", "player": "A", "prop_type": "X", "line": 1.5},
            {"pick_type": "Goblin", "player": "B", "prop_type": "Y", "line": 2.5},
        ],
        "payout": {"min_payout_x": 9.0, "model_min_payout_x": 9.0},
    }
    out = cst.attach_display_min_x(t)
    assert out["payout"]["payout_source"] == "mix_grid_average"
    assert float(out["payout"]["display_min_x"]) == 2.2


def _sg_card(cells: list[dict]) -> dict:
    return {"cells": cells, "summary": {"n_cells": len(cells)}}


def test_attach_sg_delta_live_when_exact_cell(monkeypatch):
    monkeypatch.setenv("PROPORACLE_REQUIRE_LIVE_PAYOUT", "1")
    monkeypatch.setattr(
        cst,
        "_load_sg_delta_rate_card",
        lambda force=False: _sg_card(
            [
                {
                    "composition": "0S+2G+0D",
                    "goblin_delta_sig": "1+2",
                    "power_min_x": 2.4,
                    "source": "live_cdp",
                    "status": "observed",
                    "n_live": 2,
                }
            ]
        ),
    )
    t = {
        "n_legs": 2,
        "legs": [
            {"pick_type": "Goblin", "line_distance": 1.0},
            {"pick_type": "Goblin", "line_distance": 2.0},
        ],
        "payout": {"model_min_payout_x": 9.0},
    }
    out = cst.attach_display_min_x(t)
    assert out["payout"]["payout_source"] == "sg_delta_live"
    assert float(out["payout"]["display_min_x"]) == 2.4
    assert float(out["payout"]["power_min_x"]) == 2.4


def test_attach_sg_delta_verified_extrapolated_when_peer_live(monkeypatch):
    """Extrapolated OK once same composition has close/overlapping live Δ evidence."""
    monkeypatch.setenv("PROPORACLE_REQUIRE_LIVE_PAYOUT", "1")
    monkeypatch.setattr(
        cst,
        "_load_sg_delta_rate_card",
        lambda force=False: _sg_card(
            [
                {
                    "composition": "1S+1G+0D",
                    "goblin_delta_sig": "5",
                    "power_min_x": 1.9,
                    "source": "live_cdp",
                    "status": "observed",
                    "n_live": 3,
                },
                {
                    "composition": "1S+1G+0D",
                    "goblin_delta_sig": "5.5",
                    "power_min_x": 1.8753,
                    "source": "extrapolated",
                    "status": "extrapolated",
                    "n_live": 0,
                },
            ]
        ),
    )
    t = {
        "n_legs": 2,
        "legs": [
            {"pick_type": "Standard", "line_distance": 0},
            {"pick_type": "Goblin", "line_distance": 5.5},
        ],
        "payout": {"model_min_payout_x": 9.0},
    }
    out = cst.attach_display_min_x(t)
    assert out["payout"]["payout_source"] == "sg_delta_verified"
    assert float(out["payout"]["display_min_x"]) == 1.8753
    label, badge, _ = cst._board_payout_label(1.8753, "sg_delta_verified")
    assert badge == "✓ lines"
    assert cst._resolve_ticket_display_min_x(out["payout"], out) == 1.8753


def test_attach_blocks_cold_extrapolated(monkeypatch):
    """Zero live_cdp cells in the composition → pending_live, no stamp."""
    monkeypatch.setenv("PROPORACLE_REQUIRE_LIVE_PAYOUT", "1")
    monkeypatch.setattr(
        cst,
        "_load_sg_delta_rate_card",
        lambda force=False: _sg_card(
            [
                {
                    "composition": "0S+4G+0D",
                    "goblin_delta_sig": "1+1+1+1",
                    "power_min_x": 3.3,
                    "source": "extrapolated",
                    "status": "extrapolated",
                    "n_live": 0,
                }
            ]
        ),
    )
    t = {
        "n_legs": 4,
        "legs": [
            {"pick_type": "Goblin", "line_distance": 1.0},
            {"pick_type": "Goblin", "line_distance": 1.0},
            {"pick_type": "Goblin", "line_distance": 1.0},
            {"pick_type": "Goblin", "line_distance": 1.0},
        ],
        "payout": {"model_min_payout_x": 9.0},
    }
    out = cst.attach_display_min_x(t)
    assert out["payout"]["payout_source"] == "pending_live"
    assert out["payout"].get("display_min_x") is None


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


def test_tickets_fingerprint_stable_and_skip_when_unchanged(tmp_path):
    date = "2026-07-16"
    tickets_path = tmp_path / "tickets.json"
    live = _payload(
        date,
        [
            _ticket("d|STRONG|1", 2.6, "live_cdp", line=1.5),
            _ticket("d|MAIN|2", 3.1, "live_cdp", line=2.5),
        ],
    )
    tickets_path.write_text(json.dumps(live), encoding="utf-8")
    fp1 = cpd.main_strong_tickets_fingerprint(tickets_path)
    fp2 = cpd.main_strong_tickets_fingerprint(tickets_path)
    assert fp1["fingerprint"]
    assert fp1["fingerprint"] == fp2["fingerprint"]
    assert fp1["n_slips"] == 2
    assert fp1["n_missing_live"] == 0

    capture_path = tmp_path / "payout_capture.json"
    capture_path.write_text(
        json.dumps(
            {
                "date": date,
                "tickets_fingerprint": fp1["fingerprint"],
                "summary": {"n_ok": 2},
            }
        ),
        encoding="utf-8",
    )
    decision = cpd.capture_skip_decision(tickets_path, capture_path)
    assert decision["unchanged"] is True
    assert decision["skip_scrape"] is True
    assert decision["reason"] == "tickets_unchanged_all_live"

    # New slip without live floor → must scrape
    live["groups"][0]["tickets"].append(_ticket("d|STRONG|3", 2.0, "fallback_estimate"))
    tickets_path.write_text(json.dumps(live), encoding="utf-8")
    decision2 = cpd.capture_skip_decision(tickets_path, capture_path)
    assert decision2["unchanged"] is False
    assert decision2["skip_scrape"] is False
    assert decision2["n_missing_live"] >= 1
    assert decision2["reason"] in ("tickets_changed", "missing_live_floors")
