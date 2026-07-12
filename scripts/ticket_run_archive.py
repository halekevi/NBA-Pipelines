"""
Per-run ticket archives + live playability pruning.

Policy
------
- Every ticket emit is stored immutably under
  ``ui_runner/data/ticket_runs/{date}/{run_id}/tickets.json``.
- ``ui_runner/data/combined_slate_tickets_{date}.json`` is the **grade pool**
  for that slate date (union of runs; never pruned for board churn).
- ``ui_runner/templates/tickets_latest.json`` is the **live / playable** board
  for the site+app; slips whose props left PrizePicks are removed here only.

Grading always reads the dated grade pool / run archives — not the pruned live file.
"""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "ui_runner" / "data" / "ticket_runs"
UI_DATA = ROOT / "ui_runner" / "data"
TEMPLATES = ROOT / "ui_runner" / "templates"


def new_run_id(when: datetime | None = None) -> str:
    dt = when or datetime.now(timezone.utc)
    # Include microseconds so back-to-back emits in the same second stay unique.
    return dt.strftime("%Y%m%d_%H%M%S") + f"_{dt.microsecond:06d}"

def run_dir(date_str: str, run_id: str) -> Path:
    return RUNS_DIR / str(date_str)[:10] / str(run_id)


def index_path(date_str: str) -> Path:
    return RUNS_DIR / str(date_str)[:10] / "index.json"


def grade_pool_path(date_str: str) -> Path:
    return UI_DATA / f"combined_slate_tickets_{date_str[:10]}.json"


def _leg_sig(leg: dict) -> str:
    player = re.sub(r"\s+", " ", str(leg.get("player") or "").strip().lower())
    prop = re.sub(r"\s+", " ", str(leg.get("prop_type") or leg.get("prop") or "").strip().lower())
    direction = str(leg.get("direction") or leg.get("dir") or "OVER").strip().upper()
    if direction == "LOWER":
        direction = "UNDER"
    try:
        line = f"{float(leg.get('line')):.3f}"
    except (TypeError, ValueError):
        line = str(leg.get("line") or "").strip()
    pick = str(leg.get("pick_type") or "standard").strip().lower()
    sport = str(leg.get("sport") or "").strip().upper()
    return f"{sport}|{player}|{prop}|{direction}|{line}|{pick}"


def ticket_leg_sig(ticket: dict) -> str:
    legs = ticket.get("legs") if isinstance(ticket.get("legs"), list) else []
    parts = [_leg_sig(l) for l in legs if isinstance(l, dict)]
    return "||".join(sorted(parts))


def stamp_payload_run(payload: dict, run_id: str, *, source: str = "") -> dict:
    """Attach run metadata to payload + each ticket (in place)."""
    out = payload if isinstance(payload, dict) else {}
    now = datetime.now(timezone.utc).isoformat()
    out["run_id"] = run_id
    out["run_source"] = str(source or out.get("run_source") or "ticket_emit")
    out["run_archived_at"] = now
    if not out.get("generated_at"):
        out["generated_at"] = now
    for g in out.get("groups") or []:
        if not isinstance(g, dict):
            continue
        for t in g.get("tickets") or []:
            if not isinstance(t, dict):
                continue
            t["run_id"] = run_id
            t.setdefault("first_seen_run_id", run_id)
            t["run_archived_at"] = now
            t.setdefault("playable", True)
    return out


def _load_index(date_str: str) -> dict[str, Any]:
    p = index_path(date_str)
    if not p.is_file():
        return {"date": str(date_str)[:10], "runs": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("runs"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"date": str(date_str)[:10], "runs": []}


def _save_index(date_str: str, index: dict[str, Any]) -> None:
    p = index_path(date_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    index["date"] = str(date_str)[:10]
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def archive_ticket_run(
    payload: dict,
    *,
    date_str: str | None = None,
    run_id: str | None = None,
    source: str = "ticket_emit",
) -> dict[str, Any]:
    """
    Write an immutable run snapshot and update the date index.

    Returns meta: {run_id, path, n_slips, n_strong}.
    """
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    d = str(date_str or payload.get("date") or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        raise ValueError(f"invalid date for ticket run archive: {d!r}")
    rid = str(run_id or payload.get("run_id") or new_run_id()).strip()
    stamped = stamp_payload_run(deepcopy(payload), rid, source=source)
    stamped["date"] = d

    dest_dir = run_dir(d, rid)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "tickets.json"
    dest.write_text(json.dumps(stamped, indent=2, ensure_ascii=False), encoding="utf-8")

    n_slips = 0
    n_strong = 0
    for g in stamped.get("groups") or []:
        for t in (g.get("tickets") or []) if isinstance(g, dict) else []:
            if not isinstance(t, dict):
                continue
            n_slips += 1
            if t.get("strong_builder") or "STRONG" in str(g.get("name") or "").upper():
                n_strong += 1

    index = _load_index(d)
    runs = [r for r in index.get("runs") or [] if str(r.get("run_id")) != rid]
    runs.append(
        {
            "run_id": rid,
            "generated_at": stamped.get("generated_at"),
            "archived_at": stamped.get("run_archived_at"),
            "source": source,
            "n_slips": n_slips,
            "n_strong": n_strong,
            "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
        }
    )
    runs.sort(key=lambda r: str(r.get("run_id") or ""))
    index["runs"] = runs
    index["latest_run_id"] = rid
    _save_index(d, index)

    print(f"  [ticket-run] archived run_id={rid} -> {dest} ({n_slips} slips, {n_strong} STRONG)")
    return {
        "run_id": rid,
        "path": str(dest),
        "n_slips": n_slips,
        "n_strong": n_strong,
        "date": d,
    }


def merge_into_grade_pool(
    payload: dict,
    *,
    date_str: str | None = None,
) -> Path:
    """
    Union this run into the dated grade pool JSON used by graders.

    Existing slips are kept; new slips (by ticket_id or leg signature) are appended.
    Tickets keep their ``run_id`` / ``first_seen_run_id``.
    """
    d = str(date_str or payload.get("date") or "").strip()[:10]
    path = grade_pool_path(d)
    path.parent.mkdir(parents=True, exist_ok=True)

    incoming = deepcopy(payload) if isinstance(payload, dict) else {}
    rid = str(incoming.get("run_id") or new_run_id())
    stamp_payload_run(incoming, rid, source=str(incoming.get("run_source") or "grade_pool_merge"))

    if path.is_file():
        try:
            pool = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pool = {}
    else:
        pool = {}

    if not isinstance(pool, dict) or not pool.get("groups"):
        pool = deepcopy(incoming)
        pool["date"] = d
        pool["grade_pool"] = True
        pool["run_ids"] = [rid]
        path.write_text(json.dumps(pool, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  [ticket-run] grade pool created -> {path}")
        return path

    pool["date"] = d
    pool["grade_pool"] = True
    pool["generated_at"] = incoming.get("generated_at") or pool.get("generated_at")
    run_ids = list(pool.get("run_ids") or [])
    if rid not in run_ids:
        run_ids.append(rid)
    pool["run_ids"] = run_ids
    pool["latest_run_id"] = rid

    # Index existing by ticket_id and leg signature.
    existing_ids: set[str] = set()
    existing_sigs: set[str] = set()
    group_by_name: dict[str, dict] = {}
    for g in pool.get("groups") or []:
        if not isinstance(g, dict):
            continue
        name = str(g.get("name") or "")
        group_by_name[name] = g
        for t in g.get("tickets") or []:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("ticket_id") or "").strip()
            if tid:
                existing_ids.add(tid)
            existing_sigs.add(ticket_leg_sig(t))

    added = 0
    for g in incoming.get("groups") or []:
        if not isinstance(g, dict):
            continue
        name = str(g.get("name") or "")
        target = group_by_name.get(name)
        if target is None:
            target = {
                "name": name,
                "sport": g.get("sport"),
                "tickets": [],
            }
            for k, v in g.items():
                if k != "tickets":
                    target[k] = v
            target["tickets"] = []
            pool.setdefault("groups", []).append(target)
            group_by_name[name] = target
        tickets = target.setdefault("tickets", [])
        if not isinstance(tickets, list):
            target["tickets"] = []
            tickets = target["tickets"]
        for t in g.get("tickets") or []:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("ticket_id") or "").strip()
            sig = ticket_leg_sig(t)
            if tid and tid in existing_ids:
                continue
            if sig in existing_sigs:
                continue
            t2 = deepcopy(t)
            t2["run_id"] = rid
            t2.setdefault("first_seen_run_id", rid)
            tickets.append(t2)
            if tid:
                existing_ids.add(tid)
            existing_sigs.add(sig)
            added += 1

    path.write_text(json.dumps(pool, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [ticket-run] grade pool updated -> {path} (+{added} new slips, run_ids={len(run_ids)})")
    return path


def archive_and_merge_grade_pool(
    payload: dict,
    *,
    date_str: str | None = None,
    run_id: str | None = None,
    source: str = "ticket_emit",
) -> dict[str, Any]:
    rid = str(run_id or (payload.get("run_id") if isinstance(payload, dict) else None) or new_run_id())
    if isinstance(payload, dict):
        payload["run_id"] = rid
    meta = archive_ticket_run(
        payload, date_str=date_str, run_id=rid, source=source
    )
    merge_into_grade_pool(payload, date_str=meta["date"])
    return meta


def filter_payload_playable(
    payload: dict,
    playable_ticket_ids: set[str] | None = None,
    unplayable_ticket_ids: set[str] | None = None,
) -> tuple[dict, dict[str, int]]:
    """
    Return a copy of payload with unplayable tickets removed from groups.

    Prefer ``unplayable_ticket_ids`` (explicit removals). If only
    ``playable_ticket_ids`` is set, keep tickets in that set.
    """
    out = deepcopy(payload) if isinstance(payload, dict) else {}
    kept = removed = 0
    new_groups: list[dict] = []
    for g in out.get("groups") or []:
        if not isinstance(g, dict):
            continue
        g2 = dict(g)
        tickets_out: list[dict] = []
        for t in g.get("tickets") or []:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("ticket_id") or "").strip()
            if unplayable_ticket_ids is not None and tid in unplayable_ticket_ids:
                removed += 1
                continue
            if playable_ticket_ids is not None and tid and tid not in playable_ticket_ids:
                removed += 1
                continue
            t2 = dict(t)
            t2["playable"] = True
            tickets_out.append(t2)
            kept += 1
        g2["tickets"] = tickets_out
        if tickets_out:
            new_groups.append(g2)
    out["groups"] = new_groups
    out["live_pruned_at"] = datetime.now(timezone.utc).isoformat()
    out["live_playable_only"] = True
    return out, {"kept": kept, "removed": removed}


def prune_live_tickets_from_capture(
    *,
    tickets_latest: Path | None = None,
    capture_path: Path | None = None,
    date_str: str = "",
) -> dict[str, Any]:
    """
    Remove slips that failed live board capture (props gone) from tickets_latest only.

    Grade pool / run archives are untouched.
    """
    latest = tickets_latest or (TEMPLATES / "tickets_latest.json")
    if not latest.is_file():
        return {"ok": False, "error": f"missing {latest}"}

    d = str(date_str or "").strip()[:10]
    if not d:
        try:
            d = str(json.loads(latest.read_text(encoding="utf-8")).get("date") or "")[:10]
        except (OSError, json.JSONDecodeError):
            d = ""
    cap = capture_path
    if cap is None and d:
        cap = ROOT / "data" / "reports" / f"payout_capture_{d}.json"
    if cap is None or not Path(cap).is_file():
        return {"ok": False, "error": f"missing capture {cap}"}

    capture = json.loads(Path(cap).read_text(encoding="utf-8"))
    unplayable: set[str] = set()
    for rec in capture.get("slips") or []:
        if not isinstance(rec, dict):
            continue
        status = str(rec.get("status") or "").lower()
        err = str(rec.get("error") or "").lower()
        tid = str(rec.get("ticket_id") or "").strip()
        if not tid:
            continue
        # Failed / incomplete board builds ⇒ not playable on PP right now.
        if status in ("failed",) or err.startswith("only_clicked_") or "not found" in err:
            unplayable.add(tid)
        elif status == "ok":
            # Explicitly playable — leave in live set.
            pass

    payload = json.loads(latest.read_text(encoding="utf-8"))
    before = sum(len(g.get("tickets") or []) for g in payload.get("groups") or [])
    pruned, counts = filter_payload_playable(payload, unplayable_ticket_ids=unplayable)
    after = counts["kept"]
    latest.write_text(json.dumps(pruned, indent=2, ensure_ascii=False), encoding="utf-8")

    # Mobile mirror when present.
    mobile = ROOT / "mobile" / "www" / "tickets_latest.json"
    if mobile.parent.is_dir():
        try:
            mobile.write_text(json.dumps(pruned, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    print(
        f"  [ticket-run] live prune: before={before} after={after} "
        f"removed={counts['removed']} (unplayable from capture)"
    )
    return {
        "ok": True,
        "before": before,
        "after": after,
        "removed": counts["removed"],
        "unplayable_ids": sorted(unplayable),
        "path": str(latest),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", metavar="TICKETS_JSON", help="Archive a tickets JSON as a new run")
    ap.add_argument("--date", default="", help="Slate date YYYY-MM-DD")
    ap.add_argument("--source", default="manual", help="run_source label")
    ap.add_argument(
        "--prune-live",
        action="store_true",
        help="Prune tickets_latest.json using payout_capture_{date}.json failures",
    )
    ap.add_argument("--capture", default="", help="Override payout_capture JSON path")
    args = ap.parse_args()

    if args.archive:
        payload = json.loads(Path(args.archive).read_text(encoding="utf-8"))
        archive_and_merge_grade_pool(
            payload,
            date_str=args.date or None,
            source=args.source,
        )
        return 0
    if args.prune_live:
        res = prune_live_tickets_from_capture(
            date_str=args.date,
            capture_path=Path(args.capture) if args.capture else None,
        )
        return 0 if res.get("ok") else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
