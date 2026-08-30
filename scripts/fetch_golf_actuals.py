#!/usr/bin/env python3
"""Build actuals_golf_YYYY-MM-DD.csv for combined_ticket_grader (ESPN PGA rounds)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
_GOLF_SCRIPTS = ROOT / "Sports" / "Golf" / "scripts"
if str(_GOLF_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_GOLF_SCRIPTS))

from golf_actuals import actuals_rows_for_date, load_golf_round_cache  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="Round calendar day YYYY-MM-DD")
    ap.add_argument("--output", required=True, help="Path to actuals_golf_YYYY-MM-DD.csv")
    ap.add_argument("--refresh-cache", action="store_true")
    args = ap.parse_args()

    target = str(args.date).strip()[:10]
    cache = load_golf_round_cache(force_refresh=bool(args.refresh_cache))
    rows = actuals_rows_for_date(cache, target)
    out = Path(args.output)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["player", "team", "prop_type", "actual", "round", "round_date"])
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[Golf actuals] {target}: {len(df)} rows -> {out}")


if __name__ == "__main__":
    main()
