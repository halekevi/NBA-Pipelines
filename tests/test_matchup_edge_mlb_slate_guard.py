"""Guards: empty MLB board must not emit idle 30-team blank-OPP panels."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


def test_mlb_empty_slate_soft_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "slate_sport_mlb.json"
    empty.write_text(json.dumps({"ok": True, "sport": "mlb", "rows": []}), encoding="utf-8")
    # Point resolver at empty board only (no season step8 fallback).
    monkeypatch.setattr(
        "utils.matchup_edge.builder._REPO_ROOT",
        tmp_path,
    )
    (tmp_path / "ui_runner" / "templates").mkdir(parents=True)
    (tmp_path / "mobile" / "www").mkdir(parents=True)
    (tmp_path / "ui_runner" / "templates" / "slate_sport_mlb.json").write_text(
        empty.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "Sports" / "MLB" / "scripts").mkdir(parents=True)
    # Import after path setup — call MLB builder resolve via module API.
    from utils.matchup_edge import builder as b

    resolved = b._resolve_mlb_slate(None)
    assert b._slate_row_count(resolved) == 0

    # Direct builder fail-closed when matchups missing.
    import importlib.util

    script = _REPO / "Sports" / "MLB" / "scripts" / "build_mlb_hitter_matchup_edge_json.py"
    spec = importlib.util.spec_from_file_location("mlb_me", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    mlb = _REPO / "Sports" / "MLB"
    payload = mod.build_payload(
        cache_path=mlb / "mlb_stats_cache.csv",
        defense_path=mlb / "mlb_defense_summary.csv",
        top3_path=mlb / "data/mlb_hitter_top3_vs_defense.csv",
        slate_path=empty,
        id_cache_path=mlb / "mlb_id_cache.csv",
    )
    assert payload.get("error")
    assert payload.get("players_by_team_cat") == {}
    assert payload.get("teams") == []
    assert payload.get("matchups") == {}


def test_orchestrator_continues_after_sport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """One sport raising must not abort remaining sports."""
    import scripts.build_matchup_edge_json as orch

    calls: list[str] = []

    def fake_build(sport: str, slate_path=None):
        calls.append(sport)
        if sport == "nhl":
            raise FileNotFoundError("missing defense")
        return {"sport": sport, "players_by_team_cat": {"X|pts": {"players": []}}}

    def fake_publish(payload, sport, repo):
        return [Path(f"{sport}_matchup_edge.json")]

    monkeypatch.setattr(orch, "build_matchup_payload", fake_build)
    monkeypatch.setattr(orch, "publish_payload", fake_publish)
    monkeypatch.setattr(orch, "ENABLED_SPORTS", ["wnba", "nhl", "mlb"])

    # Simulate main loop
    sports = list(orch.ENABLED_SPORTS)
    ok = 0
    failed: list[str] = []
    for sport in sports:
        try:
            payload = orch.build_matchup_payload(sport)
            orch.publish_payload(payload, sport, _REPO)
            ok += 1
        except Exception:
            failed.append(sport)
    assert failed == ["nhl"]
    assert ok == 2
    assert calls == ["wnba", "nhl", "mlb"]
