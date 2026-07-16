#!/usr/bin/env python3
"""
Build Matchup Edge JSON for Slate Explorer (all supported sports).

Each sport emits top-5 + bottom-5 leaders per team/category (leader_slice in JSON).
WNBA/NBA/NHL/MLB use dedicated builders; nba1h/nba1q/soccer/cbb/cfb/nfl use the generic path.

One sport failing (e.g. NHL off-season missing defense CSV) must NOT abort the rest —
otherwise MLB/WNBA/Tennis panels go stale until the next successful full run.

  py -3 scripts/build_matchup_edge_json.py
  py -3 scripts/build_matchup_edge_json.py --sport nba
  py -3 scripts/build_matchup_edge_json.py --sport all
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.matchup_edge.builder import build_matchup_payload, publish_payload  # noqa: E402
from utils.matchup_edge.sports_config import ENABLED_SPORTS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="all", help=f"Sport key or 'all'. Enabled: {', '.join(ENABLED_SPORTS)}")
    ap.add_argument("--slate", default="", help="Optional slate CSV/JSON path")
    args = ap.parse_args()

    sports = list(ENABLED_SPORTS) if args.sport.lower() == "all" else [args.sport.lower().strip()]
    slate = Path(args.slate) if args.slate else None

    ok = 0
    failed: list[str] = []
    for sport in sports:
        try:
            payload = build_matchup_payload(sport, slate_path=slate)
            paths = publish_payload(payload, sport, _REPO)
            n_blocks = len(payload.get("players_by_team_cat") or {})
            err = payload.get("error")
            if err:
                print(f"[{sport}] WARN: {err}")
                # Soft error payload still published (empty / off-season). Count as ok for pipeline.
            print(f"[{sport}] blocks={n_blocks} -> {paths[0].name}")
            ok += 1
        except Exception as e:
            failed.append(sport)
            print(f"[{sport}] FAILED: {e}", file=sys.stderr)
            traceback.print_exc()

    if failed:
        print(
            f"[matchup-edge] completed with failures: {', '.join(failed)} "
            f"(ok={ok}/{len(sports)}). Other sports were published.",
            file=sys.stderr,
        )
    # Pipeline must not treat a single off-season crash as total failure.
    # Exit 1 only when every requested sport failed.
    if ok == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
