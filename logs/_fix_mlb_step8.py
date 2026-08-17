from pathlib import Path

p = Path("Sports/MLB/scripts/step8_add_direction_context_mlb.py")
text = p.read_text(encoding="utf-8")
start = text.index("def build_clean_xlsx(df: pd.DataFrame, xlsx_path: str) -> None:")
end = text.index("def main() -> None:")
new = Path("logs/_mlb_step8_clean_fragment.py").read_text(encoding="utf-8")
if not new.endswith("\n\n"):
    new = new.rstrip() + "\n\n"
p.write_text(text[:start] + new + text[end:], encoding="utf-8")
print("rewrote OK", p.stat().st_size)
# quick syntax check
compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("syntax OK")
