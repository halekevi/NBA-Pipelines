#!/usr/bin/env python3
"""Offline backfill standard_line / delta on combined_slate_tickets for Goblin-Δ verify.

PP often omits Standard siblings + API standard_line for pitcher alts (Pitching Outs,
Hits Allowed, …) and thin Assists boards. Prefer sibling Standard from step2/slate;
else sport offset estimate (same as utils.pick_line_standard).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.pick_line_standard import (  # noqa: E402
    estimate_demon_standard_line,
    estimate_goblin_standard_line,
)


def _safe_float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _norm_name(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _norm_prop(s: str) -> str:
    return " ".join(str(s or "").strip().lower().replace("_", " ").split())


def _load_sibling_index() -> dict[tuple[str, str, str], float]:
    """(sport, player, prop) -> standard line from sport step2 picktype CSVs."""
    paths = [
        ROOT / "Sports/MLB/data/outputs/step2_mlb_picktypes.csv",
        ROOT / "Sports/MLB/step2_mlb_picktypes.csv",
        ROOT / "Sports/WNBA/outputs/step2_wnba_picktypes.csv",
        ROOT / "Sports/WNBA/step2_wnba_picktypes.csv",
        ROOT / "Sports/NBA/data/outputs/step2_nba_picktypes.csv",
        ROOT / "Sports/Tennis/outputs/step2_tennis_picktypes.csv",
        ROOT / "Sports/Soccer/outputs/step2_soccer_picktypes.csv",
    ]
    sport_guess = {
        "mlb": "MLB",
        "wnba": "WNBA",
        "nba": "NBA",
        "tennis": "TENNIS",
        "soccer": "SOCCER",
    }
    idx: dict[tuple[str, str, str], float] = {}
    for p in paths:
        if not p.is_file():
            continue
        try:
            df = pd.read_csv(p, low_memory=False)
        except Exception:
            continue
        name_l = p.name.lower()
        sport = next((v for k, v in sport_guess.items() if k in name_l or k in str(p).lower()), "")
        if "sport" in df.columns:
            # prefer per-row
            pass
        player_c = next((c for c in ("player", "Player", "player_name") if c in df.columns), None)
        prop_c = next((c for c in ("prop_type", "Prop", "prop", "stat") if c in df.columns), None)
        pick_c = next((c for c in ("pick_type", "Pick Type", "pick") if c in df.columns), None)
        line_c = next((c for c in ("line", "Line", "line_score") if c in df.columns), None)
        if not all([player_c, prop_c, pick_c, line_c]):
            continue
        std = df[df[pick_c].astype(str).str.lower().str.contains("standard", na=False)]
        for _, row in std.iterrows():
            sp = str(row.get("sport") or sport or "").strip().upper() or sport
            player = _norm_name(row.get(player_c))
            prop = _norm_prop(row.get(prop_c))
            line = _safe_float(row.get(line_c))
            if not sp or not player or not prop or line is None:
                continue
            idx.setdefault((sp, player, prop), line)
    return idx


def enrich_leg(leg: dict, siblings: dict[tuple[str, str, str], float]) -> bool:
    pt = str(leg.get("pick_type") or "").strip().lower()
    if "goblin" not in pt and "demon" not in pt:
        return False
    played = _safe_float(leg.get("line") or leg.get("played_line"))
    if played is None:
        return False
    cur_std = _safe_float(leg.get("standard_line") or leg.get("std_line"))
    cur_delta = None
    for k in ("line_distance", "delta", "goblin_delta", "line_discount_vs_standard"):
        f = _safe_float(leg.get(k))
        if f is not None and f > 0:
            cur_delta = f
            break
    if cur_std is not None and cur_delta is not None:
        return False

    sport = str(leg.get("sport") or leg.get("league") or "").strip().upper()
    player = _norm_name(leg.get("player") or leg.get("player_name"))
    prop = _norm_prop(leg.get("prop_type") or leg.get("prop") or leg.get("stat"))
    source = ""
    std = cur_std
    if std is None and sport and player and prop:
        std = siblings.get((sport, player, prop))
        if std is not None:
            source = "sibling_step2"
    if std is None:
        dev = leg.get("deviation_level") or 1
        if "demon" in pt:
            std = estimate_demon_standard_line(played, dev, sport=sport or "default")
        else:
            std = estimate_goblin_standard_line(played, dev, sport=sport or "default")
        if std is not None:
            source = "offset_estimate"
    if std is None:
        return False

    dist = abs(float(std) - float(played))
    if dist <= 0:
        return False
    leg["standard_line"] = float(std)
    if source:
        leg["standard_line_source"] = source
    leg["delta"] = round(dist, 3)
    # Direction-aware discount (OVER: std - line).
    direction = str(leg.get("direction") or "").strip().upper()
    if direction == "UNDER":
        leg["line_discount_vs_standard"] = round(float(played) - float(std), 3)
    else:
        leg["line_discount_vs_standard"] = round(float(std) - float(played), 3)
    return True


def enrich_tickets_payload(payload: dict) -> dict:
    siblings = _load_sibling_index()
    n_legs = 0
    n_changed = 0

    def walk(obj):
        nonlocal n_legs, n_changed
        if isinstance(obj, dict):
            legs = obj.get("legs")
            if isinstance(legs, list):
                for leg in legs:
                    if isinstance(leg, dict):
                        n_legs += 1
                        if enrich_leg(leg, siblings):
                            n_changed += 1
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    walk(payload)
    return {"n_legs_seen": n_legs, "n_legs_enriched": n_changed, "n_sibling_keys": len(siblings)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-07-22")
    ap.add_argument(
        "--tickets",
        default="",
        help="Override tickets JSON path (default ui_runner/data/combined_slate_tickets_<date>.json)",
    )
    args = ap.parse_args()
    path = Path(args.tickets) if args.tickets else (
        ROOT / "ui_runner" / "data" / f"combined_slate_tickets_{args.date}.json"
    )
    if not path.is_file():
        print(f"missing tickets: {path}")
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    stats = enrich_tickets_payload(payload)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"enriched {path}")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
