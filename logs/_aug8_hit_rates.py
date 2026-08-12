import json
import re
from collections import Counter, defaultdict
from pathlib import Path

root = Path(__file__).resolve().parents[1]
date = "2026-08-08"

gp = json.loads((root / f"ui_runner/templates/graded_props_{date}.json").read_text(encoding="utf-8"))
if isinstance(gp, dict):
    props = gp.get("props") or gp.get("rows") or gp.get("graded") or []
    meta = {k: gp.get(k) for k in ("date", "generated_at", "n", "count") if k in gp}
else:
    props = gp
    meta = {}
print("PROPS meta", meta, "n", len(props))
if props:
    print("sample keys", sorted(props[0].keys())[:40])


def res(x):
    r = str(x.get("result") or x.get("grade") or x.get("outcome") or "").upper().strip()
    if r in ("HIT", "WIN", "W", "CORRECT", "TRUE", "1"):
        return "HIT"
    if r in ("MISS", "LOSS", "L", "INCORRECT", "FALSE", "0"):
        return "MISS"
    if r in ("PUSH", "VOID", "CANCEL", "PUSHED"):
        return "PUSH"
    if r in ("PENDING", "LIVE", "OPEN", ""):
        return "PENDING"
    return r or "OTHER"


def sport(x):
    return str(x.get("sport") or x.get("league") or "").upper() or "UNK"


def ptype(x):
    return str(x.get("pick_type") or x.get("pickType") or x.get("line_type") or "").title() or "Unk"


c = Counter(res(x) for x in props)
print("OVERALL", dict(c))
decided = c["HIT"] + c["MISS"]
print("hit_rate", round(100 * c["HIT"] / decided, 2) if decided else None, "decided", decided)

print("\nBY SPORT")
by = defaultdict(Counter)
for x in props:
    by[sport(x)][res(x)] += 1
for sp in sorted(by):
    cc = by[sp]
    d = cc["HIT"] + cc["MISS"]
    hr = round(100 * cc["HIT"] / d, 1) if d else None
    print(
        f"  {sp}: HIT={cc['HIT']} MISS={cc['MISS']} PUSH={cc['PUSH']} "
        f"PEND={cc['PENDING']} HR={hr}% decided={d}"
    )

print("\nBY PICK TYPE")
by2 = defaultdict(Counter)
for x in props:
    by2[ptype(x)][res(x)] += 1
for pt in sorted(by2):
    cc = by2[pt]
    d = cc["HIT"] + cc["MISS"]
    hr = round(100 * cc["HIT"] / d, 1) if d else None
    print(f"  {pt}: HIT={cc['HIT']} MISS={cc['MISS']} HR={hr}% decided={d}")

print("\nBY SPORT x PICK TYPE (decided>=25)")
by3 = defaultdict(Counter)
for x in props:
    by3[(sport(x), ptype(x))][res(x)] += 1
for k in sorted(by3):
    cc = by3[k]
    d = cc["HIT"] + cc["MISS"]
    if d < 25:
        continue
    print(f"  {k[0]} {k[1]}: {round(100 * cc['HIT'] / d, 1)}% ({cc['HIT']}/{d})")


# Tickets: prefer JSON sidecars, else scrape HTML summary tables
print("\n=== TICKETS ===")
candidates = [
    root / f"ui_runner/templates/ticket_eval_{date}.json",
    root / f"outputs/{date}/ticket_eval_{date}.json",
    root / "ui_runner/templates/ticket_eval_slate_latest.json",
    root / f"ui_runner/data/ticket_eval_{date}.json",
]
for p in candidates:
    print("exists", p.name if p.exists() else f"missing {p.name}", p.exists())

html = root / f"ui_runner/templates/ticket_eval_{date}.html"
text = html.read_text(encoding="utf-8", errors="replace")
# try embedded JSON
m = re.search(r"const\s+DATA\s*=\s*(\{.*?\});\s*</script>", text, re.S)
if not m:
    m = re.search(r"window\.__TICKET_EVAL__\s*=\s*(\{.*?\});", text, re.S)
if not m:
    m = re.search(r'<script[^>]*id="ticket-eval-data"[^>]*>(\{.*?\})</script>', text, re.S)

ticket_obj = None
if m:
    try:
        ticket_obj = json.loads(m.group(1))
        print("parsed embedded ticket JSON keys", list(ticket_obj.keys())[:30])
    except Exception as e:
        print("embed parse fail", e)

# Also look for summary strings in HTML
for pat in [
    r"hit[_\s-]?rate[^0-9%]{0,20}(\d+(?:\.\d+)?)\s*%",
    r"(\d+)\s*/\s*(\d+)\s*tickets?\s*(?:won|hit|correct)",
    r"Tickets?\s*won[:\s]+(\d+)",
    r"Win rate[:\s]+(\d+(?:\.\d+)?)\s*%",
]:
    found = re.findall(pat, text, re.I)
    if found:
        print("html pattern", pat, "->", found[:10])


def summarize_tickets(obj, label):
    if not obj:
        return
    tickets = (
        obj.get("tickets")
        or obj.get("rows")
        or obj.get("groups")
        or obj.get("evals")
        or obj.get("results")
        or []
    )
    if isinstance(obj, list):
        tickets = obj
    if not tickets and isinstance(obj.get("by_track"), dict):
        for track, val in obj["by_track"].items():
            summarize_tickets(val, f"{label}/{track}")
        return
    print(f"\n[{label}] n_tickets_field={len(tickets) if isinstance(tickets, list) else type(tickets)}")
    if not isinstance(tickets, list) or not tickets:
        # print shallow stats
        for k in ("summary", "stats", "totals", "hit_rate", "win_rate", "n_hit", "n_miss"):
            if k in obj:
                print(" ", k, obj[k])
        return
    print(" ticket sample keys", sorted(tickets[0].keys())[:40])
    tc = Counter()
    for t in tickets:
        r = str(
            t.get("result")
            or t.get("grade")
            or t.get("outcome")
            or t.get("status")
            or t.get("ticket_result")
            or ""
        ).upper()
        if "HIT" in r or r in ("WIN", "W", "WON", "CORRECT"):
            tc["HIT"] += 1
        elif "MISS" in r or r in ("LOSS", "L", "LOST", "INCORRECT"):
            tc["MISS"] += 1
        elif "PUSH" in r or "VOID" in r:
            tc["PUSH"] += 1
        elif "PEND" in r or "LIVE" in r or "OPEN" in r or r == "":
            # maybe derived from legs
            legs = t.get("legs") or t.get("picks") or []
            if legs:
                lr = [str(l.get("result") or l.get("grade") or "").upper() for l in legs]
                if any(x in ("PENDING", "LIVE", "") for x in lr) and not all(
                    x in ("HIT", "MISS", "PUSH", "WIN", "LOSS") for x in lr if x
                ):
                    tc["PENDING"] += 1
                elif all(x in ("HIT", "WIN", "PUSH") for x in lr) and any(x in ("HIT", "WIN") for x in lr):
                    # all hit or push
                    if any(x in ("HIT", "WIN") for x in lr) and not any(x in ("MISS", "LOSS") for x in lr):
                        tc["HIT"] += 1
                    else:
                        tc["OTHER"] += 1
                elif any(x in ("MISS", "LOSS") for x in lr):
                    tc["MISS"] += 1
                else:
                    tc["OTHER"] += 1
            else:
                tc["PENDING"] += 1
        else:
            tc[r or "OTHER"] += 1
    d = tc["HIT"] + tc["MISS"]
    print(" ticket results", dict(tc))
    print(" ticket hit_rate", round(100 * tc["HIT"] / d, 1) if d else None, "decided", d)


if ticket_obj:
    summarize_tickets(ticket_obj, "embedded")

# Try ticket_eval_slate_latest
for rel in [
    "ui_runner/templates/ticket_eval_slate_latest.json",
    "ui_runner/data/tickets_latest.json",
]:
    p = root / rel
    if not p.exists():
        continue
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        print("\nloaded", rel, "keys", list(obj.keys())[:20] if isinstance(obj, dict) else type(obj))
        if isinstance(obj, dict) and str(obj.get("date")) == date:
            summarize_tickets(obj, rel)
    except Exception as e:
        print("fail", rel, e)

# Scrape key metrics from ticket_eval HTML more carefully
print("\n=== HTML HEAD SNIPPETS ===")
# look for summary cards
for m in re.finditer(r"(Hit rate|Win rate|Tickets|Won|Lost|Pending|Props)[^<]{0,80}", text, re.I):
    s = m.group(0).strip()
    if len(s) > 10:
        print(" ", s[:120])
        if sum(1 for _ in re.finditer(r".", "x")):  # noop
            pass
# limit
hits = re.findall(r"(Hit rate|Win rate|Won|Lost|Pending)[:\s]*([0-9.]+%?)", text, re.I)
print("metric pairs sample", hits[:30])

# Parse ticket cards if data-result attributes exist
attrs = Counter(re.findall(r'data-result="([^"]+)"', text, re.I))
print("data-result attrs", dict(attrs))
classes = Counter(re.findall(r'class="[^"]*(hit|miss|won|lost|pending)[^"]*"', text, re.I))
print("class mentions", len(classes))
