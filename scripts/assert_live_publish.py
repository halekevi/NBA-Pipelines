#!/usr/bin/env python3
"""Guard live tickets/slate JSON before Publish-LiveSite.ps1.

Syncs runtime/ <-> templates/, refreshes pipeline_status from slate_latest,
and refuses Goblin-only or mixer-only tickets_latest.json.

  py -3.14 scripts/assert_live_publish.py --root H:\\PropORACLE_main_cp --fix
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.ui_live_json import (  # noqa: E402
    dual_card_errors,
    refresh_pipeline_status_from_slate,
    sync_live_json_pairs,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="", help="Repo root (default: this checkout)")
    ap.add_argument(
        "--fix",
        action="store_true",
        help="Copy newer runtime/templates pairs and refresh pipeline_status.json",
    )
    args = ap.parse_args()
    root = Path(args.root).resolve() if str(args.root).strip() else _REPO
    if not root.is_dir():
        print(f"[assert-live] FAILED: not a directory: {root}", file=sys.stderr)
        return 1
    if args.fix:
        synced = sync_live_json_pairs(root)
        if synced:
            print(f"[assert-live] synced {', '.join(synced)}")
        status = refresh_pipeline_status_from_slate(root)
        if status:
            print(f"[assert-live] pipeline_status <- {status}")
    errors = dual_card_errors(root)
    if errors:
        for err in errors:
            print(f"[assert-live] FAILED: {err}", file=sys.stderr)
        print(
            "[assert-live] need Goblin-70 groups first then mixer; "
            "runtime/templates dates must match. "
            "Set PROPORACLE_ALLOW_PARTIAL_TICKETS=1 to override.",
            file=sys.stderr,
        )
        return 1
    print("[assert-live] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
