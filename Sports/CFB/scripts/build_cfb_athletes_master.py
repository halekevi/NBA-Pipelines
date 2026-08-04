#!/usr/bin/env python3
"""
Build CFB ESPN athletes master from pull_rosters.py output.

Inputs:
  data/rosters/cfb_rosters.csv

Outputs:
  Sports/CFB/data/reference/ncaa_football_athletes_master.csv
  (schema expected by step5a_attach_espn_ids.py)

Also optionally resets the contaminated PP→ESPN map to header-only.
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import unicodedata
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
ROSTER_PATH = REPO / "data" / "rosters" / "cfb_rosters.csv"
MASTER_PATH = REPO / "Sports" / "CFB" / "data" / "reference" / "ncaa_football_athletes_master.csv"
PP_MAP_PATH = REPO / "Sports" / "CFB" / "data" / "reference" / "pp_to_espn_id_map.csv"

MASTER_COLS = [
    "espn_athlete_id",
    "athlete_name",
    "athlete_name_norm",
    "team_id",
    "team_abbr",
    "position",
    "jersey",
    "status",
    "updated_at",
]


def norm_name(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s'-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s).strip()
    return re.sub(r"\s+", " ", s)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build CFB athletes master from ESPN roster pull")
    ap.add_argument("--roster", default=str(ROSTER_PATH))
    ap.add_argument("--out", default=str(MASTER_PATH))
    ap.add_argument(
        "--reset-pp-map",
        action="store_true",
        help="Backup and clear Sports/CFB/.../pp_to_espn_id_map.csv (removes CBB contamination)",
    )
    args = ap.parse_args()

    roster_path = Path(args.roster)
    if not roster_path.is_file():
        raise SystemExit(f"Missing roster CSV: {roster_path} (run scripts/pull_rosters.py --sport cfb)")

    df = pd.read_csv(roster_path, dtype=str).fillna("")
    need = {"player_id", "player_name", "team_id", "team_abbr"}
    missing = need - set(df.columns)
    if missing:
        raise SystemExit(f"Roster missing columns: {sorted(missing)}")

    today = datetime.date.today().isoformat()
    out = pd.DataFrame(
        {
            "espn_athlete_id": df["player_id"].astype(str).str.strip(),
            "athlete_name": df["player_name"].astype(str).str.strip(),
            "athlete_name_norm": df["player_name"].astype(str).map(norm_name),
            "team_id": df["team_id"].astype(str).str.strip(),
            "team_abbr": df["team_abbr"].astype(str).str.strip().str.upper(),
            "position": df["position"].astype(str).str.strip() if "position" in df.columns else "",
            "jersey": df["jersey"].astype(str).str.strip() if "jersey" in df.columns else "",
            "status": df["status"].astype(str).str.strip() if "status" in df.columns else "",
            "updated_at": today,
        }
    )
    out = out[out["espn_athlete_id"].astype(bool) & out["athlete_name"].astype(bool)]
    out = out.drop_duplicates(subset=["espn_athlete_id"], keep="first").reset_index(drop=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out[MASTER_COLS].to_csv(out_path, index=False, encoding="utf-8")
    print(f"[cfb-master] wrote {len(out):,} athletes -> {out_path}")
    print(f"[cfb-master] teams={out['team_abbr'].nunique():,}")

    if args.reset_pp_map:
        map_path = PP_MAP_PATH
        if map_path.is_file():
            bak = map_path.with_suffix(map_path.suffix + f".bak_{today.replace('-', '')}")
            shutil.copy2(map_path, bak)
            print(f"[cfb-master] backed up PP map -> {bak}")
        map_path.parent.mkdir(parents=True, exist_ok=True)
        empty = pd.DataFrame(
            columns=[
                "pp_player_id",
                "espn_athlete_id",
                "team_id",
                "player_name",
                "team_abbr",
                "source",
                "updated_at",
            ]
        )
        empty.to_csv(map_path, index=False, encoding="utf-8")
        print(f"[cfb-master] reset PP map (header only) -> {map_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
