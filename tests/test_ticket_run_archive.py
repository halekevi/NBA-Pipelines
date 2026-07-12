"""Tests for per-run ticket archive + live playability prune."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ticket_run_archive as tra  # noqa: E402


def _payload(date: str, run_tag: str, n: int = 2) -> dict:
    tickets = []
    for i in range(1, n + 1):
        tickets.append(
            {
                "ticket_id": f"{date}|STRONG|{run_tag}|{i}",
                "strong_builder": True,
                "legs": [
                    {
                        "player": f"Player {run_tag}{i}",
                        "prop_type": "Rebounds",
                        "direction": "OVER",
                        "line": 1.5 + i,
                        "pick_type": "Goblin",
                        "sport": "WNBA",
                    },
                    {
                        "player": f"Other {run_tag}{i}",
                        "prop_type": "Assists",
                        "direction": "OVER",
                        "line": 2.5,
                        "pick_type": "Goblin",
                        "sport": "WNBA",
                    },
                ],
            }
        )
    return {
        "date": date,
        "generated_at": "2026-07-12 00:00:00 UTC",
        "groups": [{"name": "STRONG Goblin HOT", "tickets": tickets}],
    }


def test_archive_and_grade_pool_union(tmp_path, monkeypatch):
    monkeypatch.setattr(tra, "RUNS_DIR", tmp_path / "ticket_runs")
    monkeypatch.setattr(tra, "UI_DATA", tmp_path)
    monkeypatch.setattr(tra, "ROOT", tmp_path)

    d = "2026-07-12"
    a = _payload(d, "A", n=2)
    b = _payload(d, "B", n=2)
    # Overlap one leg-signature duplicate by copying a ticket id/legs from A into B
    b["groups"][0]["tickets"].append(json.loads(json.dumps(a["groups"][0]["tickets"][0])))

    m1 = tra.archive_and_merge_grade_pool(a, date_str=d, run_id="20260712_100000", source="t1")
    m2 = tra.archive_and_merge_grade_pool(b, date_str=d, run_id="20260712_110000", source="t2")
    assert m1["run_id"] == "20260712_100000"
    assert (tmp_path / "ticket_runs" / d / "20260712_100000" / "tickets.json").is_file()
    assert (tmp_path / "ticket_runs" / d / "20260712_110000" / "tickets.json").is_file()

    pool = json.loads((tmp_path / f"combined_slate_tickets_{d}.json").read_text(encoding="utf-8"))
    n = sum(len(g.get("tickets") or []) for g in pool.get("groups") or [])
    # 2 from A + 2 new from B (duplicate skipped) = 4
    assert n == 4
    assert pool.get("run_ids") == ["20260712_100000", "20260712_110000"]


def test_filter_payload_playable_removes_ids():
    payload = _payload("2026-07-12", "X", n=3)
    drop = {payload["groups"][0]["tickets"][1]["ticket_id"]}
    pruned, counts = tra.filter_payload_playable(payload, unplayable_ticket_ids=drop)
    assert counts["removed"] == 1
    assert counts["kept"] == 2
    assert pruned.get("live_playable_only") is True
    ids = [t["ticket_id"] for t in pruned["groups"][0]["tickets"]]
    assert drop.pop() not in ids
