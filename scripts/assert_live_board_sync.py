#!/usr/bin/env python3
"""Fail when published tickets_latest lags slate_latest (or today's ET slate).

Used by daily STEP E, push_live_to_main, and mid-day refresh so Railway cannot
ship a today explorer board with yesterday / tennis-only leftover slips.

Exit codes:
  0  tickets date matches slate date (and is today when slate is today)
  1  I/O or usage error
  2  tickets lag slate / today — do not git-push live JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ymd10(value: Any) -> str:
    text = str(value or "").strip()[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return ""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _group_sports(payload: dict[str, Any]) -> list[str]:
    sports: set[str] = set()
    known = ("MLB", "WNBA", "NBA", "NHL", "TENNIS", "SOCCER", "CBB", "WCBB", "NFL", "CFB", "GOLF")
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return []
    for group in groups:
        if not isinstance(group, dict):
            continue
        raw = str(group.get("sport") or group.get("Sport") or "").strip().upper()
        if raw:
            sports.add(raw)
        name = str(group.get("group_name") or group.get("name") or "").upper()
        for token in known:
            if token in name:
                sports.add(token)
        tickets = group.get("tickets") if isinstance(group.get("tickets"), list) else []
        legs = list(group.get("legs") or group.get("picks") or [])
        for ticket in tickets:
            if isinstance(ticket, dict):
                legs.extend(ticket.get("legs") or ticket.get("picks") or [])
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            ls = str(leg.get("sport") or leg.get("Sport") or "").strip().upper()
            if ls:
                sports.add(ls)
    return sorted(sports)


def _slate_sports(payload: dict[str, Any]) -> list[str]:
    sports = payload.get("sports")
    if not isinstance(sports, dict):
        return []
    out: list[str] = []
    for key, rows in sports.items():
        if isinstance(rows, list) and rows:
            out.append(str(key).strip().upper())
    return sorted(set(out))


def inspect_live_board(
    templates_dir: Path,
    today: str = "",
) -> dict[str, Any]:
    tickets = _load_json(templates_dir / "tickets_latest.json")
    slate = _load_json(templates_dir / "slate_latest.json")
    tickets_date = _ymd10(tickets.get("date"))
    slate_date = _ymd10(slate.get("date"))
    ticket_sports = _group_sports(tickets)
    slate_sports = _slate_sports(slate)
    groups = tickets.get("groups")
    group_n = len(groups) if isinstance(groups, list) else 0

    reason = ""
    ok = True
    if not tickets_date and not slate_date:
        reason = "missing tickets_latest.json and slate_latest.json dates"
        ok = False
    elif not tickets_date:
        reason = f"tickets_latest.json has no date (slate={slate_date or 'missing'})"
        ok = False
    elif slate_date and tickets_date < slate_date:
        reason = f"tickets {tickets_date} lag slate {slate_date}"
        ok = False
    elif today and slate_date == today and tickets_date < today:
        reason = f"tickets {tickets_date} lag today {today} (slate is today)"
        ok = False
    elif today and tickets_date and tickets_date < today and slate_date and slate_date < today:
        # Both yesterday: explorer + tickets agree; not a skew. Daily may still
        # want a rebuild, but a push would not *create* the mixed-date bug.
        reason = ""
        ok = True

    missing_on_tickets = [
        s for s in slate_sports if s in {"MLB", "WNBA", "SOCCER", "TENNIS", "NBA", "NHL"} and s not in ticket_sports
    ]
    warn = ""
    if ok and today and tickets_date == today and missing_on_tickets and group_n > 0:
        warn = (
            f"tickets {tickets_date} cover {ticket_sports or ['(none)']} but slate "
            f"has {missing_on_tickets}"
        )

    return {
        "ok": ok,
        "reason": reason,
        "warn": warn,
        "today": today,
        "tickets_date": tickets_date,
        "slate_date": slate_date,
        "ticket_sports": ticket_sports,
        "slate_sports": slate_sports,
        "ticket_groups": group_n,
        "tickets_path": str(templates_dir / "tickets_latest.json"),
        "slate_path": str(templates_dir / "slate_latest.json"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--today", default="", help="YYYY-MM-DD (ET today). Optional extra lag check.")
    ap.add_argument(
        "--templates-dir",
        default="",
        help="Directory with tickets_latest.json + slate_latest.json",
    )
    ap.add_argument("--json", action="store_true", help="Print inspect payload as JSON")
    args = ap.parse_args(argv)

    templates = Path(args.templates_dir) if args.templates_dir else (REPO_ROOT / "ui_runner" / "templates")
    info = inspect_live_board(templates, today=str(args.today or "").strip()[:10])
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        td = info.get("tickets_date") or "?"
        sd = info.get("slate_date") or "?"
        sports = ",".join(info.get("ticket_sports") or []) or "(none)"
        print(f"tickets={td} slate={sd} groups={info.get('ticket_groups')} sports={sports}")
        if info.get("reason"):
            print(f"FAIL: {info['reason']}")
        if info.get("warn"):
            print(f"WARN: {info['warn']}")
        if info.get("ok"):
            print("OK: live tickets/slate dates are in sync")
    if not info.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
