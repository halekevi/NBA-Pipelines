from combined_slate_tickets import default_soccer_match_date, default_tennis_match_date


def test_soccer_and_tennis_match_date_are_same_day():
    assert default_soccer_match_date("2026-07-14") == "2026-07-14"
    assert default_tennis_match_date("2026-07-14") == "2026-07-14"
    assert default_soccer_match_date("2026-07-14") == default_tennis_match_date("2026-07-14")


def test_tennis_match_date_ignores_clock_offset():
    # Same-day rule: slate date wins even for historical bundles.
    assert default_tennis_match_date("2026-06-01") == "2026-06-01"


def test_soccer_step8_dated_copy_uses_pipeline_date():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "Sports" / "Soccer" / "scripts" / "step8_add_direction_context_soccer.py"
    text = src.read_text(encoding="utf-8")
    assert "date.today()" not in text
    assert "def _copy_dated_step8_soccer(output_xlsx_path: str, slate_date: str)" in text
    assert "_copy_dated_step8_soccer(xlsx_path, target_str)" in text

