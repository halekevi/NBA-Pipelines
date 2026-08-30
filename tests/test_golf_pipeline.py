"""PGA/Golf pipeline finalize: real L5, tournament-week window, MAIN include."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from combined_slate_tickets import enforce_target_date, main_exclude_sports_for_date  # noqa: E402
from utils.hit_tracking_columns import fill_l5_from_stat_games  # noqa: E402

GOLF_STEP8 = ROOT / "Sports" / "Golf" / "scripts" / "step8_add_direction_context_golf.py"
GOLF_STEP7 = ROOT / "Sports" / "Golf" / "scripts" / "step7_rank_props_golf.py"


def _load_golf_step8():
    import importlib.util

    spec = importlib.util.spec_from_file_location("golf_step8", GOLF_STEP8)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_golf_tournament_window_covers_thu_sun():
    mod = _load_golf_step8()
    # Sunday of a Thu–Sun event still keeps Thursday start_time.
    keep = mod.golf_tournament_keep_dates("2026-08-30")
    assert "2026-08-27" in keep  # Thursday of the same event
    assert "2026-08-30" in keep
    assert "2026-08-31" in keep
    assert "2026-08-26" not in keep


def test_golf_step8_does_not_invent_l5_from_hit_rate():
    src = GOLF_STEP8.read_text(encoding="utf-8")
    assert "hit_rate" in src
    assert "fillna(0.5) * 5" not in src
    assert "l5_over_fallback" not in src
    assert "fill_l5_from_stat_games" in src


def test_golf_step7_keeps_stat_g_columns():
    src = GOLF_STEP7.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Must not rebuild a skinny DataFrame that drops stat_g*.
    assigns = [
        n for n in ast.walk(tree) if isinstance(n, ast.Assign)
    ]
    skinny = False
    for a in assigns:
        if any(isinstance(t, ast.Name) and t.id == "out" for t in a.targets):
            if isinstance(a.value, ast.Call) and getattr(a.value.func, "attr", "") == "DataFrame":
                skinny = True
    assert not skinny
    assert "stat_g1" in src


def test_golf_fill_l5_from_rounds_not_rate():
    df = pd.DataFrame(
        {
            "line": [70.5],
            "stat_g1": [68],
            "stat_g2": [71],
            "stat_g3": [69],
            "stat_g4": [72],
            "stat_g5": [70],
            "last5_over": [pd.NA],
        }
    )
    out = fill_l5_from_stat_games(df, line_col="line")
    assert float(out.loc[0, "l5_over"]) == 2.0
    assert float(out.loc[0, "l5_under"]) == 3.0
    assert float(out.loc[0, "last5_over"]) == 2.0


def test_golf_not_in_default_main_exclude():
    assert "GOLF" not in main_exclude_sports_for_date("2026-08-30")


def test_golf_enforce_target_date_keeps_thursday_on_sunday():
    df = pd.DataFrame(
        {
            "game_time": ["08/27 8:00 AM"],
            "player": ["Test Golfer"],
            "line": [70.5],
        }
    )
    out = enforce_target_date(
        df,
        "Golf",
        "2026-08-30",
        allow_cross_date_fallback=True,
        extra_dates=["2026-08-27", "2026-08-28", "2026-08-29"],
    )
    assert len(out) == 1


def test_golf_round_calendar_date_maps_thu_to_r1_sun_to_r4():
    sys.path.insert(0, str(ROOT / "Sports" / "Golf" / "scripts"))
    from golf_actuals import actuals_rows_for_date, round_calendar_date  # noqa: E402

    assert round_calendar_date("2026-08-27", 1) == "2026-08-27"
    assert round_calendar_date("2026-08-27", 4) == "2026-08-30"
    cache = pd.DataFrame(
        {
            "player_name": ["Test Golfer"],
            "player_key": ["test golfer"],
            "tournament_date": ["2026-08-27"],
            "tournament_name": ["Test Open"],
            "round": [4],
            "strokes": [68.0],
            "birdies_or_better": [5.0],
            "pars": [10.0],
            "bogeys_or_worse": [3.0],
        }
    )
    rows = actuals_rows_for_date(cache, "2026-08-30")
    props = {r["prop_type"]: r["actual"] for r in rows}
    assert props["Strokes"] == 68.0
    assert props["Birdies Or Better"] == 5.0
    assert actuals_rows_for_date(cache, "2026-08-29") == []


def test_golf_grader_over_uses_gte_line():
    sys.path.insert(0, str(ROOT / "Sports" / "Golf" / "scripts"))
    import golf_grader  # noqa: E402

    assert golf_grader._grade("OVER", 67.5, 68.0)[0] == "HIT"
    assert golf_grader._grade("OVER", 67.5, 67.5)[0] == "HIT"
    assert golf_grader._grade("OVER", 67.5, 67.0)[0] == "MISS"
    assert golf_grader._grade("UNDER", 67.5, 67.0)[0] == "HIT"
    assert golf_grader._grade("UNDER", 67.5, 67.5)[0] == "MISS"
    assert golf_grader._grade("OVER", 67.5, None)[0] == "VOID"


def test_golf_on_grader_and_daily_schedules():
    grader = (ROOT / "scripts" / "run_grader.ps1").read_text(encoding="utf-8")
    daily = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")
    evening = (ROOT / "scripts" / "run_grader_evening.ps1").read_text(encoding="utf-8")
    late = (ROOT / "scripts" / "run_nba_late_fetch.ps1").read_text(encoding="utf-8")
    pipe = (ROOT / "run_pipeline.ps1").read_text(encoding="utf-8")
    refresh = (ROOT / "scripts" / "run_refresh_with_log.ps1").read_text(encoding="utf-8")
    assert "golf_grader.py" in grader
    assert "fetch_golf_actuals.py" in grader
    assert "--golf_actuals" in grader
    assert "graded_golf_$GradeDate.xlsx" in grader
    assert "step8_golf_direction_clean_$RunDate.xlsx" in daily
    assert '"golf"' in daily or "golf" in daily
    assert "run_grader.ps1" in evening
    assert "step1_fetch_prizepicks_golf.py" in late
    assert "$GOLF_PARALLEL_ACTIVE = $true" in pipe
    assert '"golf"' in refresh

