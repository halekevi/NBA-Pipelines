"""Personal P&L for placed slips (N-correct only)."""

from ui_runner.placed_pnl import (
    parse_n_correct,
    settle_snapshot,
    snapshot_from_custom,
    snapshot_from_ticket,
    summarize,
    ticket_fingerprint,
)


def _power_ticket():
    return {
        "web_group_name": "X-Sport Goblin-70 Power 3",
        "power_payout": 2.0,
        "display_min_x": 2.0,
        "payout": {"n_correct": {"3": 2.0}, "sweep_payout": 99.0, "first_place": 99.0},
        "legs": [
            {"player": "A", "prop_type": "Points", "line": 10.5, "direction": "OVER", "pick_type": "Goblin"},
            {"player": "B", "prop_type": "Points", "line": 8.5, "direction": "OVER", "pick_type": "Goblin"},
            {"player": "C", "prop_type": "Assists", "line": 2.5, "direction": "OVER", "pick_type": "Goblin"},
        ],
    }


def test_fingerprint_sorts():
    fp = ticket_fingerprint(_power_ticket()["legs"][::-1])
    assert fp.startswith("a|points|10.5|OVER")


def test_snapshot_ignores_first_place():
    snap = snapshot_from_ticket(_power_ticket(), group_name="X-Sport Goblin-70 Power 3", stake=20)
    assert snap["product"] == "Power"
    assert snap["n_correct"] == {"3": 2.0}
    assert 99.0 not in snap["n_correct"].values()


def test_power_win_and_loss():
    snap = snapshot_from_ticket(_power_ticket(), group_name="Power 3", stake=20)
    grades = {
        ("a", "points", "10.50", "OVER"): "HIT",
        ("b", "points", "8.50", "OVER"): "HIT",
        ("c", "assists", "2.50", "OVER"): "HIT",
    }
    win = settle_snapshot(snap, fingerprint=snap["fingerprint"], slate_date="2026-08-28", stake=20, grades=grades)
    assert win["result"] == "WIN"
    assert win["multiplier"] == 2.0
    assert win["net"] == 20.0
    grades[("c", "assists", "2.50", "OVER")] = "MISS"
    loss = settle_snapshot(snap, fingerprint=snap["fingerprint"], slate_date="2026-08-28", stake=20, grades=grades)
    assert loss["result"] == "LOSS"
    assert loss["net"] == -20.0


def test_flex_partial_cash():
    ticket = {
        "flex_payout": 0.5,
        "payout": {"n_correct": {"3": 1.7, "2": 0.5}},
        "legs": _power_ticket()["legs"],
    }
    snap = snapshot_from_ticket(ticket, group_name="Goblin-70 Flex 3", stake=20)
    assert snap["product"] == "Flex"
    grades = {
        ("a", "points", "10.50", "OVER"): "HIT",
        ("b", "points", "8.50", "OVER"): "HIT",
        ("c", "assists", "2.50", "OVER"): "MISS",
    }
    cash = settle_snapshot(snap, fingerprint="x", slate_date="2026-08-28", stake=20, grades=grades)
    assert cash["result"] == "CASH"
    assert cash["multiplier"] == 0.5
    assert cash["net"] == -10.0


def test_pending_and_summary():
    snap = snapshot_from_ticket(_power_ticket(), group_name="Power 3", stake=20)
    pending = settle_snapshot(snap, fingerprint="x", slate_date="2026-08-28", stake=20, grades={})
    assert pending["status"] == "pending"
    win_grades = {
        ("a", "points", "10.50", "OVER"): "HIT",
        ("b", "points", "8.50", "OVER"): "HIT",
        ("c", "assists", "2.50", "OVER"): "HIT",
    }
    win = settle_snapshot(snap, fingerprint="x", slate_date="2026-08-28", stake=20, grades=win_grades)
    s = summarize([pending, win])
    assert s["pending"] == 1
    assert s["wins"] == 1
    assert s["roi_pct"] == 100.0


def test_no_snapshot_stays_pending():
    grades = {
        ("a", "points", "10.50", "OVER"): "HIT",
        ("b", "points", "8.50", "OVER"): "HIT",
        ("c", "assists", "2.50", "OVER"): "HIT",
    }
    fp = ticket_fingerprint(_power_ticket()["legs"])
    row = settle_snapshot(None, fingerprint=fp, slate_date="2026-08-28", stake=20, grades=grades)
    assert row["status"] == "pending"
    assert row["result"] == "PENDING"
    assert row["net"] is None


def test_custom_snapshot_drops_first_place():
    legs = _power_ticket()["legs"]
    snap = snapshot_from_custom(
        legs,
        product="Power",
        n_correct={"3": 2.0, "first_place": 99.0, "sweep_payout": 50},
        stake=20,
    )
    assert snap["product"] == "Power"
    assert snap["n_correct"] == {"3": 2.0}
    assert parse_n_correct({"first_place": 37.5}) == {}
