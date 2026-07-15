from combined_slate_tickets import default_soccer_match_date, default_tennis_match_date


def test_soccer_and_tennis_match_date_are_same_day():
    assert default_soccer_match_date("2026-07-14") == "2026-07-14"
    assert default_tennis_match_date("2026-07-14") == "2026-07-14"
    assert default_soccer_match_date("2026-07-14") == default_tennis_match_date("2026-07-14")


def test_tennis_match_date_ignores_clock_offset():
    # Same-day rule: slate date wins even for historical bundles.
    assert default_tennis_match_date("2026-06-01") == "2026-06-01"
