#!/usr/bin/env python3
"""Best props on today's live slate with probabilities."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fnum(x, d=None):
    try:
        if x is None or x == "":
            return d
        v = float(x)
        return d if v != v else v
    except Exception:
        return d


def side_hits(r):
    d = str(r.get("dir") or r.get("direction") or "").upper()
    if d.startswith("U"):
        return fnum(r.get("l5_under"), 0) or 0, fnum(r.get("l10_under"), 0) or 0
    return fnum(r.get("l5_over"), 0) or 0, fnum(r.get("l10_over"), 0) or 0


def main() -> None:
    display_path = ROOT / "ui_runner" / "templates" / "slate_display_date.json"
    slate_path = ROOT / "ui_runner" / "templates" / "slate_latest.json"
    display = json.loads(display_path.read_text(encoding="utf-8")) if display_path.is_file() else {}
    slate = json.loads(slate_path.read_text(encoding="utf-8"))
    print("DISPLAY", display)
    print("SLATE", slate.get("date"), slate.get("generated_at"))
    sports = slate.get("sports") or {}
    print(
        "SPORT_COUNTS",
        {k: len(v) if isinstance(v, list) else 0 for k, v in sports.items()},
    )

    rows = []
    for sp, lst in sports.items():
        if not isinstance(lst, list):
            continue
        for r in lst:
            sport = str(r.get("sport") or sp).upper()
            pick = str(r.get("pick_type") or "").strip()
            if pick.lower() == "demon":
                continue
            prop = str(r.get("prop") or r.get("prop_type") or "")
            if "fantasy" in prop.lower():
                continue
            d = str(r.get("dir") or r.get("direction") or "").upper()
            l5, l10 = side_hits(r)
            prob = (
                fnum(r.get("leg_prob_used"))
                or fnum(r.get("hit_prob_selected"))
                or fnum(r.get("hit_prob_actionable"))
                or fnum(r.get("ml_prob"))
                or fnum(r.get("hit_rate"))
            )
            if prob is None:
                continue
            if prob > 1.5:
                prob = prob / 100.0
            score = float(prob)
            if l5 >= 4:
                score += 0.08
            if l5 >= 5:
                score += 0.04
            if l10 >= 8:
                score += 0.06
            if l10 >= 9:
                score += 0.03
            tier = str(r.get("tier") or "").upper()
            if tier == "A":
                score += 0.02
            # Prefer live gate shape for MAIN action
            gate_ok = False
            if "gob" in pick.lower() and d.startswith("O") and l5 >= 4 and l10 >= 8:
                gate_ok = True
                score += 0.05
            if "stan" in pick.lower() and d.startswith("O") and l5 >= 3 and l10 >= 8:
                gate_ok = True
                score += 0.04
            if "stan" in pick.lower() and d.startswith("U") and l10 >= 8:
                gate_ok = True
                score += 0.03
            rows.append(
                {
                    "sport": sport,
                    "player": r.get("player"),
                    "team": r.get("team"),
                    "opp": r.get("opp"),
                    "prop": prop,
                    "pick": pick,
                    "dir": d,
                    "line": fnum(r.get("line")),
                    "prob": prob,
                    "l5": l5,
                    "l10": l10,
                    "tier": tier,
                    "stat_def": r.get("stat_def_tier") or "",
                    "def": r.get("def_tier") or "",
                    "score": score,
                    "gate_ok": gate_ok,
                    "edge": fnum(r.get("edge")),
                }
            )

    rows.sort(key=lambda x: (-x["score"], -x["prob"], -x["l5"], -x["l10"]))
    gated = [r for r in rows if r["gate_ok"]]
    print("\n=== TOP ACTION (pass live L5/L10 style gates) ===")
    for i, r in enumerate((gated or rows)[:25], 1):
        def_s = r["stat_def"] or r["def"] or "-"
        print(
            f"{i:2}. {r['sport']:7} {r['pick'][:7]:7} {r['player']} | "
            f"{r['prop']} {r['dir']} {r['line']} | "
            f"p={r['prob']:.1%} L5={int(r['l5'])}/5 L10={int(r['l10'])}/10 "
            f"tier={r['tier'] or '-'} def={def_s}"
        )

    print("\n=== BY SPORT (top 5) ===")
    by = defaultdict(list)
    for r in (gated or rows):
        by[r["sport"]].append(r)
    for sp in sorted(by, key=lambda s: -len(by[s])):
        print(f"--- {sp} (gated n={len(by[sp])})")
        for r in by[sp][:5]:
            print(
                f"  {r['pick'][:7]:7} {r['player']} | {r['prop']} {r['dir']} {r['line']} | "
                f"p={r['prob']:.1%} L5={int(r['l5'])} L10={int(r['l10'])}"
            )


if __name__ == "__main__":
    main()
