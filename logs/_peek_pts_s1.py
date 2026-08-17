import pandas as pd
p=r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\outputs\2026-08-12\wnba\step1_wnba_props.csv"
df=pd.read_csv(p,dtype=str).fillna("")
m=df["player"].eq("Paige Bueckers") & df["prop_type"].str.lower().eq("points")
cols=[c for c in ["player","line","pick_type","standard_line","start_time"] if c in df.columns]
print(df.loc[m,cols].sort_values(by="line", key=lambda s: pd.to_numeric(s,errors="coerce")).to_string(index=False))
print("pick counts", df.loc[m,"pick_type"].value_counts().to_dict())
# Aja
m2=df["player"].str.contains("ja Wilson", case=False) & df["prop_type"].str.lower().eq("points")
print("Aja points", m2.sum())
if m2.any():
    print(df.loc[m2,cols].sort_values(by="line", key=lambda s: pd.to_numeric(s,errors="coerce")).to_string(index=False))
