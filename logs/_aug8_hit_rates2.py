import json
import re
from collections import Counter, defaultdict
from pathlib import Path

root = Path(__file__).resolve().parents[1]
date = "2026-08-08"
gp = json.loads((root / f"ui_runner/templates/graded_props_{date}.json").read_text(encoding="utf-8"))
props = gp.get("props") or gp.get("rows") or []


def res(x):
    # prefer explicit hit bool if present
    if "hit" in x and x["hit"] is not None:
        h = x["hit"]
        if h is True or h == 1 or str(h).lower() in ("true", "hit", "win"):
            return "HIT"
        if h is False or h == 0 or str(h).lower() in ("false", "miss", "loss"):
            return "MISS"
    r = str(x.get("result") or x.get("grade") or "").upper().strip()
    if r in ("HIT", "WIN", "W"):
        return "HIT"
    if r in ("MISS", "LOSS", "L"):
        return "MISS"
    if r in ("PUSH", "VOID"):
        return "PUSH"
    if r in ("PENDING", "LIVE", "OPEN", ""):
        return "PENDING"
    return r or "OTHER"


def sport(x):
    return str(x.get("sport") or "").upper() or "UNK"


def ptype(x):
    return str(x.get("pick_type") or "").title() or "Unk"


def summarize(label, rows):
    c = Counter(res(x) for x in rows)
    d = c["HIT"] + c["MISS"]
    hr = round(100 * c["HIT"] / d, 1) if d else None
    print(f"{label}: HIT={c['HIT']} MISS={c['MISS']} PUSH={c['PUSH']} PEND={c['PENDING']} HR={hr}% decided={d}")
    return c, d, hr


print("=== ALL GRADED PROPS ===")
summarize("ALL", props)

print("\n=== ON TICKET PROPS ===")
on_t = [x for x in props if x.get("on_ticket") or x.get("on_shadow_ticket")]
summarize("on_ticket|shadow", on_t)
on_main = [x for x in props if x.get("on_ticket")]
summarize("on_ticket only", on_main)
on_shadow = [x for x in props if x.get("on_shadow_ticket") and not x.get("on_ticket")]
summarize("shadow only", on_shadow)

print("\n=== ON TICKET BY SPORT ===")
by = defaultdict(list)
for x in on_main:
    by[sport(x)].append(x)
for sp in sorted(by):
    summarize(sp, by[sp])

print("\n=== ON TICKET BY PICK TYPE ===")
by2 = defaultdict(list)
for x in on_main:
    by2[ptype(x)].append(x)
for pt in sorted(by2):
    summarize(pt, by2[pt])

# Ticket HTML parse
html_path = root / f"ui_runner/templates/ticket_eval_{date}.html"
text = html_path.read_text(encoding="utf-8", errors="replace")

# Count RESULT banners
won = len(re.findall(r"RESULT:.*?WON", text, re.I))
lost = len(re.findall(r"RESULT:.*?LOSS", text, re.I))
pending = len(re.findall(r"RESULT:.*?PENDING", text, re.I))
void = len(re.findall(r"RESULT:.*?VOID", text, re.I))
print("\n=== TICKET EVAL HTML RESULT BANNERS ===")
print(f"WON={won} LOSS={lost} PENDING={pending} VOID={void}")
dec = won + lost
print(f"ticket_win_rate={round(100*won/dec,1) if dec else None}% decided={dec}")

# Try to find per-track sections
for track in [
    "ticket_eval",
    "strong_recombo",
    "strong_mix",
    "strong_standard",
    "winrate_goblin",
    "high_leg",
    "long_parlay",
]:
    p = root / f"ui_runner/templates/ticket_eval_{track}_{date}.html"
    if track == "ticket_eval":
        p = html_path
    if not p.exists():
        # alternate naming
        alts = list((root / "ui_runner/templates").glob(f"*{track}*{date}*.html"))
        if not alts:
            continue
        p = alts[0]
    t = p.read_text(encoding="utf-8", errors="replace")
    w = len(re.findall(r"RESULT:.*?WON", t, re.I))
    l = len(re.findall(r"RESULT:.*?LOSS", t, re.I))
    pend = len(re.findall(r"RESULT:.*?PENDING", t, re.I))
    d = w + l
    print(f"  {p.name}: WON={w} LOSS={l} PEND={pend} WR={round(100*w/d,1) if d else None}%")

# Look for summary JSON next to outputs
for p in [
    root / f"outputs/{date}/ticket_eval_summary.json",
    root / f"data/reports/ticket_eval_analysis_{date}.json",
    root / "data/reports/ticket_eval_analysis_latest.json",
]:
    if p.exists():
        print("found", p)
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            print(" keys", list(obj.keys())[:30] if isinstance(obj, dict) else type(obj))
        except Exception as e:
            print(" err", e)

# Parse grade-ticket-result classes more carefully
for cls, label in [
    (r'grade-ticket-result\s+won', "won_class"),
    (r'grade-ticket-result\s+lost', "lost_class"),
    (r'class="[^"]*grade-ticket-result won', "won2"),
    (r'class="grade-ticket-result won"', "won3"),
]:
    print(label, len(re.findall(cls, text, re.I)))

# Extract unique ticket cards by looking at RESULT lines context
results = re.findall(r'class="grade-ticket-result[^"]*"[^>]*>([^<]+)', text, re.I)
print("result texts", Counter([re.sub(r'\s+', ' ', r).strip() for r in results]))

# Sport breakdown for all props already known - also goblin-only board quality
print("\n=== ALL PROPS EXCLUDING DEMONS ===")
no_demon = [x for x in props if ptype(x) != "Demon"]
summarize("no demon", no_demon)
by3 = defaultdict(list)
for x in no_demon:
    by3[sport(x)].append(x)
for sp in sorted(by3):
    summarize(sp, by3[sp])
