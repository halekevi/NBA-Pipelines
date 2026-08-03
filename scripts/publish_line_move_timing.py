#!/usr/bin/env python3
"""
Publish rolling Standard line-move timing insight for the website.

Combines:
  - data/reports/pp_line_move_summary.csv (bak backtest, if present)
  - data/line_move_snapshots/** (slim ongoing snapshots)

Writes:
  ui_runner/templates/line_move_timing.json
  mobile/www/line_move_timing.json (when mobile/www exists)

Usage:
  py -3 scripts/publish_line_move_timing.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SNAP_ROOT = _REPO / "data" / "line_move_snapshots"
_REPORT_SUMMARY = _REPO / "data" / "reports" / "pp_line_move_summary.csv"
_REPORT_TRANS = _REPO / "data" / "reports" / "pp_line_move_transitions.csv"
_OUT_TEMPLATES = _REPO / "ui_runner" / "templates" / "line_move_timing.json"
_OUT_MOBILE = _REPO / "mobile" / "www" / "line_move_timing.json"

_RUN_ORDER = ("5AM", "8AM", "9AM", "1030AM", "11AM", "1PM")
_LABEL_ALIASES = {
    "5AM": "5AM",
    "8AM": "8AM",
    "9AM": "9AM",
    "1030AM": "1030AM",
    "10:30AM": "1030AM",
    "1030": "1030AM",
    "11AM": "11AM",
    "1PM": "1PM",
    "13": "1PM",
}


def _norm_label(raw: str) -> str | None:
    s = str(raw or "").strip().upper().replace(" ", "")
    return _LABEL_ALIASES.get(s)


def _favorability(direction: str, delta: float) -> bool:
    # OVER: lower line favorable; UNDER: higher line favorable
    if direction == "OVER":
        return delta < 0
    if direction == "UNDER":
        return delta > 0
    return False


def _load_snap_latest_by_day() -> dict[str, dict[str, dict[str, Any]]]:
    """slate_date -> run_label -> payload (prefer *_latest.json)."""
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    if not _SNAP_ROOT.is_dir():
        return {}
    for day_dir in sorted(_SNAP_ROOT.iterdir()):
        if not day_dir.is_dir():
            continue
        date = day_dir.name
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        for path in day_dir.glob("*_latest.json"):
            label = _norm_label(path.name.replace("_latest.json", ""))
            if not label:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out[date][label] = payload
        # Also accept stamped files if no latest pointer
        if not out[date]:
            by_label: dict[str, Path] = {}
            for path in day_dir.glob("*.json"):
                m = re.match(r"^([A-Za-z0-9]+)_\d{6}\.json$", path.name)
                if not m:
                    continue
                label = _norm_label(m.group(1))
                if not label:
                    continue
                prev = by_label.get(label)
                if prev is None or path.name > prev.name:
                    by_label[label] = path
            for label, path in by_label.items():
                try:
                    out[date][label] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
    return dict(out)


def _legs_index(payload: dict[str, Any]) -> dict[tuple, float]:
    idx: dict[tuple, float] = {}
    for leg in payload.get("legs") or []:
        try:
            key = (
                str(leg.get("sport") or "").upper(),
                str(leg.get("player") or "").lower(),
                str(leg.get("prop") or "").lower(),
                str(leg.get("direction") or "").upper(),
            )
            line = float(leg["line"])
        except (TypeError, ValueError, KeyError):
            continue
        idx[key] = line
    return idx


def _transitions_from_snapshots() -> pd.DataFrame:
    days = _load_snap_latest_by_day()
    rows: list[dict[str, Any]] = []
    for date, runs in days.items():
        present = [r for r in _RUN_ORDER if r in runs]
        if len(present) < 2:
            continue
        for i in range(len(present) - 1):
            old_r, new_r = present[i], present[i + 1]
            old_idx = _legs_index(runs[old_r])
            new_idx = _legs_index(runs[new_r])
            for key, old_line in old_idx.items():
                if key not in new_idx:
                    continue
                new_line = new_idx[key]
                delta = new_line - old_line
                if abs(delta) < 1e-9:
                    continue
                direction = key[3]
                rows.append(
                    {
                        "slate_date": date,
                        "old_run": old_r,
                        "new_run": new_r,
                        "sport": key[0],
                        "abs_delta": abs(delta),
                        "moved_favorable": _favorability(direction, delta),
                        "source": "snapshot",
                    }
                )
    return pd.DataFrame(rows)


def _transitions_from_reports() -> pd.DataFrame:
    if not _REPORT_TRANS.is_file():
        return pd.DataFrame()
    try:
        df = pd.read_csv(_REPORT_TRANS)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    need = {"old_run", "new_run", "abs_delta", "moved_favorable", "slate_date"}
    if not need.issubset(set(df.columns)):
        return pd.DataFrame()
    df = df.copy()
    df["source"] = "bak_report"
    df["moved_favorable"] = df["moved_favorable"].astype(bool)
    return df


def _rollup(transitions: pd.DataFrame) -> list[dict[str, Any]]:
    if transitions.empty:
        return []
    windows: list[dict[str, Any]] = []
    for new_run, g in transitions.groupby("new_run", sort=False):
        fav = g[g["moved_favorable"]]
        unfav = g[~g["moved_favorable"]]
        n = len(g)
        fav_pct = round(100 * len(fav) / n, 1) if n else 0.0
        unfav_pct = round(100 * len(unfav) / n, 1) if n else 0.0
        net = float(fav["abs_delta"].sum() - unfav["abs_delta"].sum()) if n else 0.0
        role = "mixed"
        if unfav_pct >= 55 or net <= -8:
            role = "unfavorable"
        elif fav_pct >= 55 or net >= 8:
            role = "favorable"
        if n >= 80:
            role = "high_volume" if role == "mixed" else role
        windows.append(
            {
                "id": str(new_run),
                "label": f"Into {new_run}",
                "moves": int(n),
                "days": int(g["slate_date"].nunique()),
                "fav_pct": fav_pct,
                "unfav_pct": unfav_pct,
                "avg_abs": round(float(g["abs_delta"].mean()), 3),
                "net_fav_abs": round(net, 1),
                "role": role,
            }
        )
    order = {r: i for i, r in enumerate(_RUN_ORDER)}
    windows.sort(key=lambda w: order.get(w["id"], 99))
    return windows


def _tips(windows: list[dict[str, Any]], sample_days: int) -> list[str]:
    tips: list[str] = []
    if not windows:
        tips.append("Line-move history is still collecting — keep scheduled refreshes on.")
        return tips
    by_id = {w["id"]: w for w in windows}
    hi_vol = max(windows, key=lambda w: w["moves"])
    tips.append(
        f"Most Standard line movement lands into {hi_vol['id']} "
        f"({hi_vol['moves']} moves across {hi_vol['days']} days)."
    )
    unfav = [w for w in windows if w["role"] == "unfavorable" or w["unfav_pct"] >= 55]
    if unfav:
        u = max(unfav, key=lambda w: w["unfav_pct"])
        tips.append(
            f"Most unfavorable stretch historically: into {u['id']} "
            f"({u['unfav_pct']}% against your direction)."
        )
    fav = [w for w in windows if w["role"] == "favorable" or w["fav_pct"] >= 55]
    if fav:
        f = max(fav, key=lambda w: w["fav_pct"])
        tips.append(
            f"Most favorable stretch: into {f['id']} "
            f"({f['fav_pct']}% with your direction)."
        )
    tips.append(
        "Practical: lock strong Standard overs earlier when you can; "
        "re-check mid-morning (≈10:30) before afternoon slips."
    )
    if sample_days < 20:
        tips.append(f"Sample still thin ({sample_days} days) — confidence rises as snapshots accumulate.")
    return tips


def main() -> int:
    snap_t = _transitions_from_snapshots()
    report_t = _transitions_from_reports()
    frames = [f for f in (snap_t, report_t) if not f.empty]
    if frames:
        transitions = pd.concat(frames, ignore_index=True)
        # Prefer snapshot rows when both exist same day/transition (drop bak dupes)
        transitions = transitions.drop_duplicates(
            subset=["slate_date", "old_run", "new_run", "sport", "abs_delta", "moved_favorable"],
            keep="first",
        )
    else:
        transitions = pd.DataFrame()

    windows = _rollup(transitions)
    sample_days = int(transitions["slate_date"].nunique()) if not transitions.empty else 0
    date_min = str(transitions["slate_date"].min()) if not transitions.empty else None
    date_max = str(transitions["slate_date"].max()) if not transitions.empty else None
    snap_days = len(_load_snap_latest_by_day())

    headline = "Collecting Standard line-move history across daily refreshes."
    if windows:
        hi = max(windows, key=lambda w: w["moves"])
        headline = (
            f"Standard lines move most into {hi['id']} "
            f"({hi['fav_pct']:.0f}% favorable / {hi['unfav_pct']:.0f}% unfavorable)."
        )

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample_days": sample_days,
        "snapshot_days": snap_days,
        "date_range": [date_min, date_max],
        "headline": headline,
        "windows": windows,
        "tips": _tips(windows, sample_days),
        "definitions": {
            "favorable": "OVER line down or UNDER line up vs prior refresh",
            "unfavorable": "OVER line up or UNDER line down vs prior refresh",
        },
    }

    _OUT_TEMPLATES.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    _OUT_TEMPLATES.write_text(text, encoding="utf-8")
    if _OUT_MOBILE.parent.is_dir():
        _OUT_MOBILE.write_text(text, encoding="utf-8")
    print(
        f"[line-timing] days={sample_days} windows={len(windows)} "
        f"-> {_OUT_TEMPLATES.relative_to(_REPO)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
