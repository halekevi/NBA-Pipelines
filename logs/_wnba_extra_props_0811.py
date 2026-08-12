#!/usr/bin/env python3
"""Extra WNBA props today: overs + unders beyond the elite Goblin soft floors."""
from __future__ import annotations

import json
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
    rows = slate.get("sports", {}).get("wnba") or []
    print("SLATE", slate.get("date"), "wnba_n", len(rows))

    out = []
    for r in rows:
        pick = str(r.get("pick_type") or "")
        if pick.lower() == "demon":
            continue
        prop = str(r.get("prop") or "")
        if "fantasy" in prop.lower():
            continue
        d = str(r.get("dir") or "").upper()
        if d.startswith("U"):
            l5 = fnum(r.get("l5_under"), 0) or 0
            l10 = fnum(r.get("l10_under"), 0) or 0
        else:
            l5 = fnum(r.get("l5_over"), 0) or 0
            l10 = fnum(r.get("l10_over"), 0) or 0
        prob = (
            fnum(r.get("leg_prob_used"))
            or fnum(r.get("hit_prob_selected"))
            or fnum(r.get("ml_prob"))
            or fnum(r.get("hit_rate"))
        )
        if prob is None:
            continue
        if prob > 1.5:
            prob /= 100.0
        line = fnum(r.get("line"))
        # skip ultra-soft goblin floors already listed heavily (pts/asts tiny lines with p=0.85 + 5/5/10/10)
        soft_floor = (
            "gob" in pick.lower()
            and d.startswith("O")
            and l5 >= 5
            and l10 >= 10
            and prob >= 0.84
        )
        gate = False
        if "gob" in pick.lower() and d.startswith("O") and l5 >= 4 and l10 >= 8:
            gate = True
        if "stan" in pick.lower() and d.startswith("O") and l5 >= 3 and l10 >= 8:
            gate = True
        if d.startswith("U") and l10 >= 8:
            gate = True
            if "stan" in pick.lower():
                gate = True
            if "gob" in pick.lower() and l5 >= 4:
                gate = True
        if not gate:
            continue
        score = prob + (0.05 if l5 >= 4 else 0) + (0.04 if l10 >= 8 else 0) + (0.03 if l10 >= 9 else 0)
        if str(r.get("tier") or "").upper() == "A":
            score += 0.02
        # prefer not-already-saturated soft goblins in "additional" list
        if soft_floor:
            score -= 0.12
        # unders boost slightly for this query
        if d.startswith("U"):
            score += 0.04
        # stat def alignment
        sdef = str(r.get("stat_def_tier") or "").upper()
        if d.startswith("O") and sdef == "EASY":
            score += 0.03
        if d.startswith("O") and sdef == "HARD":
            score -= 0.02
        if d.startswith("U") and sdef == "HARD":
            score += 0.03
        if d.startswith("U") and sdef == "EASY":
            score -= 0.02
        out.append(
            {
                "player": r.get("player"),
                "team": r.get("team"),
                "opp": r.get("opp"),
                "prop": prop,
                "pick": pick,
                "dir": d,
                "line": line,
                "prob": prob,
                "l5": l5,
                "l10": l10,
                "tier": r.get("tier"),
                "stat_def": r.get("stat_def_tier") or "",
                "def": r.get("def_tier") or "",
                "edge": fnum(r.get("edge")),
                "score": score,
                "soft_floor": soft_floor,
            }
        )

    out.sort(key=lambda x: (-x["score"], -x["prob"], -x["l10"], -x["l5"]))

    unders = [x for x in out if x["dir"].startswith("U")]
    overs = [x for x in out if x["dir"].startswith("O") and not x["soft_floor"]]
    soft = [x for x in out if x["soft_floor"]]

    print("\n=== WNBA UNDERS (L10>=8) ===")
    for i, r in enumerate(unders[:20], 1):
        print(
            f"{i:2}. {r['pick'][:7]:7} {r['player']} ({r['team']} vs {r['opp']}) | "
            f"{r['prop']} UNDER {r['line']} | p={r['prob']:.1%} "
            f"L5={int(r['l5'])}/5 L10={int(r['l10'])}/10 tier={r['tier']} "
            f"statD={r['stat_def'] or '-'} def={r['def'] or '-'}"
        )

    print("\n=== WNBA ADDITIONAL OVERS (gated, not the 5/5+10/10 soft-floor pile) ===")
    for i, r in enumerate(overs[:20], 1):
        print(
            f"{i:2}. {r['pick'][:7]:7} {r['player']} ({r['team']} vs {r['opp']}) | "
            f"{r['prop']} OVER {r['line']} | p={r['prob']:.1%} "
            f"L5={int(r['l5'])}/5 L10={int(r['l10'])}/10 tier={r['tier']} "
            f"statD={r['stat_def'] or '-'} def={r['def'] or '-'}"
        )

    print("\n=== counts ===")
    print("unders", len(unders), "addl_overs", len(overs), "soft_floor_goblins", len(soft))


if __name__ == "__main__":
    main()
