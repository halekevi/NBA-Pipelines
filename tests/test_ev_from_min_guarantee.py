"""EV must follow scraped / display min-guarantee, not modeled Standard sweep."""
from __future__ import annotations

from utils.ticket_ev_tiers import refresh_ticket_ev_from_min_guarantee


def test_power_ev_uses_scraped_min_guarantee():
    pay = {
        "ticket_type": "power",
        "p_all_win": 0.5,
        "ev": 9.99,  # stale model EV
        "min_payout_x": 10.0,
        "payout": 10.0,
    }
    ev = refresh_ticket_ev_from_min_guarantee(pay, 1.3, update_recommendation=True)
    assert ev == round(0.5 * 1.3 - 1.0, 4)
    assert pay["ev"] == ev
    assert pay["payout"] == 1.3
    assert pay["min_guarantee"] == 1.3
    assert pay["min_payout_x"] == 1.3
    assert pay["recommendation"] == "SKIP"  # negative EV


def test_attach_display_min_x_refreshes_ev():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import combined_slate_tickets as cst

    t = {
        "n_legs": 2,
        "display_min_x": 1.3,
        "payout": {
            "ticket_type": "power",
            "p_all_win": 0.4,
            "payout_source": "live_cdp",
            "power_min_x": 1.3,
            "display_min_x": 1.3,
            "ev": 2.0,
            "min_payout_x": 3.0,
        },
        "legs": [{"pick_type": "Goblin"}, {"pick_type": "Goblin"}],
    }
    out = cst.attach_display_min_x(t)
    assert out["payout"]["payout_source"] == "live_cdp"
    assert float(out["payout"]["display_min_x"]) == 1.3
    assert out["payout"]["ev"] == round(0.4 * 1.3 - 1.0, 4)
