from pathlib import Path

p = Path("scripts/combined_slate_tickets.py")
lines = p.read_text(encoding="utf-8").splitlines()
changed = False
for i, line in enumerate(lines):
    if line.strip() == 'df = _apply_l5_truth_from_stat_games(df, "NBA1H")':
        # only inside load_wcbb (sport set to WCBB above)
        window = "\n".join(lines[max(0, i - 80) : i])
        if 'df["sport"] = "WCBB"' in window or "df['sport'] = \"WCBB\"" in window or 'sport"] = "WCBB"' in window:
            lines[i] = '    df = _apply_l5_truth_from_stat_games(df, "WCBB")'
            changed = True
    if (
        line == "    return df"
        and i > 0
        and "astype(object).where(df.notna()" in lines[i - 1]
    ):
        # look back for WCBB sport assignment without later def
        back = "\n".join(lines[max(0, i - 120) : i])
        fwd = "\n".join(lines[i : min(len(lines), i + 15)])
        if 'df["sport"] = "WCBB"' in back and "_resolve_readable_mlb" in fwd or (
            'df["sport"] = "WCBB"' in back and "def _resolve_readable_mlb_step8" in "\n".join(lines[i : i + 40])
        ):
            lines[i] = '    return _overlay_sport_stat_defense(df, "WCBB")'
            changed = True
            print("patched return at", i + 1)
            break
else:
    # second pass: find WCBB return more carefully
    in_wcbb = False
    for i, line in enumerate(lines):
        if line.startswith("def load_wcbb"):
            in_wcbb = True
            continue
        if in_wcbb and line.startswith("def "):
            in_wcbb = False
        if in_wcbb and line.strip() == 'df = _apply_l5_truth_from_stat_games(df, "NBA1H")':
            lines[i] = '    df = _apply_l5_truth_from_stat_games(df, "WCBB")'
            changed = True
            print("patched L5 at", i + 1)
        if in_wcbb and line == "    return df":
            lines[i] = '    return _overlay_sport_stat_defense(df, "WCBB")'
            changed = True
            print("patched return at", i + 1)

if changed:
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("OK")
else:
    print("NO CHANGE")
