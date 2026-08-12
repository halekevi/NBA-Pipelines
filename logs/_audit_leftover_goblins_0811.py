#!/usr/bin/env python3
"""List remaining Goblin OVERs still harder than resolved Standard."""
from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui_runner.app import _filter_slate_explorer_rows  # noqa: E402

_SSL = ssl._create_unverified_context()


def load(url: str):
    with urllib.request.urlopen(url, timeout=90, context=_SSL) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    for sport in ("wnba", "mlb", "tennis"):
        rows = load(f"https://web-production-f280f.up.railway.app/api/slate-sport/{sport}").get("rows") or []
        filt = _filter_slate_explorer_rows([dict(r) for r in rows])
        leftover = []
        for r in filt:
            if str(r.get("pick_type")) != "Goblin":
                continue
            if not str(r.get("dir") or "").upper().startswith("O"):
                continue
            try:
                line = float(r.get("line"))
                std = float(r.get("standard_line") or 0)
                edge = float(r.get("edge") or 0)
            except (TypeError, ValueError):
                continue
            if std and line > std + 0.25:
                leftover.append(
                    (
                        r.get("player"),
                        r.get("prop"),
                        line,
                        std,
                        edge,
                        r.get("season_avg"),
                        r.get("projection"),
                        r.get("l10_over"),
                    )
                )
        leftover.sort(key=lambda x: -(x[2] - x[3]))
        print(f"\n{sport.upper()} leftover goblin OVER > resolved std: {len(leftover)}")
        for a in leftover[:20]:
            print(" ", a)


if __name__ == "__main__":
    main()
