#!/usr/bin/env python3
"""
golf_grader.py — Grade PGA props from ESPN round stats vs step8 slate.

Writes graded_golf_{date}.xlsx (sheets graded + Box Raw).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO = _SCRIPT_DIR.parents[2]
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from golf_actuals import actuals_lookup, load_golf_round_cache, prop_stat_key, _player_key  # noqa: E402
from scripts.l10_streak_utils import enrich_graded_l10_columns  # noqa: E402

_DEF_GRADED_COLS = [
    "player",
    "prop_type",
    "prop_norm",
    "line",
    "direction",
    "actual",
    "result",
    "reason",
    "notes",
]


def _empty_graded() -> pd.DataFrame:
    return pd.DataFrame(columns=_DEF_GRADED_COLS)


def _load_slate(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    if path.suffix.lower() in (".xlsx", ".xls"):
        try:
            return pd.read_excel(path, sheet_name="ALL", engine="openpyxl", dtype=str).fillna("")
        except ValueError:
            return pd.read_excel(path, sheet_name=0, engine="openpyxl", dtype=str).fillna("")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _grade(direction: str, line: float, actual: float | None) -> tuple[str, str, str]:
    if actual is None:
        return "VOID", "NO_MATCH_OR_INCOMPLETE", "NO_DATA"
    d = direction.strip().upper()
    if d == "OVER":
        return ("HIT", "", "") if actual >= line else ("MISS", "", "")
    if d == "UNDER":
        return ("HIT", "", "") if actual < line else ("MISS", "", "")
    return "VOID", "NO_DIRECTION", "NO_DIRECTION"


def _slate_field(row: pd.Series, *keys: str) -> str:
    for key in keys:
        if key not in row.index:
            continue
        val = row.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s and s.lower() not in ("nan", "none", "null"):
            return s
    return ""


def _default_slate_candidates(target: str) -> list[Path]:
    dated = _REPO / "outputs" / target
    golf_dir = dated / "golf"
    return [
        golf_dir / "step8_golf_direction_clean.xlsx",
        golf_dir / f"step8_golf_direction_clean_{target}.xlsx",
        golf_dir / "step8_golf_direction.csv",
        dated / f"step8_golf_direction_clean_{target}.xlsx",
        _REPO / "Sports" / "Golf" / "outputs" / "step8_golf_direction_clean.xlsx",
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--slate", default="")
    ap.add_argument("--output", default="")
    ap.add_argument("--refresh-cache", action="store_true")
    args = ap.parse_args()

    target = str(args.date).strip()[:10]
    slate_path = Path(args.slate) if str(args.slate).strip() else None
    if slate_path and not slate_path.is_absolute():
        slate_path = _REPO / slate_path
    if slate_path is None or not slate_path.is_file():
        slate_path = next((p for p in _default_slate_candidates(target) if p.is_file()), None)
    out = Path(args.output) if str(args.output).strip() else (_REPO / "outputs" / target / f"graded_golf_{target}.xlsx")
    if not out.is_absolute():
        out = _REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)

    if slate_path is None:
        print(f"[Golf grader] No step8 slate for {target} — writing empty graded workbook")
        _empty_graded().to_excel(out, sheet_name="graded", index=False)
        return

    slate = _load_slate(slate_path)
    if slate.empty:
        print(f"[Golf grader] Empty slate: {slate_path}")
        _empty_graded().to_excel(out, sheet_name="graded", index=False)
        return

    colmap = {
        "Player": "player",
        "Prop": "prop_type",
        "Line": "line",
        "Direction": "direction",
        "final_bet_direction": "direction",
    }
    for a, b in colmap.items():
        if a in slate.columns and b not in slate.columns:
            slate[b] = slate[a]

    cache = load_golf_round_cache(force_refresh=bool(args.refresh_cache))
    lookup = actuals_lookup(cache, target)

    rows: list[dict[str, object]] = []
    skipped = 0
    for _, r in slate.iterrows():
        player = str(r.get("player", "")).strip()
        prop_raw = str(r.get("prop_type", "")).strip()
        stat = prop_stat_key(prop_raw)
        if stat is None:
            skipped += 1
            continue
        direction = str(r.get("direction", r.get("final_bet_direction", ""))).strip()
        try:
            line = float(r.get("line", "") or r.get("Line", ""))
        except (TypeError, ValueError):
            line = float("nan")
        pk = _player_key(player)
        actual = lookup.get((pk, stat))
        res, note, void_reason = _grade(direction, line, actual)
        note_out = note or ("" if actual is not None else "PLAYER_OR_DATE_NOT_FOUND")
        rows.append(
            {
                "player": player,
                "prop_type": prop_raw,
                "prop_norm": stat,
                "line": line,
                "direction": direction,
                "actual": actual if actual is not None else "",
                "result": res,
                "reason": void_reason if res == "VOID" else "",
                "notes": note_out,
                "ml_prob": _slate_field(r, "ml_prob", "ML Prob"),
                "tier": _slate_field(r, "tier", "Tier"),
                "edge": _slate_field(r, "edge", "Edge"),
                "pick_type": _slate_field(r, "pick_type", "Pick Type"),
                "l5_over": _slate_field(r, "l5_over", "L5 Over", "last5_over"),
                "l5_under": _slate_field(r, "l5_under", "L5 Under", "last5_under"),
                "l10_over": _slate_field(r, "l10_over", "L10 Over"),
                "l10_under": _slate_field(r, "l10_under", "L10 Under"),
                "l10_streak": _slate_field(r, "l10_streak", "L10 Streak"),
                "team": _slate_field(r, "team", "Team", "event", "Event"),
            }
        )

    df = pd.DataFrame(rows) if rows else _empty_graded()
    if not df.empty:
        df = enrich_graded_l10_columns(df, line_col="line")
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="graded", index=False)
        if not df.empty:
            df.to_excel(w, sheet_name="Box Raw", index=False)
    if skipped:
        print(f"[Golf grader] Skipped unsupported/matchup props: {skipped}")
    n_hit = int((df["result"] == "HIT").sum()) if not df.empty else 0
    n_miss = int((df["result"] == "MISS").sum()) if not df.empty else 0
    print(f"[Golf grader] Saved -> {out}  rows={len(df)}  HIT={n_hit} MISS={n_miss}")


if __name__ == "__main__":
    main()
