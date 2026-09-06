"""Bet-window labels and append-only payout scrape log."""
from __future__ import annotations

from pathlib import Path

from utils.bet_windows import (
    append_payout_scrape_log,
    rebuild_bet_windows,
    summarize_fetch_window,
    window_label,
)


def test_window_label_maps_refresh_slots():
    assert window_label("2026-08-27T01:05:00-04:00") == "1AM"
    assert window_label("2026-08-27T08:02:00-04:00") == "8AM"
    assert window_label("2026-08-27T09:00:00-04:00") == "9AM"
    assert window_label("2026-08-27T09:47:00-04:00") == "9:45"
    assert window_label("2026-08-27T10:32:00-04:00") == "10:30"
    assert window_label("2026-08-27T13:04:00-04:00") == "1PM"
    assert window_label("2026-08-27T16:31:00-04:00") == "4:30"


def test_job_window_uses_1am_and_8am_labels(monkeypatch):
    from utils.bet_windows import job_window_label

    monkeypatch.setenv("PROPORACLE_BET_WINDOW", "1AM")
    assert job_window_label("2026-08-27T02:40:00-04:00") == "1AM"
    monkeypatch.setenv("PROPORACLE_BET_WINDOW", "8AM")
    assert job_window_label("2026-08-27T09:20:00-04:00") == "8AM"
    monkeypatch.delenv("PROPORACLE_BET_WINDOW", raising=False)
    assert job_window_label("2026-08-27T08:02:00-04:00", explicit="8AM") == "8AM"


def test_summarize_force_payout_only_when_moved(monkeypatch):
    from utils.bet_windows import summarize_fetch_window

    pulls = [
        {"fetched_at": "2026-08-28T01:05:00-04:00", "window": "1AM", "n_props": 10, "n_moved": 0},
        {"fetched_at": "2026-08-28T08:02:00-04:00", "window": "8AM", "n_props": 10, "n_moved": 0},
        {"fetched_at": "2026-08-28T09:47:00-04:00", "window": "9:45", "n_props": 12, "n_moved": 4},
    ]
    monkeypatch.setattr("utils.bet_windows._line_pulls", lambda date: pulls)
    first = summarize_fetch_window("2026-08-28", "1AM")
    assert first["is_initial_stamp"] is True
    assert first["force_payout"] is True
    eight = summarize_fetch_window("2026-08-28", "8AM")
    assert eight["is_initial_stamp"] is False
    assert eight["n_moved_this_window"] == 0
    assert eight["force_payout"] is False
    assert eight["rebuild_tickets"] is False
    later = summarize_fetch_window("2026-08-28", "945AM")
    assert later["n_moved_this_window"] == 4
    assert later["n_moved_from_initial"] == 4
    assert later["force_payout"] is True


def test_write_fetch_window_stamp(tmp_path: Path, monkeypatch):
    import utils.bet_windows as bw

    monkeypatch.setattr(bw, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(bw, "LINE_WINDOW_CACHE", tmp_path / "last_line_window.json")
    monkeypatch.setattr(bw, "STAMP_TEMPLATES", tmp_path / "templates" / "last_fetch_window.json")
    monkeypatch.setattr(bw, "STAMP_RUNTIME", tmp_path / "runtime" / "last_fetch_window.json")
    monkeypatch.setattr(bw, "_line_pulls", lambda date: [])
    out = bw.write_fetch_window_stamp(bw.summarize_fetch_window("2026-08-28", "1PM"))
    assert out["window"] == "1PM"
    assert out["force_payout"] is True
    assert (tmp_path / "templates" / "last_fetch_window.json").is_file()
    assert (tmp_path / "last_line_window.json").is_file()


def test_append_scrape_log_and_rebuild(tmp_path: Path, monkeypatch):
    import utils.bet_windows as bw

    monkeypatch.setattr(bw, "REPORTS", tmp_path)
    monkeypatch.setattr(bw, "LINE_DB", tmp_path / "missing.db")
    captured = [
        {
            "status": "ok",
            "ticket_id": "t1",
            "n_legs": 3,
            "power_min_x": 2.0,
            "captured_at": "2026-08-27T16:32:00-04:00",
            "legs": [
                {"player": "A", "prop_type": "Pts", "pick_type": "Goblin", "line": 16.5},
            ],
        }
    ]
    n = append_payout_scrape_log("2026-08-27", captured)
    assert n == 1
    payload = rebuild_bet_windows("2026-08-27")
    assert payload["date"] == "2026-08-27"
    assert payload["payout_scrapes"]
    row = payload["payout_scrapes"][0]
    assert row["window"] == "4:30"
    assert row["median_power_x"] == 2.0
    assert "16:32" in str(row["last_captured_at"])
