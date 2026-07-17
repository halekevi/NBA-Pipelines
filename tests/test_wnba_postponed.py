#!/usr/bin/env python3
"""WNBA postponed schedule helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from wnba_postponed import (  # noqa: E402
    _event_is_postponed_or_canceled,
    _team_abbrs_for_event,
    apply_wnba_postponed_void_labels,
    relabel_void_reason_if_postponed,
)


def test_event_postponed_detection():
    ev = {
        "shortName": "NY @ DAL",
        "status": {"type": {"name": "STATUS_POSTPONED", "description": "Postponed"}},
        "competitions": [
            {
                "competitors": [
                    {"team": {"abbreviation": "NY"}},
                    {"team": {"abbreviation": "DAL"}},
                ]
            }
        ],
    }
    assert _event_is_postponed_or_canceled(ev)
    assert _team_abbrs_for_event(ev) == {"NYL", "DAL"}


def test_relabel_void_reason():
    labels = {"DAL": "POSTPONED · NY @ DAL", "NYL": "POSTPONED · NY @ DAL"}
    out = relabel_void_reason_if_postponed(
        sport="WNBA",
        team="DAL",
        opp_team="NYL",
        void_reason="NO_ACTUAL",
        result="VOID",
        iso_date="2026-07-16",
        team_labels=labels,
    )
    assert out.startswith("POSTPONED")
    # DNP untouched
    out2 = relabel_void_reason_if_postponed(
        sport="WNBA",
        team="DAL",
        void_reason="INJURY_REPORT_DNP",
        result="VOID",
        iso_date="2026-07-16",
        team_labels=labels,
    )
    assert out2 == "INJURY_REPORT_DNP"


def test_apply_dataframe_labels():
    import pandas as pd

    df = pd.DataFrame(
        [
            {"team": "DAL", "result": "VOID", "void_reason_grade": "NO_ACTUAL", "actual": None},
            {"team": "WAS", "result": "VOID", "void_reason_grade": "NO_ACTUAL", "actual": None},
            {"team": "DAL", "result": "HIT", "void_reason_grade": "", "actual": 5},
        ]
    )
    # Monkeypatch lookup via apply with pre-known labels by patching module
    import wnba_postponed as mod

    orig = mod.wnba_postponed_team_labels_for_date
    mod.wnba_postponed_team_labels_for_date = lambda _d: {
        "DAL": "POSTPONED · NY @ DAL",
        "NYL": "POSTPONED · NY @ DAL",
    }
    try:
        n = apply_wnba_postponed_void_labels(df, "2026-07-16")
    finally:
        mod.wnba_postponed_team_labels_for_date = orig
    assert n == 1
    assert str(df.loc[0, "void_reason_grade"]).startswith("POSTPONED")
    assert df.loc[1, "void_reason_grade"] == "NO_ACTUAL"
