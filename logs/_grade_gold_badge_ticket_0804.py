"""Grade the 2026-08-04 gold-badge manual ticket vs graded_props.

Usage (after games / grader run):
  py -3 logs/_grade_gold_badge_ticket_0804.py
  py -3 logs/_grade_gold_badge_ticket_0804.py --date 2026-08-04
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from grade_strong_builder_tickets import grade_ticket_legs, load_graded  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-04")
    ap.add_argument(
        "--ticket",
        default=str(ROOT / "data/reports/gold_badge_ticket_2026-08-04.json"),
    )
    args = ap.parse_args()

    path = Path(args.ticket)
    if not path.is_file():
        print(f"missing ticket artifact: {path}")
        return 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    ticket = payload.get("ticket") or {}
    legs = ticket.get("legs") or []
    if not legs and payload.get("groups"):
        legs = (((payload["groups"][0] or {}).get("tickets") or [{}])[0]).get("legs") or []

    graded = load_graded(args.date)
    if not graded:
        print(f"{args.date}: no mobile/www/graded_props_{args.date}.json yet — PENDING")
        return 2

    result = grade_ticket_legs(legs, graded)
    print(f"ticket_id={ticket.get('ticket_id') or payload.get('ticket_id')}")
    print(f"n_legs={len(legs)} unique_players={sorted({l.get('player') for l in legs})}")
    print(f"composition={payload.get('composition')} result={result}")

    # per-leg detail
    from grade_strong_builder_tickets import leg_key  # noqa: WPS433

    hits = 0
    misses = 0
    pending = 0
    for leg in legs:
        h = graded.get(leg_key(leg))
        mark = "HIT" if h == 1 else ("MISS" if h == 0 else "PENDING")
        if h == 1:
            hits += 1
        elif h == 0:
            misses += 1
        else:
            pending += 1
        print(
            f"  {mark:7s} {leg.get('player')} {leg.get('direction')} "
            f"{leg.get('line')} {leg.get('prop')} [{leg.get('pick_type')}] "
            f"{leg.get('badge')}"
        )
    print(f"hits={hits} misses={misses} pending={pending}")

    # persist grade back onto artifact
    payload.setdefault("result", {})
    payload["result"].update(
        {
            "status": result,
            "graded_at_date": args.date,
            "hits": hits,
            "misses": misses,
            "pending": pending,
        }
    )
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated {path}")
    return 0 if result in ("WIN", "LOSS", "VOID") else 2


if __name__ == "__main__":
    raise SystemExit(main())
