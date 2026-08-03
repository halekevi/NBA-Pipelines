#!/usr/bin/env python3
"""Save slim Standard-line snapshots for line-move history."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.player_name_utils import normalize_player_name  # noqa: E402

_SNAP_ROOT = _REPO / "data" / "line_move_snapshots"
_LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _norm(raw: Any) -> str:
    return " ".join(str(raw or "").strip().lower().split())


def _to_float(raw: Any) -> float | None:
    try:
        if raw is None or str(raw).strip() == "":
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _pick_is_standard(raw: Any) -> bool:
    s = _norm(raw)
    return s in ("standard", "std", "") or s.startswith("standard")


def _rows_from_xlsx(path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    df = pd.read_excel(path, sheet_name="Full Slate", engine="openpyxl")
    cols = {str(c).strip().lower(): c for c in df.columns}

    def col(*names: str):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    c_sport = col("sport")
    c_player = col("player")
    c_prop = col("prop", "prop type", "prop_type")
    c_dir = col("dir", "direction")
    c_pick = col("pick type", "pick_type", "pick")
    c_line = col("line")
    c_std = col("standard line", "standard_line")
    if not all([c_sport, c_player, c_prop, c_dir, c_line]):
        return []
    out: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        pick = r.get(c_pick) if c_pick else "Standard"
        if not _pick_is_standard(pick):
            continue
        line = _to_float(r.get(c_line))
        if line is None:
            continue
        direction = _norm(r.get(c_dir)).upper()
        if direction not in ("OVER", "UNDER"):
            continue
        player = normalize_player_name(str(r.get(c_player) or ""))
        prop = _norm(r.get(c_prop))
        sport = _norm(r.get(c_sport)).upper()
        if not player or not prop or not sport:
            continue
        out.append(
            {
                "sport": sport,
                "player": player,
                "prop": prop,
                "direction": direction,
                "line": line,
                "standard_line": _to_float(r.get(c_std)) if c_std else None,
            }
        )
    return out


def _rows_from_slate_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if not _pick_is_standard(r.get("pick_type") or r.get("pick") or r.get("line_type")):
            continue
        line = _to_float(r.get("line"))
        if line is None:
            continue
        direction = _norm(r.get("direction") or r.get("dir")).upper()
        if direction not in ("OVER", "UNDER"):
            continue
        player = normalize_player_name(str(r.get("player") or ""))
        prop = _norm(r.get("prop") or r.get("prop_type"))
        sport = _norm(r.get("sport")).upper()
        if not player or not prop or not sport:
            continue
        out.append(
            {
                "sport": sport,
                "player": player,
                "prop": prop,
                "direction": direction,
                "line": line,
                "standard_line": _to_float(r.get("standard_line")),
            }
        )
    return out


def _resolve_source(date: str) -> Path | None:
    candidates = [
        _REPO / "outputs" / date / f"combined_slate_tickets_{date}.xlsx",
        _REPO / "ui_runner" / "templates" / "slate_latest.json",
        _REPO / "mobile" / "www" / "slate_latest.json",
    ]
    for p in candidates:
        if p.is_file() and p.stat().st_size > 100:
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot Standard PP lines for move history.")
    ap.add_argument("--date", required=True, help="Slate date YYYY-MM-DD")
    ap.add_argument("--label", required=True, help="Run label e.g. 5AM / 8AM / 1030AM / 1PM")
    ap.add_argument("--source", default="", help="Optional xlsx/json path override")
    args = ap.parse_args()

    date = str(args.date).strip()[:10]
    label = str(args.label).strip().replace(" ", "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print(f"[line-snap] bad date: {date}", file=sys.stderr)
        return 1
    if not _LABEL_RE.match(label):
        print(f"[line-snap] bad label: {label}", file=sys.stderr)
        return 1

    src = Path(args.source).expanduser().resolve() if args.source else _resolve_source(date)
    if src is None or not src.is_file():
        print(f"[line-snap] no slate source for {date}", file=sys.stderr)
        return 1

    try:
        if src.suffix.lower() in (".xlsx", ".xls"):
            legs = _rows_from_xlsx(src)
        else:
            legs = _rows_from_slate_json(src)
    except Exception as exc:
        print(f"[line-snap] read failed ({src.name}): {exc}", file=sys.stderr)
        return 1

    seen: set[tuple] = set()
    uniq: list[dict[str, Any]] = []
    for leg in legs:
        key = (leg["sport"], leg["player"], leg["prop"], leg["direction"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(leg)

    now = datetime.now().astimezone()
    stamp = now.strftime("%H%M%S")
    out_dir = _SNAP_ROOT / date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{label}_{stamp}.json"
    try:
        src_rel = str(src.relative_to(_REPO))
    except ValueError:
        src_rel = str(src)
    payload = {
        "slate_date": date,
        "run_label": label,
        "captured_at": now.isoformat(timespec="seconds"),
        "source": src_rel,
        "n_standard": len(uniq),
        "legs": uniq,
    }
    out_path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    latest = out_dir / f"{label}_latest.json"
    latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        rel = out_path.relative_to(_REPO)
    except ValueError:
        rel = out_path
    print(f"[line-snap] {date} {label}: {len(uniq)} Standard lines -> {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
