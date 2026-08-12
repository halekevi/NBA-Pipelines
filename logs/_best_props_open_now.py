import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
now = datetime.now(ET)
ROOT = Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp")
slate = json.loads((ROOT / "ui_runner/templates/slate_latest.json").read_text(encoding="utf-8"))
sports = slate["sports"]


def fnum(x, d=None):
    try:
        if x is None or x == "":
            return d
        v = float(x)
        return d if math.isnan(v) else v
    except Exception:
        return d


def parse_time(gt):
    if not gt:
        return None
    s = str(gt)
    try:
        if "T" in s or s.startswith("2026"):
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(ET)
    except Exception:
        pass
    m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", s, re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return now.replace(hour=h, minute=mi, second=0, microsecond=0)


def side(r):
    d = str(r.get("dir") or "").upper()
    if d == "OVER":
        a, b = fnum(r.get("l5_over"), 0) or 0, fnum(r.get("l5_under"), 0) or 0
        c, e = fnum(r.get("l10_over"), 0) or 0, fnum(r.get("l10_under"), 0) or 0
    else:
        a, b = fnum(r.get("l5_under"), 0) or 0, fnum(r.get("l5_over"), 0) or 0
        c, e = fnum(r.get("l10_under"), 0) or 0, fnum(r.get("l10_over"), 0) or 0
    n5, n10 = a + b, c + e
    return a, n5, (a / n5 if n5 else None), c, n10, (c / n10 if n10 else None)


OPEN_WNBA = {"GSV", "LAS"}
OPEN_MLB = {"SD", "HOU"}


def keep(sp, r):
    team = str(r.get("team") or "").upper()
    opp = str(r.get("opp") or "").upper()
    if sp == "wnba":
        return team in OPEN_WNBA and opp in OPEN_WNBA
    if sp == "mlb":
        return team in OPEN_MLB and opp in OPEN_MLB
    if sp == "tennis":
        t = parse_time(r.get("game_time"))
        return bool(t and t >= now.replace(second=0, microsecond=0))
    return False


out = []
for sp in ("wnba", "mlb", "tennis"):
    for r in sports.get(sp) or []:
        if not keep(sp, r):
            continue
        pt = str(r.get("pick_type") or "")
        if "demon" in pt.lower():
            continue
        l5o, l5n, l5r, l10o, l10n, l10r = side(r)
        if not l5n or l5n < 5 or (l5r or 0) < 0.8:
            continue
        if l10n and l10n >= 8 and (l10r or 0) < 0.6:
            continue
        leg = fnum(r.get("leg_prob_used"))
        ml = fnum(r.get("ml_prob"))
        hit = fnum(r.get("hit_prob_selected"))
        model = leg if leg is not None else ml
        if (model or 0) < 0.55 and not ((l5r or 0) >= 1 and (l10r or 0) >= 0.7):
            continue
        line = fnum(r.get("line"), 0) or 0
        proj = fnum(r.get("projection")) or 0
        d = str(r.get("dir") or "").upper()
        soft = 0.0
        if proj and line:
            soft = (proj - line) / max(line, 0.5) if d == "OVER" else (line - proj) / max(line, 0.5)
        score = (
            0.35 * (l5r or 0)
            + 0.20 * (l10r or l5r or 0)
            + 0.20 * (hit or l5r or 0)
            + 0.15 * (model or 0)
            + 0.10 * min(fnum(r.get("consistency_score"), 0) or 0, 1)
        )
        if soft > 0.8:
            score -= 0.05
        if "goblin" in pt.lower() and soft < 0.5 and line >= 2.5:
            score += 0.03
        out.append((score, sp, r, l5o, l5n, l10o, l10n, leg, soft))

out.sort(key=lambda x: -x[0])
picked = []
seen = set()
pcount = defaultdict(int)
for score, sp, r, l5o, l5n, l10o, l10n, leg, soft in out:
    key = (sp, str(r.get("player")).lower(), str(r.get("prop")).lower())
    if key in seen:
        continue
    pl = str(r.get("player")).lower()
    if pcount[(sp, pl)] >= 2:
        continue
    picked.append((score, sp, r, l5o, l5n, l10o, l10n, leg, soft))
    seen.add(key)
    pcount[(sp, pl)] += 1

print("NOW", now.strftime("%Y-%m-%d %H:%M ET"))
print("OPEN: WNBA LAS@GSV 7:00 PM | MLB SD@HOU 8:20 PM | Tennis not started yet")
print()
for sp in ("wnba", "mlb", "tennis"):
    rows = [x for x in picked if x[1] == sp][:8]
    print("====", sp.upper(), "====")
    if not rows:
        print("  (none left with L5>=4/5)")
    for i, (_, sp, r, l5o, l5n, l10o, l10n, leg, soft) in enumerate(rows, 1):
        print(
            f"{i}. {r.get('player')} | {r.get('prop')} {str(r.get('dir')).upper()} {r.get('line')} | "
            f"{r.get('pick_type')} | L5 {int(l5o)}/{int(l5n)} L10 {int(l10o)}/{int(l10n) if l10n else 0} | "
            f"leg={leg} | {r.get('team')} vs {r.get('opp')} | {r.get('game_time')}"
        )
    print()
