#!/usr/bin/env python3
"""Audit live Prop Explorer boards for remaining junk Goblin cards."""
from __future__ import annotations

import json
import re
import ssl
import urllib.request

_SSL = ssl._create_unverified_context()


def load(url: str):
    with urllib.request.urlopen(url, timeout=90, context=_SSL) as r:
        return json.loads(r.read().decode("utf-8"))
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui_runner.app import _filter_slate_explorer_rows  # noqa: E402


def main() -> None:
    home = urllib.request.urlopen(
        "https://web-production-f280f.up.railway.app/", timeout=40, context=_SSL
    ).read().decode("utf-8", "replace")
    m = re.search(r'data-deploy-sha="([^"]+)"', home)
    js = re.search(r"proporacle-home\.js\?v=([^\"&]+)", home)
    print("deploy", m.group(1) if m else None)
    print("homejs", js.group(1) if js else None)

    for sport in ("wnba", "mlb", "tennis", "soccer"):
        j = load(f"https://web-production-f280f.up.railway.app/api/slate-sport/{sport}")
        rows = j.get("rows") or []
        print(f"\n=== {sport.upper()} rows={len(rows)} gen={j.get('generated_at')} ===")
        hard = []
        absurd = []
        for r in rows:
            if str(r.get("pick_type")) != "Goblin":
                continue
            if not str(r.get("dir") or "").upper().startswith("O"):
                continue
            try:
                line = float(r.get("line"))
                std = float(r.get("standard_line") or 0)
                avg = float(r.get("season_avg") or 0)
                proj = float(r.get("projection") or 0)
                edge = float(r.get("edge") or 0)
            except (TypeError, ValueError):
                continue
            base = max(avg, proj)
            if std and line > std + 0.25:
                hard.append((r.get("player"), r.get("prop"), line, std, edge))
            if base > 0 and line > base + 8 and edge < 0:
                absurd.append((r.get("player"), r.get("prop"), line, std, base, edge, r.get("l10_over")))
        print(" API goblin OVER > std_field", len(hard))
        print(" API goblin OVER absurd vs avg/proj", len(absurd))
        for a in sorted(absurd, key=lambda x: -(x[2] - x[4]))[:8]:
            print("  ", a)

        filt = _filter_slate_explorer_rows([dict(r) for r in rows])
        abs2 = []
        for r in filt:
            if str(r.get("pick_type")) != "Goblin":
                continue
            if not str(r.get("dir") or "").upper().startswith("O"):
                continue
            try:
                line = float(r.get("line"))
                avg = float(r.get("season_avg") or 0)
                proj = float(r.get("projection") or 0)
                edge = float(r.get("edge") or 0)
            except (TypeError, ValueError):
                continue
            base = max(avg, proj)
            if base > 0 and line > base + 8 and edge < 0:
                abs2.append((r.get("player"), r.get("prop"), line, base, edge))
        print(" after server filter absurd", len(abs2), "rows", len(filt), "removed", len(rows) - len(filt))
        print(" pick mix API", dict(Counter(str(r.get("pick_type")) for r in rows)))
        print(" pick mix filt", dict(Counter(str(r.get("pick_type")) for r in filt)))

        # Ionescu points specifically
        if sport == "wnba":
            iones = [
                r
                for r in filt
                if "ionescu" in str(r.get("player") or "").lower() and str(r.get("prop")) == "Points"
            ]
            print(" Ionescu Points after filter:")
            for r in sorted(iones, key=lambda x: float(x.get("line") or 0)):
                print(
                    f"  {r.get('pick_type')} {r.get('dir')} {r.get('line')} std={r.get('standard_line')} "
                    f"edge={r.get('edge')} src={r.get('standard_line_source')}"
                )


if __name__ == "__main__":
    main()
