"""Hit rates when L5 / L10 / season averages sit far from the PrizePicks line.

Joins main_cp graded_props_*.json (HIT/MISS) to dated step8 boards from
main_cp and the OPEN archive. Standard + Goblin unless noted.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path(r"H:\PropORACLE_main_cp")
OPEN = Path(r"H:\PropORACLE")
GRADED = MAIN / "ui_runner" / "templates"
SPORTS = ("WNBA", "MLB", "Soccer", "Tennis")
SPORT_FOLDER = {"WNBA": "wnba", "MLB": "mlb", "Soccer": "soccer", "Tennis": "tennis"}

ABS_BUCKETS = [
    ("against", lambda g: g < -1e-9),
    ("0 to <1", lambda g: (g >= 0) & (g < 1)),
    ("1 to <2", lambda g: (g >= 1) & (g < 2)),
    ("2 to <3", lambda g: (g >= 2) & (g < 3)),
    ("3 to <5", lambda g: (g >= 3) & (g < 5)),
    ("5+", lambda g: g >= 5),
]
PCT_BUCKETS = [
    ("against", lambda p: p < -1e-9),
    ("0-10%", lambda p: (p >= 0) & (p < 0.10)),
    ("10-25%", lambda p: (p >= 0.10) & (p < 0.25)),
    ("25-50%", lambda p: (p >= 0.25) & (p < 0.50)),
    ("50%+", lambda p: p >= 0.50),
]
SPREAD_BUCKETS = [
    ("<1", lambda s: s < 1),
    ("1 to <2", lambda s: (s >= 1) & (s < 2)),
    ("2 to <4", lambda s: (s >= 2) & (s < 4)),
    ("4+", lambda s: s >= 4),
]
L5_VS_SZN_BUCKETS = [
    ("L5 << szn (≤−2)", lambda d: d <= -2),
    ("L5 < szn (−2 to −0.5)", lambda d: (d > -2) & (d <= -0.5)),
    ("aligned (|d|<0.5)", lambda d: d.abs() < 0.5),
    ("L5 > szn (0.5 to 2)", lambda d: (d >= 0.5) & (d < 2)),
    ("L5 >> szn (≥2)", lambda d: d >= 2),
]


def _col(df, *names):
    lower = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _norm_name_s(s: pd.Series) -> pd.Series:
    x = s.astype(str).str.strip().str.lower()
    x = x.str.replace(r"[^a-z0-9 ]+", " ", regex=True)
    return x.str.replace(r"\s+", " ", regex=True).str.strip()


def _norm_prop_s(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().str.replace(r"\s+", " ", regex=True)


def _norm_dir_s(s: pd.Series) -> pd.Series:
    x = s.astype(str).str.strip().str.upper()
    return x.replace({"O": "OVER", "U": "UNDER"})


def _norm_pick_s(s: pd.Series) -> pd.Series:
    x = s.astype(str).str.strip().str.lower()
    out = pd.Series("Standard", index=s.index)
    out = out.mask(x.str.contains("goblin", na=False), "Goblin")
    out = out.mask(x.str.contains("demon", na=False), "Demon")
    out = out.mask(x.str.contains("standard", na=False), "Standard")
    return out


def find_step8(date: str, sport: str) -> Path | None:
    folder = SPORT_FOLDER[sport]
    slug = folder
    for root in (MAIN, OPEN):
        d = root / "outputs" / date
        for p in (
            d / folder / f"step8_{slug}_direction_clean.xlsx",
            d / folder / f"step8_{slug}_direction_clean_{date}.xlsx",
            d / f"step8_{slug}_direction_clean_{date}.xlsx",
            d / f"step8_{slug}_direction_clean.xlsx",
        ):
            if p.exists():
                return p
    return None


def _same(a: pd.Series, b: pd.Series) -> pd.Series:
    return a.notna() & b.notna() & ((a - b).abs() < 1e-6)


def load_step8(path: Path, sport: str, date: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    c_player = _col(df, "Player", "player", "player_name")
    c_prop = _col(df, "Prop", "prop", "prop_type")
    c_line = _col(df, "Line", "line", "line_score")
    c_dir = _col(df, "Direction", "direction", "bet_direction")
    c_l5 = _col(df, "Last 5 Avg", "last_5_avg", "stat_last5_avg", "l5_avg")
    c_l10 = _col(df, "Last 10 Avg", "last_10_avg", "stat_last10_avg", "l10_avg")
    c_szn = _col(df, "Season Avg", "season_avg", "stat_season_avg")
    if not all([c_player, c_prop, c_line, c_dir]):
        return pd.DataFrame()

    gcols = []
    for i in range(1, 11):
        c = _col(df, f"G{i}", f"g{i}", f"stat_g{i}", f"stat_G{i}")
        if c:
            gcols.append(c)
    gmat = (
        df[gcols].apply(pd.to_numeric, errors="coerce")
        if gcols
        else pd.DataFrame(index=df.index)
    )
    g_l5 = gmat.iloc[:, :5].mean(axis=1) if gmat.shape[1] else pd.Series(np.nan, index=df.index)
    g_l10 = gmat.mean(axis=1) if gmat.shape[1] else pd.Series(np.nan, index=df.index)

    l5 = pd.to_numeric(df[c_l5], errors="coerce") if c_l5 else pd.Series(np.nan, index=df.index)
    l10 = pd.to_numeric(df[c_l10], errors="coerce") if c_l10 else pd.Series(np.nan, index=df.index)
    szn = pd.to_numeric(df[c_szn], errors="coerce") if c_szn else pd.Series(np.nan, index=df.index)

    l5 = l5.fillna(g_l5)
    l10 = l10.fillna(g_l10)
    # Rebuild windows that were fillna'd from another window.
    l10 = np.where(_same(l10, l5) & g_l10.notna() & ~_same(g_l10, l5), g_l10, l10)
    l10 = pd.Series(l10, index=df.index)
    l10 = np.where(_same(l10, szn) & g_l10.notna() & ~_same(g_l10, szn), g_l10, l10)
    l10 = pd.Series(l10, index=df.index)
    l5 = np.where(_same(l5, szn) & g_l5.notna() & ~_same(g_l5, szn), g_l5, l5)
    l5 = pd.Series(l5, index=df.index)

    line = pd.to_numeric(df[c_line], errors="coerce")
    out = pd.DataFrame(
        {
            "date": date,
            "sport": sport,
            "player_n": _norm_name_s(df[c_player]),
            "prop_n": _norm_prop_s(df[c_prop]),
            "line_r": line.round(2),
            "direction": _norm_dir_s(df[c_dir]),
            "l5": l5,
            "l10": l10,
            "szn": szn,
        }
    )
    return out.drop_duplicates(["player_n", "prop_n", "line_r", "direction"], keep="last")


def rate(hits, n):
    if n <= 0:
        return None
    return round(100.0 * hits / n, 1)


def overall(df):
    n = int(len(df))
    h = int(df["hit"].sum()) if n else 0
    return {"hits": h, "n": n, "rate": rate(h, n)}


def tabulate(df, field, specs):
    s = pd.to_numeric(df[field], errors="coerce")
    out = {}
    for name, fn in specs:
        mask = s.notna() & fn(s)
        n = int(mask.sum())
        if n == 0:
            continue
        h = int(df.loc[mask, "hit"].sum())
        out[name] = {"hits": h, "n": n, "rate": rate(h, n)}
    return out


def main():
    dates = sorted(p.name[len("graded_props_") : -5] for p in GRADED.glob("graded_props_20*.json"))
    step_frames = []
    missing = defaultdict(list)
    n_files = 0
    for date in dates:
        for sport in SPORTS:
            p = find_step8(date, sport)
            if not p:
                missing[sport].append(date)
                continue
            print(f"load {date} {sport} {p}", flush=True)
            step_frames.append(load_step8(p, sport, date))
            n_files += 1
    step8 = pd.concat(step_frames, ignore_index=True) if step_frames else pd.DataFrame()
    print("step8 rows", len(step8), "files", n_files, flush=True)

    graded_rows = []
    for date in dates:
        raw = json.loads((GRADED / f"graded_props_{date}.json").read_text(encoding="utf-8"))
        for g in raw.get("props", []):
            sport = str(g.get("sport") or "")
            if sport not in SPORTS:
                continue
            result = str(g.get("result") or "").upper()
            if result not in ("HIT", "MISS"):
                continue
            d = str(g.get("direction") or g.get("over_under") or "").strip().upper()
            if d in ("O", "OVER"):
                d = "OVER"
            elif d in ("U", "UNDER"):
                d = "UNDER"
            pk = str(g.get("pick_type") or "").strip().lower()
            if "goblin" in pk:
                pick = "Goblin"
            elif "demon" in pk:
                pick = "Demon"
            else:
                pick = "Standard"
            try:
                line_v = float(g.get("line"))
            except (TypeError, ValueError):
                line_v = math.nan
            graded_rows.append(
                {
                    "date": date,
                    "sport": sport,
                    "player_n": re.sub(
                        r"\s+",
                        " ",
                        re.sub(r"[^a-z0-9 ]+", " ", str(g.get("player") or "").strip().lower()),
                    ).strip(),
                    "prop_n": re.sub(r"\s+", " ", str(g.get("prop") or "").strip().lower()),
                    "line": line_v,
                    "direction": d,
                    "pick": pick,
                    "hit": 1 if result == "HIT" else 0,
                }
            )
    graded = pd.DataFrame(graded_rows)
    graded["line_r"] = graded["line"].round(2)
    print("graded decided", len(graded), flush=True)

    keys = ["date", "sport", "player_n", "prop_n", "line_r", "direction"]
    merged = graded.merge(step8, on=keys, how="inner")
    # fallback without line (moved lines)
    leftover = graded.merge(merged[keys].drop_duplicates().assign(_hit=1), on=keys, how="left")
    leftover = leftover[leftover["_hit"].isna()].drop(columns="_hit")
    loose = leftover.merge(
        step8.drop(columns=["line_r"]).drop_duplicates(["date", "sport", "player_n", "prop_n", "direction"], keep="last"),
        on=["date", "sport", "player_n", "prop_n", "direction"],
        how="inner",
    )
    if len(loose):
        merged = pd.concat([merged, loose], ignore_index=True)
    print("merged", len(merged), flush=True)

    line = pd.to_numeric(merged["line"], errors="coerce")
    over = merged["direction"].eq("OVER")
    under = merged["direction"].eq("UNDER")
    for src, dest in (("l5", "g_l5"), ("l10", "g_l10"), ("szn", "g_szn")):
        avg = pd.to_numeric(merged[src], errors="coerce")
        gap = pd.Series(np.nan, index=merged.index)
        gap = gap.mask(over, avg - line)
        gap = gap.mask(under, line - avg)
        merged[dest] = gap
        merged[f"p_{dest[2:]}"] = gap / line.abs()

    merged["min_gap"] = merged[["g_l5", "g_l10", "g_szn"]].min(axis=1, skipna=True)
    merged["p_min"] = merged["min_gap"] / line.abs()
    merged["spread"] = merged[["l5", "l10", "szn"]].max(axis=1, skipna=True) - merged[["l5", "l10", "szn"]].min(axis=1, skipna=True)
    merged["l5_vs_szn"] = pd.to_numeric(merged["l5"], errors="coerce") - pd.to_numeric(merged["szn"], errors="coerce")
    merged["l5_vs_szn_dir"] = merged["l5_vs_szn"].where(over, -merged["l5_vs_szn"])
    merged["all_three"] = merged[["g_l5", "g_l10", "g_szn"]].notna().all(axis=1)
    pos = (merged[["g_l5", "g_l10", "g_szn"]] > 0).all(axis=1)
    neg = (merged[["g_l5", "g_l10", "g_szn"]] < 0).all(axis=1)
    merged["all_agree_side"] = merged["all_three"] & (pos | neg)

    sg = merged[merged["pick"].isin(["Standard", "Goblin"])].copy()
    sg3 = sg[sg["all_three"]].copy()
    demons = merged[merged["pick"].eq("Demon")].copy()

    def pack(df, df3):
        return {
            "overall": overall(df),
            "with_all_three": overall(df3),
            "min_gap_abs": tabulate(df3, "min_gap", ABS_BUCKETS),
            "min_gap_pct": tabulate(df3, "p_min", PCT_BUCKETS),
            "l5_gap_abs": tabulate(df, "g_l5", ABS_BUCKETS),
            "l10_gap_abs": tabulate(df, "g_l10", ABS_BUCKETS),
            "szn_gap_abs": tabulate(df, "g_szn", ABS_BUCKETS),
            "l5_gap_pct": tabulate(df, "p_l5", PCT_BUCKETS),
            "l10_gap_pct": tabulate(df, "p_l10", PCT_BUCKETS),
            "szn_gap_pct": tabulate(df, "p_szn", PCT_BUCKETS),
            "spread": tabulate(df, "spread", SPREAD_BUCKETS),
            "l5_vs_szn": tabulate(df, "l5_vs_szn", L5_VS_SZN_BUCKETS),
            "l5_vs_szn_dir": tabulate(df, "l5_vs_szn_dir", L5_VS_SZN_BUCKETS),
        }

    combined = pack(sg, sg3)
    combined["demons_overall"] = overall(demons)

    def gate(df, need):
        m = df["all_agree_side"] & (df["min_gap"] >= need)
        return overall(df[m])

    combined["all_three_cover"] = {
        "min>=1": gate(sg3, 1),
        "min>=2": gate(sg3, 2),
        "min>=3": gate(sg3, 3),
        "min>=5": gate(sg3, 5),
        "min>=25% of line": overall(sg3[sg3["all_agree_side"] & (sg3["p_min"] >= 0.25)]),
        "min>=50% of line": overall(sg3[sg3["all_agree_side"] & (sg3["p_min"] >= 0.50)]),
        "against (min<0)": overall(sg3[sg3["min_gap"] < 0]),
    }
    for book, label in (("Standard", "std"), ("Goblin", "gob")):
        rows = sg3[sg3["pick"].eq(book)]
        combined[f"{label}_overall"] = overall(rows)
        combined[f"{label}_min_gap_abs"] = tabulate(rows, "min_gap", ABS_BUCKETS)
        combined[f"{label}_l5_gap_abs"] = tabulate(sg[sg["pick"].eq(book)], "g_l5", ABS_BUCKETS)
    for d in ("OVER", "UNDER"):
        rows = sg3[sg3["direction"].eq(d)]
        combined[f"{d.lower()}_overall"] = overall(rows)
        combined[f"{d.lower()}_min_gap_abs"] = tabulate(rows, "min_gap", ABS_BUCKETS)
        combined[f"{d.lower()}_l5_gap_abs"] = tabulate(sg[sg["direction"].eq(d)], "g_l5", ABS_BUCKETS)

    by_sport = {}
    for sp in SPORTS:
        d = sg[sg["sport"].eq(sp)]
        d3 = sg3[sg3["sport"].eq(sp)]
        by_sport[sp] = pack(d, d3)

    dates_used = sorted(sg["date"].unique().tolist()) if len(sg) else []
    match_summary = (
        sg.groupby(["date", "sport"])
        .agg(n=("hit", "size"), hits=("hit", "sum"))
        .reset_index()
        .to_dict("records")
    )
    out = {
        "window": {
            "first": dates_used[0] if dates_used else None,
            "last": dates_used[-1] if dates_used else None,
            "n_dates": len(dates_used),
            "dates": dates_used,
        },
        "universe": "Standard + Goblin, decided HIT/MISS, joined to step8 L5/L10/season avgs. WNBA/MLB/Soccer/Tennis.",
        "gap_def": "OVER: avg-line; UNDER: line-avg. Positive = average on the pick side of the line.",
        "min_gap": "Smallest of the three directional gaps. Large min_gap means L5, L10, AND season all sit well on the pick side.",
        "spread": "max(L5,L10,szn)-min(...). Large spread = windows disagree with each other.",
        "combined": combined,
        "by_sport": by_sport,
        "join": {
            "n_graded_decided": int(len(graded)),
            "n_std_goblin_matched": int(len(sg)),
            "n_all_three_avgs": int(len(sg3)),
            "n_dates_with_match": len(dates_used),
            "n_board_files": n_files,
            "missing_step8_n": {k: len(v) for k, v in missing.items()},
            "match_by_date_sport": match_summary,
        },
    }
    dest = MAIN / "data" / "reports" / "avg_gap_hit_rates_latest.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    slim_sport = {
        k: {
            "overall": v["overall"],
            "with_all_three": v["with_all_three"],
            "min_gap_abs": v["min_gap_abs"],
            "l5_gap_abs": v["l5_gap_abs"],
            "szn_gap_abs": v["szn_gap_abs"],
            "spread": v["spread"],
            "l5_vs_szn": v["l5_vs_szn"],
        }
        for k, v in by_sport.items()
    }
    print(json.dumps({"window": out["window"], "join": {k: out["join"][k] for k in out["join"] if k != "match_by_date_sport"}, "combined": combined, "by_sport": slim_sport}, indent=2))
    print("wrote", dest)


if __name__ == "__main__":
    main()
