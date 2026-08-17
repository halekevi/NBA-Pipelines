import pandas as pd
p=r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\outputs\2026-08-12\wnba\step2_wnba_picktypes.csv"
df=pd.read_csv(p,dtype=str).fillna("")
for name in ["A'ja","Paige Bueckers"]:
    m=df["player"].str.contains(name.replace("'","'?"), case=False, regex=True) & df.get("prop_norm",df.get("prop_type","")).astype(str).str.lower().isin(["pts","points"])
    if "prop_norm" in df.columns:
        m=df["player"].str.contains(name.replace("'","'?"), case=False, regex=True) & df["prop_norm"].str.lower().eq("pts")
    print("===", name, "===")
    cols=[c for c in ["player","line","pick_type","standard_line"] if c in df.columns]
    print(df.loc[m,cols].sort_values("line").to_string(index=False) if m.any() else "(none)")
