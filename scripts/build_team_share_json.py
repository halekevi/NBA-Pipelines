#!/usr/bin/env python3
"""Build team-share JSON artifacts for Matchup Edge / Full Slate enrichment.

Usage:
  python scripts/build_team_share_json.py
  python scripts/build_team_share_json.py --sports wnba,nba,cbb,wcbb
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.team_share import share_artifact_path, write_sport_share

DEFAULT_SPORTS = ["wnba", "nba", "cbb", "wcbb", "mlb", "nhl", "tennis", "soccer", "nfl"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sports", default=",".join(DEFAULT_SPORTS), help="Comma-separated sports")
    ap.add_argument("--repo", default=str(ROOT), help="Repo root")
    args = ap.parse_args()
    repo = Path(args.repo)
    sports = [s.strip().lower() for s in str(args.sports).split(",") if s.strip()]

    for sport in sports:
        try:
            path = write_sport_share(sport, repo)
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("applicable"):
                print(
                    f"[OK] {sport:6} teams={data.get('team_count')} players={data.get('player_count')} "
                    f"props={len(data.get('props') or [])} -> {path.relative_to(repo)}"
                )
            else:
                print(f"[SKIP] {sport:6} {data.get('reason')} -> {path.relative_to(repo)}")
        except Exception as e:
            print(f"[ERR] {sport}: {e}")
            try:
                p = share_artifact_path(sport, repo)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(
                    json.dumps(
                        {
                            "sport": sport,
                            "applicable": False,
                            "reason": str(e),
                            "by_player": {},
                            "team_averages": {},
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
