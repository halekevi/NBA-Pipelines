import pandas as pd
df=pd.read_csv(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\outputs\2026-08-12\wnba\step8_wnba_direction.csv",dtype=str).fillna("")
m=(df["player"]=="Paige Bueckers")
if "prop_norm" in df.columns:
    m=m & (df["prop_norm"].str.lower()=="pts")
else:
    m=m & (df["prop_type"].str.lower()=="points")
cols=[c for c in ["player","prop_type","prop_norm","line","pick_type","standard_line","final_bet_direction","edge"] if c in df.columns]
print(df.loc[m,cols].to_string(index=False))
