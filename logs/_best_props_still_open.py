import json
import math
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None

ROOT = Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp")
now = datetime.now(ET) if ET else datetime.now().astimezone()
print("NOW_ET", now.isoformat())

display = json.loads((ROOT / "ui_runner/templates/slate_display_date.json").read_text(encoding="utf-8"))
slate = json.loads((ROOT / "ui_runner/templates/slate_latest.json").read_text(encoding="utf-8"))
print("DISPLAY", display)
print("SLATE", slate.get("date"), slate.get("generated_at"))
sports = slate.get("sports") or {}


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


def espn_scoreboard(sport: str, ymd: str):
    ymdn = ymd.replace("-", "")
    paths = {
        "mlb": f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={ymdn}",
        "wnba": f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={ymdn}",
    }
    url = paths[sport]
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(sport, "FETCH_FAIL", e)
        return {}


def team_states(sport: str, ymd: str):
    data = espn_scoreboard(sport, ymd)
    out = {}
    print("===", sport.upper(), "===")
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        st = (comp.get("status") or {}).get("type") or {}
        state = str(st.get("state") or "").lower()  # pre/in/post
        desc = st.get("description")
        detail = st.get("detail")
        teams = []
        for c in comp.get("competitors") or []:
            ab = (c.get("team") or {}).get("abbreviation") or (c.get("team") or {}).get("shortDisplayName")
            if ab:
                teams.append(str(ab).upper())
                out[str(ab).upper()] = state
        print(f"  {' vs '.join(teams)} | {desc} | {state} | {detail}")
    return out


ymd = str(slate.get("date") or display.get("date") or "2026-08-09")
mlb_state = team_states("mlb", ymd)
wnba_state = team_states("wnba", ymd)

# Alias map for common mismatches
WNBA_ALIASES = {
    "GS": "GSV",
    "GSV": "GSV",
    "LV": "LVA",
    "LVA": "LVA",
    "LA": "LAS",
    "LAS": "LAS",
    "NY": "NYL",
    "NYL": "NYL",
    "PHX": "PHX",
    "PHO": "PHX",
    "WAS": "WAS",
    "WSH": "WAS",
    "DAL": "DAL",
    "MIN": "MIN",
    "SEA": "SEA",
    "ATL": "ATL",
    "CHI": "CHI",
    "CON": "CON",
    "IND": "IND",
}


def map_wnba(ab):
    a = str(ab or "").upper().strip()
    return WNBA_ALIASES.get(a, a)


def game_open(sport: str, team: str, opp: str) -> str | None:
    """Return 'open' if pre, 'live' if in, 'done' if post, None if unknown."""
    su = sport.upper()
    if su == "MLB":
        states = mlb_state
        t, o = str(team or "").upper(), str(opp or "").upper()
    elif su == "WNBA":
        states = wnba_state
        t, o = map_wnba(team), map_wnba(opp)
    else:
        return None
    vals = [states.get(t), states.get(o)]
    vals = [v for v in vals if v]
    if not vals:
        return None
    if any(v == "pre" for v in vals) and not any(v in ("in", "post") for v in vals):
        return "open"
    if any(v == "in" for v in vals):
        return "live"
    if all(v == "post" for v in vals):
        return "done"
    if any(v == "pre" for v in vals):
        return "open"
    return vals[0]


def side_hits(r):
    d = str(r.get("dir") or r.get("direction") or "").upper()
    if d == "OVER":
        a, b = fnum(r.get("l5_over"), 0) or 0, fnum(r.get("l5_under"), 0) or 0
        c, e = fnum(r.get("l10_over"), 0) or 0, fnum(r.get("l10_under"), 0) or 0
    else:
        a, b = fnum(r.get("l5_under"), 0) or 0, fnum(r.get("l5_over"), 0) or 0
        c, e = fnum(r.get("l10_under"), 0) or 0, fnum(r.get("l10_over"), 0) or 0
    n5, n10 = a + b, c + e
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


def score_row(r, sport):
    l5o, l5n, l5r, l10o, l10n, l10r = side_hits(r)
    if not l5n or l5n < 5 or (l5r or 0) < 0.8:
        return None
    if l10n and l10n >= 8 and (l10r or 0) < 0.6:
        return None
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
    if (model or 0) < 0.55 and not ((l5r or 0) >= 1.0 and (l10r or 0) >= 0.7):
        return None
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
    return score, {
        "sport": sport.upper(),
        "player": r.get("player"),
        "team": r.get("team"),
        "opp": r.get("opp"),
        "prop": r.get("prop"),
        "line": fnum(r.get("line")),
        "dir": str(r.get("dir") or "").upper(),
        "pick_type": str(r.get("pick_type") or ""),
        "l5": f"{int(l5o)}/{int(l5n)}",
        "l10": f"{int(l10o)}/{int(l10n)}" if l10n else "—",
        "leg_prob": round(leg, 3) if leg is not None else None,
        "ml_prob": round(ml, 3) if ml is not None else None,
        "projection": round(fnum(r.get("projection")) or 0, 2) if fnum(r.get("projection")) else None,
        "game_time": r.get("game_time"),
        "score": round(score, 4),
        "status": None,
    }


def top_open(sport_key, n=8, allow_live=False):
    rows = sports.get(sport_key) or []
    scored = []
    for r in rows:
        out = score_row(r, sport_key)
        if not out:
            continue
        sc, item = out
        st = game_open(sport_key, item["team"], item["opp"])
        item["status"] = st or "unknown"
        if sport_key in ("mlb", "wnba"):
            if st == "done":
                continue
            if st == "live" and not allow_live:
                continue
            if st is None:
                # keep unknown but tag
                pass
        scored.append((sc, item))
    scored.sort(key=lambda x: -x[0])
    picked = []
    pcount = defaultdict(int)
    propcount = defaultdict(int)
    for sc, item in scored:
        pl = str(item["player"] or "").lower()
        prop = str(item["prop"] or "").lower()
        if pcount[pl] >= 2:
            continue
        if propcount[(pl, prop)] >= 1:
            continue
        picked.append(item)
        pcount[pl] += 1
        propcount[(pl, prop)] += 1
        if len(picked) >= n:
            break
    return picked, len(scored)


print("\n=== BEST STILL AVAILABLE (pre-game preferred) ===")
for sp in ("wnba", "mlb", "tennis", "soccer"):
    tops, n_cand = top_open(sp, 8, allow_live=False)
    print(f"\n==== {sp.upper()} open/unknown candidates={n_cand} showing={len(tops)} ====")
    if not tops:
        tops_live, n2 = top_open(sp, 6, allow_live=True)
        print(f"  (no pre-game; live-included candidates={n2})")
        tops = tops_live
    for i, t in enumerate(tops, 1):
        print(
            f"{i}. [{t['status']}] {t['player']} | {t['prop']} {t['dir']} {t['line']} | "
            f"{t['pick_type']} | L5 {t['l5']} L10 {t['l10']} | leg={t['leg_prob']} | "
            f"{t['team']} vs {t['opp']} | {t['game_time']}"
        )
