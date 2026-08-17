"""Today's best Standard/Goblin props: L5 >= 4 and defense aligned."""
from __future__ import annotations

import pandas as pd
from pathlib import Path

BASE = Path(r"H:\halek\ProfileFromC\Desktop\PropORACLE_main_cp\outputs\2026-08-15")
WEAK = {"weak", "below avg", "below average", "very weak"}
TOUGH = {"elite", "strong", "above avg", "above average"}


def col(df, *names):
    lower = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def load(path, sport):
    df = pd.read_excel(path)
    df["_sport"] = sport
    p = col(df, "Player", "player")
    t = col(df, "Team", "team")
    o = col(df, "Opp", "opp", "opp_team")
    pr = col(df, "Prop", "prop", "prop_type")
    pk = col(df, "Pick Type", "pick_type")
    ln = col(df, "Line", "line")
    d = col(df, "Direction", "final_bet_direction")
    l5o = col(df, "L5 Over", "l5_over", "last5_over")
    l5u = col(df, "L5 Under", "l5_under", "last5_under")
    dt = col(df, "Def Tier", "def_tier")
    rs = col(df, "Rank Score", "rank_score")
    hr = col(df, "Hit Rate L5", "hit_rate_L5", "Hit Rate (5g)")
    tier = col(df, "Tier", "tier")
    out = pd.DataFrame({
        "sport": sport,
        "player": df[p] if p else "",
        "team": df[t] if t else "",
        "opp": df[o] if o else "",
        "prop": df[pr] if pr else "",
        "pick": df[pk].astype(str).str.strip() if pk else "",
        "line": pd.to_numeric(df[ln], errors="coerce") if ln else None,
        "dir": df[d].astype(str).str.upper().str.strip() if d else "",
        "l5o": pd.to_numeric(df[l5o], errors="coerce") if l5o else pd.NA,
        "l5u": pd.to_numeric(df[l5u], errors="coerce") if l5u else pd.NA,
        "def": df[dt].astype(str).str.strip() if dt else "",
        "rank": pd.to_numeric(df[rs], errors="coerce") if rs else pd.NA,
        "hr5": pd.to_numeric(df[hr], errors="coerce") if hr else pd.NA,
        "tier": df[tier].astype(str) if tier else "",
    })
    out["pick"] = out["pick"].str.replace(r"\s+", " ", regex=True)
    out["pick_n"] = out["pick"].str.lower()
    return out


def l5_hits(row):
    if row["dir"] == "UNDER":
        return row["l5u"]
    return row["l5o"]


def def_ok(row, sport):
    if sport == "Tennis":
        return True  # no team D
    d = str(row["def"] or "").strip().lower()
    if d in ("", "nan", "none", "avg", "average", "?"):
        return False
    if row["dir"] == "UNDER":
        return d in TOUGH
    return d in WEAK


files = {
    "MLB": BASE / "step8_mlb_direction_clean_2026-08-15.xlsx",
    "WNBA": BASE / "step8_wnba_direction_clean_2026-08-15.xlsx",
    "Soccer": BASE / "step8_soccer_direction_clean_2026-08-15.xlsx",
    "Tennis": BASE / "step8_tennis_direction_clean_2026-08-15.xlsx",
}

parts = [load(p, s) for s, p in files.items()]
allp = pd.concat(parts, ignore_index=True)
allp["l5"] = allp.apply(l5_hits, axis=1)
allp = allp[allp["dir"].isin(["OVER", "UNDER"])]
allp = allp[allp["l5"].fillna(0) >= 4]
allp["def_ok"] = [def_ok(r, r["sport"]) for r in allp.to_dict("records")]

# Tennis: L5 only. Others: L5 + defense.
core = allp[(allp["sport"] == "Tennis") | (allp["def_ok"])].copy()
core = core[core["pick_n"].isin(["standard", "goblin"])]
core = core.sort_values(["pick_n", "dir", "l5", "rank"], ascending=[True, True, False, False])


def show(title, df, n=8):
    print(f"\n=== {title}  (n={len(df)}) ===")
    if df.empty:
        print("  (none)")
        return
    cols = ["sport", "player", "team", "opp", "prop", "dir", "line", "l5", "def", "rank", "hr5", "tier"]
    print(df[cols].head(n).to_string(index=False, float_format=lambda x: f"{x:.2f}"))


for pick, label in [("standard", "STANDARD"), ("goblin", "GOBLIN")]:
    sub = core[core["pick_n"] == pick]
    for sport in ["MLB", "WNBA", "Soccer", "Tennis"]:
        ss = sub[sub["sport"] == sport]
        show(f"{label} {sport} OVER", ss[ss["dir"] == "OVER"], 6)
        show(f"{label} {sport} UNDER", ss[ss["dir"] == "UNDER"], 5)

print("\n--- L5>=4 but defense NOT aligned (skip unless Tennis) ---")
mis = allp[(allp["pick_n"].isin(["standard", "goblin"])) & (~allp["def_ok"]) & (allp["sport"] != "Tennis")]
print(f"filtered out {len(mis)} std/goblin rows (Avg D or wrong-side D)")
print("\nSoccer L5 coverage among std/goblin:")
s = allp[allp["sport"] == "Soccer"]
print("  soccer L5>=4 std/goblin", len(s[s["pick_n"].isin(["standard", "goblin"])]))
