#!/usr/bin/env python3
"""When did Aug 11 Standard lines move vs morning step1 scrape."""
from __future__ import annotations

import csv
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    ("Mason Barnett", "Hits Allowed"),
    ("Drew Anderson", "Hits Allowed"),
    ("Michael Wacha", "Pitches Thrown"),
    ("Erica Wheeler", "Pts+Rebs"),
    ("Erica Wheeler", "Pts+Rebs+Asts"),
    ("Erica Wheeler", "Pts+Asts"),
    ("Erica Wheeler", "Points"),
    ("Erica Wheeler", "Assists"),
    ("Erica Wheeler", "Rebounds"),
    ("Erica Wheeler", "3-PT Made"),
    ("Kelsey Mitchell", "Pts+Asts"),
    ("Aliyah Boston", "Free Throws Made"),
    ("Aliyah Boston", "Free Throws Attempted"),
    ("Aliyah Boston", "Pts+Rebs"),
    ("Aliyah Boston", "Rebounds"),
    ("Lauren Betts", "Points"),
    ("Lauren Betts", "Pts+Rebs"),
    ("Lauren Betts", "Pts+Asts"),
    ("Xiyu Wang", "Total Games"),
    ("Clay Holmes", "Hits Allowed"),
    ("Michael Soroka", "Hits Allowed"),
    ("Drew Anderson", "Singles"),
    ("Drew Anderson", "Hits"),
    ("Drew Anderson", "Runs"),
    ("Drew Anderson", "Total Bases"),
    ("Drew Anderson", "Hits+Runs+RBIs"),
]


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_xlsx(path: Path) -> list[dict]:
    if not path.exists():
        return []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    headers = [str(h or "").strip() for h in next(rows)]
    out = []
    for row in rows:
        d = {headers[i]: row[i] for i in range(len(headers))}
        out.append(d)
    return out


def find_lines(rows: list[dict], player: str, prop: str) -> list[str]:
    hits = []
    for r in rows:
        name = str(r.get("player") or r.get("Player") or r.get("player_name") or "")
        pr = str(r.get("prop") or r.get("Prop") or r.get("prop_type") or r.get("stat_type") or "")
        if player.lower() not in name.lower():
            continue
        if pr.lower() != prop.lower():
            continue
        pick = str(r.get("pick_type") or r.get("Pick Type") or r.get("board") or r.get("odds_type") or "")
        line = r.get("line") if r.get("line") is not None else r.get("Line")
        direction = r.get("dir") or r.get("Dir") or r.get("direction") or ""
        hits.append(f"{pick or '?'} {direction} {line}".strip())
    return hits


def main() -> None:
    sources = {
        "mlb_step1_13:07": load_csv(ROOT / "Sports/MLB/outputs/step1_snapshots/step1_mlb_props_2026-08-11.csv"),
        "wnba_step1_13:00": load_csv(ROOT / "Sports/WNBA/outputs/step1_snapshots/step1_wnba_props_2026-08-11.csv"),
        "tennis_step1_13:00": load_csv(ROOT / "Sports/Tennis/outputs/step1_tennis_props.csv"),
        "mlb_step8_15:02": load_xlsx(ROOT / "outputs/2026-08-11/mlb/step8_mlb_direction_clean.xlsx"),
        "mlb_step8_16:06": load_xlsx(ROOT / "Sports/MLB/step8_mlb_direction_clean.xlsx"),
        "wnba_step8_13:14": load_xlsx(ROOT / "outputs/2026-08-11/wnba/step8_wnba_direction_clean.xlsx"),
        "wnba_step8_16:06": load_xlsx(ROOT / "Sports/WNBA/step8_wnba_direction_clean.xlsx")
        if (ROOT / "Sports/WNBA/step8_wnba_direction_clean.xlsx").exists()
        else [],
        "tennis_step8_13:11": load_xlsx(ROOT / "outputs/2026-08-11/tennis/step8_tennis_direction_clean.xlsx"),
        "tennis_step8_16:06": load_xlsx(ROOT / "Sports/Tennis/step8_tennis_direction_clean.xlsx"),
        "mlb_bak_08:00": load_xlsx(
            ROOT / "data/historical/sport_root_backups/MLB/step8_mlb_direction_clean.bak_20260811_080454.xlsx"
        ),
        "mlb_bak_10:50": load_xlsx(
            ROOT / "data/historical/sport_root_backups/MLB/step8_mlb_direction_clean.bak_20260811_130753.xlsx"
        ),
    }
    # print header sizes
    for k, v in sources.items():
        print(f"{k}: {len(v)} rows")
        if v:
            print("  cols sample:", list(v[0].keys())[:12])

    print("\n=== LINE TIMELINE ===")
    for player, prop in TARGETS:
        print(f"\n{player} | {prop}")
        for label, rows in sources.items():
            hits = find_lines(rows, player, prop)
            if hits:
                # unique preserve order
                uniq = list(dict.fromkeys(hits))
                print(f"  {label}: {uniq[:8]}")


if __name__ == "__main__":
    main()
