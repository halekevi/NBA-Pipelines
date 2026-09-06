from __future__ import annotations
import json, re, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

OPEN = Path("H:/PropORACLE")
MAIN = Path("H:/PropORACLE_main_cp")
sys.path.insert(0, str(OPEN / "scripts"))
from rank_best_props_today import DELTA_FLOOR, DELTA_PCT, _over_d_ok, _under_d_ok

SLATE = "2026-08-23"
STEP8_DIR = OPEN / "outputs" / SLATE
GRADED_JSON = MAIN / "mobile" / "www" / ("graded_props_%s.json" % SLATE)
OUT = OPEN / "data" / "reports" / ("badge_hit_rates_%s.json" % SLATE)
OUT_SIBLING = OPEN / "data" / "reports" / ("badge_hit_rates_%s_tennis_soccer_nfl.json" % SLATE)
L10_THRESH = 7

SOCCER_PROP_ALIASES = {
    "goalie saves": ["goalkeeper saves"],
    "goalkeeper saves": ["goalie saves"],
    "goalie saves combo": ["goalkeeper saves"],
}
TENNIS_PROP_ALIASES = {
    "total games won": ["games won", "total games"],
    "games won": ["total games won"],
    "match total games": ["total games", "total games won"],
    "total games": ["match total games", "total games won"],
}


def _num(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = str(v).strip()
    if s in ("", "-", "NaN", "nan", "None", "null"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _norm_dir(v):
    s = str(v or "").strip().upper()
    if s in ("O", "OVER", "MORE"):
        return "OVER"
    if s in ("U", "UNDER", "LESS"):
        return "UNDER"
    return s


def _norm_pick(v):
    s = str(v or "").strip().lower()
    if "gob" in s:
        return "Goblin"
    if "dem" in s:
        return "Demon"
    if "std" in s or "standard" in s or s in ("", "nan"):
        return "Standard"
    return str(v).strip().title() or "Standard"


def _norm_sport(v):
    s = str(v or "").strip().upper()
    return {
        "WNBA": "WNBA",
        "MLB": "MLB",
        "SOCCER": "Soccer",
        "TENNIS": "Tennis",
        "NFL": "NFL",
        "NFLP": "NFL",
    }.get(s, s.title() if s else "")


def _norm_name(v):
    s = re.sub(r"[^a-z0-9 ]", "", str(v or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _norm_prop(v):
    s = re.sub(r"[^a-z0-9+ ]", "", str(v or "").lower().replace("-", " "))
    return re.sub(r"\s+", " ", s).strip()


def _delta_need(line):
    return max(float(DELTA_FLOOR), abs(line) * float(DELTA_PCT))


def _norm_tier(raw):
    s = str(raw or "").strip()
    if not s or s.lower() in {"n/a", "na", "none", "-", "unknown", "nan"}:
        return ""
    low = s.lower()
    if "below" in low:
        return "Below Avg"
    if "above" in low:
        return "Above Avg"
    if low in {"weak", "bottom", "easy"} or "weak" in low:
        return "Weak"
    if "elite" in low or low in {"top", "hard", "stingy"}:
        return "Elite"
    if low in {"avg", "average"}:
        return "Avg"
    return s


def _d_pass(sport, direction, def_tier, prop):
    tier = _norm_tier(def_tier)
    if not tier or tier == "Avg":
        return False
    if direction == "OVER":
        return _over_d_ok(sport, tier, prop)
    if direction == "UNDER":
        return _under_d_ok(sport, tier, prop)
    return False


def _col(df, *names):
    lower = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def load_step8(sport, path):
    if str(path).lower().endswith(".csv"):
        df = pd.read_csv(path, low_memory=False)
    else:
        df = pd.read_excel(path)
    rows = []
    c_player = _col(df, "Player", "player", "player_name")
    c_prop = _col(df, "Prop", "prop", "prop_type")
    c_line = _col(df, "Line", "line", "line_score")
    c_dir = _col(df, "Direction", "direction", "bet_direction")
    c_pick = _col(df, "Pick Type", "pick_type", "PickType")
    c_l5o = _col(df, "L5 Over", "l5_over", "last5_over")
    c_l5u = _col(df, "L5 Under", "l5_under", "last5_under")
    c_l10o = _col(df, "L10 Over", "l10_over")
    c_l10u = _col(df, "L10 Under", "l10_under")
    c_season = _col(df, "Season Avg", "season_avg", "stat_season_avg", "Projection", "projection")
    c_last5 = _col(df, "Last 5 Avg", "last_5_avg", "stat_last5_avg")
    c_def = _col(df, "Def Tier", "def_tier", "DEF_TIER", "opp_def_tier")
    c_gt = _col(df, "Game Time", "game_time")
    for _, r in df.iterrows():
        player = r.get(c_player) if c_player else None
        prop = r.get(c_prop) if c_prop else None
        line = _num(r.get(c_line) if c_line else None)
        direction = _norm_dir(r.get(c_dir) if c_dir else None)
        pick = _norm_pick(r.get(c_pick) if c_pick else None)
        rows.append(
            {
                "sport": sport,
                "player": player,
                "prop": prop,
                "line": line,
                "direction": direction,
                "pick_type": pick,
                "l5_over": _num(r.get(c_l5o) if c_l5o else None),
                "l5_under": _num(r.get(c_l5u) if c_l5u else None),
                "l10_over": _num(r.get(c_l10o) if c_l10o else None),
                "l10_under": _num(r.get(c_l10u) if c_l10u else None),
                "season_avg": _num(r.get(c_season) if c_season else None),
                "last5_avg": _num(r.get(c_last5) if c_last5 else None),
                "def_tier": r.get(c_def) if c_def else "",
                "game_time": str(r.get(c_gt) if c_gt else ""),
                "join_key": (
                    _norm_name(player),
                    _norm_prop(prop),
                    round(line, 2) if line is not None else None,
                    direction,
                    pick,
                ),
            }
        )
    return rows


def enrich_row(base, s8):
    direction = base["direction"]
    line = base["line"]
    prop = base["prop"]
    sport = base["sport"]
    l5o, l5u = s8.get("l5_over"), s8.get("l5_under")
    l10o, l10u = s8.get("l10_over"), s8.get("l10_under")
    # allow graded-provided L10 override already in s8
    season, last5 = s8.get("season_avg"), s8.get("last5_avg")
    def_tier = s8.get("def_tier")
    l5 = l10 = None
    if direction == "OVER":
        if l5o is not None:
            l5 = int(round(l5o))
        if l10o is not None:
            l10 = int(round(l10o))
    elif direction == "UNDER":
        if l5u is not None:
            l5 = int(round(l5u))
        if l10u is not None:
            l10 = int(round(l10u))
    avg = season if season is not None else last5
    cover = (avg - line) if (avg is not None and line is not None) else None
    cover_pass = delta_pass = None
    if cover is not None and line is not None:
        need = _delta_need(line)
        if direction == "OVER":
            cover_pass = cover > 0
            delta_pass = cover >= need
        elif direction == "UNDER":
            cover_pass = cover < 0
            delta_pass = cover <= -need
    return {
        **base,
        "l5": l5,
        "l10": l10,
        "season_avg": avg,
        "cover": cover,
        "cover_pass": cover_pass,
        "delta_pass": delta_pass,
        "d_pass": _d_pass(sport, direction, def_tier, str(prop or "")),
        "def_tier": str(def_tier or ""),
    }


def pool_stats(rows, pred):
    xs = [r for r in rows if pred(r)]
    n = len(xs)
    if n == 0:
        return {"n": 0, "hits": 0, "hr": None}
    hits = int(sum(r["hit"] for r in xs))
    return {"n": n, "hits": hits, "hr": round(hits / n, 4)}


def make_pools(rows):
    pools = {
        "all_decided": pool_stats(rows, lambda r: True),
        "l5_ge4": pool_stats(rows, lambda r: r["l5"] is not None and r["l5"] >= 4),
        "l5_eq5": pool_stats(rows, lambda r: r["l5"] is not None and r["l5"] == 5),
        "l5_ge4_d": pool_stats(rows, lambda r: r["l5"] is not None and r["l5"] >= 4 and r["d_pass"]),
        "l5_eq5_d": pool_stats(rows, lambda r: r["l5"] is not None and r["l5"] == 5 and r["d_pass"]),
        "l10_ge7": pool_stats(rows, lambda r: r["l10"] is not None and r["l10"] >= L10_THRESH),
        "l10_ge8": pool_stats(rows, lambda r: r["l10"] is not None and r["l10"] >= 8),
        "cover_pass": pool_stats(rows, lambda r: r["cover_pass"] is True),
        "delta_pass": pool_stats(rows, lambda r: r["delta_pass"] is True),
        "d_pass": pool_stats(rows, lambda r: r["d_pass"] is True),
        "l5_ge4_l10_ge7": pool_stats(
            rows,
            lambda r: r["l5"] is not None
            and r["l5"] >= 4
            and r["l10"] is not None
            and r["l10"] >= L10_THRESH,
        ),
        "l5_ge4_d_delta": pool_stats(
            rows,
            lambda r: r["l5"] is not None and r["l5"] >= 4 and r["d_pass"] and r["delta_pass"] is True,
        ),
        "gold_like_l5_cover_delta_d": pool_stats(
            rows,
            lambda r: r["l5"] is not None
            and r["l5"] >= 4
            and r["cover_pass"] is True
            and r["delta_pass"] is True
            and r["d_pass"],
        ),
    }
    for pt in ("Standard", "Goblin"):
        sub = [r for r in rows if r["pick_type"] == pt]
        key = pt.lower()
        pools[key + "_all"] = pool_stats(sub, lambda r: True)
        pools[key + "_l5_ge4"] = pool_stats(sub, lambda r: r["l5"] is not None and r["l5"] >= 4)
        pools[key + "_l5_ge4_d"] = pool_stats(
            sub, lambda r: r["l5"] is not None and r["l5"] >= 4 and r["d_pass"]
        )
        pools[key + "_gold_like"] = pool_stats(
            sub,
            lambda r: r["l5"] is not None
            and r["l5"] >= 4
            and r["cover_pass"] is True
            and r["delta_pass"] is True
            and r["d_pass"],
        )
    return pools


def fmt(p):
    if not p or p.get("hr") is None:
        return "%7s  n=%s" % ("--", p.get("n", 0))
    return "%5.1f%%  %s/%s" % (100 * p["hr"], p["hits"], p["n"])


def build_index(rows):
    idx = defaultdict(list)
    for r in rows:
        idx[r["join_key"]].append(r)
        k2 = ("nopick", r["join_key"][0], r["join_key"][1], r["join_key"][2], r["join_key"][3])
        idx[k2].append(r)
        k3 = ("noline", r["join_key"][0], r["join_key"][1], r["join_key"][3], r["join_key"][4])
        idx[k3].append(r)
    return idx


def lookup(idx, rows, player, prop, line, direction, pick, aliases=None):
    props = [_norm_prop(prop)]
    for a in (aliases or {}).get(props[0], []):
        props.append(_norm_prop(a))
    for p in props:
        key = (_norm_name(player), p, round(line, 2) if line is not None else None, direction, pick)
        hits = idx.get(key)
        if hits:
            return hits[0]
        key2 = ("nopick", _norm_name(player), p, round(line, 2) if line is not None else None, direction)
        hits = idx.get(key2)
        if hits:
            return hits[0]
        key3 = ("noline", _norm_name(player), p, direction, pick)
        hits = idx.get(key3)
        if hits:
            return hits[0]
    # last resort: player+prop+dir any line within 0.5
    pn = _norm_name(player)
    for p in props:
        for r in rows:
            if _norm_name(r["player"]) != pn:
                continue
            if _norm_prop(r["prop"]) != p:
                continue
            if r["direction"] != direction:
                continue
            if line is None or r["line"] is None or abs(r["line"] - line) <= 0.51:
                return r
    return None


def grade_from_actuals(sport, step8_rows, actuals_path, aliases=None):
    if not actuals_path.exists():
        return [], {"missing_actuals": True}
    act = pd.read_csv(actuals_path)
    amap = defaultdict(list)
    c_player = _col(act, "player", "Player")
    c_prop = _col(act, "prop_type", "prop", "Prop")
    c_actual = _col(act, "actual", "Actual")
    for _, r in act.iterrows():
        amap[(_norm_name(r.get(c_player)), _norm_prop(r.get(c_prop)))].append(_num(r.get(c_actual)))
    out = []
    stats = defaultdict(int)
    stats["actuals_rows"] = len(act)
    stats["step8_rows"] = len(step8_rows)
    for s8 in step8_rows:
        props = [_norm_prop(s8["prop"])]
        for a in (aliases or {}).get(props[0], []):
            props.append(_norm_prop(a))
        vals = []
        for p in props:
            vals = [v for v in amap.get((_norm_name(s8["player"]), p), []) if v is not None]
            if vals:
                break
        if not vals:
            stats["no_actual"] += 1
            continue
        actual = vals[0]
        line = s8["line"]
        direction = s8["direction"]
        if line is None or direction not in ("OVER", "UNDER"):
            stats["bad_line_dir"] += 1
            continue
        if direction == "OVER":
            if actual > line:
                hit, result = 1, "HIT"
            elif actual < line:
                hit, result = 0, "MISS"
            else:
                stats["push"] += 1
                continue
        else:
            if actual < line:
                hit, result = 1, "HIT"
            elif actual > line:
                hit, result = 0, "MISS"
            else:
                stats["push"] += 1
                continue
        stats["decided"] += 1
        base = {
            "sport": sport,
            "player": str(s8["player"]),
            "prop": str(s8["prop"]),
            "line": line,
            "direction": direction,
            "pick_type": s8["pick_type"],
            "hit": hit,
            "result": result,
            "joined_from": "step8+actuals",
        }
        out.append(enrich_row(base, s8))
    return out, dict(stats)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # --- step8 sources (corrected) ---
    step8_files = {
        "MLB": STEP8_DIR / "step8_mlb_direction_clean_2026-08-23.xlsx",
        "WNBA": STEP8_DIR / "step8_wnba_direction_clean_2026-08-23.xlsx",
        # Prior bug: dated soccer filename held 08/24 games. Use sport subdir board (08/23 Game Times).
        "Soccer": STEP8_DIR / "soccer" / "step8_soccer_direction_clean.xlsx",
        # Tennis dated board barely overlaps graded players; main_cp feature board covers all graded names.
        "Tennis": MAIN / "Sports" / "Tennis" / "step8_tennis_direction.csv",
        "NFL": STEP8_DIR / "nfl" / "step8_nfl_direction_clean_2026-08-23.xlsx",
    }
    step8_by_sport = {}
    step8_index = {}
    for sp, path in step8_files.items():
        if not path.exists():
            print("MISSING step8", sp, path)
            step8_by_sport[sp] = []
            step8_index[sp] = {}
            continue
        rows = load_step8(sp, path)
        # Soccer: keep only rows that look like 08/23 (subdir already all 08/23)
        if sp == "Soccer":
            rows = [r for r in rows if "08/23" in str(r.get("game_time") or "") or not r.get("game_time")]
        step8_by_sport[sp] = rows
        step8_index[sp] = build_index(rows)
        print("step8", sp, len(rows), path)

    join_stats = defaultdict(int)
    joined = []

    # --- MLB from graded JSON ---
    raw = json.loads(GRADED_JSON.read_text(encoding="utf-8"))
    graded = raw.get("props", [])
    print("graded json", len(graded))
    for g in graded:
        result = str(g.get("result") or "").upper()
        if result not in ("HIT", "MISS"):
            join_stats["skip_void_or_other"] += 1
            continue
        sport = _norm_sport(g.get("sport"))
        if sport not in ("MLB",):
            # Tennis handled from xlsx below (JSON tennis lacks L5; xlsx has L10)
            if sport == "Tennis":
                join_stats["skip_tennis_json_use_xlsx"] += 1
            else:
                join_stats["skip_other_sport_" + sport] += 1
            continue
        player = g.get("player")
        prop = g.get("prop") or g.get("prop_type")
        line = _num(g.get("line"))
        direction = _norm_dir(g.get("direction") or g.get("over_under"))
        pick = _norm_pick(g.get("pick_type"))
        hit = 1 if result == "HIT" else 0
        s8 = lookup(step8_index["MLB"], step8_by_sport["MLB"], player, prop, line, direction, pick)
        if s8 is None:
            join_stats["no_join_MLB"] += 1
            s8 = {
                "l5_over": _num(g.get("l5_over") or g.get("last5_over")),
                "l5_under": _num(g.get("l5_under") or g.get("last5_under")),
                "l10_over": _num(g.get("l10_over")),
                "l10_under": _num(g.get("l10_under")),
                "season_avg": None,
                "last5_avg": None,
                "def_tier": g.get("def_tier") or "",
            }
            joined_from = "graded_only"
        else:
            join_stats["joined_MLB"] += 1
            joined_from = "graded_json+step8"
        base = {
            "sport": sport,
            "player": str(player),
            "prop": str(prop),
            "line": line,
            "direction": direction,
            "pick_type": pick,
            "hit": hit,
            "result": result,
            "joined_from": joined_from,
        }
        joined.append(enrich_row(base, s8))

    # --- Tennis from graded xlsx + main_cp step8 ---
    tennis_xlsx = MAIN / "outputs" / SLATE / ("graded_tennis_%s.xlsx" % SLATE)
    tennis_diag = {}
    if tennis_xlsx.exists():
        gt = pd.read_excel(tennis_xlsx, sheet_name="graded")
        tennis_diag["graded_xlsx_rows"] = int(len(gt))
        tennis_diag["graded_xlsx_result"] = {
            str(k): int(v) for k, v in gt["result"].astype(str).str.upper().value_counts().items()
        }
        dec = gt[gt["result"].astype(str).str.upper().isin(["HIT", "MISS"])]
        for _, g in dec.iterrows():
            player = g.get("player")
            prop = g.get("prop_type")
            line = _num(g.get("line"))
            direction = _norm_dir(g.get("direction"))
            pick = _norm_pick(g.get("pick_type"))
            result = str(g.get("result")).upper()
            hit = 1 if result == "HIT" else 0
            s8 = lookup(
                step8_index["Tennis"],
                step8_by_sport["Tennis"],
                player,
                prop,
                line,
                direction,
                pick,
                aliases=TENNIS_PROP_ALIASES,
            )
            if s8 is None:
                join_stats["no_join_Tennis"] += 1
                s8 = {
                    "l5_over": None,
                    "l5_under": None,
                    "l10_over": _num(g.get("l10_over")),
                    "l10_under": _num(g.get("l10_under")),
                    "season_avg": None,
                    "last5_avg": None,
                    "def_tier": "",
                }
                joined_from = "graded_xlsx_only"
            else:
                join_stats["joined_Tennis"] += 1
                # Prefer graded L10 when step8 lacks it (common for Aces/DF)
                if s8.get("l10_over") is None:
                    s8 = {**s8, "l10_over": _num(g.get("l10_over"))}
                if s8.get("l10_under") is None:
                    s8 = {**s8, "l10_under": _num(g.get("l10_under"))}
                joined_from = "graded_xlsx+step8"
            base = {
                "sport": "Tennis",
                "player": str(player),
                "prop": str(prop),
                "line": line,
                "direction": direction,
                "pick_type": pick,
                "hit": hit,
                "result": result,
                "joined_from": joined_from,
            }
            joined.append(enrich_row(base, s8))
        tennis_diag["decided"] = int(len(dec))
        tennis_diag["joined_step8"] = int(join_stats["joined_Tennis"])
        tennis_diag["no_join"] = int(join_stats["no_join_Tennis"])
    else:
        tennis_diag["missing_graded_xlsx"] = True

    # --- WNBA / Soccer from actuals ---
    wnba_extra, wnba_stats = grade_from_actuals(
        "WNBA", step8_by_sport["WNBA"], MAIN / "outputs" / SLATE / ("actuals_wnba_%s.csv" % SLATE)
    )
    soccer_extra, soccer_stats = grade_from_actuals(
        "Soccer",
        step8_by_sport["Soccer"],
        MAIN / "outputs" / SLATE / ("actuals_soccer_%s.csv" % SLATE),
        aliases=SOCCER_PROP_ALIASES,
    )
    print("wnba_extra", len(wnba_extra), wnba_stats)
    print("soccer_extra", len(soccer_extra), soccer_stats)

    # --- NFL from graded xlsx + step8 (NFLP preseason board graded as NFL) ---
    nfl_rows = step8_by_sport.get("NFL", [])
    nfl_xlsx = MAIN / "outputs" / SLATE / ("graded_nfl_%s.xlsx" % SLATE)
    nfl_extra = []
    nfl_diag = {
        "step8_rows": len(nfl_rows),
        "league_on_board": "NFLP",
        "note": "PrizePicks NFL preseason board labels League=NFLP; treat NFLP as the NFL PP board for this slate.",
        "graded_xlsx": str(nfl_xlsx) if nfl_xlsx.exists() else None,
        "actuals_rows": 0,
        "decided": 0,
        "joined_step8": 0,
        "no_join": 0,
    }
    act_nfl = MAIN / "outputs" / SLATE / ("actuals_nfl_%s.csv" % SLATE)
    if act_nfl.exists():
        adf = pd.read_csv(act_nfl)
        nfl_diag["actuals_rows"] = int(len(adf))
    if nfl_xlsx.exists():
        gn = pd.read_excel(nfl_xlsx, sheet_name="Box Raw")
        nfl_diag["graded_xlsx_rows"] = int(len(gn))
        nfl_diag["graded_xlsx_result"] = {
            str(k): int(v) for k, v in gn["result"].astype(str).str.upper().value_counts().items()
        }
        dec = gn[gn["result"].astype(str).str.upper().isin(["HIT", "MISS"])]
        for _, g in dec.iterrows():
            player = g.get("player")
            prop = g.get("prop_type_norm") or g.get("prop_type") or g.get("Prop")
            line = _num(g.get("line"))
            direction = _norm_dir(g.get("bet_direction") or g.get("direction"))
            pick = _norm_pick(g.get("pick_type"))
            result = str(g.get("result")).upper()
            hit = 1 if result == "HIT" else 0
            s8 = lookup(
                step8_index["NFL"],
                step8_by_sport["NFL"],
                player,
                prop,
                line,
                direction,
                pick,
            )
            if s8 is None:
                join_stats["no_join_NFL"] += 1
                s8 = {
                    "l5_over": _num(g.get("l5_over")),
                    "l5_under": _num(g.get("l5_under")),
                    "l10_over": _num(g.get("l10_over")),
                    "l10_under": _num(g.get("l10_under")),
                    "season_avg": _num(g.get("projection")),
                    "last5_avg": None,
                    "def_tier": g.get("def_tier") or "",
                }
                joined_from = "graded_xlsx_only"
            else:
                join_stats["joined_NFL"] += 1
                if s8.get("l5_over") is None:
                    s8 = {**s8, "l5_over": _num(g.get("l5_over"))}
                if s8.get("l5_under") is None:
                    s8 = {**s8, "l5_under": _num(g.get("l5_under"))}
                if s8.get("l10_over") is None:
                    s8 = {**s8, "l10_over": _num(g.get("l10_over"))}
                if s8.get("l10_under") is None:
                    s8 = {**s8, "l10_under": _num(g.get("l10_under"))}
                joined_from = "graded_xlsx+step8"
            base = {
                "sport": "NFL",
                "player": str(player),
                "prop": str(prop),
                "line": line,
                "direction": direction,
                "pick_type": pick,
                "hit": hit,
                "result": result,
                "joined_from": joined_from,
            }
            nfl_extra.append(enrich_row(base, s8))
        nfl_diag["decided"] = int(len(dec))
        nfl_diag["joined_step8"] = int(join_stats["joined_NFL"])
        nfl_diag["no_join"] = int(join_stats["no_join_NFL"])
        nfl_diag.pop("reason_no_hr", None)
    else:
        nfl_diag["reason_no_hr"] = "missing graded_nfl_%s.xlsx" % SLATE

    nfl_badge_inventory = {
        "n_board": len(nfl_rows),
        "with_l5": sum(1 for r in nfl_rows if r["l5_over"] is not None or r["l5_under"] is not None),
        "l5_ge4_directional_over": sum(
            1 for r in nfl_rows if r["direction"] == "OVER" and r["l5_over"] is not None and r["l5_over"] >= 4
        ),
        "with_def_tier": sum(1 for r in nfl_rows if _norm_tier(r.get("def_tier"))),
        "pick_types": {},
    }
    for r in nfl_rows:
        nfl_badge_inventory["pick_types"][r["pick_type"]] = (
            nfl_badge_inventory["pick_types"].get(r["pick_type"], 0) + 1
        )

    all_rows = list(joined) + wnba_extra + soccer_extra + nfl_extra
    no_demon = [r for r in all_rows if r["pick_type"] in ("Standard", "Goblin")]

    sources_notes = [
        "MLB: HIT/MISS from mobile graded_props JSON; badges from dated step8.",
        "WNBA: grader Box Raw empty; HIT/MISS from step8 vs actuals (pushes excluded).",
        "Soccer FIX: prior report used step8_soccer_direction_clean_2026-08-23.xlsx which had 08/24 Game Times (near-zero player overlap). Now uses outputs/2026-08-23/soccer/step8_soccer_direction_clean.xlsx (08/23 times) + actuals + goalie/goalkeeper alias.",
        "Tennis FIX: graded_tennis xlsx (150 decided) joined to main_cp Sports/Tennis step8 CSV (100% player coverage). Dated open step8 only overlapped 2 players. L5 mostly on Total Games Won; Aces/DF have no L5 in step8. Def Tier blank on tennis board for this slate (D/gold-like unavailable). L10 often from graded xlsx.",
        "NFL/NFLP FIX: fetch_football_actuals now uses ESPN site.web.api + Referer (site.api 403); empty actuals stubs re-fetch in run_grader; SEA@TEN 2026-08-23 graded (18 decided). League=NFLP is PrizePicks preseason board label.",
        "Graded JSON L5/def_tier blank for this slate; step8 join required for most badge rates.",
    ]

    report = {
        "slate_date": SLATE,
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "sources": {
            "graded_json": str(GRADED_JSON),
            "graded_tennis_xlsx": str(tennis_xlsx),
            "graded_soccer_xlsx": str(MAIN / "outputs" / SLATE / ("graded_soccer_%s.xlsx" % SLATE)),
            "graded_nfl_xlsx": str(nfl_xlsx) if nfl_xlsx.exists() else None,
            "step8_root": str(STEP8_DIR),
            "step8_soccer": str(step8_files["Soccer"]),
            "step8_tennis": str(step8_files["Tennis"]),
            "step8_nfl": str(step8_files["NFL"]),
            "notes": sources_notes,
        },
        "thresholds": {
            "l5": "directional L5 Over/Under (also last5_over/last5_under); gates >=4 and =5",
            "l10": "directional L10 Over/Under; primary >= %s/10 (also >=8)" % L10_THRESH,
            "d_gate": "OVER Weak|Below Avg; UNDER Elite|Above Avg; Avg fails; MLB hitter-K inverted",
            "cover": "season_avg - line (else last5_avg); OVER >0; UNDER <0",
            "delta": "abs(cover) >= max(%s, |line|*%s) in play direction" % (DELTA_FLOOR, DELTA_PCT),
            "gold_like": "L5>=4 + Cover + Delta + D (Dir/Rank not required here)",
        },
        "join_stats": dict(join_stats),
        "soccer_grade_stats": soccer_stats,
        "wnba_grade_stats": wnba_stats,
        "tennis_diag": tennis_diag,
        "nfl_diag": nfl_diag,
        "nfl_badge_inventory_no_outcomes": nfl_badge_inventory,
        "row_counts": {
            "mlb_from_graded_json": sum(1 for r in joined if r["sport"] == "MLB"),
            "tennis_from_graded_xlsx": sum(1 for r in joined if r["sport"] == "Tennis"),
            "wnba_from_actuals": len(wnba_extra),
            "soccer_from_actuals": len(soccer_extra),
            "nfl_decided": len(nfl_extra),
            "total": len(all_rows),
            "standard_goblin": len(no_demon),
            "with_directional_l5": sum(1 for r in all_rows if r["l5"] is not None),
        },
        "overall_all_picks": make_pools(all_rows),
        "standard_goblin_only": make_pools(no_demon),
        "by_sport_all_picks": {},
        "by_sport_standard_goblin": {},
    }
    report["standard_goblin_only"]["n_rows"] = len(no_demon)

    sport_sources = {
        "WNBA": "step8+actuals",
        "MLB": "graded_json+step8",
        "Soccer": "step8_subdir_0823+actuals",
        "Tennis": "graded_xlsx+main_cp_step8",
        "NFL": "graded_xlsx+step8",
    }
    for sp in ("WNBA", "MLB", "Soccer", "Tennis", "NFL"):
        sub_all = [r for r in all_rows if r["sport"] == sp]
        sub_sg = [r for r in no_demon if r["sport"] == sp]
        report["by_sport_all_picks"][sp] = make_pools(sub_all)
        report["by_sport_all_picks"][sp]["n_rows"] = len(sub_all)
        report["by_sport_standard_goblin"][sp] = make_pools(sub_sg)
        report["by_sport_standard_goblin"][sp]["n_rows"] = len(sub_sg)
        report["by_sport_standard_goblin"][sp]["source"] = sport_sources[sp]

    report["data_quality"] = {
        "MLB": "Official graded HIT/MISS; Std+Gob join to dated step8 for badges. Demons mostly missing from step8 join.",
        "WNBA": "Grader Box Raw empty. HIT/MISS from step8 vs actuals. Provisional but usable.",
        "Soccer": "Usable after board fix. Prefer Std+Gob (Demons drag overall HR ~14%). L5/D/cover from correct 08/23 step8. graded_soccer xlsx empty.",
        "Tennis": "Official grades n=150. Step8 join 100% on player via main_cp board. L5 only sparse (mostly Total Games Won; Aces/DF have no L5). Def Tier empty — D and gold-like not computable. L10 largely from graded xlsx. Small-n caution on L5 pools.",
        "NFL": "Official grades n=18 decided (2 VOID DNP). SEA@TEN preseason (League=NFLP). L5/D from step8; cover uses Projection when Season Avg blank. Small-n caution.",
    }
    report["recommended_view"] = (
        "Primary: standard_goblin_only + by_sport_standard_goblin for WNBA/MLB/Soccer. "
        "Tennis: use all_decided and L10 pools; treat L5/D/gold as thin/unavailable. "
        "NFL: Std+Gob pools available (n=18); treat L5/gold as small-n."
    )
    report["reliability"] = {
        "Soccer_std_gob": "moderate (n~300 decided with badges)",
        "Tennis_all": "moderate on raw HR; low on L5/D badge pools (sparse features)",
        "NFL": "low-n (18 decided SEA@TEN preseason) but outcomes are real",
    }

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Sibling focused report
    sibling = {
        "slate_date": SLATE,
        "generated_at": report["generated_at"],
        "focus": ["Tennis", "Soccer", "NFL"],
        "sources": report["sources"],
        "thresholds": report["thresholds"],
        "tennis_diag": tennis_diag,
        "soccer_grade_stats": soccer_stats,
        "nfl_diag": nfl_diag,
        "nfl_badge_inventory_no_outcomes": nfl_badge_inventory,
        "by_sport_all_picks": {k: report["by_sport_all_picks"][k] for k in ("Tennis", "Soccer", "NFL")},
        "by_sport_standard_goblin": {
            k: report["by_sport_standard_goblin"][k] for k in ("Tennis", "Soccer", "NFL")
        },
        "data_quality": {k: report["data_quality"][k] for k in ("Tennis", "Soccer", "NFL")},
        "reliability": report["reliability"],
    }
    OUT_SIBLING.write_text(json.dumps(sibling, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print("wrote", OUT_SIBLING)

    keys = [
        "all_decided",
        "l5_ge4",
        "l5_eq5",
        "l5_ge4_d",
        "l10_ge7",
        "l10_ge8",
        "cover_pass",
        "delta_pass",
        "d_pass",
        "gold_like_l5_cover_delta_d",
        "standard_all",
        "standard_l5_ge4",
        "goblin_all",
        "goblin_l5_ge4",
        "goblin_l5_ge4_d",
    ]
    print("\n=== BY SPORT (Std+Gob) ===")
    for sp in ("Soccer", "Tennis", "NFL", "WNBA", "MLB"):
        block = report["by_sport_standard_goblin"][sp]
        print("-- %s n=%s source=%s" % (sp, block["n_rows"], block.get("source")))
        for k in keys:
            if k in block:
                print("  %s %s" % (k.ljust(32), fmt(block[k])))
    print("\n=== TENNIS ALL PICKS (incl Demon) ===")
    block = report["by_sport_all_picks"]["Tennis"]
    for k in keys:
        if k in block:
            print("  %s %s" % (k.ljust(32), fmt(block[k])))
    print("\nNFL:", nfl_diag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
