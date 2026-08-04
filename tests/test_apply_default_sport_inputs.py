"""Smoke tests for combined_slate dated step8 path auto-resolution."""
from __future__ import annotations

import argparse
from pathlib import Path

import combined_slate_tickets as cst


def _ns(**kwargs):
    defaults = dict(
        date="2026-08-04",
        nba="",
        cbb="",
        wcbb="",
        nhl="",
        soccer="",
        tennis="",
        tennis_date="2026-08-04",
        golf="",
        wnba="",
        mlb="",
        nba1q="",
        nba1h="",
        nfl="",
        cfb="",
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_default_tennis_path_under_sports():
    assert "Sports" in Path(cst.DEFAULT_TENNIS_PATH).parts
    assert cst.DEFAULT_TENNIS_PATH.endswith("step8_tennis_direction_clean.xlsx")


def test_apply_default_prefers_dated_run_dirs(tmp_path, monkeypatch):
    d = "2026-08-04"
    out = tmp_path / "outputs" / d
    (out / "soccer").mkdir(parents=True)
    (out / "tennis").mkdir(parents=True)
    (out / "mlb").mkdir(parents=True)
    soccer = out / "soccer" / "step8_soccer_direction_clean.xlsx"
    tennis = out / "tennis" / f"step8_tennis_direction_clean_{d}.xlsx"
    mlb = out / "mlb" / "step8_mlb_direction_clean.xlsx"
    for p in (soccer, tennis, mlb):
        p.write_bytes(b"PK fake")

    monkeypatch.setattr(cst, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(
        cst,
        "_outputs_dir_for_date",
        lambda date: str(tmp_path / "outputs" / str(date).strip()[:10]),
    )

    args = _ns(date=d, tennis_date=d)
    cst.apply_default_sport_inputs(args)
    assert Path(args.soccer) == soccer
    assert Path(args.tennis) == tennis
    assert Path(args.mlb) == mlb


def test_apply_default_falls_back_to_sports_root(tmp_path, monkeypatch):
    d = "2026-08-04"
    sports = tmp_path / "Sports"
    paths = {
        "soccer": sports / "Soccer" / "outputs" / "step8_soccer_direction_clean.xlsx",
        "tennis": sports / "Tennis" / "step8_tennis_direction_clean.xlsx",
        "mlb": sports / "MLB" / "step8_mlb_direction_clean.xlsx",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PK fake")

    monkeypatch.setattr(cst, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(
        cst,
        "_outputs_dir_for_date",
        lambda date: str(tmp_path / "outputs" / str(date).strip()[:10]),
    )

    args = _ns(date=d, tennis_date=d)
    cst.apply_default_sport_inputs(args)
    assert Path(args.soccer) == paths["soccer"]
    assert Path(args.tennis) == paths["tennis"]
    assert Path(args.mlb) == paths["mlb"]
