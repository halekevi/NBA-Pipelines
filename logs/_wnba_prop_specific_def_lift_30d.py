"""Prop-specific opponent defense ranks (WNBA) vs 30d graded hit rates.

Builds opp-allowed ranks from box-score game logs in proporacle_ref.db:
  for each game, team A totals = what team B allowed.
Ranks: 1 = stingiest (lowest allowed) = HARD for OVER.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "cache" / "proporacle_ref.db"
START = date(2026, 7, 11)
END = date(2026, 8, 9)
OUT = ROOT / "data" / "reports" / "wnba_prop_specific_def_lift_30d.json"
DEF_OUT = ROOT / "Sports" / "WNBA" / "data" / "wnba_defense_by_stat.csv"

# graded/slate abbr -> DB team abbr
TEAM_MAP = {
    "ATL": "ATL",
    "CHI": "CHI",
    "CON": "CON",
    "CONN": "CON",
    "DAL": "DAL",
    "GS": "GS",
    "GSV": "GS",
    "IND": "IND",
    "LA": "LA",
    "LAS": "LA",
    "LV": "LV",
    "LVA": "LV",
    "MIN": "MIN",
    "NY": "NY",
    "NYL": "NY",
    "PHX": "PHX",
    "PHO": "PHX",
    "POR": "POR",
    "SEA": "SEA",
    "TOR": "TOR",
    "WSH": "WSH",
    "WAS": "WSH",
}

# prop label -> defense category
PROP_TO_CAT = {
    "Points": "pts",
    "Points (Combo)": "pts",
    "Rebounds": "reb",
    "Rebounds (Combo)": "reb",
    "Assists": "ast",
    "Assists (Combo)": "ast",
    "3-PT Made": "fg3m",
    "3-PT Made (Combo)": "fg3m",
    "3-PT Attempted": "fg3a",
    "Steals": "stl",
    "Blocked Shots": "blk",
    "Blks+Stls": "bs",
    "Pts+Rebs+Asts": "pra",
    "Pts+Rebs": "pr",
    "Pts+Asts": "pa",
    "Rebs+Asts": "ra",
    "FG Made": "fgm",
    "FG Attempted": "fga",
    "Two Pointers Made": "fg2m",
    "Two Pointers Attempted": "fg2a",
    "Free Throws Made": "ftm",
    "Free Throws Attempted": "fta",
    "Turnovers": "tov",
    "Defensive Rebounds": "dreb",
    "Offensive Rebounds": "oreb",
}

STAT_COLS = [
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "fg2m",
    "fg2a",
    "ftm",
    "fta",
]


def fnum(x, default=None):
    try:
        if x is None or x == "":
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def canon_team(raw: object) -> str:
    s = str(raw or "").strip().upper()
    if not s or "/" in s:
        return ""
    return TEAM_MAP.get(s, s)


def norm_dir(x: dict) -> str:
    for k in ("direction", "dir", "over_under", "ou"):
        v = str(x.get(k) or "").upper().strip()
        if v.startswith("O"):
            return "OVER"
        if v.startswith("U"):
            return "UNDER"
    return ""


def norm_pick(x: dict) -> str:
    v = str(x.get("pick_type") or x.get("pick") or "").upper().strip()
    if "GOB" in v:
        return "GOBLIN"
    if "DEM" in v:
        return "DEMON"
    if "STD" in v or "STAND" in v or v == "STANDARD":
        return "STANDARD"
    return v or "OTHER"


def res_hit(x: dict):
    if "hit" in x and x["hit"] is not None:
        h = x["hit"]
        if h is True or h == 1 or str(h).lower() in ("true", "hit", "win"):
            return 1
        if h is False or h == 0 or str(h).lower() in ("false", "miss", "loss"):
            return 0
    r = str(x.get("result") or x.get("grade") or "").upper().strip()
    if r in ("HIT", "WIN", "W"):
        return 1
    if r in ("MISS", "LOSS", "L"):
        return 0
    return None


def side_l5_l10(x: dict, direction: str):
    if direction == "OVER":
        l5, l10 = fnum(x.get("l5_over")), fnum(x.get("l10_over"))
    else:
        l5, l10 = fnum(x.get("l5_under")), fnum(x.get("l10_under"))
    sample = fnum(x.get("l10_games_played"), 10.0) or 10.0
    return l5, l10, sample


def live_ok(pick: str, direction: str, l5, l10, sample) -> bool:
    if pick == "GOBLIN" and direction == "OVER":
        return l5 is not None and l5 >= 4 and l10 is not None and sample >= 8 and l10 >= 8
    if pick == "STANDARD" and direction == "OVER":
        return l5 is not None and l5 >= 3 and l10 is not None and sample >= 8 and l10 >= 8
    if pick == "STANDARD" and direction == "UNDER":
        return l10 is not None and sample >= 8 and l10 >= 8
    return False


def bucket_from_rank(rank: float | None, n_teams: int) -> str:
    if rank is None or n_teams <= 0:
        return "UNK"
    # quintiles: 1 = HARD (stingy), high = EASY (soft)
    q = max(n_teams / 5.0, 1.0)
    if rank <= q:
        return "HARD"
    if rank <= 2 * q:
        return "HARD_MID"  # above avg
    if rank <= 3 * q:
        return "MID"
    if rank <= 4 * q:
        return "EASY_MID"
    return "EASY"


def coarse_bucket(b: str) -> str:
    if b in ("HARD", "HARD_MID"):
        return "HARD"
    if b in ("EASY", "EASY_MID"):
        return "EASY"
    if b == "MID":
        return "MID"
    return "UNK"


class Acc:
    __slots__ = ("h", "n")

    def __init__(self):
        self.h = 0
        self.n = 0

    def add(self, hit: int):
        self.h += int(hit)
        self.n += 1

    def d(self):
        return {
            "hr": round(100.0 * self.h / self.n, 1) if self.n else None,
            "hits": self.h,
            "n": self.n,
        }


def build_defense_by_stat() -> pd.DataFrame:
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        """
        SELECT event_id, game_date, team, pts, reb, ast, stl, blk, tov,
               fgm, fga, fg3m, fg3a, fg2m, fg2a, ftm, fta, oreb, dreb
        FROM wnba
        WHERE team IS NOT NULL AND team != ''
          AND event_id IS NOT NULL
        """,
        con,
    )
    con.close()
    # drop junk / exhibition labels if any
    bad = {"COOP", "SPO"}
    df = df[~df["team"].astype(str).str.upper().isin(bad)].copy()
    for c in STAT_COLS + ["oreb", "dreb"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # team game totals
    gcols = ["event_id", "game_date", "team"] + [
        c for c in STAT_COLS + ["oreb", "dreb"] if c in df.columns
    ]
    team_game = df[gcols].groupby(["event_id", "game_date", "team"], as_index=False).sum(numeric_only=True)

    # derived combos
    team_game["pra"] = team_game["pts"] + team_game["reb"] + team_game["ast"]
    team_game["pr"] = team_game["pts"] + team_game["reb"]
    team_game["pa"] = team_game["pts"] + team_game["ast"]
    team_game["ra"] = team_game["reb"] + team_game["ast"]
    team_game["bs"] = team_game["stl"] + team_game["blk"]

    # for each event, map team -> opponent totals (what this defense allowed)
    allowed_rows = []
    for eid, grp in team_game.groupby("event_id"):
        teams = grp["team"].tolist()
        if len(teams) != 2:
            continue
        a, b = teams[0], teams[1]
        ra = grp[grp["team"] == a].iloc[0]
        rb = grp[grp["team"] == b].iloc[0]
        # defense A allowed = offense B
        row_a = {"team": a, "game_date": ra["game_date"]}
        row_b = {"team": b, "game_date": rb["game_date"]}
        for c in [
            "pts",
            "reb",
            "ast",
            "stl",
            "blk",
            "tov",
            "fgm",
            "fga",
            "fg3m",
            "fg3a",
            "fg2m",
            "fg2a",
            "ftm",
            "fta",
            "oreb",
            "dreb",
            "pra",
            "pr",
            "pa",
            "ra",
            "bs",
        ]:
            row_a[f"opp_{c}"] = float(rb[c])
            row_b[f"opp_{c}"] = float(ra[c])
        allowed_rows.extend([row_a, row_b])

    allowed = pd.DataFrame(allowed_rows)
    # season averages per defense team
    metrics = [c for c in allowed.columns if c.startswith("opp_")]
    summary = allowed.groupby("team", as_index=False).agg(
        **{m: (m, "mean") for m in metrics},
        games=("game_date", "nunique"),
    )
    n_teams = len(summary)
    # rank: lower allowed = better defense = rank 1
    for m in metrics:
        cat = m.replace("opp_", "")
        summary[f"{cat}_rank"] = summary[m].rank(method="min", ascending=True).astype(int)
        summary[f"{cat}_tier"] = summary[f"{cat}_rank"].apply(
            lambda r: bucket_from_rank(float(r), n_teams)
        )

    # also keep overall pts rank as baseline
    summary["overall_rank"] = summary["pts_rank"]
    summary["n_teams"] = n_teams
    DEF_OUT.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(DEF_OUT, index=False)
    return summary


def load_slate_l5(day: date):
    s = day.isoformat()
    for p in (
        ROOT / f"outputs/{s}/canonical/platform_ui/slate_latest.json",
        ROOT / f"outputs/{s}/canonical/mobile_app/slate_latest.json",
    ):
        if not p.exists() or p.stat().st_size < 50:
            continue
        try:
            slate = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        idx = {}
        for r in slate.get("sports", {}).get("wnba") or []:
            player = " ".join(
                re.sub(r"[^A-Z0-9 ]+", " ", str(r.get("player") or "").upper()).split()
            )
            prop = " ".join(
                re.sub(
                    r"[^A-Z0-9 ]+",
                    " ",
                    str(r.get("prop") or r.get("prop_type") or "").upper(),
                ).split()
            )
            line = fnum(r.get("line"))
            direction = norm_dir(r)
            if not player or not prop or line is None or not direction:
                continue
            idx[(player, prop, round(line, 2), direction)] = {
                "l5_over": fnum(r.get("l5_over")),
                "l5_under": fnum(r.get("l5_under")),
                "l10_over": fnum(r.get("l10_over")),
                "l10_under": fnum(r.get("l10_under")),
                "l10_games_played": fnum(r.get("l10_games_played")),
            }
        return idx
    return {}


def main():
    print("Building prop-specific defense ranks from game logs...")
    defense = build_defense_by_stat()
    print(f"  teams={len(defense)} wrote {DEF_OUT}")
    print(defense[["team", "games", "opp_pts", "pts_rank", "opp_reb", "reb_rank", "opp_ast", "ast_rank"]].to_string(index=False))

    def_by_team = {str(r.team).upper(): r for r in defense.itertuples()}
    n_teams = int(defense["n_teams"].iloc[0]) if len(defense) else 15

    bags = defaultdict(Acc)
    days_used = []
    unmatched_opp = 0
    matched = 0

    d = START
    while d <= END:
        gp = ROOT / f"ui_runner/templates/graded_props_{d.isoformat()}.json"
        if not gp.exists():
            d += timedelta(days=1)
            continue
        days_used.append(d.isoformat())
        props = json.loads(gp.read_text(encoding="utf-8")).get("props") or []
        sidx = load_slate_l5(d)

        for x in props:
            if str(x.get("sport") or "").upper() != "WNBA":
                continue
            hit = res_hit(x)
            if hit is None:
                continue
            pick = norm_pick(x)
            if pick not in ("GOBLIN", "STANDARD"):
                continue
            direction = norm_dir(x)
            if direction not in ("OVER", "UNDER"):
                continue
            prop = str(x.get("prop") or x.get("prop_type") or "").strip()
            cat = PROP_TO_CAT.get(prop)
            if not cat:
                continue
            opp = canon_team(x.get("opp_team") or x.get("opp"))
            if not opp or opp not in def_by_team:
                unmatched_opp += 1
                continue
            matched += 1
            row = def_by_team[opp]
            rank = getattr(row, f"{cat}_rank", None)
            if rank is None:
                continue
            b = coarse_bucket(bucket_from_rank(float(rank), n_teams))
            overall_rank = getattr(row, "overall_rank", None)
            ob = coarse_bucket(bucket_from_rank(float(overall_rank), n_teams)) if overall_rank else "UNK"

            # fill L5 from slate if needed
            player = " ".join(
                re.sub(r"[^A-Z0-9 ]+", " ", str(x.get("player") or "").upper()).split()
            )
            prop_n = " ".join(re.sub(r"[^A-Z0-9 ]+", " ", prop.upper()).split())
            line = fnum(x.get("line"))
            key = (player, prop_n, round(line, 2) if line is not None else None, direction)
            if key[2] is not None and key in sidx:
                sr = sidx[key]
                for fk in ("l5_over", "l5_under", "l10_over", "l10_under", "l10_games_played"):
                    if x.get(fk) in (None, "") and sr.get(fk) is not None:
                        x[fk] = sr.get(fk)
            l5, l10, sample = side_l5_l10(x, direction)
            is_live = live_ok(pick, direction, l5, l10, sample)

            bags[f"{prop}|{pick}|{direction}|STAT|{b}"].add(hit)
            bags[f"{prop}|{pick}|{direction}|STAT|ANY"].add(hit)
            bags[f"{prop}|{pick}|{direction}|OVERALL|{ob}"].add(hit)
            bags[f"{prop}|{pick}|{direction}|OVERALL|ANY"].add(hit)
            bags[f"ALL|{pick}|{direction}|STAT|{b}"].add(hit)
            bags[f"ALL|{pick}|{direction}|STAT|ANY"].add(hit)
            bags[f"ALL|{pick}|{direction}|OVERALL|{ob}"].add(hit)
            if is_live:
                bags[f"{prop}|{pick}|{direction}|LIVE|STAT|{b}"].add(hit)
                bags[f"{prop}|{pick}|{direction}|LIVE|STAT|ANY"].add(hit)
                bags[f"{prop}|{pick}|{direction}|LIVE|OVERALL|{ob}"].add(hit)
                bags[f"ALL|{pick}|{direction}|LIVE|STAT|{b}"].add(hit)
                bags[f"ALL|{pick}|{direction}|LIVE|STAT|ANY"].add(hit)

        d += timedelta(days=1)

    def cell(key):
        a = bags.get(key)
        return a.d() if a and a.n else {"hr": None, "hits": 0, "n": 0}

    # Build contrasts: STAT HARD vs EASY and vs OVERALL
    contrasts = []
    props_seen = sorted({k.split("|")[0] for k in bags if not k.startswith("ALL|")})
    for prop in props_seen + ["ALL"]:
        for pick, direction in (("GOBLIN", "OVER"), ("STANDARD", "OVER"), ("STANDARD", "UNDER")):
            for live in ("", "LIVE|"):
                prefix = f"{prop}|{pick}|{direction}|{live}"
                any_ = cell(f"{prefix}STAT|ANY")
                hard = cell(f"{prefix}STAT|HARD")
                easy = cell(f"{prefix}STAT|EASY")
                mid = cell(f"{prefix}STAT|MID")
                oh = cell(f"{prefix}OVERALL|HARD")
                oe = cell(f"{prefix}OVERALL|EASY")
                if any_["n"] < 25 and hard["n"] + easy["n"] < 30:
                    continue
                if direction == "OVER" and hard["hr"] is not None and easy["hr"] is not None:
                    delta = round(easy["hr"] - hard["hr"], 1)
                elif direction == "UNDER" and hard["hr"] is not None and easy["hr"] is not None:
                    delta = round(hard["hr"] - easy["hr"], 1)
                else:
                    delta = None
                if direction == "OVER" and oh["hr"] is not None and oe["hr"] is not None:
                    odelta = round(oe["hr"] - oh["hr"], 1)
                elif direction == "UNDER" and oh["hr"] is not None and oe["hr"] is not None:
                    odelta = round(oh["hr"] - oe["hr"], 1)
                else:
                    odelta = None
                contrasts.append(
                    {
                        "prop": prop,
                        "pick": pick,
                        "direction": direction,
                        "live": bool(live),
                        "any": any_,
                        "stat_hard": hard,
                        "stat_mid": mid,
                        "stat_easy": easy,
                        "stat_aligned_delta": delta,
                        "overall_hard": oh,
                        "overall_easy": oe,
                        "overall_aligned_delta": odelta,
                        "stat_minus_overall_delta": (
                            round(delta - odelta, 1)
                            if delta is not None and odelta is not None
                            else None
                        ),
                    }
                )

    # leaders where stat-specific beats overall or shows real lift
    leaders = sorted(
        [
            c
            for c in contrasts
            if c["stat_aligned_delta"] is not None
            and c["stat_hard"]["n"] >= 25
            and c["stat_easy"]["n"] >= 25
        ],
        key=lambda c: -(c["stat_aligned_delta"] or -999),
    )

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": START.isoformat(), "end": END.isoformat()},
        "method": {
            "source": str(DB),
            "defense_file": str(DEF_OUT),
            "rank_rule": "1=lowest opp-allowed (stingiest) for that stat",
            "HARD": "top two quintiles (best D vs that stat)",
            "EASY": "bottom two quintiles (softest D vs that stat)",
            "aligned_delta_OVER": "EASY HR - HARD HR",
            "aligned_delta_UNDER": "HARD HR - EASY HR",
            "note": "Basketball-Reference blocked (403); used ESPN box logs in local DB",
        },
        "coverage": {
            "days": days_used,
            "n_days": len(days_used),
            "matched_props": matched,
            "unmatched_opp": unmatched_opp,
            "n_teams": n_teams,
        },
        "defense_snapshot": defense[
            ["team", "games", "opp_pts", "pts_rank", "opp_reb", "reb_rank", "opp_ast", "ast_rank", "opp_fg3m", "fg3m_rank"]
        ].to_dict(orient="records"),
        "contrasts": contrasts,
        "top_stat_aligned": leaders[:25],
        "worst_stat_aligned": list(reversed(leaders[-10:])) if leaders else [],
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\nwrote", OUT)
    print("matched", matched, "unmatched_opp", unmatched_opp)
    print("\nTOP STAT-SPECIFIC ALIGNED DELTAS (n>=25 both sides)")
    for c in leaders[:20]:
        live = "LIVE" if c["live"] else "ALL"
        print(
            f"{c['prop'][:22]:22} {c['pick'][:3]:3} {c['direction']:5} {live:4} "
            f"STAT H={c['stat_hard']['hr']}%/{c['stat_hard']['n']} "
            f"E={c['stat_easy']['hr']}%/{c['stat_easy']['n']} Δ={c['stat_aligned_delta']} "
            f"| OVERALL Δ={c['overall_aligned_delta']}"
        )


if __name__ == "__main__":
    main()
