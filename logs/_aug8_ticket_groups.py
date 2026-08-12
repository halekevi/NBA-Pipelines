import re
from collections import Counter, defaultdict
from pathlib import Path

text = Path("ui_runner/templates/ticket_eval_2026-08-08.html").read_text(
    encoding="utf-8", errors="replace"
)
tracks = re.findall(r'data-(?:track|lane|group|sheet)="([^"]+)"', text, re.I)
print("data tracks", Counter(tracks).most_common(20))
for pat in [
    r'<h2[^>]*>([^<]{3,80})</h2>',
    r'<h3[^>]*>([^<]{3,80})</h3>',
    r'class="sheet-title"[^>]*>([^<]+)',
    r'class="track-name"[^>]*>([^<]+)',
    r'class="sum-lab"[^>]*>([^<]+)',
]:
    found = re.findall(pat, text, re.I)
    if found:
        print(pat, Counter([re.sub(r"\s+", " ", x).strip() for x in found]).most_common(20))

blocks = list(re.finditer(r'class="grade-ticket-result\s+(won|lost)"[^>]*>', text, re.I))
print("blocks", len(blocks))
by = defaultdict(Counter)
for m in blocks:
    chunk = text[max(0, m.start() - 1200) : m.start()]
    cands = re.findall(
        r'(?:ticket-title|card-title|tix-name|group-label|badge-track)[^>]*>([^<]{2,100})',
        chunk,
        re.I,
    )
    if not cands:
        cands = re.findall(r'data-ticket-id="([^"]+)"', chunk, re.I)
    if not cands:
        cands = re.findall(r"<strong>([^<]{3,80})</strong>", chunk)
    title = re.sub(r"\s+", " ", (cands[-1] if cands else "?")).strip()
    by[title][m.group(1).lower()] += 1

print("top titles")
for n, k, c in sorted(((sum(c.values()), k, dict(c)) for k, c in by.items()), reverse=True)[:30]:
    d = c.get("won", 0) + c.get("lost", 0)
    wr = round(100 * c.get("won", 0) / d, 1) if d else None
    print(f"  {k}: {c} WR={wr}% n={n}")
