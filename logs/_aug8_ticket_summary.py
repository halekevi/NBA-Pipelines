import re
from pathlib import Path

text = Path("ui_runner/templates/ticket_eval_2026-08-08.html").read_text(
    encoding="utf-8", errors="replace"
)

# Pull summary card values: label then nearby value
# Typical structure: <div class="sum-lab">Hit rate</div><div class="sum-val">26.5%</div>
pairs = re.findall(
    r'class="sum-lab"[^>]*>(.*?)</[^>]+>\s*<[^>]+class="sum-val[^"]*"[^>]*>(.*?)</',
    text,
    re.I | re.S,
)
print("sum pairs")
for lab, val in pairs[:40]:
    lab = re.sub(r"<[^>]+>", "", lab)
    val = re.sub(r"<[^>]+>", "", val)
    lab = re.sub(r"\s+", " ", lab).strip()
    val = re.sub(r"\s+", " ", val).strip()
    print(f"  {lab}: {val}")

# Also banner counts with flexible class
print("won", len(re.findall(r"grade-ticket-result[^\"']*won", text, re.I)))
print("lost", len(re.findall(r"grade-ticket-result[^\"']*lost", text, re.I)))
print("RESULT WON", len(re.findall(r"RESULT:.*WON", text, re.I)))
print("RESULT LOSS", len(re.findall(r"RESULT:.*LOSS", text, re.I)))

# Per-sport ticket groups: count h2 won/loss by prefix
h2s = list(re.finditer(r"<h2[^>]*>([^<]+)</h2>", text, re.I))
print("h2 count", len(h2s))
from collections import Counter, defaultdict

sport_res = defaultdict(Counter)
for i, m in enumerate(h2s):
    title = m.group(1).strip()
    start = m.end()
    end = h2s[i + 1].start() if i + 1 < len(h2s) else len(text)
    chunk = text[start:end]
    if re.search(r"RESULT:.*WON", chunk, re.I) or re.search(r"grade-ticket-result[^\"']*won", chunk, re.I):
        r = "won"
    elif re.search(r"RESULT:.*LOSS", chunk, re.I) or re.search(r"grade-ticket-result[^\"']*lost", chunk, re.I):
        r = "lost"
    else:
        r = "other"
    sport = title.split()[0].upper() if title else "?"
    # normalize
    for key in ("MLB", "WNBA", "SOCCER", "TENNIS", "NBA", "NHL"):
        if key in title.upper():
            sport = key
            break
    sport_res[sport][r] += 1

print("by sport prefix")
for sp, c in sorted(sport_res.items()):
    d = c["won"] + c["lost"]
    wr = round(100 * c["won"] / d, 1) if d else None
    print(f"  {sp}: {dict(c)} WR={wr}%")
