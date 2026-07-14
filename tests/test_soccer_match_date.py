from combined_slate_tickets import default_soccer_match_date, default_tennis_match_date


def test_soccer_match_date_is_same_day_not_tennis_tomorrow():
    assert default_soccer_match_date("2026-07-14") == "2026-07-14"
    # Tennis still rolls to next day for live ET today bundles; soccer must not mirror that.
    tennis = default_tennis_match_date("2026-07-14")
    assert default_soccer_match_date("2026-07-14") != tennis or tennis == "2026-07-14"
