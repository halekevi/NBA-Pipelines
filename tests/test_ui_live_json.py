"""Live JSON path helpers and publish guards."""
from __future__ import annotations

import json
from pathlib import Path

from utils.ui_live_json import (
    dual_card_errors,
    refresh_pipeline_status_from_slate,
    sync_runtime_templates_pair,
    tickets_card_kind,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_tickets_card_kind_dual_and_partial():
    dual = {
        "mode": "goblin70+graded_main",
        "groups": [
            {"group_name": "Tennis Goblin-70 Flex 4", "tickets": [{"ticket_track": "goblin70"}]},
            {"group_name": "STRONG 3-leg", "tickets": [{"ticket_track": "graded_main"}]},
        ],
    }
    assert tickets_card_kind(dual) == "dual"
    assert tickets_card_kind({"groups": [dual["groups"][0]]}) == "goblin70_only"
    assert tickets_card_kind({"groups": [dual["groups"][1]]}) == "mixer_only"
    assert tickets_card_kind({"groups": []}) == "empty"
    assert tickets_card_kind(None) == "missing"


def test_sync_runtime_templates_prefers_newer_generated_at(tmp_path: Path):
    root = tmp_path
    rt = root / "ui_runner" / "runtime"
    tmpl = root / "ui_runner" / "templates"
    rt.mkdir(parents=True)
    tmpl.mkdir(parents=True)
    old = {"date": "2026-08-30", "generated_at": "2026-08-30 16:00:00 UTC", "sports": {}}
    new = {"date": "2026-08-31", "generated_at": "2026-08-31 19:00:00 UTC", "sports": {"mlb": [1]}}
    _write(rt / "slate_latest.json", old)
    _write(tmpl / "slate_latest.json", new)
    sync_runtime_templates_pair("slate_latest.json", root)
    assert json.loads((rt / "slate_latest.json").read_text(encoding="utf-8"))["date"] == "2026-08-31"
    assert json.loads((tmpl / "slate_latest.json").read_text(encoding="utf-8"))["date"] == "2026-08-31"


def test_refresh_pipeline_status_and_dual_guard(tmp_path: Path):
    root = tmp_path
    tmpl = root / "ui_runner" / "templates"
    rt = root / "ui_runner" / "runtime"
    tmpl.mkdir(parents=True)
    rt.mkdir(parents=True)
    slate = {
        "date": "2026-08-31",
        "generated_at": "2026-08-31 19:00:06 UTC",
        "sports": {"mlb": [{"player": "A"}], "cfb": [], "wnba": []},
    }
    _write(tmpl / "slate_latest.json", slate)
    dest = refresh_pipeline_status_from_slate(root)
    assert dest is not None
    status = json.loads((rt / "pipeline_status.json").read_text(encoding="utf-8"))
    assert status["mlb"]["slate"]["exists"] is True
    assert status["cfb"]["slate"]["exists"] is False
    assert status["cfb"]["slate"]["no_slate"] is True
    assert status["mlb"]["slate"]["no_slate"] is False
    assert "2026-08-31" in status["mlb"]["slate"]["modified"]
    assert status["combined"]["slate"]["exists"] is True

    tickets = {
        "date": "2026-08-31",
        "groups": [{"group_name": "Tennis Goblin-70 Flex 4", "tickets": []}],
    }
    _write(tmpl / "tickets_latest.json", tickets)
    _write(rt / "tickets_latest.json", tickets)
    errs = dual_card_errors(root)
    assert any("goblin70_only" in e for e in errs)
