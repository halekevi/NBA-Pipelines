#!/usr/bin/env python3
"""Compare Aug 11 Standards list vs current slate lines."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# From the Aug 11 Standards answer (transcript)
WANTED = [
    ("MLB", "Mason Barnett", "Hits Allowed", "UNDER", 5.5),
    ("MLB", "Drew Anderson", "Hits Allowed", "UNDER", 3.5),
    ("WNBA", "Erica Wheeler", "Pts+Rebs", "OVER", 11.5),
    ("WNBA", "Erica Wheeler", "Pts+Rebs+Asts", "OVER", 16.5),
    ("WNBA", "Erica Wheeler", "Pts+Asts", "OVER", 14.5),
    ("WNBA", "Kelsey Mitchell", "Pts+Asts", "OVER", 26.5),
    ("MLB", "Michael Wacha", "Pitches Thrown", "OVER", 93.5),
    ("WNBA", "Aliyah Boston", "Free Throws Made", "UNDER", 2.5),
    ("WNBA", "Lauren Betts", "Points", "UNDER", 6.5),
    ("TENNIS", "Xiyu Wang", "Total Games", "UNDER", 21.5),
    ("MLB", "Drew Anderson", "Hits", "UNDER", 0.5),
    ("MLB", "Drew Anderson", "Runs", "UNDER", 0.5),
    ("MLB", "Drew Anderson", "Singles", "UNDER", 0.5),
    ("MLB", "Drew Anderson", "Total Bases", "UNDER", 0.5),
    ("MLB", "Drew Anderson", "Hits+Runs+RBIs", "UNDER", 0.5),
    ("WNBA", "Erica Wheeler", "Points", "OVER", 17.5),
    ("WNBA", "Erica Wheeler", "3-PT Made", "OVER", 1.5),
    ("WNBA", "Erica Wheeler", "Assists", "OVER", 4.5),
    ("WNBA", "Erica Wheeler", "Rebounds", "OVER", 7.5),
    ("MLB", "Clay Holmes", "Hits Allowed", "UNDER", 4.5),
    ("MLB", "Michael Soroka", "Hits Allowed", "UNDER", 4.5),
    ("WNBA", "Aliyah Boston", "Pts+Rebs", "UNDER", 16.5),
    ("WNBA", "Aliyah Boston", "Pts+Asts", "UNDER", 13.5),
    ("WNBA", "Aliyah Boston", "Rebounds", "UNDER", 6.5),
    ("WNBA", "Aliyah Boston", "Free Throws Attempted", "UNDER", 3.5),
    ("WNBA", "Lauren Betts", "Pts+Asts", "UNDER", 8.5),
    ("WNBA", "Lauren Betts", "Pts+Rebs", "UNDER", 9.5),
]


def norm(p: object) -> str:
    return str(p or "").lower().replace(" ", "").replace("+", "")


def main() -> None:
    slate = json.loads((ROOT / "ui_runner/templates/slate_latest.json").read_text(encoding="utf-8"))
    print("SLATE", slate.get("date"), slate.get("generated_at"))
    rows = []
    for sp, lst in (slate.get("sports") or {}).items():
        if not isinstance(lst, list):
            continue
        for r in lst:
            rr = dict(r)
            rr["_sport"] = str(r.get("sport") or sp).upper()
            rows.append(rr)

    print(f"{'PLAYER':20} {'PROP':22} {'LISTED':10} {'STATUS':8} NOW")
    print("-" * 110)
    for sport, player, prop, direction, line in WANTED:
        matches = [
            r
            for r in rows
            if player.lower() in str(r.get("player") or "").lower()
            and (norm(prop) in norm(r.get("prop")) or norm(r.get("prop")) in norm(prop))
        ]
        # prefer exact prop name match when possible
        exact_prop = [r for r in matches if str(r.get("prop") or "").lower() == prop.lower()]
        if exact_prop:
            matches = exact_prop
        std = [r for r in matches if str(r.get("pick_type") or "") == "Standard"]
        gob = [r for r in matches if str(r.get("pick_type") or "") == "Goblin"]
        dem = [r for r in matches if str(r.get("pick_type") or "") == "Demon"]

        def fmt(xs: list) -> str:
            bits = []
            for r in xs:
                bits.append(f"{r.get('dir')} {r.get('line')}")
            return ", ".join(bits) if bits else "-"

        same = [
            r
            for r in std
            if float(r.get("line") or -999) == float(line)
            and str(r.get("dir") or "").upper().startswith(direction[0])
        ]
        if same:
            status = "SAME"
        elif std:
            status = "MOVED"
        elif matches:
            status = "NO_STD"
        else:
            status = "GONE"
        now = f"Std[{fmt(std)}] Gob[{fmt(gob)}] Dem[{fmt(dem)[:40]}]"
        print(
            f"{player[:20]:20} {prop[:22]:22} {direction[0]} {line:<7} {status:8} {now}"
        )


if __name__ == "__main__":
    main()
