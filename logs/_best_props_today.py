import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
slate = json.loads((ROOT / "ui_runner/templates/slate_latest.json").read_text(encoding="utf-8"))
sports = slate["sports"]
DATE = slate.get("date")


def fnum(x, default=None):
    try:
        if x is None or x == "":
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def side_hits(r):
    d = str(r.get("dir") or "").upper()
    if d == "OVER":
        a, b = fnum(r.get("l5_over"), 0) or 0, fnum(r.get("l5_under"), 0) or 0
        c, d10 = fnum(r.get("l10_over"), 0) or 0, fnum(r.get("l10_under"), 0) or 0
    else:
        a, b = fnum(r.get("l5_under"), 0) or 0, fnum(r.get("l5_over"), 0) or 0
        c, d10 = fnum(r.get("l10_under"), 0) or 0, fnum(r.get("l10_over"), 0) or 0
    n5, n10 = a + b, c + d10
    return a, n5, (a / n5 if n5 else None), c, n10, (c / n10 if n10 else None)


def softness(r):
    line = fnum(r.get("line"), 0) or 0
    proj = fnum(r.get("projection")) or fnum(r.get("standard_projection")) or fnum(r.get("season_avg"))
    if proj is None or line <= 0:
        return 0.0
    d = str(r.get("dir") or "").upper()
    if d == "OVER":
        return max(0.0, (proj - line) / max(line, 0.5))
    return max(0.0, (line - proj) / max(line, 0.5))


def itemize(r, sport, score):
    l5o, l5n, l5r, l10o, l10n, l10r = side_hits(r)
    hit = fnum(r.get("hit_prob_selected"))
    leg = fnum(r.get("leg_prob_used"))
    ml = fnum(r.get("ml_prob"))
    if sport == "soccer" and ml is not None and ml >= 0.99:
        ml = None
    proj = fnum(r.get("projection")) or fnum(r.get("standard_projection"))
    return {
        "sport": sport.upper(),
        "player": r.get("player"),
        "team": r.get("team"),
        "opp": r.get("opp"),
        "prop": r.get("prop"),
        "line": fnum(r.get("line")),
        "dir": str(r.get("dir") or "").upper(),
        "pick_type": str(r.get("pick_type") or ""),
        "tier": r.get("tier"),
        "l5": f"{int(l5o)}/{int(l5n)}",
        "l5_rate": round(l5r, 3) if l5r is not None else None,
        "l10": f"{int(l10o)}/{int(l10n)}" if l10n else "—",
        "l10_rate": round(l10r, 3) if l10r is not None else None,
        "hit_prob": round(hit, 3) if hit is not None else None,
        "leg_prob": round(leg, 3) if leg is not None else None,
        "ml_prob": round(ml, 3) if ml is not None else None,
        "consistency": round(fnum(r.get("consistency_score"), 0) or 0, 3),
        "rank_score": round(fnum(r.get("rank_score"), 0) or 0, 2),
        "edge": round(fnum(r.get("edge"), 0) or 0, 2),
        "projection": round(proj, 2) if proj is not None else None,
        "game_time": r.get("game_time"),
        "score": round(score, 4),
        "softness": round(softness(r), 3),
    }


def rank_pool(sport, mode="balanced", n=6):
    rows = sports.get(sport) or []
    scored = []
    for r in rows:
        l5o, l5n, l5r, l10o, l10n, l10r = side_hits(r)
        if not l5n or l5n < 5:
            continue
        pt = str(r.get("pick_type") or "").lower()
        hit = fnum(r.get("hit_prob_selected"))
        leg = fnum(r.get("leg_prob_used"))
        ml = fnum(r.get("ml_prob"))
        if sport == "soccer" and ml is not None and ml >= 0.99:
            ml = None
        cons = fnum(r.get("consistency_score"), 0) or 0
        rank = fnum(r.get("rank_score"), 0) or 0
        soft = softness(r)
        model = leg if leg is not None else ml
        emp = hit if hit is not None else l5r

        if mode == "floor":
            if (l5r or 0) < 1.0:
                continue
            if l10n and l10n >= 8 and (l10r or 0) < 0.8:
                continue
            if (model or 0) < 0.55:
                continue
            score = 0.5 * (l5r or 0) + 0.25 * (l10r or 0) + 0.15 * (emp or 0) + 0.1 * min(cons, 1)
        elif mode == "standard":
            if pt != "standard":
                continue
            if (l5r or 0) < 0.8:
                continue
            if (model or 0) < 0.58 and (l5r or 0) < 1.0:
                continue
            score = (
                0.28 * (l5r or 0)
                + 0.18 * (l10r or l5r or 0)
                + 0.22 * (model or emp or 0)
                + 0.12 * (emp or 0)
                + 0.10 * min(cons, 1)
                + 0.10 * min(max(rank, 0) / 10, 1)
            )
        else:
            if (l5r or 0) < 0.8:
                continue
            if l10n and l10n >= 8 and (l10r or 0) < 0.6:
                continue
            if (model or 0) < 0.55 and not ((l5r or 0) >= 1.0 and (l10r or 0) >= 0.7):
                continue
            score = (
                0.32 * (l5r or 0)
                + 0.18 * (l10r or l5r or 0)
                + 0.18 * (emp or 0)
                + 0.16 * (model or emp or 0)
                + 0.08 * min(cons, 1)
                + 0.08 * min(max(rank, 0) / 10, 1)
            )
            if soft > 1.5:
                score -= 0.08
            elif soft > 0.8:
                score -= 0.04
            line = fnum(r.get("line"), 0) or 0
            if pt == "goblin" and soft < 0.5 and line >= 2.5:
                score += 0.03

        scored.append((score, r))

    scored.sort(key=lambda x: -x[0])
    picked = []
    pcount = defaultdict(int)
    propcount = defaultdict(int)
    for score, r in scored:
        pl = str(r.get("player") or "").lower()
        prop = str(r.get("prop") or "").lower()
        if pcount[pl] >= 2:
            continue
        if propcount[(pl, prop)] >= 1:
            continue
        picked.append(itemize(r, sport, score))
        pcount[pl] += 1
        propcount[(pl, prop)] += 1
        if len(picked) >= n:
            break
    return picked


def soccer_loose(n=6):
    rows = sports["soccer"]
    scored = []
    for r in rows:
        l5o, l5n, l5r, l10o, l10n, l10r = side_hits(r)
        if not l5n or l5n < 5 or (l5r or 0) < 0.6:
            continue
        leg = fnum(r.get("leg_prob_used"))
        hit = fnum(r.get("hit_prob_selected"))
        cons = fnum(r.get("consistency_score"), 0) or 0
        score = (
            0.4 * (l5r or 0)
            + 0.25 * (l10r or l5r or 0)
            + 0.2 * (hit or l5r or 0)
            + 0.15 * min(cons, 1)
        )
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    picked = []
    pc = defaultdict(int)
    for score, r in scored:
        pl = str(r.get("player") or "").lower()
        if pc[pl] >= 1:
            continue
        picked.append(itemize(r, "soccer", score))
        pc[pl] += 1
        if len(picked) >= n:
            break
    return picked


out = {"date": DATE, "generated_at": slate.get("generated_at"), "sports": {}}
for sp in ["mlb", "wnba", "soccer", "tennis"]:
    out["sports"][sp] = {
        "best": rank_pool(sp, "balanced", 6),
        "standards": rank_pool(sp, "standard", 5),
        "safest_goblins": rank_pool(sp, "floor", 5),
    }
    print(f"\n==== {sp.upper()} BEST ====")
    for i, t in enumerate(out["sports"][sp]["best"], 1):
        print(
            f"{i}. {t['player']} | {t['prop']} {t['dir']} {t['line']} | {t['pick_type']} | "
            f"L5 {t['l5']} L10 {t['l10']} | leg={t['leg_prob']} hit={t['hit_prob']} | "
            f"soft={t['softness']} score={t['score']} | {t['team']} vs {t['opp']}"
        )
    print("  -- standards --")
    for i, t in enumerate(out["sports"][sp]["standards"], 1):
        print(
            f"  S{i}. {t['player']} | {t['prop']} {t['dir']} {t['line']} | "
            f"L5 {t['l5']} L10 {t['l10']} | leg={t['leg_prob']} rank={t['rank_score']}"
        )

if not out["sports"]["soccer"]["best"]:
    out["sports"]["soccer"]["best"] = soccer_loose(6)
    print("\n==== SOCCER LOOSE ====")
    for i, t in enumerate(out["sports"]["soccer"]["best"], 1):
        print(
            f"{i}. {t['player']} | {t['prop']} {t['dir']} {t['line']} | {t['pick_type']} | "
            f"L5 {t['l5']} L10 {t['l10']} | hit={t['hit_prob']} leg={t['leg_prob']}"
        )

out_path = Path(r"C:\Temp\best_props_2026-08-09.json")
out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
print("WROTE", out_path)
