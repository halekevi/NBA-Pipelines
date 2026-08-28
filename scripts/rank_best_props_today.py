#!/usr/bin/env python3
"""Rank Standard Over/Under and Goblin Over plays for the active slate.

Always prints four sports: WNBA, MLB, Soccer, Tennis. Thin pools are listed
as empty, never omitted. NFL + NFLP share one step8 workbook and print as
an extra NFL section when that file exists.

Season cover = mean of that exact prop over logged games minus the posted
line. Overs COVER when avg > line; Unders COVER when avg < line.

List gate (hard): directional L5 >= 4. D is NOT a hard filter — a D miss
  only costs a badge (typically Silver if D is the only miss).
  NFLP (preseason) exception: 2025 L5 is not a lock. Sit/cameo skill overs
  are dropped; backup overs need D; kickers still use L5 >= 4.

Badge = how many of six checks miss (N/A skipped, not a miss):
  L5 (>=4 on the play side), Cover (avg on the right side of the line),
  Delta (|avg-line| >= max(0.5, 15% of line)), Dir (model_dir agrees),
  D (all sports O=Weak|Below Avg U=Elite|Above Avg; MLB hitter_strikeouts
  inverted O=Elite|Above Avg U=Weak|Below Avg; Avg never passes), Rank (O
  worse than median D, U top 40%; hitter Ks invert; tennis ATP #).
  Gold = 0 misses, Silver = 1, Bronze = 2.
  Diamond = Gold + directional L10 >= 8 AND season HR > 70% (min 10 games vs today's line).
  Platinum = Gold + exactly one of those two extra gates.

  Prop tier (S–D) is the market: S = MLB pitcher Goblins, A = WNBA/tennis
  Goblin scoring + pitching outs + soccer saves. Sort S→D then Diamond→Bronze.
  Promotions can raise B/C into A/S (H+R+RBI + D, reb+ast cover, TB cover+D,
  hitter K cover). Shadow cells tag as W and stay on the list.

  py -3.14 scripts/rank_best_props_today.py --date 2026-08-18
  py -3.14 scripts/rank_best_props_today.py --date 2026-08-18 --step8-root H:\\...\\PropORACLE_main_cp
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from proporacle.data.table_io import read_table, table_exists
from utils.slate_context_fill import is_hitter_strikeout_prop
from utils.defense_tiers import normalize_def_tier_label  # noqa: E402
from utils.ticket_tier_defense_gates import tennis_tight_match_note  # noqa: E402
from utils.nflp_playing_time import (  # noqa: E402
    expected_snaps_bucket,
    is_nflp,
    nflp_list_eligible,
    policy_from_row,
)
from prop_hit_tiers import assign_tier, sort_key_tier_then_badge  # noqa: E402

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
CFB_N_TEAMS = 122
BLOWOUT_SIT_TEAMS = {"USC", "FSU"}
SPORTS = (
    ("WNBA", "wnba", "step8_wnba_direction.csv"),
    ("MLB", "mlb", "step8_mlb_direction.csv"),
    ("SOCCER", "soccer", "step8_soccer_direction.csv"),
    ("TENNIS", "tennis", "step8_tennis_direction.csv"),
)
_STEP1_FILES = (
    ("wnba", "step1_wnba_props.csv"),
    ("mlb", "step1_mlb_props.csv"),
    ("soccer", "step1_soccer_props.csv"),
    ("tennis", "step1_tennis_props.csv"),
    ("nfl", "step1_pp_props_today.csv"),
    ("cfb", "step1_cfb.csv"),
)


def _parse_fetch_ts(v) -> datetime | None:
    s = str(v or "").strip()
    if len(s) < 10:
        return None
    try:
        return datetime.fromisoformat(s[:19].replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except Exception:
        return None


def _root_board_freshness(root: Path, date: str) -> tuple[int, datetime]:
    """How many step1 boards were fetched on `date`, plus newest fetch timestamp."""
    same_day = 0
    latest = datetime.min
    for folder, fname in _STEP1_FILES:
        p = root / "outputs" / date / folder / fname
        if not p.is_file():
            continue
        ts = None
        try:
            df = pd.read_csv(p, nrows=5)
            for col in ("fetched_at", "line_asof"):
                if col in df.columns and len(df):
                    ts = _parse_fetch_ts(df[col].iloc[0])
                    if ts:
                        break
        except Exception:
            ts = None
        if ts is None:
            ts = datetime.fromtimestamp(p.stat().st_mtime)
        if ts.strftime("%Y-%m-%d") == date:
            same_day += 1
        naive = ts.replace(tzinfo=None)
        if naive > latest:
            latest = naive
    return same_day, latest


def _choose_step8_root(candidates: list[Path], date: str) -> Path | None:
    """Prefer a worktree whose step1 was fetched on the slate date (not yesterday's board)."""
    scored: list[tuple[int, datetime, Path]] = []
    for c in candidates:
        same_day, latest = _root_board_freshness(c, date)
        has8 = any(
            table_exists(c / "outputs" / date / folder / fname)
            for folder, fname in (
                ("wnba", "step8_wnba_direction.csv"),
                ("mlb", "step8_mlb_direction.csv"),
                ("soccer", "step8_soccer_direction.csv"),
                ("tennis", "step8_tennis_direction.csv"),
                ("nfl", "step8_nfl_direction_clean.xlsx"),
                ("cfb", "step8_cfb_direction_clean.xlsx"),
            )
        )
        if not has8:
            if same_day > 0:
                print(
                    f"  note: {c} has same-day step1 ({same_day}) but no step8 yet "
                    f"(newest={latest:%Y-%m-%d %H:%M}) — wait for 8AM pipeline to finish"
                )
            continue
        scored.append((same_day, latest, c))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = scored[0]
    for same_day, latest, c in scored[1:]:
        if c != best[2] and same_day < best[0]:
            print(
                f"  skip stale step8 root {c} "
                f"(same-day step1={same_day}, newest={latest:%Y-%m-%d %H:%M}) "
                f"-> using {best[2]} (same-day step1={best[0]}, newest={best[1]:%Y-%m-%d %H:%M})"
            )
    return best[2]


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
    for c in ("final_bet_direction", "bet_direction", "model_dir", "Direction"):
        s = str(r.get(c) or "").strip().upper()
        if s in ("OVER", "UNDER"):
            return s
    return ""


def _model_dir(r) -> str:
    for c in ("model_dir", "Direction", "final_bet_direction"):
        s = str(r.get(c) or "").strip().upper()
        if s in ("OVER", "UNDER"):
            return s
    return ""


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
    return _clean(r.get("opp_team") or r.get("opp") or r.get("Opp") or "").lower()


def _def_rank(r):
    sport = str(r.get("sport") or "").strip().upper()
    if sport == "TENNIS":
        if _opp_name(r) in _UNKNOWN_OPP:
            return None
        v = _num(r.get("opponent_rank")) or _num(r.get("opponent_def_rank"))
        return v if v is not None and v > 0 else None
    for c in (
        "OVERALL_DEF_RANK",
        "stat_def_rank",
        "def_rank",
        "opponent_def_rank",
        "opp_def_rank",
        "Def Rank",
    ):
        v = _num(r.get(c))
        if v is not None and v > 0:
            return v
    return None


def _n_teams(df: pd.DataFrame):
    if "sport" in df.columns and len(df):
        if str(df["sport"].iloc[0] or "").strip().upper() == "CFB":
            return CFB_N_TEAMS
    for c in ("OVERALL_DEF_RANK", "stat_def_rank", "def_rank", "Def Rank"):
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
        or _clean(r.get("Def Tier"))
    )
    if not raw or raw.lower() in {"n/a", "na", "none"}:
        return ""
    # Canonical Elite→Weak (also maps legacy HARD/EASY* for back-compat).
    return normalize_def_tier_label(raw) or ""

def _over_d_ok(sport: str, tier: str, prop: str = "") -> bool:
    # Default all pipeline sports: Weak | Below Avg. Avg never passes.
    # Hitter Ks invert (wide): Elite | Above Avg. Pitcher Ks keep production.
    if sport == "MLB" and is_hitter_strikeout_prop(prop):
        return tier in ("Elite", "Above Avg")
    return tier in ("Weak", "Below Avg")


def _under_d_ok(sport: str, tier: str, prop: str = "") -> bool:
    # Default all pipeline sports: Elite | Above Avg. Avg never passes.
    # Hitter Ks invert (wide): Weak | Below Avg. Pitcher Ks keep production.
    if sport == "MLB" and is_hitter_strikeout_prop(prop):
        return tier in ("Weak", "Below Avg")
    return tier in ("Elite", "Above Avg")


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
    seas = (
        _flt(r.get("stat_season_avg"))
        or _flt(r.get("season_avg"))
        or _flt(r.get("Season Avg"))
        or _flt(r.get("Projection"))
    )
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


def _first_count(*vals):
    """First numeric hit count, including 0 (do not treat 0/5 as missing)."""
    for v in vals:
        n = _num(v)
        if n is not None:
            return n
    return None


def _l5(r, over: bool):
    if over:
        return _first_count(r.get("l5_over"), r.get("last5_over"), r.get("L5 Over"))
    return _first_count(r.get("l5_under"), r.get("last5_under"), r.get("L5 Under"))


def _l10(r, over: bool):
    if over:
        return _first_count(r.get("l10_over"), r.get("L10 Over"))
    return _first_count(r.get("l10_under"), r.get("L10 Under"))


def _season_hr(r) -> float | None:
    v = _flt(r.get("hit_rate")) or _flt(r.get("Hit Rate")) or _flt(r.get("season_hr"))
    if v is None:
        return None
    if v > 1.5:
        v = v / 100.0
    return v


def _season_n(r) -> int | None:
    n = (
        _num(r.get("strat_n"))
        or _num(r.get("Strat N"))
        or _num(r.get("season_n"))
        or _num(r.get("season_games"))
    )
    if n:
        return n
    # CFB Week 1: Strat N is blank; L10 over+under is the 2025 sample vs today's line.
    l10o = _num(r.get("l10_over")) or _num(r.get("L10 Over"))
    l10u = _num(r.get("l10_under")) or _num(r.get("L10 Under"))
    if l10o is not None and l10u is not None:
        return int(l10o + l10u)
    return None


def _promo(r: dict) -> str:
    gold = r.get("badge") == "Gold"
    l10 = r.get("l10")
    l10_ok = l10 is not None and l10 >= 8
    szn_ok = (
        r.get("season_hr") is not None
        and (r.get("season_n") or 0) >= 10
        and r["season_hr"] > 0.70
    )
    if gold and l10_ok and szn_ok:
        return "Diamond"
    if gold and (l10_ok != szn_ok):
        return "Platinum"
    return r.get("badge") or ""


def _promo_sort_key(r: dict) -> int:
    promo = r.get("promo") or r.get("Promo") or ""
    l10 = r.get("l10") or r.get("L10_over") or r.get("L10_under") or 0
    if promo == "Diamond":
        return 0
    if promo == "Platinum" and l10 >= 8:
        return 1
    if (r.get("badge") or r.get("Badge")) == "Gold":
        return 2
    if promo == "Platinum":
        return 3
    if (r.get("badge") or r.get("Badge")) == "Silver":
        return 4
    return 5


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

    prop = str(rec.get("prop") or "")
    hitter_ks = sport == "MLB" and is_hitter_strikeout_prop(prop)
    skip_matchup = not tier and rank is None
    if skip_matchup:
        # Unknown opponent / missing D: do not pass D — count as a miss when
        # we expected a matchup (blank tier with no rank).
        checks["D"] = False
        checks["Rank"] = None
    else:
        if not tier:
            checks["D"] = False
        elif over:
            checks["D"] = _over_d_ok(sport, tier, prop)
        elif side == "UNDER":
            checks["D"] = _under_d_ok(sport, tier, prop)
        else:
            checks["D"] = False
        if rank is None:
            checks["Rank"] = None
        elif sport == "TENNIS":
            # Lower ATP # = stronger opponent (Elite). Overs want Weak/Below Avg (rank > 50).
            checks["Rank"] = rank > _ATP_AVG_MAX if over else rank <= _ATP_ABOVE_AVG_MAX
        elif not n_teams:
            checks["Rank"] = None
        elif hitter_ks:
            # Invert vs production: OVER favors stingy/Elite (low rank); UNDER favors Weak.
            checks["Rank"] = (
                rank <= int(math.floor(0.4 * n_teams))
                if over
                else rank >= int(math.ceil(0.5 * n_teams))
            )
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
    """Fill opponent_rank from hydrated ESPN rankings + slate cross-lookup."""
    tennis_scripts = _REPO / "Sports" / "Tennis" / "scripts"
    if str(tennis_scripts) not in sys.path:
        sys.path.insert(0, str(tennis_scripts))
    from tennis_shared import (
        fill_opponent_rank_from_slate_players,
        hydrate_rankings_from_slate,
        load_or_refresh_rankings,
        resolve_opp_rank_pair,
    )

    cache_dir = _REPO / "Sports" / "Tennis" / "cache"
    rankings = load_or_refresh_rankings(cache_dir / "tennis_rankings.json")
    rankings = hydrate_rankings_from_slate(
        df, rankings, cache_path=cache_dir / "tennis_opp_rank_cache.json"
    )
    opp_col = "opp_team" if "opp_team" in df.columns else "opp"
    filled = []
    for i in range(len(df)):
        v = resolve_opp_rank_pair(str(df.iloc[i].get(opp_col, "")), rankings)
        filled.append(v)
    out = df.copy()
    out["opponent_rank"] = filled
    return fill_opponent_rank_from_slate_players(out)


def filter_step8_to_slate_date(df: pd.DataFrame, date: str, sport: str = "") -> pd.DataFrame:
    """Keep rows whose game starts on ``date`` Eastern.

    Day-ahead boards often store the fetch day in ``game_date`` while
    ``start_time`` is the actual tip. Prefer start_time when it parses.
    """
    if df is None or getattr(df, "empty", True):
        return df
    if "start_time" in df.columns:
        st = pd.to_datetime(df["start_time"], errors="coerce", utc=True)
        if st.notna().any():
            et = st.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
            return df.loc[et.eq(date)].copy()
    if "game_date" in df.columns and str(sport).upper() != "TENNIS":
        gd = df["game_date"].astype(str).str[:10]
        return df.loc[gd.eq(date) | gd.eq("") | gd.eq("nan")].copy()
    return df


def load_sport(root: Path, date: str, sport: str, folder: str, fname: str) -> pd.DataFrame:
    path = root / "outputs" / date / folder / fname
    if not table_exists(path):
        return pd.DataFrame()
    df = read_table(path)
    df["sport"] = sport
    if sport == "TENNIS":
        df = fill_tennis_opp_rank_from_slate(df)
    return filter_step8_to_slate_date(df, date, sport)


def load_nfl(root: Path, date: str) -> pd.DataFrame:
    """NFL + NFLP share one step8 workbook (preseason is the same D table)."""
    candidates = [
        root / "outputs" / date / "nfl" / "step8_nfl_direction_clean.xlsx",
        root / "outputs" / date / "nfl" / f"step8_nfl_direction_clean_{date}.xlsx",
        root / "Sports" / "NFL" / "outputs" / "step8_nfl_direction_clean.xlsx",
        root / "outputs" / date / f"step8_nfl_direction_clean_{date}.xlsx",
    ]
    path = next((p for p in candidates if table_exists(p)), None)
    if path is None:
        return pd.DataFrame()
    df = read_table(path, sheet_order=("ALL",))
    df["sport"] = "NFL"
    return df


def load_cfb(root: Path, date: str) -> pd.DataFrame:
    """CFB Week 1+ step8 workbook (122-team FBS D table)."""
    candidates = [
        root / "outputs" / date / "cfb" / "step8_cfb_direction_clean.xlsx",
        root / "outputs" / date / "cfb" / f"step8_cfb_direction_clean_{date}.xlsx",
        root / "Sports" / "CFB" / "outputs" / "step8_cfb_direction_clean.xlsx",
    ]
    path = next((p for p in candidates if table_exists(p)), None)
    if path is None:
        return pd.DataFrame()
    df = read_table(path, sheet_order=("ALL",))
    df["sport"] = "CFB"
    return df


CBB_SEASON_END_2026 = "2026-04-07"
CBB_SEASON_RESUME = "2026-11-01"


def _cbb_season_active(date: str) -> bool:
    d = str(date or "")[:10]
    return bool(d) and (d < CBB_SEASON_END_2026 or d >= CBB_SEASON_RESUME)


def _load_cbb_family(root: Path, date: str, sport: str, folder: str) -> pd.DataFrame:
    """CBB/WCBB step8 when present (combined still uses step6 until step8 is wired)."""
    key = folder.lower()
    candidates = [
        root / "outputs" / date / folder / f"step8_{key}_direction_clean.xlsx",
        root / "outputs" / date / folder / f"step8_{key}_direction_clean_{date}.xlsx",
        root / "Sports" / "CBB" / "outputs" / f"step8_{key}_direction_clean.xlsx",
    ]
    path = next((p for p in candidates if table_exists(p)), None)
    if path is None:
        return pd.DataFrame()
    df = read_table(path, sheet_order=("ALL",))
    df["sport"] = sport
    return df


def load_cbb(root: Path, date: str) -> pd.DataFrame:
    return _load_cbb_family(root, date, "CBB", "cbb")


def load_wcbb(root: Path, date: str) -> pd.DataFrame:
    return _load_cbb_family(root, date, "WCBB", "wcbb")


def recs(df: pd.DataFrame) -> list[dict]:
    out = []
    n_teams = _n_teams(df)
    for _, r in df.iterrows():
        prop = str(r.get("prop_type") or r.get("prop") or r.get("Prop") or "").strip()
        if prop.lower() in SKIP_PROPS:
            continue
        player = str(r.get("player") or r.get("Player") or "").strip()
        team = str(r.get("team") or r.get("Team") or "").strip()
        opp = str(r.get("opp_team") or r.get("Opp") or "").strip()
        line = _flt(r.get("line"))
        if line is None:
            line = _flt(r.get("Line"))
        avg = _prop_avg(r)
        cover = None if avg is None or line is None else avg - line
        side = _dir(r)
        clears = False
        if cover is not None:
            if side == "OVER":
                clears = cover > 0
            elif side == "UNDER":
                clears = cover < 0
        league = _clean(r.get("league") or r.get("League"))
        matchup = f"{team} vs {opp}".strip(" vs")
        if league:
            matchup = f"{matchup} ({league})" if matchup else league
        rec = {
            "sport": str(r.get("sport") or ""),
            "player": player,
            "prop": prop,
            "line": r.get("line") if line is None else line,
            "pick_type": _pick(r.get("pick_type") or r.get("Pick Type")),
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
            "matchup": matchup,
            "matchup_note": tennis_tight_match_note(
                prop, _def_rank(r), direction=side, opp_name=opp
            )
            or "",
            "league": league,
        }
        rec["starter_policy"] = policy_from_row({**dict(r), **rec})
        rec["expected_snaps"] = expected_snaps_bucket(rec["starter_policy"])
        rec.update(_badge(rec, n_teams))
        rec["l10"] = rec["l10_over"] if rec["side"] == "OVER" else rec["l10_under"]
        rec["season_hr"] = _season_hr(r)
        rec["season_n"] = _season_n(r) or 0
        rec["ml_prob"] = _flt(r.get("ml_prob") or r.get("ML Prob") or r.get("MLProb"))
        if rec["ml_prob"] is not None and rec["ml_prob"] > 1.5:
            rec["ml_prob"] = rec["ml_prob"] / 100.0
        sample_hr = _flt(r.get("last5_hit_rate") or r.get("hit_rate_L5"))
        if sample_hr is None:
            if side == "OVER":
                sample_hr = _flt(r.get("line_hit_rate_over_ou_5") or r.get("line_hit_rate_over_5"))
            else:
                sample_hr = _flt(r.get("line_hit_rate_under_ou_5") or r.get("line_hit_rate_under_5"))
        if sample_hr is None:
            l5n = rec["l5_over"] if side == "OVER" else rec["l5_under"]
            if isinstance(l5n, (int, float)):
                sample_hr = float(l5n) / 5.0
        if sample_hr is not None and sample_hr > 1.5:
            sample_hr = sample_hr / 100.0
        rec["hit_rate"] = sample_hr if sample_hr is not None else rec["season_hr"]
        rec["standard_line"] = _flt(r.get("standard_line") or r.get("Standard Line"))
        rec["line_underdog"] = _flt(r.get("line_underdog"))
        rec["line_draftkings"] = _flt(r.get("line_draftkings"))
        rec["best_cross_book"] = str(r.get("best_cross_book") or "").strip()
        rec["best_cross_line"] = _flt(r.get("best_cross_line"))
        rec["cross_edge_vs_pp"] = _flt(r.get("cross_edge_vs_pp"))
        rec["promo"] = _promo(rec)
        rec.update(
            assign_tier(
                sport=rec.get("sport") or "",
                pick_type=rec.get("pick_type") or "",
                side=rec.get("side") or "",
                prop=prop,
                cover=rec.get("cover"),
                d_ok=bool((rec.get("checks") or {}).get("D") is True),
            )
        )
        rec["team"] = team
        if (
            rec.get("sport") == "CFB"
            and rec.get("side") == "OVER"
            and str(team).upper() in BLOWOUT_SIT_TEAMS
            and "kick" not in prop.lower()
            and "fg" not in prop.lower()
            and "pat" not in prop.lower()
        ):
            extra = "2H sit risk"
            rec["matchup_note"] = (
                f"{rec['matchup_note']} {extra}".strip() if rec.get("matchup_note") else extra
            )
        out.append(rec)
    return out


recs = recs  # diamond_2x_tickets import alias


def _clears_list_gate(r: dict) -> bool:
    """L5 >= 4 for in-season sports. NFLP uses playing-time + D instead of 2025 L5."""
    pt = r.get("pick_type")
    side = r.get("side") or ""
    if pt == "Demon":
        return False
    if str(r.get("sport") or "").upper() == "NFL" and is_nflp(r.get("league")):
        d_ok = bool((r.get("checks") or {}).get("D") is True)
        return nflp_list_eligible(
            policy=str(r.get("starter_policy") or ""),
            side=side,
            pick_type=pt or "Standard",
            d_ok=d_ok,
            l5_over=r.get("l5_over"),
            l5_under=r.get("l5_under"),
        )
    if pt == "Standard" and side == "OVER":
        return (r.get("l5_over") or 0) >= 4
    if pt == "Standard" and side == "UNDER":
        return (r.get("l5_under") or 0) >= 4
    if pt == "Goblin" and side == "OVER":
        return (r.get("l5_over") or 0) >= 4
    return False


def bucket(rows: list[dict], sport: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Hard list gate = directional L5 >= 4 (NFLP: playing-time + D). D miss is badge-only except NFLP skill overs."""
    std_o, std_u, gob = [], [], []
    for r in rows:
        if r["sport"] != sport:
            continue
        if not _clears_list_gate(r):
            continue
        if r["pick_type"] == "Standard" and r["side"] == "OVER":
            std_o.append(r)
        elif r["pick_type"] == "Standard" and r["side"] == "UNDER":
            std_u.append(r)
        elif r["pick_type"] == "Goblin" and r["side"] == "OVER":
            gob.append(r)

    def dedup(lst, over: bool):
        seen = set()
        out = []
        lst = sorted(lst, key=lambda x: sort_key_tier_then_badge(x, over=over))
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
    badge = (r.get("promo") or r.get("badge") or "—")
    tier = r.get("prop_tier") or "—"
    if r.get("prop_shadow"):
        tag = f"W/{badge}"
    elif r.get("prop_promoted"):
        tag = f"{tier}/{badge}*"
    else:
        tag = f"{tier}/{badge}"
    miss = r.get("miss_s") or ""
    miss_s = f"  miss {miss}" if miss else ""
    note = str(r.get("matchup_note") or "").strip()
    note_s = f"  TIGHT {note}" if note else ""
    pol = str(r.get("starter_policy") or "").strip()
    snaps = str(r.get("expected_snaps") or "").strip()
    pol_s = ""
    if pol and pol not in ("normal", ""):
        pol_s = f"  {pol} {snaps}".rstrip()
    return (
        f"  {tag:12} {r['player']:24} {r['prop']:18} {prefix}{line}  "
        f"L5 {l5}  avg {avg_s}  cov {cov_s}  {d_s:12}{miss_s}{note_s}{pol_s}  {r.get('matchup') or ''}"
    )


def _row_for_xlsx(r: dict, category: str) -> dict:
    side = r.get("side") or "OVER"
    prefix = "O" if side == "OVER" else "U"
    line = r.get("line")
    return {
        "Sport": r.get("sport") or "",
        "Prop_tier": r.get("prop_tier") or "",
        "Prop_tier_base": r.get("prop_tier_base") or "",
        "Shadow": bool(r.get("prop_shadow")),
        "Promoted": bool(r.get("prop_promoted")),
        "Promote_reason": r.get("prop_promote_reason") or "",
        "Badge": r.get("badge") or "",
        "Promo": r.get("promo") or r.get("badge") or "",
        "L10": r.get("l10"),
        "Season_HR": None if r.get("season_hr") is None else round(100 * r["season_hr"], 1),
        "Season_N": r.get("season_n") or 0,
        "Category": category,
        "Pick": r.get("pick_type") or "",
        "Player": r.get("player") or "",
        "Prop": r.get("prop") or "",
        "Side": side,
        "Line": f"{prefix}{line}",
        "Line_num": line,
        "L5_over": r.get("l5_over"),
        "L5_under": r.get("l5_under"),
        "Avg": r.get("season_avg"),
        "Cover": r.get("cover"),
        "D": r.get("def") or "",
        "D_rank": r.get("def_rank"),
        "Misses": r.get("miss_s") or "",
        "Matchup": r.get("matchup") or "",
        "Note": r.get("matchup_note") or "",
        "League": r.get("league") or "",
        "Starter_policy": r.get("starter_policy") or "",
        "Expected_snaps": r.get("expected_snaps") or "",
    }


def sport_rows_for_xlsx(sport: str, std_o, std_u, gob) -> list[dict]:
    rows: list[dict] = []
    for r in std_o:
        rows.append(_row_for_xlsx(r, "Standard OVER"))
    for r in std_u:
        rows.append(_row_for_xlsx(r, "Standard UNDER"))
    for r in gob:
        if "earned run" in str(r.get("prop") or "").lower() and float(r.get("line") or 99) <= 0.5:
            continue
        rows.append(_row_for_xlsx(r, "Goblin OVER"))
    return rows


def write_best_props_xlsx(path: Path, by_sport: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    play = []
    all_rows = []
    for sport, rows in by_sport.items():
        all_rows.extend(rows)
        play.extend(
            [
                r
                for r in rows
                if r.get("Promo") in ("Diamond", "Platinum")
                or r.get("Badge") in ("Gold", "Silver")
            ]
        )
    from prop_hit_tiers import TIER_RANK, PROMO_RANK

    def sort_key(r):
        return (
            TIER_RANK.get(r.get("Prop_tier") or "", 9),
            PROMO_RANK.get(r.get("Promo") or r.get("Badge") or "", 9),
            str(r.get("Sport") or ""),
            str(r.get("Category") or ""),
            -float(r.get("Cover") or 0),
            str(r.get("Player") or ""),
        )

    play_df = pd.DataFrame(sorted(play, key=sort_key))
    all_df = pd.DataFrame(sorted(all_rows, key=sort_key))
    sa_rows = [
        r
        for r in all_rows
        if (r.get("Prop_tier") or "") in ("S", "A")
    ]
    sa_df = pd.DataFrame(sorted(sa_rows, key=sort_key))
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        (sa_df if not sa_df.empty else pd.DataFrame({"note": ["none"]})).to_excel(
            xl, sheet_name="S+A hot", index=False
        )
        (play_df if not play_df.empty else pd.DataFrame({"note": ["none"]})).to_excel(
            xl, sheet_name="Play list (Gold+Silver)", index=False
        )
        (all_df if not all_df.empty else pd.DataFrame({"note": ["none"]})).to_excel(
            xl, sheet_name="All L5 4+", index=False
        )
        for sport, rows in by_sport.items():
            sdf = pd.DataFrame(sorted(rows, key=sort_key))
            if sdf.empty:
                sdf = pd.DataFrame({"note": [f"{sport}: none that clear L5 4+"]})
            xl_name = sport[:31]
            sdf.to_excel(xl, sheet_name=xl_name, index=False)


def print_sport(sport: str, std_o, std_u, gob, n_o=8, n_u=8, n_g=12) -> None:
    listed = std_o + std_u + gob
    n_dia = sum(1 for r in listed if r.get("promo") == "Diamond")
    n_plat = sum(1 for r in listed if r.get("promo") == "Platinum")
    n_gold = sum(1 for r in listed if r.get("badge") == "Gold")
    n_sil = sum(1 for r in listed if r.get("badge") == "Silver")
    n_brz = sum(1 for r in listed if r.get("badge") == "Bronze")
    n_tier = {t: sum(1 for r in listed if r.get("prop_tier") == t) for t in "SABCDW"}
    print(
        f"\n===== {sport} =====  "
        f"S {n_tier['S']}  A {n_tier['A']}  B {n_tier['B']}  "
        f"C {n_tier['C']}  D {n_tier['D']}  W {n_tier['W']}  |  "
        f"Diamond {n_dia}  Platinum {n_plat}  "
        f"Gold {n_gold}  Silver {n_sil}  Bronze {n_brz}"
    )
    print(f"Standard OVER  (n={len(std_o)})")
    if not std_o:
        print("  (none that clear L5 4+ / NFLP playing-time gate)" if sport == "NFL" else "  (none that clear L5 4+)")
    for r in std_o[:n_o]:
        print(_fmt(r, "OVER"))
    print(f"Standard UNDER (n={len(std_u)})")
    if not std_u:
        print("  (none that clear L5 4+ / NFLP playing-time gate)" if sport == "NFL" else "  (none that clear L5 4+)")
    for r in std_u[:n_u]:
        print(_fmt(r, "UNDER"))
    print(f"Goblin OVER    (n={len(gob)})")
    if not gob:
        print("  (none that clear L5 4+ / NFLP playing-time gate)" if sport == "NFL" else "  (none that clear L5 4+)")

    def _skip_er(r):
        return "earned run" in str(r.get("prop") or "").lower() and float(r.get("line") or 99) <= 0.5

    vis = [r for r in gob if not _skip_er(r)]
    hot = [r for r in vis if r.get("prop_tier") in ("S", "A")]
    other = [r for r in vis if r.get("prop_tier") not in ("S", "A")]
    for r in hot + other[:n_g]:
        print(_fmt(r, "OVER"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="Slate date YYYY-MM-DD")
    ap.add_argument(
        "--step8-root",
        default="",
        help="Repo with outputs/<date>/*/step8 (default: this repo, then PropORACLE_main_cp)",
    )
    ap.add_argument(
        "--xlsx",
        default="",
        help="Write Gold/Silver/Bronze lists to this .xlsx (default: outputs/<date>/best_props_<date>.xlsx)",
    )
    args = ap.parse_args()
    date = str(args.date).strip()[:10]
    if args.step8_root:
        root = Path(args.step8_root)
        if not root.is_dir():
            print(f"--step8-root not a directory: {root}")
            return 1
    else:
        candidates = [_REPO]
        main_cp = _REPO.parent / "PropORACLE_main_cp"
        if main_cp.is_dir():
            candidates.append(main_cp)
        root = _choose_step8_root(candidates, date)
    if root is None:
        print("No step8 CSVs found for", date)
        return 1
    same_day, latest = _root_board_freshness(root, date)
    print(
        f"Best props {date}  step8={root}  "
        f"same-day step1={same_day}/{len(_STEP1_FILES)}  newest_fetch={latest:%Y-%m-%d %H:%M}"
    )
    if same_day == 0:
        print(
            "  WARN: no step1 board was fetched on this slate date in the chosen root "
            "(likely a day-prior board). Re-run after 8AM refresh on PropORACLE_main_cp."
        )
    all_rows: list[dict] = []
    by_sport: dict[str, list[dict]] = {}
    for sport, folder, fname in SPORTS:
        df = load_sport(root, date, sport, folder, fname)
        if df.empty:
            print(f"\n===== {sport} =====\n  (no step8 file)")
            by_sport[sport] = []
            continue
        all_rows.extend(recs(df))
        so, su, gob = bucket(all_rows, sport)
        print_sport(sport, so, su, gob)
        by_sport[sport] = sport_rows_for_xlsx(sport, so, su, gob)
    df_nfl = load_nfl(root, date)
    if df_nfl.empty:
        print("\n===== NFL =====\n  (no step8 file)")
        by_sport["NFL"] = []
    else:
        all_rows.extend(recs(df_nfl))
        so, su, gob = bucket(all_rows, "NFL")
        print_sport("NFL", so, su, gob)
        by_sport["NFL"] = sport_rows_for_xlsx("NFL", so, su, gob)
    df_cfb = load_cfb(root, date)
    if df_cfb.empty:
        print("\n===== CFB =====\n  (no step8 file)")
        by_sport["CFB"] = []
    else:
        all_rows.extend(recs(df_cfb))
        so, su, gob = bucket(all_rows, "CFB")
        print_sport("CFB", so, su, gob, n_o=20, n_u=20, n_g=20)
        by_sport["CFB"] = sport_rows_for_xlsx("CFB", so, su, gob)
    for sport, loader in (("CBB", load_cbb), ("WCBB", load_wcbb)):
        df_x = loader(root, date)
        if df_x.empty:
            if _cbb_season_active(date):
                print(f"\n===== {sport} =====\n  (no step8 file)")
                by_sport[sport] = []
            continue
        all_rows.extend(recs(df_x))
        so, su, gob = bucket(all_rows, sport)
        print_sport(sport, so, su, gob)
        by_sport[sport] = sport_rows_for_xlsx(sport, so, su, gob)
    xlsx_path = Path(str(args.xlsx).strip()) if str(args.xlsx or "").strip() else (
        root / "outputs" / date / f"best_props_{date}.xlsx"
    )
    if not xlsx_path.is_absolute():
        xlsx_path = (root / xlsx_path).resolve()
    write_best_props_xlsx(xlsx_path, by_sport)
    print(f"\nExcel -> {xlsx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
