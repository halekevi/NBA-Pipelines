import pandas as pd
from pathlib import Path

base = Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\outputs\2026-08-12")
for name in ["wnba/step1_wnba_props.csv", "wnba/step2_wnba_picktypes.csv"]:
    p = base / name
    if not p.exists():
        print("MISSING", name)
        continue
    df = pd.read_csv(p, dtype=str).fillna("")
    m = df["player"].str.contains(r"A.?ja|Paige B", case=False, regex=True)
    cols = [c for c in ["player", "prop_type", "prop_norm", "line", "pick_type", "standard_line", "start_time"] if c in df.columns]
    print("===", name, "rows", len(df), "===")
    print(df.loc[m, cols].to_string(index=False))
    print()
