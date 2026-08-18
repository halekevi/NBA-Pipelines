#!/usr/bin/env python3
"""Merge today's tennis step8 into slate_latest.json (preserve other sports)."""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import combined_slate_tickets as cst  # noqa: E402

TEMPLATES = REPO / "ui_runner" / "templates"


def _write_text(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        if tmp.is_file() and path.parent != TEMPLATES:
            src = TEMPLATES / path.name
            try:
                if src.is_file():
                    shutil.copyfile(src, path)
                else:
                    shutil.copyfile(tmp, path)
                return True
            except OSError:
                pass
        print(f"WARN could not write {path}: {exc}")
        return False
    finally:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass


def main() -> int:
    date = (sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")).strip()[:10]
    candidates = [
        REPO / "outputs" / date / "tennis" / "step8_tennis_direction_clean.xlsx",
        REPO / "outputs" / date / f"step8_tennis_direction_clean_{date}.xlsx",
        REPO / "Sports" / "Tennis" / "step8_tennis_direction_clean.xlsx",
        REPO / "Sports" / "Tennis" / "outputs" / "step8_tennis_direction_clean.xlsx",
    ]
    tennis_path = next((p for p in candidates if p.is_file()), None)
    if tennis_path is None:
        print(f"Missing tennis step8 for {date}")
        return 1

    tennis = cst.load_tennis(str(tennis_path))
    tennis = cst.enforce_target_date(tennis, "Tennis", date, allow_cross_date_fallback=True)
    print(f"Tennis rows: {len(tennis)} from {tennis_path}")
    if tennis is None or len(tennis) == 0:
        print("Tennis board empty after date filter")
        return 1

    rows = cst.dataframe_to_slate_sport_rows(tennis)
    stamped = []
    for r in rows:
        rr = dict(r)
        gd = str(rr.get("game_date") or "").strip()[:10]
        if not gd or gd.lower() in ("nan", "none", "null"):
            rr["game_date"] = date
        rr["sport"] = "TENNIS"
        stamped.append(rr)
    rows = stamped
    gen_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    wrote_ok = 0

    for outdir in (TEMPLATES, REPO / "mobile" / "www"):
        slate_path = outdir / "slate_latest.json"
        if slate_path.is_file():
            try:
                payload = json.loads(slate_path.read_text(encoding="utf-8"))
            except OSError:
                payload = json.loads((TEMPLATES / "slate_latest.json").read_text(encoding="utf-8"))
        else:
            payload = {"date": date, "sports": {}}
        sports = payload.get("sports") if isinstance(payload.get("sports"), dict) else {}
        sports["tennis"] = rows
        payload["sports"] = sports
        payload["date"] = date
        payload["tennis_date"] = date
        payload["generated_at"] = gen_at
        payload = cst._sanitize_for_json(payload)
        ok = _write_text(slate_path, json.dumps(payload, ensure_ascii=False, default=str))
        ok = _write_text(
            outdir / "slate_sport_tennis.json",
            json.dumps(
                {"ok": True, "sport": "tennis", "date": date, "generated_at": gen_at, "rows": rows},
                ensure_ascii=False,
                default=str,
            ),
        ) and ok
        combined = []
        for sk, srows in sports.items():
            if not isinstance(srows, list):
                continue
            for r in srows:
                rr = dict(r) if isinstance(r, dict) else {"value": r}
                if not str(rr.get("sport") or "").strip():
                    rr["sport"] = str(sk).upper()
                combined.append(rr)
        ok = _write_text(
            outdir / "slate_sport_combined.json",
            json.dumps({"ok": True, "sport": "combined", "rows": combined}, ensure_ascii=False, default=str),
        ) and ok
        status_path = outdir / "pipeline_status.json"
        if status_path.is_file():
            try:
                st = json.loads(status_path.read_text(encoding="utf-8"))
            except Exception:
                st = {}
            block = st.get("tennis") if isinstance(st.get("tennis"), dict) else {}
            slate = block.get("slate") if isinstance(block.get("slate"), dict) else {}
            slate["exists"] = True
            slate["modified"] = gen_at.replace(" UTC", "")
            block["slate"] = slate
            st["tennis"] = block
            st["tennis_match_day"] = date
            gd = st.get("game_day") if isinstance(st.get("game_day"), dict) else {}
            gd["tennis"] = True
            st["game_day"] = gd
            _write_text(status_path, json.dumps(st, indent=2))
        total = sum(len(v) for v in sports.values() if isinstance(v, list))
        print(f"  {slate_path}  tennis={len(rows)}  all_sports={total}  ok={ok}")
        if ok:
            wrote_ok += 1

    if wrote_ok == 0:
        print("Failed to write tennis slate to ui_runner or mobile")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
