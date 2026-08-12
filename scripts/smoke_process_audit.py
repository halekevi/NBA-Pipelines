#!/usr/bin/env python3
"""
Process smoke audit — no full rebuild.

Checks active-sport boards, path resolution, validators, import health,
staleness, and known integrity smells. Writes a JSON report under data/reports/.

Usage:
  py -3 scripts/smoke_process_audit.py
  py -3 scripts/smoke_process_audit.py --date 2026-08-12
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = timezone.utc


def _today_et() -> str:
    return datetime.now(tz=_ET).date().isoformat()


def _age_hours(path: Path) -> float | None:
    if not path.is_file():
        return None
    return max(0.0, (time.time() - path.stat().st_mtime) / 3600.0)


def _num(x) -> float | None:
    try:
        if x is None or x == "":
            return None
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def _finding(
    findings: list[dict[str, Any]],
    *,
    severity: str,
    area: str,
    title: str,
    detail: str,
    action: str = "",
) -> None:
    findings.append(
        {
            "severity": severity,  # critical | high | medium | low | info | ok
            "area": area,
            "title": title,
            "detail": detail,
            "action": action,
        }
    )


def check_season_windows(findings: list[dict[str, Any]], date: str) -> dict[str, bool]:
    """Heuristic active flags for smoke (aligned with combined_slate off-season skips)."""
    y, m, d = map(int, date.split("-"))
    active = {
        "NBA": m >= 10 or m <= 6,
        "NBA1Q": m >= 10 or m <= 6,
        "NBA1H": m >= 10 or m <= 6,
        "NHL": m >= 9 or m <= 6,
        "CBB": m >= 11 or m <= 4,
        "WCBB": m >= 11 or m <= 4,
        "NFL": m >= 8 or m <= 2,
        "CFB": (m >= 8 and m <= 12) or m == 1,
        "MLB": m >= 3 and m <= 10,
        "WNBA": m >= 5 and m <= 10,
        "SOCCER": True,
        "TENNIS": True,
        "GOLF": True,
    }
    on = [k for k, v in active.items() if v]
    off = [k for k, v in active.items() if not v]
    _finding(
        findings,
        severity="info",
        area="calendar",
        title="Season windows for smoke date",
        detail=f"active={','.join(on)} | off={','.join(off)}",
    )
    return active


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def check_board_paths(findings: list[dict[str, Any]], date: str, active: dict[str, bool]) -> dict[str, Any]:
    out = _REPO / "outputs" / date
    sports_root = _REPO / "Sports"
    specs: dict[str, list[Path]] = {
        "WNBA": [
            out / "wnba" / "step8_wnba_direction_clean.xlsx",
            out / f"step8_wnba_direction_clean_{date}.xlsx",
            sports_root / "WNBA" / "step8_wnba_direction_clean.xlsx",
        ],
        "TENNIS": [
            out / "tennis" / f"step8_tennis_direction_clean_{date}.xlsx",
            out / "tennis" / "step8_tennis_direction_clean.xlsx",
            out / f"step8_tennis_direction_clean_{date}.xlsx",
            sports_root / "Tennis" / "outputs" / "step8_tennis_direction_clean.xlsx",
            sports_root / "Tennis" / "step8_tennis_direction_clean.xlsx",
        ],
        "SOCCER": [
            out / "soccer" / "step8_soccer_direction_clean.xlsx",
            out / f"step8_soccer_direction_clean_{date}.xlsx",
            sports_root / "Soccer" / "outputs" / "step8_soccer_direction_clean.xlsx",
            sports_root / "Soccer" / "step8_soccer_direction_clean.xlsx",
        ],
        "MLB": [
            out / "mlb" / "step8_mlb_direction_clean.xlsx",
            out / f"step8_mlb_direction_clean_{date}.xlsx",
            sports_root / "MLB" / "outputs" / "step8_mlb_direction_clean.xlsx",
            sports_root / "MLB" / "step8_mlb_direction_clean.xlsx",
        ],
        "GOLF": [
            out / "golf" / "step8_golf_direction_clean.xlsx",
            sports_root / "Golf" / "outputs" / "step8_golf_direction_clean.xlsx",
            sports_root / "Golf" / "step8_golf_direction_clean.xlsx",
        ],
        "NFL": [
            out / "nfl" / "step8_nfl_direction_clean.xlsx",
            sports_root / "NFL" / "outputs" / "step8_nfl_direction_clean.xlsx",
        ],
        "NBA": [
            out / "nba" / "step8_nba_direction_clean.xlsx",
            out / f"step8_nba_direction_clean_{date}.xlsx",
        ],
        "NHL": [
            out / "nhl" / "step8_nhl_direction_clean.xlsx",
            out / f"step8_nhl_direction_clean_{date}.xlsx",
        ],
    }
    resolved: dict[str, Any] = {}
    for sport, cands in specs.items():
        hit = _first_existing(cands)
        age = _age_hours(hit) if hit else None
        resolved[sport] = {
            "active": bool(active.get(sport, False)),
            "path": str(hit) if hit else None,
            "age_hours": round(age, 2) if age is not None else None,
            "candidates": [str(c) for c in cands],
        }
        if not active.get(sport, False):
            continue
        if hit is None:
            _finding(
                findings,
                severity="high",
                area=sport.lower(),
                title=f"{sport}: no step8 clean board resolved",
                detail="None of the combined_slate candidate paths exist.",
                action=f"Run {sport} pipeline for {date} (or SkipFetch rebuild).",
            )
        else:
            # Prefer dated outputs over Sports/* defaults when both exist
            dated_hits = [c for c in cands if ("outputs" in str(c) and date in str(c)) and c.is_file()]
            sports_default = sports_root / sport.title() / "step8_tennis_direction_clean.xlsx" if sport == "TENNIS" else None
            if sport == "TENNIS":
                preferred = cands[0]
                if preferred.is_file() and age is not None and age < 48:
                    # Compare preferred vs last Sports/Tennis fallback mtime
                    fallback = cands[-1]
                    if fallback.is_file() and fallback.stat().st_mtime > preferred.stat().st_mtime + 60:
                        _finding(
                            findings,
                            severity="high",
                            area="tennis",
                            title="Stale Sports/Tennis step8 newer than dated preferred path",
                            detail=f"preferred={preferred} fallback={fallback}",
                            action="Mirror dated clean into all tennis candidates (step8 already does this).",
                        )
                # Detect wrong-format preferred (snake_case vs title-case clean)
                try:
                    import pandas as pd

                    cols = set(pd.read_excel(hit, nrows=0).columns.astype(str))
                    if "Player" not in cols and "player" in {c.lower() for c in cols}:
                        # If preferred path is snake_case raw, combined may mis-map series
                        if hit == cands[0] or "tennis" in str(hit):
                            _finding(
                                findings,
                                severity="critical",
                                area="tennis",
                                title="Resolved tennis board looks like raw/snake-case, not clean XLSX",
                                detail=f"path={hit} cols_sample={sorted(cols)[:12]}",
                                action="Overwrite preferred path with step8_tennis_direction_clean.xlsx (title-case).",
                            )
                except Exception as exc:
                    _finding(
                        findings,
                        severity="medium",
                        area="tennis",
                        title="Could not inspect tennis board columns",
                        detail=str(exc),
                    )
            if age is not None and age > 36 and sport in {"WNBA", "TENNIS", "SOCCER", "MLB"}:
                _finding(
                    findings,
                    severity="medium",
                    area=sport.lower(),
                    title=f"{sport}: board is {age:.1f}h old",
                    detail=str(hit),
                    action="Consider mid-day SkipFetch rebuild if lines moved.",
                )
            else:
                _finding(
                    findings,
                    severity="ok",
                    area=sport.lower(),
                    title=f"{sport}: board resolved",
                    detail=f"{hit} ({age:.1f}h old)" if age is not None else str(hit),
                )
    return resolved


def check_slate_json(findings: list[dict[str, Any]], date: str) -> dict[str, Any]:
    path = _REPO / "ui_runner" / "templates" / "slate_latest.json"
    mobile = _REPO / "mobile" / "www" / "slate_latest.json"
    out: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        _finding(
            findings,
            severity="critical",
            area="publish",
            title="Missing slate_latest.json",
            detail=str(path),
            action="Run combined_slate_tickets.py --write-slate-web-only",
        )
        return out
    payload = json.loads(path.read_text(encoding="utf-8"))
    slate_date = str(payload.get("date") or "")[:10]
    sports = payload.get("sports") or {}
    counts = {k: len(v) if isinstance(v, list) else 0 for k, v in sports.items()}
    out.update({"date": slate_date, "counts": counts, "age_hours": _age_hours(path)})
    if slate_date and slate_date != date:
        _finding(
            findings,
            severity="high",
            area="publish",
            title=f"slate_latest date {slate_date} != smoke date {date}",
            detail=str(counts),
            action="Republish slate for today.",
        )
    else:
        _finding(
            findings,
            severity="ok",
            area="publish",
            title="slate_latest present",
            detail=f"date={slate_date} props={sum(counts.values())} sports={counts}",
        )
    if mobile.is_file():
        try:
            m = json.loads(mobile.read_text(encoding="utf-8"))
            if str(m.get("date") or "")[:10] != slate_date:
                _finding(
                    findings,
                    severity="medium",
                    area="publish",
                    title="mobile/www slate_latest date mismatch vs templates",
                    detail=f"mobile={m.get('date')} templates={slate_date}",
                    action="Copy templates slate to mobile/www after publish.",
                )
        except Exception as exc:
            _finding(
                findings,
                severity="medium",
                area="publish",
                title="mobile slate_latest unreadable",
                detail=str(exc),
            )
    # Integrity smells inside published slate
    issues = 0
    samples: list[str] = []
    for sport, rows in sports.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            line = _num(row.get("line"))
            edge = _num(row.get("edge"))
            proj = _num(row.get("projection"))
            sea = _num(row.get("season_avg"))
            if (
                line is not None
                and line >= 3
                and edge is not None
                and abs(abs(edge) - abs(line)) < 0.05
                and sea is None
                and (proj is None or abs(proj) < 0.05)
            ):
                issues += 1
                if len(samples) < 5:
                    samples.append(f"{sport}:{row.get('player')}|{row.get('prop')}")
    if issues:
        _finding(
            findings,
            severity="high",
            area="publish",
            title=f"Published slate still has {issues} proj-zero / edge≈-line rows",
            detail="; ".join(samples),
            action="Re-run validate_slate_history_gate + write-slate-web-only after board fixes.",
        )
    return out


def check_pipeline_status(findings: list[dict[str, Any]]) -> None:
    path = _REPO / "ui_runner" / "templates" / "pipeline_status.json"
    if not path.is_file():
        _finding(
            findings,
            severity="medium",
            area="status",
            title="pipeline_status.json missing",
            detail=str(path),
        )
        return
    age = _age_hours(path) or 0
    data = json.loads(path.read_text(encoding="utf-8"))
    # detect all sports sharing same modified stamp (stale generator)
    mods = []
    for sport, blob in (data or {}).items():
        if isinstance(blob, dict):
            slate = blob.get("slate") or {}
            mods.append(str(slate.get("modified") or ""))
    uniq = {m for m in mods if m}
    if age > 24 * 7:
        _finding(
            findings,
            severity="medium",
            area="status",
            title=f"pipeline_status.json is {age/24:.1f} days old",
            detail=str(path),
            action="Regenerate via generate_mobile_bundle / daily publish.",
        )
    if len(uniq) <= 1 and len(mods) >= 5:
        _finding(
            findings,
            severity="medium",
            area="status",
            title="pipeline_status looks frozen (identical modified stamps)",
            detail=f"unique_modified={sorted(uniq)[:3]}",
            action="Rebuild pipeline_status from real board mtimes.",
        )


def check_entrypoint_paths(findings: list[dict[str, Any]]) -> None:
    # Known footgun: run_fast_rebuild looked for $Root/run_pipeline.ps1
    fast = (_REPO / "scripts" / "run_fast_rebuild.ps1").read_text(encoding="utf-8", errors="replace")
    if 'Join-Path $Root "run_pipeline.ps1"' in fast and 'Join-Path $Root "scripts\\run_pipeline.ps1"' not in fast:
        # check if run_pipeline also exists at root
        root_pipe = _REPO / "run_pipeline.ps1"
        scripts_pipe = _REPO / "scripts" / "run_pipeline.ps1"
        if scripts_pipe.is_file() and not root_pipe.is_file():
            _finding(
                findings,
                severity="high",
                area="orchestration",
                title="run_fast_rebuild.ps1 points at missing root run_pipeline.ps1",
                detail=f"expected {root_pipe} missing; real script is {scripts_pipe}",
                action="Fix path to scripts\\run_pipeline.ps1 (or add shim).",
            )
        elif root_pipe.is_file():
            _finding(
                findings,
                severity="ok",
                area="orchestration",
                title="run_pipeline.ps1 exists at repo root (fast rebuild OK)",
                detail=str(root_pipe),
            )
    # Daily scripts exist
    for name in ("run_daily.ps1", "run_daily_5am.ps1", "run_wnba_pipeline.ps1", "run_pipeline.ps1"):
        p = _REPO / "scripts" / name
        alt = _REPO / name
        if not p.is_file() and not alt.is_file():
            _finding(
                findings,
                severity="high",
                area="orchestration",
                title=f"Missing entrypoint {name}",
                detail="not in scripts/ or repo root",
            )


def check_imports(findings: list[dict[str, Any]]) -> None:
    modules = [
        "Sports/Tennis/scripts/tennis_shared.py",
        "Sports/WNBA/step4_fetch_player_stats.py",
        "Sports/Golf/scripts/step8_add_direction_context_golf.py",
        "Sports/Soccer/scripts/step8_add_direction_context_soccer.py",
        "scripts/validate_slate_history_gate.py",
    ]
    for rel in modules:
        path = _REPO / rel
        if not path.is_file():
            _finding(
                findings,
                severity="high",
                area="imports",
                title=f"Missing module {rel}",
                detail="",
            )
            continue
        try:
            src = path.read_text(encoding="utf-8")
            ast.parse(src, filename=str(path))
            _finding(
                findings,
                severity="ok",
                area="imports",
                title=f"Syntax OK: {rel}",
                detail="",
            )
        except SyntaxError as exc:
            _finding(
                findings,
                severity="critical",
                area="imports",
                title=f"Syntax error in {rel}",
                detail=str(exc),
            )


def check_code_smells(findings: list[dict[str, Any]]) -> None:
    # hit_rate * 5 invent remnants
    bad_hits: list[str] = []
    for path in _REPO.rglob("*.py"):
        if any(x in path.parts for x in (".git", "node_modules", "_archive", ".venv", "venv")):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "hit_rate * 5" in text or "hit_rate*5" in text:
            # allow comments that say never invent
            if "Never invent" in text or "no hit_rate invent" in text.lower():
                continue
            bad_hits.append(str(path.relative_to(_REPO)))
    if bad_hits:
        _finding(
            findings,
            severity="high",
            area="integrity",
            title="Possible L5 invent from hit_rate*5 still present",
            detail="; ".join(bad_hits[:8]),
            action="Remove or guard like tennis/golf/soccer step8.",
        )
    else:
        _finding(
            findings,
            severity="ok",
            area="integrity",
            title="No active hit_rate*5 L5 invent found",
            detail="",
        )


def run_validator(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode, out
    except Exception as exc:
        return 99, str(exc)


def run_validators(findings: list[dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    checks = [
        ("history_gate", [sys.executable, "scripts/validate_slate_history_gate.py"], 90),
        (
            "pipeline_outputs",
            [sys.executable, "scripts/validate_pipeline_outputs.py", "--date", _today_et()],
            180,
        ),
        (
            "l5_stat_g",
            [sys.executable, "scripts/validate_l5_stat_g_consistency.py"],
            120,
        ),
    ]
    for name, cmd, timeout in checks:
        t0 = time.time()
        code, out = run_validator(cmd, timeout=timeout)
        elapsed = round(time.time() - t0, 2)
        results[name] = {"exit": code, "seconds": elapsed, "tail": "\n".join(out.splitlines()[-12:])}
        sev = "ok" if code == 0 else ("high" if code not in (99,) else "medium")
        if code != 0 and "unrecognized" in out.lower():
            sev = "medium"
        if code != 0 and "No such file" in out:
            sev = "medium"
        _finding(
            findings,
            severity=sev if code == 0 else ("high" if name == "history_gate" else sev),
            area="validators",
            title=f"validator {name}: exit {code} ({elapsed}s)",
            detail=results[name]["tail"][:800],
            action="" if code == 0 else f"Inspect: {' '.join(cmd)}",
        )
    # unit tests for recent process fixes
    code, out = run_validator(
        [sys.executable, "-m", "pytest", "tests/test_slate_history_process_fixes.py", "-q"],
        timeout=90,
    )
    results["process_fix"] = {"exit": code, "tail": out[-500:]}
    _finding(
        findings,
        severity="ok" if code == 0 else "high",
        area="validators",
        title=f"process fix unit tests: exit {code}",
        detail=out[-400:],
    )
    return results


def time_sport_loads(findings: list[dict[str, Any]], date: str, resolved: dict[str, Any]) -> dict[str, Any]:
    """Light timing of board open+normalize without full combined ticket build."""
    import pandas as pd

    timings: dict[str, Any] = {}
    for sport, meta in resolved.items():
        path = meta.get("path")
        if not path or not meta.get("active"):
            continue
        p = Path(path)
        t0 = time.time()
        try:
            if p.suffix.lower() in {".xlsx", ".xlsm"}:
                df = pd.read_excel(p, engine="openpyxl")
            else:
                df = pd.read_csv(p, low_memory=False)
            elapsed = round(time.time() - t0, 3)
            timings[sport] = {"seconds": elapsed, "rows": int(len(df)), "cols": int(len(df.columns))}
            sev = "ok"
            action = ""
            if elapsed > 8:
                sev = "medium"
                action = "Consider parquet cache or slim clean sheet for web publish."
            _finding(
                findings,
                severity=sev,
                area="perf",
                title=f"{sport} board read {elapsed}s ({len(df)} rows)",
                detail=str(p),
                action=action,
            )
        except Exception as exc:
            timings[sport] = {"error": str(exc)}
            _finding(
                findings,
                severity="high",
                area="perf",
                title=f"{sport} board failed to open",
                detail=str(exc),
            )
    return timings


def check_wcbb_loader_smell(findings: list[dict[str, Any]]) -> None:
    # combined often logs: Could not load WCBB file: 'float' object has no attribute 'add'
    path = _REPO / "scripts" / "combined_slate_tickets.py"
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "load_wcbb" in text:
        _finding(
            findings,
            severity="medium",
            area="wcbb",
            title="WCBB loader still error-prone off-season",
            detail="Recent runs: 'float' object has no attribute 'add' when loading WCBB",
            action="Guard load_wcbb when off-season / empty; fix Series.add on scalar.",
        )


def summarize(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=_today_et())
    ap.add_argument("--skip-validators", action="store_true")
    args = ap.parse_args()
    date = str(args.date).strip()[:10]

    findings: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "generated_at": datetime.now(tz=_ET).isoformat(),
        "date": date,
        "repo": str(_REPO),
    }

    print(f"[smoke] Process audit for {date}")
    active = check_season_windows(findings, date)
    resolved = check_board_paths(findings, date, active)
    report["boards"] = resolved
    report["slate"] = check_slate_json(findings, date)
    check_pipeline_status(findings)
    check_entrypoint_paths(findings)
    check_imports(findings)
    check_code_smells(findings)
    check_wcbb_loader_smell(findings)
    report["timings"] = time_sport_loads(findings, date, resolved)
    if not args.skip_validators:
        report["validators"] = run_validators(findings)
    else:
        report["validators"] = {"skipped": True}

    report["findings"] = findings
    report["summary"] = summarize(findings)

    out_dir = _REPO / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"process_smoke_audit_{date}.json"
    latest = out_dir / "process_smoke_audit_latest.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Console digest
    print("\n=== SUMMARY ===")
    for k in ("critical", "high", "medium", "low", "info", "ok"):
        if report["summary"].get(k):
            print(f"  {k}: {report['summary'][k]}")
    print("\n=== ACTIONABLE ===")
    for f in findings:
        if f["severity"] in {"critical", "high", "medium"}:
            print(f"[{f['severity'].upper()}] {f['area']}: {f['title']}")
            if f.get("detail"):
                print(f"    {f['detail'][:220]}")
            if f.get("action"):
                print(f"    → {f['action']}")
    print(f"\n[smoke] wrote {out_path}")
    # non-zero if critical/high
    bad = report["summary"].get("critical", 0) + report["summary"].get("high", 0)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
