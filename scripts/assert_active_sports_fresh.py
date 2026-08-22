#!/usr/bin/env python3
"""Hard gate: every *active* sport for the ET slate day must be FRESH.

Mirrors home-page /api/pipeline/status freshness signals:
  - slate_latest.json row counts (PENDING when empty)
  - generated_at / date wall-clock converted to US Eastern calendar day
  - strict game_day props for MLB/WNBA/Soccer/Tennis (+ NBA1H/1Q/NHL/NFL when in season)

"Active / expected" uses pipeline_slate_status.json first:
  - off_season  → skip (not expected; e.g. summer NBA/NHL)
  - no_slate    → skip when step1 fetch is empty (intentional empty PP board)
  - complete    → must be FRESH on published slate
  - failed      → FAIL (sport was supposed to run)
  - missing status for an in-season summer sport → expected (catch partial publish)

Also expect a sport when step1 CSV has props, even if status is missing.

Exit codes:
  0  all expected sports FRESH (or none expected)
  1  I/O / usage error
  2  one or more expected sports PENDING / STALE / failed pipeline
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")

# Match run_pipeline.ps1 / proporacle-home.js season gates (summer 2026).
NBA_SEASON_RESUME = "2026-10-01"
NHL_SEASON_RESUME = "2026-09-01"
NFL_SEASON_RESUME = "2026-08-13"  # match run_pipeline.ps1; override via PROPORACLE_NFL_RESUME
WNBA_SEASON_START = "2026-05-01"
WNBA_ALLSTAR_PAUSE_START = "2026-07-19"
WNBA_SEASON_RESUME = "2026-07-28"

# Core summer set always considered for the gate when in season.
# NFL/CFB scaffolding can show failed/no_slate without killing the summer daily.
SUMMER_CORE = ("mlb", "soccer", "tennis", "wnba")
# Added only after season resume dates (not summer scaffolding).
WINTER_CORE = ("nba", "nba1h", "nba1q", "nhl")

# Site SLATE_STRICT_GAME_DAY_SPORTS + tennis.
STRICT_GAME_DAY = frozenset({"nhl", "nfl", "mlb", "nba1h", "nba1q", "soccer", "wnba", "tennis"})

STEP1_CANDIDATES: dict[str, tuple[str, ...]] = {
    "mlb": (
        "outputs/{d}/mlb/step1_mlb_props.csv",
        "Sports/MLB/step1_mlb_props.csv",
    ),
    "soccer": (
        "outputs/{d}/soccer/step1_soccer_props.csv",
        "Sports/Soccer/outputs/step1_soccer_props.csv",
        "Sports/Soccer/step1_soccer_props.csv",
    ),
    "tennis": (
        "outputs/{d}/tennis/step1_tennis_props.csv",
        "Sports/Tennis/outputs/step1_tennis_props.csv",
        "Sports/Tennis/step1_tennis_props.csv",
    ),
    "wnba": (
        "outputs/{d}/wnba/step1_wnba_props.csv",
        "Sports/WNBA/step1_wnba_props.csv",
    ),
    "nba": (
        "outputs/{d}/nba/step1_pp_props_today.csv",
        "Sports/NBA/step1_pp_props_today.csv",
    ),
    "nhl": (
        "outputs/{d}/nhl/step1_nhl_props.csv",
        "Sports/NHL/outputs/step1_nhl_props.csv",
    ),
    "nfl": (
        "outputs/{d}/nfl/step1_nfl_props.csv",
        "Sports/NFL/outputs/step1_nfl_props.csv",
    ),
}


def _env_ymd(name: str, default: str) -> str:
    import os

    raw = (os.environ.get(name) or "").strip()
    return raw[:10] if len(raw) >= 10 else default


def eastern_today_ymd(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(ET).date().strftime("%Y-%m-%d")


def ymd_in_eastern(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date().strftime("%Y-%m-%d")


def parse_pipeline_modified_as_utc(s: str) -> datetime | None:
    """Match proporacle-home.js parsePipelineModifiedAsUtc (UTC wall clock)."""
    import re

    m = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})",
        (s or "").strip(),
    )
    if not m:
        return None
    return datetime(
        int(m.group(1)),
        int(m.group(2)),
        int(m.group(3)),
        int(m.group(4)),
        int(m.group(5)),
        int(m.group(6)),
        tzinfo=timezone.utc,
    )


def _ymd10(value: Any) -> str | None:
    text = str(value or "").strip()[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _csv_has_data_rows(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for _ in reader:
                return True
    except Exception:
        return False
    return False


def step1_has_props(repo: Path, sport: str, run_date: str) -> bool:
    for rel in STEP1_CANDIDATES.get(sport, ()):
        p = repo / rel.format(d=run_date)
        if _csv_has_data_rows(p):
            return True
    return False


def in_season_candidates(today: str) -> list[str]:
    """Sports that *could* be active today for the hard gate.

    Summer daily focuses on MLB/Soccer/Tennis/WNBA. NBA/NHL join after resume.
    NFL is only considered when status/fetch says it actually ran (see resolve_expected).
    """
    wnba_pause_start = _env_ymd("WNBA_PAUSE_START", WNBA_ALLSTAR_PAUSE_START)
    wnba_resume = _env_ymd(
        "WNBA_RESUME_DATE",
        _env_ymd("PROPORACLE_WNBA_RESUME", WNBA_SEASON_RESUME),
    )
    nba_resume = _env_ymd("NBA_SEASON_RESUME", NBA_SEASON_RESUME)
    nhl_resume = _env_ymd("NHL_SEASON_RESUME", NHL_SEASON_RESUME)

    out: list[str] = ["mlb", "soccer", "tennis"]
    wnba_off = wnba_pause_start <= today < wnba_resume
    if today >= WNBA_SEASON_START and not wnba_off:
        out.append("wnba")
    if today >= nba_resume:
        out.extend(["nba", "nba1h", "nba1q"])
    if today >= nhl_resume:
        out.append("nhl")
    return out


def load_pipeline_status(repo: Path, run_date: str) -> dict[str, str]:
    path = repo / "outputs" / run_date / "pipeline_slate_status.json"
    payload = _load_json(path)
    sports = payload.get("sports") or {}
    if not isinstance(sports, dict):
        return {}
    return {str(k).lower(): str(v or "").strip().lower() for k, v in sports.items()}


def slate_rows(slate: dict[str, Any], sport: str) -> list[dict[str, Any]]:
    sports = slate.get("sports") or {}
    if not isinstance(sports, dict):
        return []
    key = sport.lower()
    rows = sports.get(key) or sports.get(key.upper()) or []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def row_game_date_et(row: dict[str, Any], today_et: str) -> str | None:
    gd = _ymd10(row.get("game_date") or row.get("Game Date") or row.get("gameDate") or row.get("date"))
    if gd:
        return gd
    gt = str(row.get("game_time") or "").strip()
    import re

    m_iso = re.match(r"^(\d{4}-\d{2}-\d{2})", gt)
    if m_iso:
        return m_iso.group(1)
    m_md = re.match(r"^(\d{1,2})/(\d{1,2})(?:\b|[\sT])", gt)
    if m_md:
        y = today_et[:4]
        return f"{y}-{int(m_md.group(1)):02d}-{int(m_md.group(2)):02d}"
    return None


def sport_has_game_on_ymd(rows: list[dict[str, Any]], target: str, today_et: str) -> bool:
    if not target or not rows:
        return False
    return any(row_game_date_et(r, today_et) == target for r in rows)


def slate_build_modified_utc(slate: dict[str, Any]) -> datetime | None:
    ga = str(slate.get("generated_at") or "").strip()
    if ga:
        dt = parse_pipeline_modified_as_utc(ga.replace(" UTC", "").strip())
        if dt:
            return dt
    ds = _ymd10(slate.get("date"))
    if ds:
        try:
            return datetime.strptime(ds, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def resolve_expected(
    today: str,
    status: dict[str, str],
    repo: Path,
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Return (expected, skipped[(sport, reason)], failed_pipeline)."""
    expected: list[str] = []
    skipped: list[tuple[str, str]] = []
    failed_pipeline: list[str] = []

    candidates = list(in_season_candidates(today))
    # Opportunistic sports (NFL etc.): only if fetch/status prove they ran today.
    nfl_resume = _env_ymd(
        "NFL_SEASON_RESUME",
        _env_ymd("PROPORACLE_NFL_RESUME", NFL_SEASON_RESUME),
    )
    if today >= nfl_resume:
        st_nfl = status.get("nfl", "")
        if st_nfl == "complete" or step1_has_props(repo, "nfl", today):
            candidates.append("nfl")

    core_fail_set = frozenset(SUMMER_CORE) | frozenset(WINTER_CORE)

    for sport in candidates:
        st = status.get(sport, "")
        has_props = step1_has_props(repo, sport, today)

        if st == "off_season":
            skipped.append((sport, "off_season"))
            continue
        if st == "no_slate":
            # Intentional empty after successful fetch — do not require FRESH,
            # unless step1 actually has props (status/fetch mismatch).
            if has_props:
                expected.append(sport)
            else:
                skipped.append((sport, "no_slate (empty PP board after fetch)"))
            continue
        if st == "failed":
            if sport in core_fail_set or has_props:
                failed_pipeline.append(sport)
                expected.append(sport)
            else:
                skipped.append((sport, "failed_non_core_scaffolding"))
            continue
        if st == "complete":
            expected.append(sport)
            continue
        # Missing / unknown status: expect summer/winter core in-season, or any with props.
        if has_props or sport in SUMMER_CORE or sport in WINTER_CORE:
            expected.append(sport)
        else:
            skipped.append((sport, "not_in_status_and_no_props"))

    # Dedupe preserve order
    seen: set[str] = set()
    expected_u = []
    for s in expected:
        if s not in seen:
            seen.add(s)
            expected_u.append(s)
    return expected_u, skipped, failed_pipeline


def classify_sport(
    sport: str,
    slate: dict[str, Any],
    today_et: str,
    *,
    require_game_day: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Return (FRESH|PENDING|STALE, detail)."""
    rows = slate_rows(slate, sport)
    detail: dict[str, Any] = {"rows": len(rows)}

    if not rows:
        return "PENDING", detail

    mod = slate_build_modified_utc(slate)
    mod_et = ymd_in_eastern(mod) if mod else None
    detail["modified_et"] = mod_et
    detail["modified_utc"] = mod.strftime("%Y-%m-%d %H:%M:%S") if mod else None

    fresh = bool(mod_et and mod_et == today_et)

    tennis_day = _ymd10(slate.get("tennis_date")) or today_et
    soccer_day = _ymd10(slate.get("soccer_date")) or today_et
    if sport == "tennis":
        target = tennis_day
    elif sport == "soccer":
        target = soccer_day
    else:
        target = today_et
    detail["game_day_target"] = target

    has_games: bool | None = None
    if sport in STRICT_GAME_DAY:
        has_games = sport_has_game_on_ymd(rows, target, today_et)
        detail["game_day"] = has_games
        if require_game_day and fresh and has_games is False:
            fresh = False

    if fresh:
        return "FRESH", detail
    if mod_et and mod_et != today_et:
        return "STALE", detail
    if has_games is False:
        return "STALE", detail
    return "STALE", detail


def assert_active_sports_fresh(
    repo: Path,
    today: str = "",
    templates_dir: Path | None = None,
    *,
    require_game_day: bool = True,
) -> dict[str, Any]:
    today = today or eastern_today_ymd()
    templates_dir = templates_dir or (repo / "ui_runner" / "templates")
    slate_path = templates_dir / "slate_latest.json"
    slate = _load_json(slate_path)
    status = load_pipeline_status(repo, today)

    expected, skipped, failed_pipeline = resolve_expected(today, status, repo)

    results: dict[str, Any] = {}
    bad: list[str] = []

    for sport, reason in skipped:
        results[sport] = {"badge": "SKIP", "reason": reason}

    for sport in expected:
        badge, detail = classify_sport(
            sport, slate, today, require_game_day=require_game_day
        )
        entry = {"badge": badge, **detail}
        if sport in failed_pipeline:
            entry["pipeline"] = "failed"
            if badge == "FRESH":
                # Pipeline said failed even if leftover rows look fresh — still fail.
                entry["badge"] = "FAILED"
                badge = "FAILED"
        results[sport] = entry
        if badge != "FRESH":
            bad.append(sport)

    ok = len(bad) == 0
    report = {
        "ok": ok,
        "today_et": today,
        "slate_path": str(slate_path),
        "slate_date": _ymd10(slate.get("date")),
        "slate_generated_at": slate.get("generated_at"),
        "pipeline_status": status,
        "expected": expected,
        "skipped": [{"sport": s, "reason": r} for s, r in skipped],
        "failed_pipeline": failed_pipeline,
        "sports": results,
        "bad": bad,
        "message": (
            "OK: all expected active sports FRESH"
            if ok
            else f"BAD: expected sports not FRESH: {', '.join(bad)}"
        ),
    }
    return report


def _print_report(report: dict[str, Any]) -> None:
    print(f"[ACTIVE-SPORTS-FRESH] {report['message']}")
    print(f"  today_et={report['today_et']} slate_date={report.get('slate_date')}")
    print(f"  expected=[{', '.join(report.get('expected') or [])}]")
    for item in report.get("skipped") or []:
        print(f"  SKIP  {item['sport']}: {item['reason']}")
    sports = report.get("sports") or {}
    for sport in sorted(sports.keys()):
        info = sports[sport]
        badge = info.get("badge")
        if badge == "SKIP":
            continue
        rows = info.get("rows", "?")
        mod = info.get("modified_et") or "—"
        gd = info.get("game_day")
        gd_s = "" if gd is None else f" game_day={gd}"
        pipe = info.get("pipeline")
        pipe_s = f" pipeline={pipe}" if pipe else ""
        print(f"  {badge:7} {sport}: rows={rows} modified_et={mod}{gd_s}{pipe_s}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=REPO_ROOT)
    p.add_argument("--today", default="", help="ET slate day YYYY-MM-DD (default: now ET)")
    p.add_argument(
        "--templates-dir",
        type=Path,
        default=None,
        help="Directory containing slate_latest.json (default: ui_runner/templates)",
    )
    p.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write full JSON report",
    )
    p.add_argument(
        "--no-game-day",
        action="store_true",
        help="Only require modified_et == today (skip strict game_day row check)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Always exit 0 after printing (for manual inspection)",
    )
    args = p.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        print(f"[ACTIVE-SPORTS-FRESH] repo not found: {repo}", file=sys.stderr)
        return 1

    try:
        report = assert_active_sports_fresh(
            repo,
            today=args.today,
            templates_dir=args.templates_dir.resolve() if args.templates_dir else None,
            require_game_day=not args.no_game_day,
        )
    except Exception as exc:
        print(f"[ACTIVE-SPORTS-FRESH] error: {exc}", file=sys.stderr)
        return 1

    _print_report(report)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  wrote {args.json_out}")

    if args.dry_run:
        return 0
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
