#!/usr/bin/env python3
"""Unified slip grade review by track and slice (MAIN / opt3 / STRONG pre-post gate)."""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from analyze_graded_history import _norm_dir, _norm_pick, _norm_sport, _parse_hit  # noqa: E402
from ticket_slip_grader import iter_slip_legs  # noqa: E402

from combined_export_trust import classify_combined_export_payload  # noqa: E402

DEFAULT_SLICE_CSV = _REPO / "data" / "reports" / "slip_grade_review_by_slice.csv"
DEFAULT_VOID_CSV = _REPO / "data" / "reports" / "slip_grade_void_attribution.csv"
POST_GATE_DATE = "2026-07-10"
OUTAGE_WINDOWS: tuple[tuple[str, str], ...] = (
    ("2026-06-23", "2026-06-26"),
    ("2026-07-07", "2026-07-10"),
)

TRACK_MAIN = "MAIN"
TRACK_OPT3 = "opt3_shadow"
TRACK_STRONG_PRE = "STRONG_pregame"
TRACK_STRONG_POST = "STRONG_postgame"
ALL_TRACKS = (TRACK_MAIN, TRACK_OPT3, TRACK_STRONG_PRE, TRACK_STRONG_POST)


def _norm_name(s: object) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _norm_line(v: object) -> str:
    try:
        return str(round(float(v or 0), 2))
    except (TypeError, ValueError):
        return "0.0"


def _norm_prop(v: object) -> str:
    return _norm_name(v).replace("-", "")


@dataclass
class GradedLeg:
    hit: int | None
    void_reason: str | None
    result: str | None


@dataclass
class SlipGrade:
    date: str
    track: str
    slip_id: str
    sport_mix: str
    n_legs: int
    n_legs_bucket: str
    tier_mix: str
    pick_type_mix: str
    month: str
    outage_flag: bool
    post_gate_flag: bool
    decided: bool
    paid: bool
    slip_void: bool
    void_reason: str
    export_trust: str = "live"
    leg_hits: int = 0
    leg_decided: int = 0
    leg_void: int = 0
    leg_total: int = 0


def _parse_date(s: str) -> date_cls:
    return date_cls.fromisoformat(s[:10])


def _in_outage_window(d: str) -> bool:
    cur = _parse_date(d)
    for start, end in OUTAGE_WINDOWS:
        if _parse_date(start) <= cur <= _parse_date(end):
            return True
    return False


def _post_gate(d: str) -> bool:
    return d[:10] >= POST_GATE_DATE


def leg_lookup_key(leg: dict) -> tuple:
    return (
        _norm_sport(leg.get("sport")),
        _norm_name(leg.get("player")),
        _norm_prop(leg.get("prop_type") or leg.get("prop")),
        _norm_dir(leg.get("direction") or leg.get("dir")),
        _norm_pick(leg.get("pick_type")).title(),
        _norm_line(leg.get("line")),
    )


def _leg_hit_value(row: GradedLeg) -> int | None:
    if row.hit in (0, 1):
        return int(row.hit)
    if row.result:
        return _parse_hit(row.result)
    return None


def load_graded_index(date_str: str, repo: Path) -> dict[tuple, GradedLeg]:
    paths = (
        repo / "ui_runner" / "templates" / f"graded_props_{date_str}.json",
        repo / "mobile" / "www" / f"graded_props_{date_str}.json",
    )
    for path in paths:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        out: dict[tuple, GradedLeg] = {}
        for row in data.get("props") or []:
            key = (
                _norm_sport(row.get("sport")),
                _norm_name(row.get("player")),
                _norm_prop(row.get("prop") or row.get("prop_type")),
                _norm_dir(row.get("direction")),
                _norm_pick(row.get("pick_type")).title(),
                _norm_line(row.get("line")),
            )
            hit_raw = row.get("hit")
            hit: int | None
            if hit_raw in (0, 1, "0", "1"):
                hit = int(hit_raw)
            else:
                hit = _parse_hit(row.get("result") or row.get("grade"))
            out[key] = GradedLeg(
                hit=hit,
                void_reason=str(row.get("void_reason") or "").strip() or None,
                result=str(row.get("result") or row.get("grade") or "").strip().upper() or None,
            )
        return out
    return {}


def _classify_sport_mix(legs: list[dict]) -> str:
    sports = sorted({str(l.get("sport") or "").strip().upper() for l in legs if str(l.get("sport") or "").strip()})
    if not sports:
        return "unknown"
    if len(sports) == 1:
        if sports[0] == "WNBA":
            return "WNBA-only"
        if sports[0] == "MLB":
            return "MLB-only"
        return f"{sports[0]}-only"
    return "cross-sport"


def _classify_pick_mix(legs: list[dict]) -> str:
    picks = {_norm_pick(l.get("pick_type")) for l in legs}
    picks.discard("")
    has_gob = any("goblin" in p for p in picks)
    has_std = any(p in ("standard", "std") or "standard" in p for p in picks)
    if has_gob and not has_std:
        return "Goblin-only"
    if has_std and not has_gob:
        return "Standard-only"
    if has_gob and has_std:
        return "mixed"
    return "unknown"


def _classify_tier_mix(legs: list[dict]) -> str:
    tiers = {str(l.get("tier") or "").strip().upper() for l in legs}
    tiers.discard("")
    has_a = "A" in tiers
    has_b = "B" in tiers
    if has_a and not has_b:
        return "A-only"
    if has_b and not has_a:
        return "B-only"
    if has_a and has_b:
        return "mixed"
    return "unknown"


def _n_legs_bucket(n: int) -> str:
    if n <= 2:
        return "2-leg"
    if n == 3:
        return "3-leg"
    return "4+ leg"


def _lookup_leg(graded_index: dict[tuple, GradedLeg], leg: dict) -> GradedLeg | None:
    """Match graded row: full key, then relaxed sport/player/prop/line."""
    key = leg_lookup_key(leg)
    row = graded_index.get(key)
    if row is not None:
        return row
    sport = _norm_sport(leg.get("sport"))
    player = _norm_name(leg.get("player"))
    prop = _norm_prop(leg.get("prop_type") or leg.get("prop"))
    line = _norm_line(leg.get("line"))
    for (sp, pl, pr, _d, _pk, ln), candidate in graded_index.items():
        if sp == sport and pl == player and ln == line and (pr == prop or prop in pr or pr in prop):
            return candidate
    return None


def grade_slip(
    slip: dict,
    *,
    date_str: str,
    track: str,
    graded_index: dict[tuple, GradedLeg],
    export_trust: str = "live",
) -> SlipGrade:
    legs = iter_slip_legs(slip)
    leg_hits = 0
    leg_decided = 0
    leg_void = 0
    missing_rows = 0
    void_dnp = 0
    partial = False

    for leg in legs:
        row = _lookup_leg(graded_index, leg)
        if row is None:
            missing_rows += 1
            continue
        hit = _leg_hit_value(row)
        if hit in (0, 1):
            leg_decided += 1
            leg_hits += hit
            if hit == 0 and row.void_reason and re.search(r"DNP|INJURY", row.void_reason, re.I):
                void_dnp += 1
        elif row.result == "VOID" or (row.void_reason and re.search(r"DNP|INJURY", row.void_reason, re.I)):
            void_dnp += 1
            partial = True
        else:
            partial = True

    n_legs = len(legs)
    slip_void = missing_rows > 0
    decided = (not slip_void) and n_legs > 0 and leg_decided == n_legs
    paid = decided and leg_hits == n_legs

    if slip_void:
        void_reason = "no_graded_row"
    elif partial and not decided:
        void_reason = "partial"
    elif void_dnp > 0 and not decided:
        void_reason = "DNP"
    else:
        void_reason = ""

    slip_id = str(
        slip.get("ticket_id")
        or f"{date_str}|{track}|{slip.get('ticket_no') or slip.get('web_group_name') or 'slip'}"
    )

    return SlipGrade(
        date=date_str,
        track=track,
        slip_id=slip_id,
        sport_mix=_classify_sport_mix(legs),
        n_legs=n_legs,
        n_legs_bucket=_n_legs_bucket(n_legs),
        tier_mix=_classify_tier_mix(legs),
        pick_type_mix=_classify_pick_mix(legs),
        month=date_str[:7],
        outage_flag=_in_outage_window(date_str),
        post_gate_flag=_post_gate(date_str),
        export_trust=export_trust,
        decided=decided,
        paid=paid,
        slip_void=slip_void,
        void_reason=void_reason,
        leg_hits=leg_hits,
        leg_decided=leg_decided,
        leg_void=missing_rows,
        leg_total=n_legs,
    )


def _graded_dates(repo: Path, from_date: str | None) -> list[str]:
    dates: set[str] = set()
    for pattern in (
        "ui_runner/templates/graded_props_*.json",
        "mobile/www/graded_props_*.json",
    ):
        for path in glob.glob(str(repo / pattern)):
            base = os.path.basename(path)
            if ".bak_" in base:
                continue
            d = base.replace("graded_props_", "").replace(".json", "")
            if len(d) == 10 and d[4] == "-" and d[7] == "-":
                dates.add(d)
    out = sorted(dates)
    if from_date:
        out = [d for d in out if d >= from_date[:10]]
    return out


def _load_payload(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_track_filter(track_filter: str | None) -> set[str] | None:
    if not track_filter:
        return None
    key = track_filter.strip().upper()
    if key == "STRONG":
        return {TRACK_STRONG_PRE, TRACK_STRONG_POST}
    name_map = {t.upper(): t for t in ALL_TRACKS}
    if key in name_map:
        return {name_map[key]}
    return set()


def collect_slip_grades(
    repo: Path,
    dates: Iterable[str],
    *,
    track_filter: str | None = None,
) -> list[SlipGrade]:
    grades: list[SlipGrade] = []
    want = _resolve_track_filter(track_filter)
    if track_filter and not want:
        return grades

    for date_str in dates:
        graded_index = load_graded_index(date_str, repo)
        if not graded_index:
            continue

        main_path = repo / "ui_runner" / "data" / f"combined_slate_tickets_{date_str}.json"
        opt3_path = repo / "ui_runner" / "data" / f"combined_slate_tickets_winrate_goblin_opt3_{date_str}.json"

        main_payload = _load_payload(main_path)
        main_trust, _ = classify_combined_export_payload(main_payload, date_str)
        if main_payload and (want is None or TRACK_MAIN in want or TRACK_STRONG_PRE in want or TRACK_STRONG_POST in want):
            for slip in _iter_slips(main_payload):
                if want is None or TRACK_MAIN in want:
                    grades.append(
                        grade_slip(
                            slip,
                            date_str=date_str,
                            track=TRACK_MAIN,
                            graded_index=graded_index,
                            export_trust=main_trust,
                        )
                    )
                if slip.get("strong_builder"):
                    strong_track = TRACK_STRONG_POST if _post_gate(date_str) else TRACK_STRONG_PRE
                    if want is None or strong_track in want:
                        grades.append(
                            grade_slip(
                                slip,
                                date_str=date_str,
                                track=strong_track,
                                graded_index=graded_index,
                                export_trust=main_trust,
                            )
                        )

        opt3_payload = _load_payload(opt3_path)
        opt3_trust, _ = classify_combined_export_payload(opt3_payload, date_str)
        if opt3_payload and (want is None or TRACK_OPT3 in want):
            for slip in _iter_slips(opt3_payload):
                grades.append(
                    grade_slip(
                        slip,
                        date_str=date_str,
                        track=TRACK_OPT3,
                        graded_index=graded_index,
                        export_trust=opt3_trust,
                    )
                )

    return grades


def _iter_slips(payload: dict) -> list[dict]:
    out: list[dict] = []
    for group in payload.get("groups") or []:
        for slip in group.get("tickets") or []:
            if isinstance(slip, dict):
                out.append(slip)
    return out


def _agg_rows(slips: list[SlipGrade], slice_type: str, key_fn) -> list[dict]:
    buckets: dict[str, list[SlipGrade]] = defaultdict(list)
    for slip in slips:
        buckets[key_fn(slip)].append(slip)
    rows: list[dict] = []
    for slice_value in sorted(buckets):
        rows.append(_summary_row(buckets[slice_value], slice_type=slice_type, slice_value=slice_value))
    return rows


def _summary_row(
    slips: list[SlipGrade],
    *,
    slice_type: str,
    slice_value: str,
    track: str = "ALL",
    sport_mix: str = "ALL",
    n_legs: str = "ALL",
    tier_mix: str = "ALL",
    pick_type_mix: str = "ALL",
    date: str = "ALL",
    outage_flag: str = "ALL",
    post_gate_flag: str = "ALL",
) -> dict:
    decided_slips = [s for s in slips if s.decided]
    paid = sum(1 for s in decided_slips if s.paid)
    decided_n = len(decided_slips)
    leg_decided = sum(s.leg_decided for s in slips)
    leg_hits = sum(s.leg_hits for s in slips)
    void_legs = sum(s.leg_void for s in slips)
    cash_rate = (paid / decided_n) if decided_n else None
    leg_hr = (leg_hits / leg_decided) if leg_decided else None
    return {
        "date": date,
        "slice_type": slice_type,
        "slice_value": slice_value,
        "track": track,
        "sport_mix": sport_mix,
        "n_legs": n_legs,
        "tier_mix": tier_mix,
        "pick_type_mix": pick_type_mix,
        "decided": decided_n,
        "paid": paid,
        "cash_rate": round(cash_rate, 4) if cash_rate is not None else None,
        "leg_hr": round(leg_hr, 4) if leg_hr is not None else None,
        "void_legs": void_legs,
        "outage_flag": outage_flag,
        "post_gate_flag": post_gate_flag,
        "slips_total": len(slips),
        "slips_void": sum(1 for s in slips if s.slip_void),
        "slips_partial": sum(1 for s in slips if (not s.decided) and (not s.slip_void)),
    }


def build_slice_rows(slips: list[SlipGrade]) -> list[dict]:
    rows: list[dict] = []

    rows.extend(
        _agg_rows(
            slips,
            "by_track",
            lambda s: s.track,
        )
    )
    # Ensure post-gate STRONG row exists even when empty.
    if not any(s.track == TRACK_STRONG_POST for s in slips):
        rows.append(
            _summary_row(
                [],
                slice_type="by_track",
                slice_value=TRACK_STRONG_POST,
                track=TRACK_STRONG_POST,
            )
        )
    rows.extend(
        _agg_rows(
            slips,
            "by_track_sport",
            lambda s: f"{s.track}|{s.sport_mix}",
        )
    )
    rows.extend(
        _agg_rows(
            slips,
            "by_track_n_legs",
            lambda s: f"{s.track}|{s.n_legs_bucket}",
        )
    )
    rows.extend(
        _agg_rows(
            slips,
            "by_track_pick_type",
            lambda s: f"{s.track}|{s.pick_type_mix}",
        )
    )
    rows.extend(
        _agg_rows(
            slips,
            "by_track_tier",
            lambda s: f"{s.track}|{s.tier_mix}",
        )
    )
    rows.extend(_agg_rows(slips, "by_month", lambda s: s.month))
    rows.extend(
        _agg_rows(
            slips,
            "by_outage",
            lambda s: "during_outage" if s.outage_flag else "clean",
        )
    )
    rows.extend(
        _agg_rows(
            slips,
            "by_post_gate",
            lambda s: "post_gate" if s.post_gate_flag else "pre_gate",
        )
    )

    for row in rows:
        if row["slice_type"] == "by_track":
            row["track"] = row["slice_value"]
        elif row["slice_type"] == "by_track_sport":
            track, sport = row["slice_value"].split("|", 1)
            row["track"], row["sport_mix"] = track, sport
        elif row["slice_type"] == "by_track_n_legs":
            track, n_legs = row["slice_value"].split("|", 1)
            row["track"], row["n_legs"] = track, n_legs
        elif row["slice_type"] == "by_track_pick_type":
            track, pick_mix = row["slice_value"].split("|", 1)
            row["track"], row["pick_type_mix"] = track, pick_mix
        elif row["slice_type"] == "by_track_tier":
            track, tier = row["slice_value"].split("|", 1)
            row["track"], row["tier_mix"] = track, tier
        elif row["slice_type"] == "by_outage":
            row["outage_flag"] = row["slice_value"] == "during_outage"
        elif row["slice_type"] == "by_post_gate":
            row["post_gate_flag"] = row["slice_value"] == "post_gate"

    return rows


def build_void_rows(slips: list[SlipGrade]) -> list[dict]:
    rows: list[dict] = []
    for slip in slips:
        if not slip.slip_void and slip.void_reason not in ("partial", "DNP"):
            continue
        rows.append(
            {
                "date": slip.date,
                "track": slip.track,
                "slip_id": slip.slip_id,
                "void_reason": slip.void_reason or "partial",
                "n_legs": slip.n_legs,
                "leg_void": slip.leg_void,
                "leg_decided": slip.leg_decided,
                "outage_flag": slip.outage_flag,
                "post_gate_flag": slip.post_gate_flag,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Unified slip grade review by slice.")
    ap.add_argument("--repo-root", default=str(_REPO))
    ap.add_argument("--from", dest="from_date", default=None, help="Min slate date YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", default=None, help="Max slate date YYYY-MM-DD")
    ap.add_argument("--track", default=None, help="Filter track: MAIN, opt3_shadow, STRONG")
    ap.add_argument("--slice-csv", default=str(DEFAULT_SLICE_CSV))
    ap.add_argument("--void-csv", default=str(DEFAULT_VOID_CSV))
    args = ap.parse_args(argv)

    repo = Path(args.repo_root)
    dates = _graded_dates(repo, args.from_date)
    if args.to_date:
        dates = [d for d in dates if d <= args.to_date[:10]]

    track_filter = args.track
    if track_filter:
        tf = track_filter.upper()
        if tf == "STRONG":
            track_filter = "STRONG"
        elif tf not in {t.upper() for t in ALL_TRACKS} and tf != "STRONG":
            print(f"[slip-grade-review] unknown track filter: {args.track}", file=sys.stderr)
            return 2

    slips = collect_slip_grades(repo, dates, track_filter=track_filter)
    if not slips:
        print("[slip-grade-review] no slips graded (check dated exports + graded_props)")
        return 1

    slice_rows = build_slice_rows(slips)
    void_rows = build_void_rows(slips)

    slice_path = Path(args.slice_csv)
    void_path = Path(args.void_csv)
    slice_path.parent.mkdir(parents=True, exist_ok=True)
    void_path.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(slice_rows).to_csv(slice_path, index=False)
    pd.DataFrame(void_rows).to_csv(void_path, index=False)

    by_track = pd.DataFrame(slice_rows)
    by_track = by_track[by_track["slice_type"] == "by_track"][
        ["slice_value", "decided", "paid", "cash_rate", "leg_hr"]
    ]
    print(f"[slip-grade-review] wrote {len(slice_rows)} slice rows -> {slice_path}")
    print(f"[slip-grade-review] wrote {len(void_rows)} void rows -> {void_path}")
    print(f"[slip-grade-review] dates={len(dates)} slips={len(slips)}")
    print(by_track.to_string(index=False))

    live = [s for s in slips if s.export_trust == "live"]
    if live:
        live_rows = build_slice_rows(live)
        live_track = pd.DataFrame(live_rows)
        live_track = live_track[live_track["slice_type"] == "by_track"][
            ["slice_value", "decided", "paid", "cash_rate", "leg_hr"]
        ]
        print("\n[slip-grade-review] live-export only (matches shadow track cohort):")
        print(live_track.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
