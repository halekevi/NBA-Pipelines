#!/usr/bin/env python3
"""Rank Standard Over/Under and Goblin Over plays for the active slate.

Always prints four sports: WNBA, MLB, Soccer, Tennis. Thin pools are listed
as empty, never omitted.

Season cover = mean of that exact prop over logged games minus the posted
line. Overs COVER when avg > line; Unders COVER when avg < line.

Badge = how many of six checks miss (N/A skipped, not a miss):
  L5 (>=4 on the play side), Cover (avg on the right side of the line),
  Delta (|avg-line| >= max(0.5, 15% of line)), Dir (model_dir agrees),
  D (O vs Weak/Below Avg, U vs Elite/Above Avg), Rank (O worse than
  median D, U top 40%; 1 = stingiest). Gold = 0 misses, Silver = 1, Bronze = 2.

  py -3.14 scripts/rank_best_props_today.py --date 2026-08-18
  py -3.14 scripts/rank_best_props_today.py --date 2026-08-18 --step8-root H:\\...\\PropORACLE_main_cp
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
WEAK = {"weak", "easy", "easiest"}
ELITE = {"elite", "hard", "hardest", "tough"}
WEAK_ALIGN = WEAK | {"below avg", "below average"}
ELITE_ALIGN = ELITE | {"above avg", "above average", "solid"}
SKIP_PROPS = {"fantasy score", "fantasy"}
# Tennis ATP/WTA: lower # = stronger opponent (inverse of team D rank).
_ATP_ELITE_MAX = 10
_ATP_ABOVE_AVG_MAX = 25
_ATP_AVG_MAX = 50
_ATP_BELOW_AVG_MAX = 100
_UNKNOWN_OPP = {"unknown_opp", "unk", "unknown", ""}
DELTA_FLOOR = 0.50
DELTA_PCT = 0.15
BADGE_ORDER = {"Gold": 0, "Silver": 1, "Bronze": 2}
SPORTS = (
    ("WNBA", "wnba", "step8_wnba_direction.csv"),
    ("MLB", "mlb", "step8_mlb_direction.csv"),
    ("SOCCER", "soccer", "step8_soccer_direction.csv"),
    ("TENNIS", "tennis", "step8_tennis_direction.csv"),
)


def _pick(v) -> str:
    s = str(v or "").strip().lower()
    if "dem" in s:
        return "Demon"
    if "gob" in s:
        return "Goblin"
    if "std" in s or s == "standard":
        return "Standard"
    return str(v or "").strip() or "Unknown"


def _dir(r) -> str:
    for c in ("final_bet_direction", "bet_direction", "model_dir"):
        s = str(r.get(c) or "").strip().upper()
        if s in ("OVER", "UNDER"):
            return s
    return ""


def _model_dir(r) -> str:
    s = str(r.get("model_dir") or "").strip().upper()
    return s if s in ("OVER", "UNDER") else ""


def _atp_tier_from_rank(rank) -> str:
    """Map individual opponent ATP/WTA rank to the same five D labels as team sports."""
    v = _num(rank)
    if v is None or v <= 0:
        return ""
    if v <= _ATP_ELITE_MAX:
        return "Elite"
    if v <= _ATP_ABOVE_AVG_MAX:
        return "Above Avg"
    if v <= _ATP_AVG_MAX:
        return "Avg"
    if v <= _ATP_BELOW_AVG_MAX:
        return "Below Avg"
    return "Weak"


def _opp_name(r) -> str:
    return _clean(r.get("opp_team") or r.get("opp") or "").lower()


def _def_rank(r):
    sport = str(r.get("sport") or "").strip().upper()
    if sport == "TENNIS":
        if _opp_name(r) in _UNKNOWN_OPP:
            return None
        v = _num(r.get("opponent_rank")) or _num(r.get("opponent_def_rank"))
        return v if v is not None and v > 0 else None
    for c in ("OVERALL_DEF_RANK", "stat_def_rank", "def_rank", "opponent_def_rank"):
        v = _num(r.get(c))
        if v is not None and v > 0:
            return v
    return None


def _n_teams(df: pd.DataFrame):
    for c in ("OVERALL_DEF_RANK", "stat_def_rank", "def_rank"):
        if c not in df.columns:
            continue
        m = pd.to_numeric(df[c], errors="coerce").max()
        if pd.notna(m) and float(m) >= 5:
            return int(m)
    return None


def _delta_need(line: float) -> float:
    return max(DELTA_FLOOR, abs(line) * DELTA_PCT)


def _clean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("", "nan", "none") else s


def _def(r) -> str:
    sport = str(r.get("sport") or "").strip().upper()
    if sport == "TENNIS":
        return _atp_tier_from_rank(_def_rank(r))
    raw = (
        _clean(r.get("stat_def_tier"))
        or _clean(r.get("DEF_TIER"))
        or _clean(r.get("def_tier"))
        or _clean(r.get("opp_def_tier"))
    )
    low = raw.lower()
    if low in {"n/a", "na", "none"}:
        return ""
    if low in WEAK or "easy" in low:
        return "Weak"
    if "below" in low:
        return "Below Avg"
    if low in ELITE or "hard" in low or "elite" in low:
        return "Elite"
    if "above" in low:
        return "Above Avg"
    return raw


def _over_d_ok(sport: str, tier: str) -> bool:
    if sport in ("WNBA", "MLB"):
        return tier == "Weak"
    if sport in ("SOCCER", "TENNIS"):
        return tier in ("Weak", "Below Avg")
    return False


def _under_d_ok(sport: str, tier: str) -> bool:
    if sport in ("WNBA", "MLB"):
        return tier == "Elite"
    if sport in ("SOCCER", "TENNIS"):
        return tier in ("Elite", "Above Avg")
    return False


def _num(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if str(v).strip() in ("", "nan", "None"):
            return None
        return int(float(v))
    except Exception:
        return None


def _flt(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if str(v).strip() in ("", "nan", "None"):
            return None
        return float(v)
    except Exception:
        return None


def _prop_avg(r) -> float | None:
    """Mean of that exact prop over all logged games (season avg, else g1..gN)."""
    seas = _flt(r.get("stat_season_avg")) or _flt(r.get("season_avg"))
    if seas is not None:
        return seas
    vals = []
    for i in range(1, 21):
        v = _flt(r.get(f"stat_g{i}"))
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _l5(r, over: bool):
    if over:
        return _num(r.get("l5_over")) or _num(r.get("last5_over"))
    return _num(r.get("l5_under")) or _num(r.get("last5_under"))


def _l10(r, over: bool):
    if over:
        return _num(r.get("l10_over"))
    return _num(r.get("l10_under"))


def _d_aligns(tier: str, over: bool) -> bool:
    low = (tier or "").strip().lower()
    if not low:
        return False
    if over:
        return low in WEAK_ALIGN or "below" in low or "easy" in low
    return low in ELITE_ALIGN or "above" in low or "hard" in low or "elite" in low


def _badge(rec: dict, n_teams: int | None) -> dict:
    """Six checks; Gold = 0 misses, Silver = 1, Bronze = 2. N/A checks are skipped."""
    side = rec.get("side") or ""
    over = side == "OVER"
    l5 = rec["l5_over"] if over else rec["l5_under"]
    cover = rec.get("cover")
    line = rec.get("line") if isinstance(rec.get("line"), (int, float)) else _flt(rec.get("line"))
    tier = rec.get("def") or ""
    rank = rec.get("def_rank")
    model = rec.get("model_dir") or ""
    sport = rec.get("sport") or ""

    checks: dict[str, bool | None] = {}
    checks["L5"] = None if l5 is None else l5 >= 4
    if cover is None:
        checks["Cover"] = None
    elif over:
        checks["Cover"] = cover > 0
    elif side == "UNDER":
        checks["Cover"] = cover < 0
    else:
        checks["Cover"] = None

    if cover is None or line is None:
        checks["Delta"] = None
    else:
        need = _delta_need(float(line))
        checks["Delta"] = cover >= need if over else cover <= -need

    if not model:
        checks["Dir"] = None
    elif rec.get("pick_type") == "Goblin":
        checks["Dir"] = model == "OVER"
    else:
        checks["Dir"] = model == side

    skip_matchup = not tier and rank is None
    if skip_matchup:
        checks["D"] = None
        checks["Rank"] = None
    else:
        checks["D"] = None if not tier else _d_aligns(tier, over)
        if rank is None:
            checks["Rank"] = None
        elif sport == "TENNIS":
            # Lower ATP # = stronger opponent (Elite). Overs want Weak/Below Avg (rank > 50).
            checks["Rank"] = rank > _ATP_AVG_MAX if over else rank <= _ATP_ABOVE_AVG_MAX
        elif not n_teams:
            checks["Rank"] = None
        elif over:
            checks["Rank"] = rank >= int(math.ceil(0.5 * n_teams))
        else:
            checks["Rank"] = rank <= int(math.floor(0.4 * n_teams))

    applicable = {k: v for k, v in checks.items() if v is not None}
    misses = [k for k, v in applicable.items() if v is False]
    if len(applicable) < 4:
        badge = ""
    elif not misses:
        badge = "Gold"
    elif len(misses) == 1:
        badge = "Silver"
    elif len(misses) == 2:
        badge = "Bronze"
    else:
        badge = ""
    return {
        "checks": checks,
        "misses": misses,
        "n_app": len(applicable),
        "badge": badge,
        "miss_s": ", ".join(misses) if misses else "",
    }


def fill_tennis_opp_rank_from_slate(df: pd.DataFrame) -> pd.DataFrame:
    """Replace placeholder opponent_rank=75 with the opponent's player_atp_rank on this slate."""
    if df is None or df.empty:
        return df
    out = df.copy()

    def _rk(v):
        n = _num(v)
        if n is None or n <= 0 or n >= 900:
            return None
        return n

    def _name(v) -> str:
        s = _clean(v).upper()
        return "" if s in _UNKNOWN_OPP or s == "NAN" else s

    name_rank: dict[str, int] = {}
    if "player" in out.columns and "player_atp_rank" in out.columns:
        for _, r in out.iterrows():
            n = _name(r.get("player"))
            rk = _rk(r.get("player_atp_rank"))
            if n and rk:
                name_rank[n] = rk
    ocol = "opp_team" if "opp_team" in out.columns else ("opp" if "opp" in out.columns else None)
    filled = []
    for _, r in out.iterrows():
        opp = _name(r.get(ocol) if ocol else "")
        rk = name_rank.get(opp)
        if rk is None and opp:
            for n, v in name_rank.items():
                if opp in n or n in opp:
                    rk = v
                    break
        existing = _rk(r.get("opponent_rank"))
        if existing == 75:
            existing = None
        filled.append(rk if rk is not None else existing)
    out["opponent_rank"] = filled
    return out


def load_sport(root: Path, date: str, sport: str, folder: str, fname: str) -> pd.DataFrame:
    path = root / "outputs" / date / folder / fname
    if not path.is_file():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    df["sport"] = sport
    if sport == "TENNIS":
        df = fill_tennis_opp_rank_from_slate(df)
    if "game_date" in df.columns and sport != "TENNIS":
        gd = df["game_date"].astype(str).str[:10]
        df = df[gd.eq(date) | gd.eq("") | gd.eq("nan")].copy()
    return df


def recs(df: pd.DataFrame) -> list[dict]:
    out = []
    n_teams = _n_teams(df)
    for _, r in df.iterrows():
        prop = str(r.get("prop_type") or r.get("prop") or "").strip()
        if prop.lower() in SKIP_PROPS:
            continue
        player = str(r.get("player") or "").strip()
        team = str(r.get("team") or "").strip()
        opp = str(r.get("opp_team") or "").strip()
        line = _flt(r.get("line"))
        avg = _prop_avg(r)
        cover = None if avg is None or line is None else avg - line
        side = _dir(r)
        clears = False
        if cover is not None:
            if side == "OVER":
                clears = cover > 0
            elif side == "UNDER":
                clears = cover < 0
        rec = {
            "sport": str(r.get("sport") or ""),
            "player": player,
            "prop": prop,
            "line": r.get("line") if line is None else line,
            "pick_type": _pick(r.get("pick_type")),
            "side": side,
            "model_dir": _model_dir(r),
            "l5_over": _l5(r, True),
            "l5_under": _l5(r, False),
            "l10_over": _l10(r, True),
            "l10_under": _l10(r, False),
            "season_avg": None if avg is None else round(avg, 2),
            "cover": None if cover is None else round(cover, 2),
            "clears_line": clears,
            "def": _def(r),
            "def_rank": _def_rank(r),
            "matchup": f"{team} vs {opp}".strip(" vs"),
        }
        rec.update(_badge(rec, n_teams))
        out.append(rec)
    return out


def bucket(rows: list[dict], sport: str) -> tuple[list[dict], list[dict], list[dict]]:
    std_o, std_u, gob = [], [], []
    for r in rows:
        if r["sport"] != sport:
            continue
        d = r["def"]
        if r["pick_type"] == "Standard" and r["side"] == "OVER" and (r["l5_over"] or 0) >= 4:
            if not _over_d_ok(sport, d):
                continue
            std_o.append(r)
        elif r["pick_type"] == "Standard" and r["side"] == "UNDER" and (r["l5_under"] or 0) >= 4:
            if not _under_d_ok(sport, d):
                continue
            std_u.append(r)
        elif r["pick_type"] == "Goblin" and r["side"] == "OVER" and (r["l5_over"] or 0) >= 4:
            if not _over_d_ok(sport, d):
                continue
            gob.append(r)

    def dedup(lst, over: bool):
        seen = set()
        out = []

        def cover_key(x):
            c = x.get("cover")
            if c is None:
                return 0.0
            return -c if over else c

        lst = sorted(
            lst,
            key=lambda x: (
                BADGE_ORDER.get(x.get("badge") or "", 3),
                -((x["l5_over"] if over else x["l5_under"]) or 0),
                cover_key(x),
                -((x["l10_over"] if over else x["l10_under"]) or 0),
                x["player"],
            ),
        )
        for r in lst:
            k = (r["player"], r["prop"], r["line"])
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    return dedup(std_o, True), dedup(std_u, False), dedup(gob, True)


def _fmt(r: dict, side: str) -> str:
    line = r.get("line")
    prefix = "O" if side == "OVER" else "U"
    l5 = f"{r.get('l5_over')}/{r.get('l5_under')}"
    d = r.get("def") or "no-D"
    rk = r.get("def_rank")
    d_s = f"{d}#{rk}" if rk else d
    avg = r.get("season_avg")
    cover = r.get("cover")
    avg_s = f"{avg:5.2f}" if isinstance(avg, (int, float)) else "  n/a"
    if isinstance(cover, (int, float)):
        cov_s = f"{cover:+5.2f}"
    else:
        cov_s = "  n/a"
    badge = (r.get("badge") or "—").upper()[:6]
    miss = r.get("miss_s") or ""
    miss_s = f"  miss {miss}" if miss else ""
    return (
        f"  {badge:6} {r['player']:24} {r['prop']:18} {prefix}{line}  "
        f"L5 {l5}  avg {avg_s}  cov {cov_s}  {d_s:12}{miss_s}  {r.get('matchup') or ''}"
    )


def print_sport(sport: str, std_o, std_u, gob, n_o=8, n_u=8, n_g=12) -> None:
    listed = std_o + std_u + gob
    n_gold = sum(1 for r in listed if r.get("badge") == "Gold")
    n_sil = sum(1 for r in listed if r.get("badge") == "Silver")
    n_brz = sum(1 for r in listed if r.get("badge") == "Bronze")
    print(f"\n===== {sport} =====  Gold {n_gold}  Silver {n_sil}  Bronze {n_brz}")
    print(f"Standard OVER  (n={len(std_o)})")
    if not std_o:
        print("  (none that clear L5 4+ / D filter)")
    for r in std_o[:n_o]:
        print(_fmt(r, "OVER"))
    print(f"Standard UNDER (n={len(std_u)})")
    if not std_u:
        print("  (none that clear L5 4+ / D filter)")
    for r in std_u[:n_u]:
        print(_fmt(r, "UNDER"))
    print(f"Goblin OVER    (n={len(gob)})")
    if not gob:
        print("  (none that clear L5 4+ / D filter)")
    g_badge = [r for r in gob if r.get("badge") in ("Gold", "Silver")]
    g_brz = [r for r in gob if r.get("badge") == "Bronze"]
    g_rest = [r for r in gob if r.get("badge") not in ("Gold", "Silver", "Bronze")]
    shown = 0
    for r in g_badge + g_brz + g_rest:
        if "earned run" in r["prop"].lower() and float(r.get("line") or 99) <= 0.5:
            continue
        print(_fmt(r, "OVER"))
        shown += 1
        if shown >= n_g and r.get("badge") not in ("Gold", "Silver"):
            break


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="Slate date YYYY-MM-DD")
    ap.add_argument(
        "--step8-root",
        default="",
        help="Repo with outputs/<date>/*/step8 (default: this repo, then PropORACLE_main_cp)",
    )
    args = ap.parse_args()
    date = str(args.date).strip()[:10]
    candidates = []
    if args.step8_root:
        candidates.append(Path(args.step8_root))
    candidates.append(_REPO)
    main_cp = _REPO.parent / "PropORACLE_main_cp"
    if main_cp.is_dir():
        candidates.append(main_cp)
    root = None
    for c in candidates:
        if (c / "outputs" / date / "wnba" / "step8_wnba_direction.csv").is_file():
            root = c
            break
    if root is None:
        print("No step8 CSVs found for", date)
        return 1
    print(f"Best props {date}  step8={root}")
    all_rows: list[dict] = []
    for sport, folder, fname in SPORTS:
        df = load_sport(root, date, sport, folder, fname)
        if df.empty:
            print(f"\n===== {sport} =====\n  (no step8 file)")
            continue
        all_rows.extend(recs(df))
        print_sport(sport, *bucket(all_rows, sport))
    print("\n===== BADGE BOARD (L5 4+ lists, 0–2 misses) =====")
    for sport, _folder, _fname in SPORTS:
        so, su, gob = bucket(all_rows, sport)
        rows = [r for r in so + su + gob if r.get("badge")]
        if not rows:
            print(f"\n{sport}: (none)")
            continue
        print(f"\n{sport}")
        for r in rows:
            print(_fmt(r, r.get("side") or "OVER"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
