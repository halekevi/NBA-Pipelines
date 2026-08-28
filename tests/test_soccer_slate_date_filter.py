"""Soccer slate must not fall back to tomorrow's props under today's grade date."""

from __future__ import annotations

import pandas as pd
from scripts.soccer_grader_advanced import (
    filter_soccer_slate_by_date,
    normalize_soccer_slate_columns,
)


def test_filter_soccer_slate_empty_when_all_rows_are_other_day():
    slate = normalize_soccer_slate_columns(
        pd.DataFrame(
            {
                "Player": ["A", "B"],
                "Prop": ["Shots", "Shots"],
                "Line": [1.5, 2.5],
                "Game Time": ["07/14 3:00 PM", "07/14 3:00 PM"],
            }
        )
    )
    out = filter_soccer_slate_by_date(slate, "2026-07-13")
    assert out.empty


def test_filter_soccer_slate_keeps_matching_day():
    slate = normalize_soccer_slate_columns(
        pd.DataFrame(
            {
                "Player": ["A", "B"],
                "Prop": ["Shots", "Shots"],
                "Line": [1.5, 2.5],
                "Game Time": ["07/14 3:00 PM", "07/13 8:00 PM"],
            }
        )
    )
    out = filter_soccer_slate_by_date(slate, "2026-07-14")
    assert len(out) == 1
    assert str(out.iloc[0]["player"]) == "A"
