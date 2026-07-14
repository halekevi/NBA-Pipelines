"""Ticket-eval track + group allow for STRONG Standard HOT shadow."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_ticket_eval import (  # noqa: E402
    _group_is_allowed,
    _group_is_strong_standard_hot,
    _normalize_eval_track,
)


def test_normalize_eval_track_strong_standard_shadow():
    assert _normalize_eval_track("strong_standard_shadow") == "strong_standard_shadow"
    assert _normalize_eval_track("strong-standard-hot") == "strong_standard_shadow"


def test_group_is_strong_standard_hot_names():
    assert _group_is_strong_standard_hot("STRONG Standard HOT")
    assert _group_is_strong_standard_hot("STRONG Standard HOT 3-Leg")
    assert not _group_is_strong_standard_hot("STRONG 3-Leg")
    assert not _group_is_strong_standard_hot("STRONG Goblin HOT")


def test_group_allowed_for_strong_standard_hot():
    assert _group_is_allowed("STRONG Standard HOT", pool_mode="strong_standard_shadow")
    assert _group_is_allowed("STRONG Standard HOT 2-Leg", pool_mode="")
