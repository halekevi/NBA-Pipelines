from pathlib import Path

p = Path("scripts/combined_slate_tickets.py")
text = p.read_text(encoding="utf-8")
old = (
    'l5o = pd.to_numeric(df.get("l5_over", np.nan), errors="coerce")\n'
    '    l5u = pd.to_numeric(df.get("l5_under", np.nan), errors="coerce")'
)
new = "l5o, l5u = _l5_over_under_series(df)"
print("exact pairs", text.count(old))
text = text.replace(old, new)
old2 = (
    'l5o_g = pd.to_numeric(df.get("l5_over", np.nan), errors="coerce")\n'
    '    l5u_g = pd.to_numeric(df.get("l5_under", np.nan), errors="coerce")'
)
new2 = "l5o_g, l5u_g = _l5_over_under_series(df)"
print("g pairs", text.count(old2))
text = text.replace(old2, new2)
text = text.replace("l5o, l5u = _l5_pair(df)", "l5o, l5u = _l5_over_under_series(df)")
p.write_text(text, encoding="utf-8")
print("remaining unsafe", text.count('df.get("l5_over", np.nan)'))
