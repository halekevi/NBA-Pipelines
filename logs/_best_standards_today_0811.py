#!/usr/bin/env python3
"""Best Standard props across all sports on today's slate."""
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


def main() -> None:
    slate = json.loads((ROOT / "ui_runner/templates/slate_latest.json").read_text(encoding="utf-8"))
    print("SLATE", slate.get("date"), slate.get("generated_at"))
    sports = slate.get("sports") or {}

    rows = []
    for sp, lst in sports.items():
        if not isinstance(lst, list):
            continue
        for r in lst:
            pick = str(r.get("pick_type") or "").strip()
            if "stan" not in pick.lower():
                continue
            prop = str(r.get("prop") or r.get("prop_type") or "")
            if "fantasy" in prop.lower():
                continue
            sport = str(r.get("sport") or sp).upper()
            d = str(r.get("dir") or r.get("direction") or "").upper()
            if d.startswith("U"):
                l5 = fnum(r.get("l5_under"), 0) or 0
                l10 = fnum(r.get("l10_under"), 0) or 0
            else:
                l5 = fnum(r.get("l5_over"), 0) or 0
                l10 = fnum(r.get("l10_over"), 0) or 0
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
                prob /= 100.0

            # Standard live-style gates
            gate = False
            if d.startswith("O") and l5 >= 3 and l10 >= 8:
                gate = True
            if d.startswith("U") and l10 >= 8:
                gate = True
            # Tennis / soccer often thinner — allow L10>=8 alone if L5 missing-ish but require l10
            if sport in ("TENNIS", "SOCCER", "SOC") and l10 >= 8 and prob >= 0.55:
                gate = True

            score = float(prob)
            if gate:
                score += 0.10
            if l5 >= 4:
                score += 0.05
            if l5 >= 5:
                score += 0.03
            if l10 >= 8:
                score += 0.05
            if l10 >= 9:
                score += 0.03
            if str(r.get("tier") or "").upper() == "A":
                score += 0.02
            sdef = str(r.get("stat_def_tier") or "").upper()
            if d.startswith("O") and sdef == "EASY":
                score += 0.03
            if d.startswith("O") and sdef == "HARD":
                score -= 0.02
            if d.startswith("U") and sdef == "HARD":
                score += 0.03
            if d.startswith("U") and sdef == "EASY":
                score -= 0.02

            rows.append(
                {
                    "sport": sport,
                    "player": r.get("player"),
                    "team": r.get("team"),
                    "opp": r.get("opp"),
                    "prop": prop,
                    "dir": d,
                    "line": fnum(r.get("line")),
                    "prob": prob,
                    "l5": l5,
                    "l10": l10,
                    "tier": r.get("tier") or "",
                    "stat_def": r.get("stat_def_tier") or "",
                    "def": r.get("def_tier") or "",
                    "edge": fnum(r.get("edge")),
                    "gate": gate,
                    "score": score,
                }
            )

    gated = [r for r in rows if r["gate"]]
    gated.sort(key=lambda x: (-x["score"], -x["prob"], -x["l10"], -x["l5"]))
    print(f"Standard total={len(rows)} gated={len(gated)}")

    print("\n=== TOP 40 STANDARD (gated) ===")
    for i, r in enumerate(gated[:40], 1):
        def_s = r["stat_def"] or r["def"] or "-"
        print(
            f"{i:2}. {r['sport']:7} {r['player']} | {r['prop']} {r['dir']} {r['line']} | "
            f"p={r['prob']:.1%} L5={int(r['l5'])}/5 L10={int(r['l10'])}/10 "
            f"tier={r['tier'] or '-'} def={def_s}"
        )

    print("\n=== BY SPORT (top 8 each) ===")
    by = defaultdict(list)
    for r in gated:
        by[r["sport"]].append(r)
    for sp in sorted(by, key=lambda s: (-len(by[s]), s)):
        print(f"--- {sp} n={len(by[sp])}")
        for r in by[sp][:8]:
            print(
                f"  {r['player']} | {r['prop']} {r['dir']} {r['line']} | "
                f"p={r['prob']:.1%} L5={int(r['l5'])} L10={int(r['l10'])} tier={r['tier'] or '-'}"
            )

    print("\n=== UNDERS ONLY (Standard gated) ===")
    unders = [r for r in gated if r["dir"].startswith("U")]
    for i, r in enumerate(unders[:25], 1):
        print(
            f"{i:2}. {r['sport']:7} {r['player']} | {r['prop']} UNDER {r['line']} | "
            f"p={r['prob']:.1%} L5={int(r['l5'])}/5 L10={int(r['l10'])}/10"
        )
    print("under_count", len(unders))


if __name__ == "__main__":
    main()
