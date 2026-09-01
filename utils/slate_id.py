"""Pipeline slate date (ET calendar day). Never fall back to the wall clock.

Dated copies, step8 filters, and status JSON must use ``--date`` / ``-Date``.
``date.today()`` dumps a night-ahead board into the wrong folder when the
pipeline runs on the previous evening.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ISO_YMD = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_pipeline_ymd(raw: object) -> str | None:
    """Return YYYY-MM-DD or None. Does not use the clock."""
    s = str(raw or "").strip()[:10]
    return s if _ISO_YMD.match(s) else None


@dataclass(frozen=True)
class SlateId:
    """Canonical slate key for one pipeline run."""

    et_date: str

    @classmethod
    def from_pipeline_date(cls, raw: object) -> SlateId | None:
        d = parse_pipeline_ymd(raw)
        return cls(et_date=d) if d else None


def dated_copy_ymd(raw: object, *, context: str) -> str | None:
    """Folder date for ``outputs/<date>/``. Skip (do not use today) if missing."""
    d = parse_pipeline_ymd(raw)
    if not d:
        print(f"[{context}] WARN: no pipeline --date — skipping dated copy")
    return d
