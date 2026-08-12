from pathlib import Path

p = Path("scripts/combined_slate_tickets.py")
lines = p.read_text(encoding="utf-8").splitlines()
# line 13168 is 0-indexed 13167: return df before tennis proxy
for i, line in enumerate(lines):
    if line == "    return df" and i > 0 and "astype(object).where(df.notna()" in lines[i - 1]:
        # confirm next non-empty is tennis proxy
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        if j < len(lines) and lines[j].startswith("def _tennis_hit_rate_zero_like_proxy"):
            lines[i] = '    return _overlay_sport_stat_defense(df, "NHL")'
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print("patched NHL at", i + 1)
            break
else:
    print("NHL patch site not found")
