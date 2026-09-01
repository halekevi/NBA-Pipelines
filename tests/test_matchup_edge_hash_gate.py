from pathlib import Path

from utils.matchup_edge.builder import (
    _fingerprint_path,
    existing_matchup_source_hash,
    matchup_source_hash,
)


def test_fingerprint_missing_and_file(tmp_path):
    assert _fingerprint_path(None) == "missing"
    p = tmp_path / "slate.csv"
    p.write_text("x\n", encoding="utf-8")
    fp = _fingerprint_path(p)
    assert fp.startswith("slate.csv:")
    p.write_text("xy\n", encoding="utf-8")
    assert _fingerprint_path(p) != fp


def test_existing_hash_reads_templates(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.matchup_edge.builder._REPO_ROOT", tmp_path)
    templates = tmp_path / "ui_runner" / "templates"
    templates.mkdir(parents=True)
    (templates / "mlb_matchup_edge.json").write_text(
        '{"source_hash": "abc123", "teams": []}', encoding="utf-8"
    )
    assert existing_matchup_source_hash("mlb", tmp_path) == "abc123"
    assert existing_matchup_source_hash("wnba", tmp_path) is None


def test_matchup_source_hash_stable_for_same_inputs(monkeypatch, tmp_path):
    slate = tmp_path / "step8.csv"
    slate.write_text("player,prop\nA,pts\n", encoding="utf-8")
    monkeypatch.setattr(
        "utils.matchup_edge.builder._resolve_matchup_slate",
        lambda sport, slate_path=None: slate,
    )
    monkeypatch.setattr("utils.matchup_edge.builder.SPORT_CONFIGS", {})
    a = matchup_source_hash("mlb")
    b = matchup_source_hash("mlb")
    assert a == b
    assert len(a) == 20
    slate.write_text("player,prop\nA,pts\nB,reb\n", encoding="utf-8")
    assert matchup_source_hash("mlb") != a
