#!/usr/bin/env python3
"""Update per-player rolling STRONG leg hit rates from graded_props + strong_builder exports."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "reports" / "strong_player_rolling_hr.json"
ROLLING_N = 20
EXCLUDE_HR = 0.25
EXCLUDE_MIN_N = 20


def _norm_prop(v: object) -> str:
    return str(v or "").strip()


def _load_graded(root: Path, date: str) -> dict | None:
    for rel in (
        f"mobile/www/graded_props_{date}.json",
        f"ui_runner/templates/graded_props_{date}.json",
    ):
        path = root / rel
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
    return None


def _build_graded_lookup(graded: dict) -> dict[tuple, int]:
    lookup: dict[tuple, int] = {}
    for p in graded.get("props", []):
        g = str(p.get("grade") or p.get("result") or "").upper()
        if g not in ("HIT", "MISS"):
            continue
        hit = 1 if g == "HIT" else 0
        key = (
            p.get("player"),
            _norm_prop(p.get("prop") or p.get("prop_type")),
            str(p.get("sport", "")).upper(),
        )
        lookup[key] = hit
    return lookup


def _leg_hit(lookup: dict[tuple, int], leg: dict) -> int | None:
    player = leg.get("player")
    prop = _norm_prop(leg.get("prop_type") or leg.get("prop"))
    sport = str(leg.get("sport", "")).upper()
    if (player, prop, sport) in lookup:
        return lookup[(player, prop, sport)]
    for (p, pr, sp), hit in lookup.items():
        if p == player and sp == sport and (pr == prop or prop in pr or pr in prop):
            return hit
    return None


def collect_strong_leg_events(root: Path) -> dict[str, list[tuple[str, int]]]:
    """player -> chronological [(date, hit), ...] for STRONG-builder legs."""
    events: dict[str, list[tuple[str, int]]] = defaultdict(list)
    pattern = str(root / "ui_runner" / "data" / "combined_slate_tickets_*.json")
    for path in sorted(glob.glob(pattern)):
        base = os.path.basename(path)
        if any(x in base for x in ("winrate", "high_leg", "long_parlay")):
            continue
        date = base.replace("combined_slate_tickets_", "").replace(".json", "")
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        graded = _load_graded(root, date)
        if not graded:
            continue
        lookup = _build_graded_lookup(graded)
        strong = [
            t
            for g in data.get("groups", [])
            for t in g.get("tickets", [])
            if t.get("strong_builder")
        ]
        for ticket in strong:
            for leg in ticket.get("legs", []):
                player = str(leg.get("player") or "").strip()
                if not player:
                    continue
                hit = _leg_hit(lookup, leg)
                if hit is None:
                    continue
                events[player].append((date, hit))
    return events


def build_rolling_table(events: dict[str, list[tuple[str, int]]]) -> dict[str, dict]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out: dict[str, dict] = {}
    for player, evs in events.items():
        evs_sorted = sorted(evs, key=lambda x: x[0])
        window = evs_sorted[-ROLLING_N:]
        n = len(window)
        hr = (sum(h for _, h in window) / n) if n else None
        out[player] = {
            "hr": round(hr, 4) if hr is not None else None,
            "n": n,
            "last_updated": today,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Update STRONG player rolling leg HR JSON.")
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    root = Path(args.repo_root)
    events = collect_strong_leg_events(root)
    table = build_rolling_table(events)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(table, indent=2, sort_keys=True), encoding="utf-8")
    excluded = sorted(
        p
        for p, v in table.items()
        if int(v.get("n") or 0) >= EXCLUDE_MIN_N and float(v.get("hr") or 1.0) < EXCLUDE_HR
    )
    print(f"[strong-hr] updated {len(table)} players -> {out_path}")
    if excluded:
        print(f"[strong-hr] excluded (HR<{EXCLUDE_HR:.0%} n>={EXCLUDE_MIN_N}): {excluded}")
    else:
        print("[strong-hr] excluded: (none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
