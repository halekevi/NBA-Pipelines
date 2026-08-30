#!/usr/bin/env python3
"""Snapshot PrizePicks step1 boards and diff line/pick_type movement.

Used to catch day-ahead Standard numbers vs gameday cuts (often parked as Demon).

  py -3.14 scripts/pp_line_timeline.py snapshot --label 2108 --game-date 2026-08-18
  py -3.14 scripts/pp_line_timeline.py diff --a 1757 --b 2108 --game-date 2026-08-18
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_ET = ZoneInfo("America/New_York")
SNAP_ROOT = _REPO / "data" / "reports" / "pp_board_snaps"

STEP1 = (
    ("WNBA", "wnba", "step1_wnba_props.csv"),
    ("MLB", "mlb", "step1_mlb_props.csv"),
    ("SOCCER", "soccer", "step1_soccer_props.csv"),
    ("TENNIS", "tennis", "step1_tennis_props.csv"),
    ("GOLF", "golf", "step1_golf_props.csv"),
)
L5_FILES = {
    "WNBA": ("wnba", "step8_wnba_direction.csv"),
    "MLB": ("mlb", "step8_mlb_direction.csv"),
    "SOCCER": ("soccer", "step8_soccer_direction.csv"),
    "TENNIS": ("tennis", "step8_tennis_direction.csv"),
    "GOLF": ("golf", "step8_golf_direction.csv"),
}


def _player_key(v: object) -> str:
    return " ".join(str(v or "").strip().lower().split())


def _prop_key(v: object) -> str:
    return " ".join(str(v or "").strip().lower().replace("+", " ").split())


def _pick(v: object) -> str:
    s = str(v or "").strip().lower()
    if "dem" in s:
        return "Demon"
    if "gob" in s:
        return "Goblin"
    if "std" in s or s == "standard":
        return "Standard"
    return str(v or "").strip() or "Unknown"


def _read(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    except Exception:
        return pd.DataFrame()


def _l5_map(game_date: str) -> dict[tuple[str, str, str], dict]:
    out: dict[tuple[str, str, str], dict] = {}
    base = _REPO / "outputs" / game_date
    for sport, (folder, fname) in L5_FILES.items():
        df = _read(base / folder / fname)
        if df.empty:
            continue
        pcol = "player" if "player" in df.columns else "Player"
        prop = "prop_type" if "prop_type" in df.columns else "prop"
        for _, r in df.iterrows():
            gd = str(r.get("game_date") or "")[:10]
            if sport != "TENNIS" and gd and gd != game_date:
                continue
            key = (sport, _player_key(r.get(pcol)), _prop_key(r.get(prop)))
            out[key] = {
                "l5_over": None if pd.isna(r.get("l5_over")) else int(float(r.get("l5_over"))),
                "l5_under": None if pd.isna(r.get("l5_under")) else int(float(r.get("l5_under"))),
                "def": str(r.get("stat_def_tier") or r.get("DEF_TIER") or r.get("def_tier") or "").strip(),
            }
    return out


def load_board(step1_dir: Path, game_date: str) -> list[dict]:
    l5 = _l5_map(game_date)
    rows: list[dict] = []
    for sport, folder, fname in STEP1:
        path = step1_dir / folder / fname
        if not path.is_file():
            path = step1_dir / fname
        df = _read(path)
        if df.empty:
            continue
        for _, r in df.iterrows():
            gd = str(r.get("game_date") or "")[:10]
            start = str(r.get("start_time") or "")
            if gd and gd != game_date:
                # keep if start_time calendar is the game date
                if game_date not in start:
                    continue
            player = str(r.get("player") or r.get("Player") or "").strip()
            prop = str(r.get("prop_type") or r.get("Prop") or "").strip()
            if not player or not prop:
                continue
            line = pd.to_numeric(pd.Series([r.get("line")]), errors="coerce").iloc[0]
            pick = _pick(r.get("pick_type"))
            meta = l5.get((sport, _player_key(player), _prop_key(prop)), {})
            rec = {
                "sport": sport,
                "player": player,
                "prop": prop,
                "line": None if pd.isna(line) else float(line),
                "pick_type": pick,
                "game_date": gd or game_date,
                "team": str(r.get("team") or "").strip(),
                "opp": str(r.get("opp_team") or "").strip(),
                "l5_over": meta.get("l5_over"),
                "l5_under": meta.get("l5_under"),
                "def": meta.get("def") or "",
                "key": f"{sport}|{_player_key(player)}|{_prop_key(prop)}|{pick}",
            }
            rows.append(rec)
    return rows


def summarize(rows: list[dict]) -> dict:
    from collections import Counter

    by_pick = Counter(r["pick_type"] for r in rows)
    by_sport = Counter(r["sport"] for r in rows)
    notable = [
        r
        for r in rows
        if r["pick_type"] in ("Standard", "Goblin")
        and (
            (r.get("l5_over") is not None and r["l5_over"] >= 4)
            or (r.get("l5_under") is not None and r["l5_under"] >= 4)
        )
    ]
    return {
        "n": len(rows),
        "by_pick": dict(by_pick),
        "by_sport": dict(by_sport),
        "notable_l5_4": len(notable),
    }


def cmd_snapshot(label: str, game_date: str, src_date: str, src_dir: str = "") -> Path:
    src = Path(src_dir) if src_dir else (_REPO / "outputs" / src_date)
    dest = SNAP_ROOT / game_date / label
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for sport, folder, fname in STEP1:
        p = src / folder / fname
        if p.is_file():
            ddir = dest / folder
            ddir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, ddir / fname)
            try:
                copied.append(str(p.relative_to(_REPO)).replace("\\", "/"))
            except ValueError:
                copied.append(str(p))
    rows = load_board(dest, game_date)
    payload = {
        "generated_at": datetime.now(_ET).isoformat(timespec="seconds"),
        "label": label,
        "game_date": game_date,
        "src_date": src_date,
        "sources": copied,
        "counts": summarize(rows),
        "rows": rows,
    }
    outp = dest / "board.json"
    outp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"snapshot {label} -> {outp}  n={payload['counts']['n']}  {payload['counts']['by_pick']}")
    return dest


def _index(rows: list[dict]) -> dict[str, dict]:
    # last write wins if duplicates
    return {r["key"]: r for r in rows}


def cmd_diff(game_date: str, a_label: str, b_label: str) -> dict:
    a_path = SNAP_ROOT / game_date / a_label / "board.json"
    b_path = SNAP_ROOT / game_date / b_label / "board.json"
    a = json.loads(a_path.read_text(encoding="utf-8"))
    b = json.loads(b_path.read_text(encoding="utf-8"))
    ia, ib = _index(a["rows"]), _index(b["rows"])
    cuts, juiced, type_chg, added, removed = [], [], [], [], []
    for k, rb in ib.items():
        ra = ia.get(k)
        if ra is None:
            added.append(rb)
            continue
        la, lb = ra.get("line"), rb.get("line")
        pa, pb = ra.get("pick_type"), rb.get("pick_type")
        if pa != pb:
            type_chg.append({"key": k, "from": pa, "to": pb, "line_from": la, "line_to": lb, **{x: rb[x] for x in ("sport", "player", "prop")}})
        if la is not None and lb is not None and abs(float(lb) - float(la)) >= 0.5:
            rec = {
                "key": k,
                "delta": float(lb) - float(la),
                "line_from": la,
                "line_to": lb,
                "pick_from": pa,
                "pick_to": pb,
                "sport": rb["sport"],
                "player": rb["player"],
                "prop": rb["prop"],
                "l5_over": rb.get("l5_over"),
                "l5_under": rb.get("l5_under"),
            }
            if float(lb) < float(la):
                cuts.append(rec)
            else:
                juiced.append(rec)
    for k, ra in ia.items():
        if k not in ib:
            removed.append(ra)
    std_cuts = [c for c in cuts if c.get("pick_from") == "Standard" and c.get("pick_to") == "Standard"]
    gob_cuts = [c for c in cuts if c.get("pick_from") == "Goblin" and c.get("pick_to") == "Goblin"]
    out = {
        "generated_at": datetime.now(_ET).isoformat(timespec="seconds"),
        "game_date": game_date,
        "a": {"label": a_label, "asof": a.get("generated_at"), "n": a["counts"]["n"]},
        "b": {"label": b_label, "asof": b.get("generated_at"), "n": b["counts"]["n"]},
        "n_cuts": len(cuts),
        "n_standard_cuts": len(std_cuts),
        "n_goblin_cuts": len(gob_cuts),
        "n_juiced": len(juiced),
        "n_type_change": len(type_chg),
        "n_added": len(added),
        "n_removed": len(removed),
        "cuts": cuts[:40],
        "standard_cuts": std_cuts[:40],
        "juiced": juiced[:40],
        "type_changes": type_chg[:40],
        "std_to_demon": [t for t in type_chg if t["from"] == "Standard" and t["to"] == "Demon"],
        "counts_a": a["counts"],
        "counts_b": b["counts"],
    }
    dest = SNAP_ROOT / game_date / f"diff_{a_label}_to_{b_label}.json"
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"diff {a_label}->{b_label}: cuts={out['n_cuts']} std_cuts={out['n_standard_cuts']} gob_cuts={out['n_goblin_cuts']} juiced={out['n_juiced']} added={out['n_added']} removed={out['n_removed']}")
    for c in std_cuts[:10]:
        print(f"  STD CUT {c['sport']} {c['player']} {c['prop']} {c['line_from']}->{c['line_to']}")
    for c in [x for x in cuts if x not in std_cuts][:6]:
        print(f"  CUT {c['sport']} {c['player']} {c['prop']} {c['line_from']}->{c['line_to']} ({c['pick_from']})")
    return out


def ingest_day_ahead_json(path: Path, label: str, game_date: str) -> None:
    """Turn day_ahead_standard_lines_*.json into a comparable board.json (Standards only)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for rec in raw.get("all_standards") or []:
        if str(rec.get("game_date") or "")[:10] != game_date:
            continue
        rows.append(
            {
                "sport": rec.get("sport"),
                "player": rec.get("player"),
                "prop": rec.get("prop"),
                "line": rec.get("line"),
                "pick_type": "Standard",
                "game_date": game_date,
                "team": rec.get("team") or "",
                "opp": rec.get("opp_team") or "",
                "l5_over": rec.get("l5_over"),
                "l5_under": rec.get("l5_under"),
                "def": "",
                "key": f"{rec.get('sport')}|{_player_key(rec.get('player'))}|{_prop_key(rec.get('prop'))}|Standard",
            }
        )
    dest = SNAP_ROOT / game_date / label
    dest.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": raw.get("generated_at"),
        "label": label,
        "game_date": game_date,
        "src_date": "day_ahead_json",
        "sources": raw.get("sources"),
        "counts": summarize(rows),
        "rows": rows,
        "note": "Standards only (from day_ahead_standard_lines snapshot)",
    }
    (dest / "board.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"ingested {path.name} as {label} n={len(rows)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--label", required=True)
    s.add_argument("--game-date", required=True)
    s.add_argument("--src-date", default="", help="outputs/<src-date> folder (default=game-date)")
    s.add_argument("--src-dir", default="", help="Explicit directory with wnba/mlb/soccer/tennis/golf step1 CSVs")
    d = sub.add_parser("diff")
    d.add_argument("--game-date", required=True)
    d.add_argument("--a", required=True)
    d.add_argument("--b", required=True)
    i = sub.add_parser("ingest-day-ahead")
    i.add_argument("--file", required=True)
    i.add_argument("--label", required=True)
    i.add_argument("--game-date", required=True)
    args = ap.parse_args()
    if args.cmd == "snapshot":
        cmd_snapshot(
            args.label,
            args.game_date,
            args.src_date or args.game_date,
            src_dir=args.src_dir,
        )
    elif args.cmd == "diff":
        cmd_diff(args.game_date, args.a, args.b)
    else:
        ingest_day_ahead_json(Path(args.file), args.label, args.game_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
