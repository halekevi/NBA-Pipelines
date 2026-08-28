"""Unit tests for assert_active_sports_fresh gate."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.assert_active_sports_fresh import (
    assert_active_sports_fresh,
    classify_sport,
    in_season_candidates,
    resolve_expected,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("player_name\n", encoding="utf-8")
        return
    cols = list(rows[0].keys())
    lines = [",".join(cols)]
    for r in rows:
        lines.append(",".join(str(r.get(c, "")) for c in cols))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_in_season_summer_2026_aug():
    c = in_season_candidates("2026-08-22")
    assert "mlb" in c and "soccer" in c and "tennis" in c and "wnba" in c
    assert "nba" not in c and "nhl" not in c


def test_classify_fresh_vs_pending_stale():
    today = "2026-08-22"
    slate = {
        "date": today,
        "generated_at": "2026-08-22 17:00:00 UTC",
        "sports": {
            "mlb": [{"game_date": today, "player": "A"}],
            "soccer": [],
        },
    }
    badge, _ = classify_sport("mlb", slate, today)
    assert badge == "FRESH"
    badge, _ = classify_sport("soccer", slate, today)
    assert badge == "PENDING"

    stale_slate = {
        "date": "2026-08-15",
        "generated_at": "2026-08-15 13:00:00 UTC",
        "sports": {"mlb": [{"game_date": today, "player": "A"}]},
    }
    badge, _ = classify_sport("mlb", stale_slate, today)
    assert badge == "STALE"


def test_no_slate_skip_unless_props(tmp_path: Path):
    today = "2026-08-22"
    status = {
        "mlb": "no_slate",
        "soccer": "complete",
        "tennis": "complete",
        "wnba": "complete",
        "nba": "off_season",
        "nhl": "off_season",
    }
    expected, skipped, failed = resolve_expected(today, status, tmp_path)
    assert "mlb" not in expected
    assert any(s == "mlb" and "no_slate" in r for s, r in skipped)
    assert "soccer" in expected and "tennis" in expected and "wnba" in expected
    assert not failed

    _write_csv(
        tmp_path / "outputs" / today / "mlb" / "step1_mlb_props.csv",
        [{"player_name": "X", "line": "1.5"}],
    )
    expected2, _, _ = resolve_expected(today, status, tmp_path)
    assert "mlb" in expected2


def test_assert_fails_soccer_only_publish(tmp_path: Path):
    today = "2026-08-22"
    templates = tmp_path / "ui_runner" / "templates"
    _write_json(
        tmp_path / "outputs" / today / "pipeline_slate_status.json",
        {
            "run_date": today,
            "sports": {
                "mlb": "complete",
                "soccer": "complete",
                "tennis": "complete",
                "wnba": "complete",
                "nba": "off_season",
                "nhl": "off_season",
            },
        },
    )
    # Partial publish: only soccer rows (stash bug).
    _write_json(
        templates / "slate_latest.json",
        {
            "date": today,
            "generated_at": f"{today} 18:00:00 UTC",
            "sports": {
                "soccer": [{"game_date": today, "player": "S"}],
                "mlb": [],
                "wnba": [],
                "tennis": [],
            },
        },
    )
    report = assert_active_sports_fresh(tmp_path, today=today, templates_dir=templates)
    assert report["ok"] is False
    assert "mlb" in report["bad"]
    assert "wnba" in report["bad"]
    assert "tennis" in report["bad"]
    assert report["sports"]["soccer"]["badge"] == "FRESH"


def test_assert_ok_all_fresh(tmp_path: Path):
    today = "2026-08-22"
    templates = tmp_path / "ui_runner" / "templates"
    _write_json(
        tmp_path / "outputs" / today / "pipeline_slate_status.json",
        {
            "run_date": today,
            "sports": {
                "mlb": "complete",
                "soccer": "complete",
                "tennis": "complete",
                "wnba": "complete",
                "nba": "off_season",
            },
        },
    )
    _write_json(
        templates / "slate_latest.json",
        {
            "date": today,
            "generated_at": f"{today} 18:00:00 UTC",
            "tennis_date": today,
            "sports": {
                "mlb": [{"game_date": today}],
                "soccer": [{"game_date": today}],
                "tennis": [{"game_date": today}],
                "wnba": [{"game_date": today}],
            },
        },
    )
    report = assert_active_sports_fresh(tmp_path, today=today, templates_dir=templates)
    assert report["ok"] is True
    assert not report["bad"]
