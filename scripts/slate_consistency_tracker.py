#!/usr/bin/env python3
"""
Track slate consistency leaders (OVER/UNDER) and grade them after games.

Snapshots tonight's most consistent player+prop sides from the live slate, marks
which landed on tickets, then grades against graded_props_{date}.json next day.

Artifacts:
  data/slate_consistency/snapshots/consistency_leaders_{date}.json
  data/slate_consistency/graded/consistency_leaders_graded_{date}.json
  data/slate_consistency/track_record.json
  ui_runner/data/slate_consistency_track_record.json  (mirror)

CLI:
  py -3.14 scripts/slate_consistency_tracker.py snapshot [--date YYYY-MM-DD]
  py -3.14 scripts/slate_consistency_tracker.py grade [--date YYYY-MM-DD]
  py -3.14 scripts/slate_consistency_tracker.py status [--date YYYY-MM-DD]
  py -3.14 scripts/slate_consistency_tracker.py rebuild-summary
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BASE = REPO / "data" / "slate_consistency"
SNAPSHOT_DIR = BASE / "snapshots"
GRADED_DIR = BASE / "graded"
TRACK_PATH = BASE / "track_record.json"
UI_TRACK_PATH = REPO / "ui_runner" / "data" / "slate_consistency_track_record.json"

SLATE_COMBINED = REPO / "ui_runner" / "templates" / "slate_sport_combined.json"
SLATE_LATEST = REPO / "ui_runner" / "templates" / "slate_latest.json"
TICKETS_LATEST = REPO / "ui_runner" / "templates" / "tickets_latest.json"
GRADED_PROPS_PATHS = (
    REPO / "ui_runner" / "templates",
    REPO / "mobile" / "www",
    REPO / "ui_runner" / "data",
)

TENNIS_GAME_PROPS = {"total games", "total games won", "games won"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _prop_key(s: Any) -> str:
    s = _norm(s)
    s = s.replace("3-pt made", "3pt made").replace("3 pt made", "3pt made")
    s = s.replace("pts+rebs", "pts+reb").replace("points + rebounds", "pts+reb")
    s = s.replace("double faults", "double faults")
    return s


def _fnum(x: Any, default: float | None = None) -> float | None:
    try:
        if x is None or x == "":
            return default
        v = float(x)
        if math.isnan(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _rate(over: Any, under: Any) -> tuple[float | None, float]:
    o = _fnum(over, 0.0) or 0.0
    u = _fnum(under, 0.0) or 0.0
    den = o + u
    if den <= 0:
        return None, 0.0
    return o / den, den


def _is_tennis_games(sport: str, prop: str) -> bool:
    return sport.upper() == "TENNIS" and _norm(prop) in TENNIS_GAME_PROPS


def snapshot_path(d: str) -> Path:
    return SNAPSHOT_DIR / f"consistency_leaders_{d[:10]}.json"


def graded_path(d: str) -> Path:
    return GRADED_DIR / f"consistency_leaders_graded_{d[:10]}.json"


def _load_slate_rows(slate_date: str) -> list[dict]:
    rows: list[dict] = []
    td = slate_date[:10]
    # Prefer combined export
    for path in (SLATE_COMBINED, SLATE_LATEST):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data.get("rows"), list):
            rows.extend([r for r in data["rows"] if isinstance(r, dict)])
        sports = data.get("sports") or {}
        if isinstance(sports, dict):
            for sport_rows in sports.values():
                if isinstance(sport_rows, list):
                    rows.extend([r for r in sport_rows if isinstance(r, dict)])
    out: list[dict] = []
    seen: set[tuple] = set()
    for r in rows:
        sport = str(r.get("sport") or "").upper()
        player = str(r.get("player") or "").strip()
        prop = str(r.get("prop") or r.get("prop_type") or "").strip()
        if not player or not prop:
            continue
        gd = str(r.get("game_date") or "").strip()[:10]
        # Keep undated rows (tennis/soccer often use game_time only)
        if gd and gd != td and gd not in (td,):
            # allow if slate file date mismatches slightly for overnight tennis
            pass
        key = (sport, _norm(player), _prop_key(prop), str(r.get("line")), str(r.get("dir") or r.get("direction") or "").upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _ticket_leg_keys(tickets_path: Path = TICKETS_LATEST) -> set[tuple[str, str, str]]:
    """Return {(player_norm, prop_key, direction)} present on live tickets."""
    if not tickets_path.is_file():
        return set()
    try:
        data = json.loads(tickets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    keys: set[tuple[str, str, str]] = set()
    for g in data.get("groups") or []:
        for slip in g.get("tickets") or g.get("slips") or []:
            for leg in slip.get("legs") or []:
                if not isinstance(leg, dict):
                    continue
                player = _norm(leg.get("player"))
                prop = _prop_key(leg.get("prop_type") or leg.get("prop"))
                direction = str(leg.get("direction") or leg.get("dir") or "").upper()
                if direction in ("O", "MORE"):
                    direction = "OVER"
                if direction in ("U", "LESS"):
                    direction = "UNDER"
                if player and prop and direction in ("OVER", "UNDER"):
                    keys.add((player, prop, direction))
    return keys


def _build_profiles(rows: list[dict]) -> list[dict]:
    profiles: dict[tuple, dict] = {}
    for r in rows:
        sport = str(r.get("sport") or "").upper()
        player = str(r.get("player") or "").strip()
        prop = str(r.get("prop") or r.get("prop_type") or "").strip()
        l5o, l5n = _rate(r.get("l5_over"), r.get("l5_under"))
        l10o, l10n = _rate(r.get("l10_over"), r.get("l10_under"))
        if l10o is None or l10n < 6 or l5n < 4:
            continue
        pk = (sport, _norm(player), _prop_key(prop))
        ddir = str(r.get("dir") or r.get("direction") or "").upper()
        entry = {
            "sport": sport,
            "player": player,
            "prop": prop,
            "team": r.get("team"),
            "opp": r.get("opp"),
            "line": _fnum(r.get("line")),
            "l5_over": l5o,
            "l5_under": (1.0 - l5o) if l5o is not None else None,
            "l5_n": int(l5n),
            "l10_over": l10o,
            "l10_under": 1.0 - l10o,
            "l10_n": int(l10n),
            "season_avg": _fnum(r.get("season_avg")),
            "dirs": set([ddir] if ddir in ("OVER", "UNDER") else []),
            "tennis_games": _is_tennis_games(sport, prop),
        }
        prev = profiles.get(pk)
        if not prev or entry["l10_n"] > prev["l10_n"]:
            if prev:
                entry["dirs"] |= prev["dirs"]
            profiles[pk] = entry
        else:
            prev["dirs"] |= entry["dirs"]
    return list(profiles.values())


def _unique_side(profiles: list[dict], side: str, *, exclude_tennis_games: bool, n: int = 15, min_l10: float = 0.8) -> list[dict]:
    scored: list[dict] = []
    for e in profiles:
        if exclude_tennis_games and e["tennis_games"]:
            continue
        rate = e["l10_over"] if side == "OVER" else e["l10_under"]
        l5 = e["l5_over"] if side == "OVER" else e["l5_under"]
        if rate is None or l5 is None or rate < min_l10:
            continue
        score = 0.6 * rate + 0.4 * l5
        scored.append({**e, "side": side, "side_l5": round(l5, 4), "side_l10": round(rate, 4), "score": round(score, 4)})
    scored.sort(key=lambda x: (x["score"], x["l10_n"], x["l5_n"]), reverse=True)
    out: list[dict] = []
    seen: set[tuple] = set()
    for e in scored:
        k = (e["sport"], _norm(e["player"]))
        if k in seen:
            continue
        seen.add(k)
        row = {
            "sport": e["sport"],
            "player": e["player"],
            "prop": e["prop"],
            "side": side,
            "line": e.get("line"),
            "team": e.get("team"),
            "opp": e.get("opp"),
            "season_avg": e.get("season_avg"),
            "l5": e["side_l5"],
            "l5_n": e["l5_n"],
            "l10": e["side_l10"],
            "l10_n": e["l10_n"],
            "score": e["score"],
            "tennis_games": e["tennis_games"],
            "today_dirs": sorted(e["dirs"]),
        }
        out.append(row)
        if len(out) >= n:
            break
    return out


def _profile_to_track_row(e: dict, side: str) -> dict:
    rate = e["l10_over"] if side == "OVER" else e["l10_under"]
    l5 = e["l5_over"] if side == "OVER" else e["l5_under"]
    score = 0.6 * (rate or 0) + 0.4 * (l5 or 0)
    return {
        "sport": e["sport"],
        "player": e["player"],
        "prop": e["prop"],
        "side": side,
        "line": e.get("line"),
        "team": e.get("team"),
        "opp": e.get("opp"),
        "season_avg": e.get("season_avg"),
        "l5": round(l5, 4) if l5 is not None else None,
        "l5_n": e["l5_n"],
        "l10": round(rate, 4) if rate is not None else None,
        "l10_n": e["l10_n"],
        "score": round(score, 4),
        "tennis_games": e["tennis_games"],
        "today_dirs": sorted(e["dirs"]),
    }


def _mark_on_tickets(entries: list[dict], ticket_keys: set[tuple[str, str, str]]) -> list[dict]:
    out = []
    for e in entries:
        k = (_norm(e["player"]), _prop_key(e["prop"]), e["side"])
        on = k in ticket_keys
        if not on:
            for tp, tpr, td in ticket_keys:
                if td != e["side"]:
                    continue
                if _prop_key(e["prop"]) != tpr:
                    continue
                if _norm(e["player"]) in tp or tp in _norm(e["player"]):
                    on = True
                    break
        row = dict(e)
        row["on_tickets"] = on
        out.append(row)
    return out


def _ticket_consistent_legs(profiles: list[dict], ticket_keys: set[tuple[str, str, str]]) -> list[dict]:
    """Force-include ticketed player+prop sides that clear the consistency bar."""
    by_key = {(_norm(p["player"]), _prop_key(p["prop"])): p for p in profiles}
    out: list[dict] = []
    for player_n, prop_n, side in sorted(ticket_keys):
        e = by_key.get((player_n, prop_n))
        if not e:
            # combo tickets: match nested player name on exact prop
            e = next(
                (
                    p
                    for p in profiles
                    if _prop_key(p["prop"]) == prop_n and (_norm(p["player"]) in player_n or player_n in _norm(p["player"]))
                ),
                None,
            )
        if not e:
            continue
        rate = e["l10_over"] if side == "OVER" else e["l10_under"]
        l5 = e["l5_over"] if side == "OVER" else e["l5_under"]
        if rate is None or l5 is None:
            continue
        min_l10 = 0.9 if e["tennis_games"] else 0.8
        if rate < min_l10 or e["l10_n"] < 6 or e["l5_n"] < 4:
            continue
        row = _profile_to_track_row(e, side)
        row["on_tickets"] = True
        row["bucket"] = "on_tickets_consistent"
        out.append(row)
    return out


def cmd_snapshot(slate_date: str) -> int:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _load_slate_rows(slate_date)
    profiles = _build_profiles(rows)
    ticket_keys = _ticket_leg_keys()

    overs = _mark_on_tickets(_unique_side(profiles, "OVER", exclude_tennis_games=True, n=15), ticket_keys)
    unders = _mark_on_tickets(_unique_side(profiles, "UNDER", exclude_tennis_games=True, n=15), ticket_keys)
    ticketed = _ticket_consistent_legs(profiles, ticket_keys)

    tracked = []
    seen: set[tuple] = set()
    for bucket, items in (
        ("over_excl_tennis_games", overs),
        ("under_excl_tennis_games", unders),
        ("on_tickets_consistent", ticketed),
    ):
        for e in items:
            k = (e["sport"], _norm(e["player"]), _prop_key(e["prop"]), e["side"])
            if k in seen:
                # prefer marking on_tickets if later ticketed pass has it
                if e.get("on_tickets"):
                    for i, prev in enumerate(tracked):
                        pk = (prev["sport"], _norm(prev["player"]), _prop_key(prev["prop"]), prev["side"])
                        if pk == k:
                            tracked[i]["on_tickets"] = True
                            break
                continue
            seen.add(k)
            row = dict(e)
            row["bucket"] = e.get("bucket") or bucket
            tracked.append(row)

    payload = {
        "slate_date": slate_date[:10],
        "snapshotted_at": _utc_now(),
        "active_sports": sorted({str(r.get("sport") or "").upper() for r in rows if r.get("sport")}),
        "n_slate_rows": len(rows),
        "n_profiles": len(profiles),
        "n_tracked": len(tracked),
        "n_on_tickets": sum(1 for t in tracked if t.get("on_tickets")),
        "tracked": tracked,
        "summary_preview": {
            "top_over": [{"player": e["player"], "prop": e["prop"], "l10": e["l10"], "on_tickets": e["on_tickets"]} for e in overs[:8]],
            "top_under": [{"player": e["player"], "prop": e["prop"], "l10": e["l10"], "on_tickets": e["on_tickets"]} for e in unders[:8]],
            "on_tickets": [
                {"player": e["player"], "prop": e["prop"], "side": e["side"], "l10": e["l10"]}
                for e in tracked
                if e.get("on_tickets")
            ],
        },
    }
    out = snapshot_path(slate_date)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"[slate-consistency] snapshot {payload['n_tracked']} legs "
        f"({payload['n_on_tickets']} on tickets) -> {out}"
    )
    return 0


def _load_graded_props(slate_date: str) -> list[dict]:
    fname = f"graded_props_{slate_date[:10]}.json"
    for base in GRADED_PROPS_PATHS:
        path = base / fname
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = data if isinstance(data, list) else data.get("props") or data.get("rows") or []
        if isinstance(rows, list) and rows:
            return [r for r in rows if isinstance(r, dict)]
    return []


def _match_graded(player: str, sport: str, prop: str, side: str, graded: list[dict]) -> dict | None:
    want_p = _norm(player)
    want_sport = sport.upper()
    want_prop = _prop_key(prop)
    want_side = side.upper()
    cands: list[dict] = []
    for row in graded:
        if _norm(row.get("player")) != want_p:
            continue
        if str(row.get("sport") or "").upper() != want_sport:
            continue
        if _prop_key(row.get("prop_type") or row.get("prop")) != want_prop:
            continue
        row_dir = str(row.get("direction") or row.get("dir") or row.get("over_under") or "").upper()
        if row_dir in ("O", "MORE"):
            row_dir = "OVER"
        if row_dir in ("U", "LESS"):
            row_dir = "UNDER"
        if want_side and row_dir and row_dir != want_side:
            continue
        cands.append(row)
    if not cands:
        return None

    def sk(r: dict) -> tuple:
        res = str(r.get("result") or "").upper()
        return (0 if res in ("HIT", "MISS") else 1, str(r.get("tier") or "Z"))

    cands.sort(key=sk)
    return cands[0]


def _rebuild_track_record(last_n: int = 45) -> dict:
    GRADED_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(GRADED_DIR.glob("consistency_leaders_graded_*.json"), reverse=True)[:last_n]
    days = []
    total_hit = total_miss = total_decided = 0
    on_tix_hit = on_tix_miss = 0
    by_side = {"OVER": {"hit": 0, "miss": 0}, "UNDER": {"hit": 0, "miss": 0}}
    for path in reversed(files):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        s = data.get("summary") or {}
        hit = int(s.get("hit") or 0)
        miss = int(s.get("miss") or 0)
        decided = hit + miss
        total_hit += hit
        total_miss += miss
        total_decided += decided
        ot = data.get("on_tickets_summary") or {}
        on_tix_hit += int(ot.get("hit") or 0)
        on_tix_miss += int(ot.get("miss") or 0)
        for r in data.get("results") or []:
            res = str(r.get("result") or "").upper()
            side = str(r.get("side") or "").upper()
            if res in ("HIT", "MISS") and side in by_side:
                by_side[side][res.lower()] += 1
        days.append(
            {
                "slate_date": data.get("slate_date"),
                "hit_rate": data.get("hit_rate"),
                "hit": hit,
                "miss": miss,
                "decided": decided,
                "on_tickets_hit_rate": data.get("on_tickets_hit_rate"),
                "n_tracked": s.get("total"),
            }
        )
    ot_dec = on_tix_hit + on_tix_miss
    payload = {
        "updated_at": _utc_now(),
        "days": days,
        "overall": {
            "hit": total_hit,
            "miss": total_miss,
            "decided": total_decided,
            "hit_rate": round(total_hit / total_decided, 4) if total_decided else None,
            "on_tickets_hit": on_tix_hit,
            "on_tickets_miss": on_tix_miss,
            "on_tickets_hit_rate": round(on_tix_hit / ot_dec, 4) if ot_dec else None,
            "by_side": {
                side: {
                    **vals,
                    "hit_rate": round(vals["hit"] / (vals["hit"] + vals["miss"]), 4)
                    if (vals["hit"] + vals["miss"])
                    else None,
                }
                for side, vals in by_side.items()
            },
        },
    }
    TRACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACK_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    UI_TRACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    UI_TRACK_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def cmd_grade(slate_date: str) -> int:
    snap_p = snapshot_path(slate_date)
    if not snap_p.is_file():
        print(f"[slate-consistency] grade skip: no snapshot for {slate_date}", file=sys.stderr)
        return 0
    try:
        snap = json.loads(snap_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[slate-consistency] grade error: {exc}", file=sys.stderr)
        return 1

    graded_rows = _load_graded_props(slate_date)
    if not graded_rows:
        print(f"[slate-consistency] grade skip: no graded_props for {slate_date}", file=sys.stderr)
        return 0

    summary = {"hit": 0, "miss": 0, "void": 0, "push": 0, "pending": 0, "no_match": 0, "total": 0}
    on_tix = {"hit": 0, "miss": 0, "void": 0, "push": 0, "pending": 0, "no_match": 0, "total": 0}
    results: list[dict] = []

    for item in snap.get("tracked") or []:
        player = str(item.get("player") or "")
        sport = str(item.get("sport") or "")
        prop = str(item.get("prop") or "")
        side = str(item.get("side") or "").upper()
        row = dict(item)
        match = _match_graded(player, sport, prop, side, graded_rows)
        if not match:
            row["result"] = "NO_MATCH"
            summary["no_match"] += 1
            if item.get("on_tickets"):
                on_tix["no_match"] += 1
        else:
            result = str(match.get("result") or "").upper().strip() or "PENDING"
            row["result"] = result
            row["actual"] = _fnum(match.get("actual_value") or match.get("actual"))
            row["graded_line"] = _fnum(match.get("line")) or item.get("line")
            row["margin"] = _fnum(match.get("margin"))
            bucket = result.lower()
            if bucket in summary:
                summary[bucket] += 1
            elif result == "PENDING":
                summary["pending"] += 1
            else:
                summary["no_match"] += 1
            if item.get("on_tickets"):
                if bucket in on_tix:
                    on_tix[bucket] += 1
                elif result == "PENDING":
                    on_tix["pending"] += 1
                else:
                    on_tix["no_match"] += 1
        summary["total"] += 1
        if item.get("on_tickets"):
            on_tix["total"] += 1
        results.append(row)

    decided = summary["hit"] + summary["miss"]
    ot_decided = on_tix["hit"] + on_tix["miss"]
    payload = {
        "slate_date": slate_date[:10],
        "graded_at": _utc_now(),
        "summary": summary,
        "hit_rate": round(summary["hit"] / decided, 4) if decided else None,
        "on_tickets_summary": on_tix,
        "on_tickets_hit_rate": round(on_tix["hit"] / ot_decided, 4) if ot_decided else None,
        "results": results,
    }
    GRADED_DIR.mkdir(parents=True, exist_ok=True)
    out = graded_path(slate_date)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    track = _rebuild_track_record()
    print(
        f"[slate-consistency] graded {summary['total']} "
        f"(hit={summary['hit']} miss={summary['miss']} pending={summary['pending']} "
        f"no_match={summary['no_match']}) hit_rate={payload['hit_rate']} "
        f"on_tickets_hr={payload['on_tickets_hit_rate']} -> {out}"
    )
    overall = (track.get("overall") or {}).get("hit_rate")
    print(f"[slate-consistency] track overall hit_rate={overall}")
    return 0


def cmd_status(slate_date: str | None) -> int:
    d = (slate_date or str(date.today()))[:10]
    snap = snapshot_path(d)
    graded = graded_path(d)
    print(f"date={d}")
    print(f"snapshot={'yes' if snap.is_file() else 'no'}  {snap}")
    print(f"graded={'yes' if graded.is_file() else 'no'}  {graded}")
    if snap.is_file():
        data = json.loads(snap.read_text(encoding="utf-8"))
        print(f"tracked={data.get('n_tracked')} on_tickets={data.get('n_on_tickets')}")
        for e in data.get("tracked") or []:
            if e.get("on_tickets"):
                print(f"  TICKET {e['side']:5s} {e['sport']:7s} {e['player']} — {e['prop']} L10={e.get('l10')}")
    if graded.is_file():
        data = json.loads(graded.read_text(encoding="utf-8"))
        print(f"graded_hr={data.get('hit_rate')} on_tickets_hr={data.get('on_tickets_hit_rate')}")
        print(f"summary={data.get('summary')}")
    if TRACK_PATH.is_file():
        tr = json.loads(TRACK_PATH.read_text(encoding="utf-8"))
        print(f"track_overall={tr.get('overall')}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Track slate consistency leader hit rates")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("snapshot", help="Freeze tonight's consistency leaders")
    sp.add_argument("--date", default=str(date.today()))

    gp = sub.add_parser("grade", help="Grade a snapshot against graded_props")
    gp.add_argument("--date", default=str(date.today()))

    stp = sub.add_parser("status", help="Show snapshot/grade status")
    stp.add_argument("--date", default=None)

    sub.add_parser("rebuild-summary", help="Rebuild cumulative track_record.json")

    args = p.parse_args()
    if args.cmd == "snapshot":
        return cmd_snapshot(args.date)
    if args.cmd == "grade":
        return cmd_grade(args.date)
    if args.cmd == "status":
        return cmd_status(args.date)
    if args.cmd == "rebuild-summary":
        tr = _rebuild_track_record()
        print(json.dumps(tr.get("overall"), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
