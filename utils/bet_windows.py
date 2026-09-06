"""Slate-day bet windows: line pulls + payout scrapes with timestamps.

Used to see when lines and N-correct floors moved (1AM / 8AM / 9AM / 9:45 /
10:30 / 1PM / 4:30). Never uses 1st-place multipliers.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
LINE_DB = ROOT / "data" / "line_history.db"
REPORTS = ROOT / "data" / "reports"
CACHE_DIR = ROOT / "data" / "cache"
LINE_WINDOW_CACHE = CACHE_DIR / "last_line_window.json"
STAMP_TEMPLATES = ROOT / "ui_runner" / "templates" / "last_fetch_window.json"
STAMP_RUNTIME = ROOT / "ui_runner" / "runtime" / "last_fetch_window.json"

WINDOWS: tuple[tuple[int, int, str], ...] = (
    (1, 0, "1AM"),
    (8, 0, "8AM"),
    (9, 0, "9AM"),
    (9, 45, "9:45"),
    (10, 30, "10:30"),
    (13, 0, "1PM"),
    (16, 30, "4:30"),
)

# Scheduled-job labels (1AM / 8AM included) so a long run still buckets correctly.
WINDOW_ALIASES: dict[str, str] = {
    "1AM": "1AM",
    "DAILY1AM": "1AM",
    "5AM": "5AM",
    "8AM": "8AM",
    "DAILY8AM": "8AM",
    "9AM": "9AM",
    "945AM": "9:45",
    "9:45": "9:45",
    "1030AM": "10:30",
    "10:30": "10:30",
    "1PM": "1PM",
    "13:00": "1PM",
    "430PM": "4:30",
    "4:30": "4:30",
}


def now_et_iso() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def parse_et(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def normalize_window_label(raw: object) -> str:
    key = str(raw or "").strip().upper().replace(" ", "").replace("-", "")
    return WINDOW_ALIASES.get(key, "")


def window_label(raw: object) -> str:
    dt = parse_et(raw)
    if dt is None:
        return "other"
    mins = dt.hour * 60 + dt.minute
    best = min(WINDOWS, key=lambda w: abs((w[0] * 60 + w[1]) - mins))
    if abs((best[0] * 60 + best[1]) - mins) > 50:
        return dt.strftime("%H:%M")
    return best[2]


def job_window_label(captured_at: object = None, *, explicit: object = None) -> str:
    """Prefer the scheduled job (1AM / 8AM / …) over clock rounding."""
    import os

    for cand in (explicit, os.environ.get("PROPORACLE_BET_WINDOW")):
        named = normalize_window_label(cand)
        if named:
            return named
    return window_label(captured_at)


def scrape_log_path(date: str) -> Path:
    return REPORTS / f"payout_scrape_log_{date}.jsonl"


def append_payout_scrape_log(
    date: str,
    captured: list[dict[str, Any]],
    *,
    captured_at: str | None = None,
) -> int:
    """Append one JSONL row per ok/partial slip. Returns rows written."""
    date_s = str(date or "")[:10]
    if not date_s:
        return 0
    stamp = captured_at or now_et_iso()
    REPORTS.mkdir(parents=True, exist_ok=True)
    n = 0
    with scrape_log_path(date_s).open("a", encoding="utf-8") as fh:
        for rec in captured or []:
            if not isinstance(rec, dict):
                continue
            if str(rec.get("status") or "").lower() not in {"ok", "partial"}:
                continue
            try:
                px = float(rec.get("power_min_x") or rec.get("power_payout_x") or 0)
            except (TypeError, ValueError):
                continue
            if not (px > 0):
                continue
            at = str(rec.get("captured_at") or stamp)
            win = job_window_label(at, explicit=rec.get("window"))
            legs = rec.get("legs") if isinstance(rec.get("legs"), list) else []
            lines = []
            for leg in legs:
                if not isinstance(leg, dict):
                    continue
                lines.append(
                    {
                        "player": str(leg.get("player") or "").strip(),
                        "prop": str(leg.get("prop_type") or leg.get("prop") or "").strip(),
                        "line": leg.get("line"),
                        "pick_type": str(leg.get("pick_type") or "").strip(),
                        "standard_line": leg.get("standard_line"),
                    }
                )
            row = {
                "captured_at": at,
                "window": win,
                "ticket_id": str(rec.get("ticket_id") or ""),
                "n_legs": rec.get("n_legs") or len(lines),
                "power_min_x": px,
                "flex_n_correct": rec.get("flex_n_correct") or {},
                "lines": lines,
                "source": "live_cdp",
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def _line_pulls(date: str) -> list[dict[str, Any]]:
    if not LINE_DB.is_file():
        return []
    pulls: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(LINE_DB) as conn:
            conn.row_factory = sqlite3.Row
            has_game = any(
                r[1] == "game_date"
                for r in conn.execute("PRAGMA table_info(line_history)").fetchall()
            )
            if has_game:
                q = (
                    "SELECT fetched_at, COUNT(*) AS n FROM line_history "
                    "WHERE substr(CAST(fetched_at AS TEXT),1,10)=? OR CAST(game_date AS TEXT)=? "
                    "GROUP BY fetched_at ORDER BY fetched_at"
                )
                fetch_rows = conn.execute(q, (date, date)).fetchall()
            else:
                fetch_rows = conn.execute(
                    "SELECT fetched_at, COUNT(*) AS n FROM line_history "
                    "WHERE substr(CAST(fetched_at AS TEXT),1,10)=? "
                    "GROUP BY fetched_at ORDER BY fetched_at",
                    (date,),
                ).fetchall()
            moved: dict[str, int] = {}
            try:
                for r in conn.execute(
                    "SELECT fetched_at, COUNT(*) AS n FROM line_events "
                    "WHERE event='moved' AND (game_date=? OR substr(CAST(fetched_at AS TEXT),1,10)=?) "
                    "GROUP BY fetched_at",
                    (date, date),
                ):
                    moved[str(r["fetched_at"])] = int(r["n"] or 0)
            except sqlite3.OperationalError:
                moved = {}
            for r in fetch_rows:
                ts = str(r["fetched_at"] or "")
                pulls.append(
                    {
                        "fetched_at": ts,
                        "window": window_label(ts),
                        "n_props": int(r["n"] or 0),
                        "n_moved": int(moved.get(ts) or 0),
                    }
                )
    except sqlite3.Error:
        return []
    return pulls


def _payout_windows(date: str) -> list[dict[str, Any]]:
    path = scrape_log_path(date)
    if not path.is_file():
        return []
    by_win: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            win = str(rec.get("window") or window_label(rec.get("captured_at")))
            bucket = by_win.setdefault(
                win,
                {
                    "window": win,
                    "n_scrapes": 0,
                    "power_xs": [],
                    "first_captured_at": rec.get("captured_at"),
                    "last_captured_at": rec.get("captured_at"),
                },
            )
            bucket["n_scrapes"] += 1
            try:
                bucket["power_xs"].append(float(rec.get("power_min_x")))
            except (TypeError, ValueError):
                pass
            at = str(rec.get("captured_at") or "")
            if at and (
                not bucket.get("first_captured_at")
                or at < str(bucket.get("first_captured_at") or "")
            ):
                bucket["first_captured_at"] = at
            if at and at > str(bucket.get("last_captured_at") or ""):
                bucket["last_captured_at"] = at
    out = []
    for win, b in by_win.items():
        xs = [x for x in b["power_xs"] if math.isfinite(x) and x > 0]
        xs.sort()
        med = xs[len(xs) // 2] if xs else None
        out.append(
            {
                "window": win,
                "n_scrapes": b["n_scrapes"],
                "median_power_x": med,
                "min_power_x": xs[0] if xs else None,
                "max_power_x": xs[-1] if xs else None,
                "first_captured_at": b["first_captured_at"],
                "last_captured_at": b["last_captured_at"],
            }
        )
    order = {w[2]: i for i, w in enumerate(WINDOWS)}
    out.sort(key=lambda r: (order.get(str(r["window"]), 99), str(r.get("first_captured_at") or "")))
    return out


def rebuild_bet_windows(date: str | None = None) -> dict[str, Any]:
    date_s = str(date or datetime.now(ET).strftime("%Y-%m-%d"))[:10]
    payload = {
        "date": date_s,
        "generated_at": now_et_iso(),
        "line_pulls": _line_pulls(date_s),
        "payout_scrapes": _payout_windows(date_s),
        "note": "N-correct / To Win only. Line pulls from line_history.db; payouts from CDP jsonl.",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    dated = REPORTS / f"bet_windows_{date_s}.json"
    latest = REPORTS / "bet_windows_latest.json"
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    dated.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return payload


def summarize_fetch_window(
    date: str | None = None,
    window: str | None = None,
) -> dict[str, Any]:
    """Did this scheduled window stamp lines, and should payout Force run?

    Line timestamps are recorded on every fetch (including n_moved=0).
    Force payout when this is the day's first stamp, or this window moved
    lines vs the previous pull (changes off the last / initial stamp).
    """
    date_s = str(date or datetime.now(ET).strftime("%Y-%m-%d"))[:10]
    win = normalize_window_label(window) or job_window_label()
    pulls = _line_pulls(date_s)
    this = [p for p in pulls if str(p.get("window") or "") == win]
    n_moved_this = sum(int(p.get("n_moved") or 0) for p in this)
    initial = pulls[0] if pulls else None
    latest = pulls[-1] if pulls else None
    is_initial = False
    if this and pulls:
        is_initial = str(pulls[0].get("fetched_at") or "") == str(this[0].get("fetched_at") or "")
    elif pulls and not this:
        is_initial = False
    else:
        is_initial = True
    n_moved_from_initial = 0
    if pulls and not is_initial:
        n_moved_from_initial = sum(int(p.get("n_moved") or 0) for p in pulls[1:])
    no_pulls = not pulls
    if not this and pulls:
        this = [p for p in pulls if str(p.get("fetched_at") or "") == str(pulls[-1].get("fetched_at") or "")]
        n_moved_this = sum(int(p.get("n_moved") or 0) for p in this)
        is_initial = len({str(p.get("fetched_at") or "") for p in pulls}) == 1
    force_payout = bool(no_pulls or is_initial or n_moved_this > 0)
    if not _payout_windows(date_s):
        force_payout = True
    return {
        "date": date_s,
        "window": win or "other",
        "generated_at": now_et_iso(),
        "n_pulls_this_window": len(this),
        "n_moved_this_window": n_moved_this,
        "n_moved_from_initial": n_moved_from_initial,
        "is_initial_stamp": is_initial or no_pulls,
        "force_payout": force_payout,
        "rebuild_tickets": force_payout,
        "latest_fetched_at": str((latest or {}).get("fetched_at") or ""),
        "initial_fetched_at": str((initial or {}).get("fetched_at") or ""),
    }


def write_fetch_window_stamp(summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist last_line_window.json + last_fetch_window.json for live publish."""
    payload = dict(summary or summarize_fetch_window())
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LINE_WINDOW_CACHE.write_text(text, encoding="utf-8")
    for dest in (STAMP_TEMPLATES, STAMP_RUNTIME):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return payload
