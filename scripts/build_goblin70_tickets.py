#!/usr/bin/env python3
"""Build Goblin-70 tickets and publish the playable card to /tickets.

Main card (app): all-Goblin OVER, L5 >= 4, sport cover floor, no shadow,
no Demons, no Standard legs. Power OK. D is a badge, not a filter.

Standard allowlist stays in the report JSON only (tracker / Flex fill).
N-correct / To Win only. Never 1st-place multipliers.

  py -3.14 scripts/build_goblin70_tickets.py
  py -3.14 scripts/build_goblin70_tickets.py --date 2026-08-26
  py -3.14 scripts/build_goblin70_tickets.py --date 2026-08-26 --no-write-web
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import rank_best_props_today as R  # noqa: E402
from utils.n_correct_payout import PAY_FALLBACK as PAY, resolve_n_correct  # noqa: E402
from utils.ticket_70_pool import (  # noqa: E402
    directional_l5,
    goblin_70_eligible,
    goblin_sort_key,
    goblin_ticket_p,
    is_pitcher_prop,
    nflp_std_over_eligible,
    nflp_ticket_eligible,
    nflp_ticket_p,
    standard_flex_kind,
    standard_sort_key,
    standard_ticket_p,
)

OUT_DIR = _REPO / "data" / "reports"
ET = ZoneInfo("America/New_York")


def fold_name(s: object) -> str:
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.casefold()
    t = re.sub(r"\b(jr|sr|iii|ii|iv)\b\.?", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def tennis_match_key(mu: object) -> str:
    s = str(mu or "").split("(")[0]
    parts = re.split(r"\s+vs\.?\s+", s, flags=re.I)
    if len(parts) == 2:
        a, b = fold_name(parts[0]), fold_name(parts[1])
        if a and b:
            return " | ".join(sorted((a, b)))
    return fold_name(s)


def load_today_board(date: str) -> list[dict]:
    candidates = [_REPO]
    sibling = _REPO.parent / "PropORACLE_main_cp"
    if sibling.is_dir() and sibling.resolve() != _REPO.resolve():
        candidates.append(sibling)
    choose = getattr(R, "_choose_step8_root", None)
    root = choose(candidates, date) if callable(choose) else None
    if root is None:
        for cand in candidates:
            out = cand / "outputs" / date
            if (out / "wnba").is_dir() or (out / "mlb").is_dir():
                root = cand
                break
    if root is None:
        return []
    rows: list[dict] = []
    for sport, folder, fname in R.SPORTS:
        df = R.load_sport(root, date, sport, folder, fname)
        if df.empty:
            continue
        rows.extend(R.recs(df))
    for loader_name in ("load_nfl", "load_cfb"):
        loader = getattr(R, loader_name, None)
        if not callable(loader):
            continue
        extra = loader(root, date)
        if extra is not None and not extra.empty:
            rows.extend(R.recs(extra))
    return rows

# PAY lives in utils.n_correct_payout. Resolve order: slip pin → same-day
# CDP with matching Goblin-Δ → mix_by_delta → this fallback.

SKIP_PLAYERS = frozenset({"jacob fearnley"})

SPORT_PURE = (
    ("WNBA", 3, "Power", 3),
    ("MLB", 3, "Power", 3),
    ("Tennis", 3, "Power", 2),
    ("Soccer", 3, "Power", 2),
)

MAIN_CARD = (
    ("P3-1", 3, "Power", "goblin"),
    ("P3-2", 3, "Power", "goblin"),
    ("P3-3", 3, "Power", "goblin"),
    ("P3-4", 3, "Power", "goblin"),
    ("P3-5", 3, "Power", "goblin"),
    ("F4-1", 4, "Flex", "goblin"),
    ("F4-2", 4, "Flex", "goblin"),
    ("F4-3", 4, "Flex", "goblin"),
    ("F4-4", 4, "Flex", "goblin"),
)

WEB_SPORT = {
    "TENNIS": "Tennis",
    "SOCCER": "Soccer",
    "WNBA": "WNBA",
    "MLB": "MLB",
    "NFL": "NFL",
    "CFB": "CFB",
}

WEB_JSON_PATHS = (
    _REPO / "ui_runner" / "templates" / "tickets_latest.json",
    _REPO / "ui_runner" / "data" / "tickets_latest.json",
    _REPO / "ui_runner" / "docs" / "tickets_latest.json",
    _REPO / "mobile" / "www" / "tickets_latest.json",
)


def unique_by_player(rows: list[dict], key_fn) -> list[dict]:
    ordered = sorted(rows, key=key_fn)
    seen: set[str] = set()
    out: list[dict] = []
    for r in ordered:
        pn = fold_name(r.get("player"))
        if not pn or pn in seen:
            continue
        seen.add(pn)
        out.append(r)
    return out


def matchup_key(r: dict) -> str:
    mu = str(r.get("matchup") or "").strip()
    sport = str(r.get("sport") or "").upper()
    if sport in {"WNBA", "MLB"}:
        parts = re.split(r"\s+vs\.?\s+", mu, flags=re.I)
        if len(parts) == 2:
            return " | ".join(sorted(p.strip().upper() for p in parts))
    return mu


def mlb_conflict(a: dict, b: dict) -> bool:
    if a.get("sport") != "MLB" or b.get("sport") != "MLB":
        return False
    if matchup_key(a) != matchup_key(b) or not matchup_key(a):
        return False
    return is_pitcher_prop(a) != is_pitcher_prop(b)


def can_add(combo: list[dict], r: dict, *, wnba_cap: int) -> bool:
    pn = fold_name(r.get("player"))
    if any(fold_name(x.get("player")) == pn for x in combo):
        return False
    sport = str(r.get("sport") or "")
    mu = matchup_key(r)
    if sport == "WNBA" and mu:
        same = sum(1 for x in combo if x.get("sport") == "WNBA" and matchup_key(x) == mu)
        if same >= wnba_cap:
            return False
    if sport == "NFL" and mu:
        same = sum(1 for x in combo if x.get("sport") == "NFL" and matchup_key(x) == mu)
        if same >= 2:
            return False
    if sport == "TENNIS":
        tk = tennis_match_key(mu)
        if tk and any(
            x.get("sport") == "TENNIS" and tennis_match_key(matchup_key(x)) == tk
            for x in combo
        ):
            return False
    if any(mlb_conflict(r, x) for x in combo):
        return False
    return True


def pack(
    pool: list[dict],
    n: int,
    taken: set[str],
    *,
    mix_sports: bool = True,
    wnba_cap: int = 1,
) -> list[dict]:
    combo: list[dict] = []
    sports: set[str] = set()

    def add_from(prefer_new_sport: bool) -> None:
        nonlocal combo, sports
        for r in pool:
            if len(combo) == n:
                return
            pn = fold_name(r.get("player"))
            if pn in taken:
                continue
            if not can_add(combo, r, wnba_cap=wnba_cap):
                continue
            if prefer_new_sport and r.get("sport") in sports:
                continue
            combo.append(r)
            sports.add(str(r.get("sport") or ""))

    if mix_sports:
        add_from(True)
    add_from(False)
    return combo if len(combo) == n else []


def binomial(n: int, k: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) * (p**k) * ((1 - p) ** (n - k))


def ticket_math(legs: list[dict], product: str, family: str, *, date: str = "") -> dict:
    n = len(legs)
    pay = resolve_n_correct(legs, product, family, date=date)
    table = pay["n_correct"]
    ps = [float(x["p"]) for x in legs]
    p = sum(ps) / n
    ev = sum(binomial(n, k, p) * m for k, m in table.items())
    cash = sum(binomial(n, k, p) for k, m in table.items() if m > 0)
    return {
        "mean_leg_p": round(p, 4),
        "sweep_pct": round(100 * binomial(n, n, p), 1),
        "cash_pct": round(100 * cash, 1),
        "ev_n_correct": round(ev, 3),
        "n_correct": table,
        "payout_note": pay["note"],
        "payout_source": pay.get("payout_source") or "n_correct_median",
    }


def compact(r: dict, *, std: bool = False) -> dict:
    l5 = r.get("l5_over") if str(r.get("side")) == "OVER" else r.get("l5_under")
    out = {
        "sport": r.get("sport"),
        "player": r.get("player"),
        "prop": r.get("prop"),
        "side": r.get("side"),
        "line": r.get("line"),
        "pick_type": r.get("pick_type"),
        "l5": l5,
        "cover": r.get("cover"),
        "d": r.get("def"),
        "badge": r.get("promo") or r.get("badge"),
        "tier": r.get("prop_tier"),
        "matchup": r.get("matchup") or "",
        "team": r.get("team") or "",
        "p": r.get("p"),
        "ml_prob": r.get("ml_prob"),
        "hit_rate": r.get("hit_rate"),
        "standard_line": r.get("standard_line"),
        "line_underdog": r.get("line_underdog"),
        "line_draftkings": r.get("line_draftkings"),
        "best_cross_book": r.get("best_cross_book"),
        "best_cross_line": r.get("best_cross_line"),
        "cross_edge_vs_pp": r.get("cross_edge_vs_pp"),
    }
    if std:
        out["std_kind"] = r.get("std_kind")
    return out


def playable_tickets(payload: dict) -> list[dict]:
    """App card: Goblin-70 plus NFLP week-3 groups. Standard fill stays off."""
    return [
        t
        for t in (payload.get("tickets") or [])
        if t.get("family") in {"goblin", "nflp", "nflp_std"}
    ]


def web_sport(sport: object) -> str:
    raw = str(sport or "").strip()
    return WEB_SPORT.get(raw.upper(), raw)


def split_matchup(matchup: object, player: object, team: object = "") -> tuple[str, str]:
    if str(team or "").strip():
        s = str(matchup or "").split("(")[0].strip()
        parts = re.split(r"\s+vs\.?\s+", s, flags=re.I)
        opp = parts[1].strip() if len(parts) == 2 else ""
        return str(team).strip(), opp
    s = str(matchup or "").split("(")[0].strip()
    parts = re.split(r"\s+vs\.?\s+", s, flags=re.I)
    if len(parts) != 2:
        return str(player or "").strip(), ""
    a, b = parts[0].strip(), parts[1].strip()
    pn = fold_name(player)
    if pn and fold_name(b) == pn:
        return b, a
    if pn and fold_name(a) == pn:
        return a, b
    return a, b


def _sweep_x(ticket: dict) -> float:
    n = int(ticket.get("n_legs") or 0)
    table = ticket.get("n_correct") or {}
    try:
        return float(table.get(n) or table.get(str(n)))
    except (TypeError, ValueError):
        return 0.0


def _leg_to_web(leg: dict, *, ticket_id: str, date: str) -> dict:
    player = str(leg.get("player") or "").strip()
    sport = web_sport(leg.get("sport"))
    team, opp = split_matchup(leg.get("matchup"), player, leg.get("team"))
    line = leg.get("line")
    try:
        line_f = float(line)
        line_key = f"{line_f:.3f}"
    except (TypeError, ValueError):
        line_f = None
        line_key = ""
    side = str(leg.get("side") or "OVER").upper()
    prop = str(leg.get("prop") or "")
    p = float(leg.get("p") or 0.0)
    l5 = leg.get("l5")
    try:
        l5_f = float(l5) if l5 is not None else None
    except (TypeError, ValueError):
        l5_f = None
    cover = leg.get("cover")
    try:
        cover_f = float(cover) if cover is not None else None
    except (TypeError, ValueError):
        cover_f = None
    try:
        hr = float(leg.get("hit_rate")) if leg.get("hit_rate") is not None else None
    except (TypeError, ValueError):
        hr = None
    if hr is None and l5_f is not None:
        hr = l5_f / 5.0
    try:
        ml = float(leg.get("ml_prob")) if leg.get("ml_prob") is not None else None
    except (TypeError, ValueError):
        ml = None
    try:
        std_line = float(leg.get("standard_line")) if leg.get("standard_line") is not None else None
    except (TypeError, ValueError):
        std_line = None
    try:
        ud_line = float(leg.get("line_underdog")) if leg.get("line_underdog") is not None else None
    except (TypeError, ValueError):
        ud_line = None
    try:
        dk_line = float(leg.get("line_draftkings")) if leg.get("line_draftkings") is not None else None
    except (TypeError, ValueError):
        dk_line = None
    best_book = str(leg.get("best_cross_book") or "").strip()
    try:
        best_line = float(leg.get("best_cross_line")) if leg.get("best_cross_line") is not None else None
    except (TypeError, ValueError):
        best_line = None
    try:
        cross_edge = float(leg.get("cross_edge_vs_pp")) if leg.get("cross_edge_vs_pp") is not None else None
    except (TypeError, ValueError):
        cross_edge = None
    if not best_book and line_f is not None:
        best_book = "PP"
        best_line = line_f if best_line is None else best_line
        if cross_edge is None:
            cross_edge = 0.0
    material = "|".join(
        [
            sport.lower(),
            player.lower(),
            team.lower(),
            opp.lower(),
            prop.lower(),
            line_key,
            side.lower(),
            date,
        ]
    )
    return {
        "ticket_id": ticket_id,
        "ticket_track": "goblin70",
        "sport": sport,
        "player": player,
        "team": team,
        "opp": opp,
        "prop_type": prop,
        "pick_type": "Goblin",
        "direction": side,
        "line": line_f,
        "edge": cover_f,
        "abs_edge": None if cover_f is None else abs(cover_f),
        "pick_platform": "prizepicks",
        "hit_rate": hr,
        "ml_prob": ml,
        "standard_line": std_line,
        "line_underdog": ud_line,
        "line_draftkings": dk_line,
        "best_cross_book": best_book,
        "best_cross_line": best_line,
        "cross_edge_vs_pp": cross_edge,
        "tier": str(leg.get("tier") or ""),
        "def_tier": str(leg.get("d") or ""),
        "l5_over": l5_f if side == "OVER" else None,
        "l5_under": l5_f if side == "UNDER" else None,
        "l5_side_hit_rate": None if l5_f is None else l5_f / 5.0,
        "leg_prob_used": p,
        "leg_prob_source": "goblin70_hist",
        "canonical_leg_id": "leg_" + hashlib.sha1(material.encode("utf-8")).hexdigest()[:20],
        "game_date": date,
        "badge": str(leg.get("badge") or ""),
        "cover": cover_f,
        "matchup": str(leg.get("matchup") or ""),
    }


def _ticket_to_web(ticket: dict, *, date: str, ticket_no: int, group_name: str) -> dict:
    sweep = _sweep_x(ticket)
    mean_p = float(ticket.get("mean_leg_p") or 0.0)
    sweep_pct = float(ticket.get("sweep_pct") or 0.0) / 100.0
    cash_pct = float(ticket.get("cash_pct") or 0.0) / 100.0
    ev_mult = float(ticket.get("ev_n_correct") or 0.0)
    ev = round(ev_mult - 1.0, 4)
    n = int(ticket.get("n_legs") or 0)
    product = str(ticket.get("product") or "Power")
    tt = "flex" if product.lower() == "flex" else "power"
    gn = re.sub(r"[|]+", "_", group_name)[:80]
    ticket_id = f"{date}|{gn}|{ticket_no}"
    n_correct = {int(k): float(v) for k, v in (ticket.get("n_correct") or {}).items()}
    legs = [_leg_to_web(leg, ticket_id=ticket_id, date=date) for leg in ticket.get("legs") or []]
    hrs = [float(x["hit_rate"]) for x in legs if x.get("hit_rate") is not None]
    mls = [float(x["ml_prob"]) for x in legs if x.get("ml_prob") is not None]
    avg_hr = (sum(hrs) / len(hrs)) if hrs else mean_p
    if legs and len(mls) == len(legs):
        ml_win = 1.0
        for m in mls:
            ml_win *= m
    else:
        ml_win = sweep_pct
    return {
        "web_group_name": group_name,
        "ticket_id": ticket_id,
        "ticket_no": ticket_no,
        "ticket_track": "goblin70",
        "mode": "goblin70",
        "avg_hit_rate": round(avg_hr, 4),
        "est_win_prob": round(ml_win, 4),
        "est_flex_cash_prob": round(cash_pct, 4) if tt == "flex" else None,
        "power_payout": sweep if tt == "power" else None,
        "flex_payout": sweep if tt == "flex" else None,
        "base_power_payout": sweep if tt == "power" else None,
        "ev_power": ev,
        "display_min_x": sweep,
        "core_build": True,
        "core_recipe": "goblin70",
        "core_label": "Goblin-70 (L5>=4 + cover floor)",
        "pool_policy": "goblin70",
        "strong_builder": False,
        "legs": legs,
        "n_legs": n,
        "play": product,
        "payout": {
            "ticket_type": tt,
            "payout": sweep,
            "min_guarantee": sweep,
            "min_payout_x": sweep,
            "display_min_x": sweep,
            "p_all_win": round(sweep_pct, 4),
            "p_miss_1": round(cash_pct - sweep_pct, 4) if tt == "flex" else 0.0,
            "ev": ev,
            "recommendation": "OK",
            "entry_10_to_win_guarantee": round(10 * sweep, 2),
            "entry_20_to_win_guarantee": round(20 * sweep, 2),
            "sweep_payout": sweep,
            "sweep_payout_x": sweep,
            "audit_all_hit_x": sweep,
            "payout_source": ticket.get("payout_source") or "n_correct_median",
            "payout_note": ticket.get("payout_note") or "",
            "n_correct": n_correct,
            "ev_formula": "E[N-correct] - 1",
        },
    }


def to_web_payload(payload: dict) -> dict:
    date = str(payload.get("date") or "")[:10]
    goblin = playable_tickets(payload)
    groups: list[dict] = []
    by_group: dict[str, list[dict]] = {}
    for t in goblin:
        n = int(t.get("n_legs") or 0)
        product = str(t.get("product") or "Power")
        gname = str(t.get("web_group") or "").strip() or (
            f"X-Sport Goblin-70 {product} {n}"
        )
        by_group.setdefault(gname, []).append(t)
    for gname, slips in by_group.items():
        web_slips = [
            _ticket_to_web(t, date=date, ticket_no=i, group_name=gname)
            for i, t in enumerate(slips, start=1)
        ]
        n_legs = int(slips[0].get("n_legs") or 0)
        product = str(slips[0].get("product") or "Power")
        sweep = _sweep_x(slips[0])
        groups.append(
            {
                "group_name": gname,
                "n_legs": n_legs,
                "power_payout": sweep if product.lower() == "power" else None,
                "flex_payout": sweep if product.lower() == "flex" else None,
                "tickets": web_slips,
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "date": date,
        "tennis_date": date,
        "ticket_track": "goblin70",
        "mode": "goblin70",
        "pool_mode": "goblin70",
        "allow_standard": False,
        "filters": {
            "pick_types": "Goblin",
            "allow_standard": False,
            "goblin_only": True,
            "pool_mode": "goblin70",
            "min_l5": 4,
            "cover_floor": "WNBA/Tennis>=2, MLB/Soccer>=1",
            "note": (
                "Goblin OVER + directional L5>=4 + sport cover floor. "
                "No Demons, no shadow, no Standard legs. D is a badge. "
                "N-correct / To Win only."
            ),
        },
        "payout_note": payload.get("payout_note"),
        "step8_root": payload.get("step8_root"),
        "pool": payload.get("pool"),
        "groups": groups,
    }


def is_g70_group(group: dict) -> bool:
    name = str(group.get("group_name") or "")
    if "Goblin-70" in name:
        return True
    if name.startswith("NFL Power"):
        return True
    tickets = group.get("tickets") or []
    if tickets and isinstance(tickets[0], dict):
        return str(tickets[0].get("ticket_track") or "").lower() == "goblin70"
    return False


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def grade_pool_paths(date: str) -> list[Path]:
    name = f"combined_slate_tickets_{date}.json"
    out = [
        _REPO / "ui_runner" / "data" / name,
        _REPO / "ui_runner" / "templates" / name,
    ]
    sibling = _REPO.parent / "PropORACLE_main_cp"
    if sibling.is_dir() and sibling.resolve() != _REPO.resolve():
        out.extend(
            [
                sibling / "ui_runner" / "data" / name,
                sibling / "ui_runner" / "templates" / name,
            ]
        )
    return out


def _first_mixer_payload(date: str, candidates: list[Path]) -> tuple[dict | None, list[dict]]:
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        data = _read_json(path)
        if not data:
            continue
        if str(data.get("date") or "")[:10] != date:
            continue
        groups = [g for g in (data.get("groups") or []) if isinstance(g, dict) and not is_g70_group(g)]
        if groups:
            return data, groups
    return None, []


def load_graded_main(date: str) -> tuple[dict | None, list[dict]]:
    """Mixer groups for the live card.

    Prefer the grade-pool JSON (full graded-main) over tickets_latest. After a
    refresh, tickets_latest is often Goblin-70-only or a pruned live file; using
    it first would wipe STRONG / MLB Goblin OVER / tennis mixer groups.
    """
    live: list[Path] = list(WEB_JSON_PATHS)
    sibling = _REPO.parent / "PropORACLE_main_cp"
    if sibling.is_dir() and sibling.resolve() != _REPO.resolve():
        live.extend(
            [
                sibling / "ui_runner" / "templates" / "tickets_latest.json",
                sibling / "ui_runner" / "data" / "tickets_latest.json",
            ]
        )
    pool = _first_mixer_payload(date, grade_pool_paths(date))
    live_payload = _first_mixer_payload(date, live)
    if pool[1] and (not live_payload[1] or len(pool[1]) >= len(live_payload[1])):
        return pool
    return live_payload


def _sport_token(raw: object) -> str:
    mapped = web_sport(raw).strip().upper()
    if mapped.startswith("NFLP"):
        return "NFL"
    return mapped.split()[0] if mapped else ""


def _board_leg_key(
    player: object,
    sport: object,
    prop: object,
    pick_type: object,
    side: object,
) -> tuple[str, str, str, str, str]:
    d = str(side or "").strip().upper()
    if "UNDER" in d:
        d = "UNDER"
    else:
        d = "OVER"
    pt = str(pick_type or "Standard").strip().title()
    if pt not in {"Goblin", "Demon", "Standard"}:
        pt = "Standard"
    return (
        fold_name(player),
        _sport_token(sport),
        str(prop or "").strip().lower(),
        pt,
        d,
    )


def index_board_legs(board: list[dict]) -> dict[tuple[str, str, str, str, str], list[dict]]:
    idx: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for r in board or []:
        if not isinstance(r, dict):
            continue
        k = _board_leg_key(
            r.get("player"),
            r.get("sport"),
            r.get("prop") or r.get("prop_type"),
            r.get("pick_type"),
            r.get("side") or r.get("direction"),
        )
        if not k[0] or not k[2]:
            continue
        idx.setdefault(k, []).append(r)
    return idx


def _pick_board_row(rows: list[dict], old_line: float | None) -> dict | None:
    if not rows:
        return None
    if old_line is not None:
        for r in rows:
            try:
                if abs(float(r.get("line")) - old_line) < 1e-9:
                    return r
            except (TypeError, ValueError):
                continue
    return rows[0]


def _apply_board_row_to_leg(leg: dict, row: dict) -> bool:
    """Copy fetch fields onto a live ticket leg. True if the line moved."""
    changed = False
    try:
        new_line = float(row.get("line"))
    except (TypeError, ValueError):
        new_line = None
    try:
        old_line = float(leg.get("line"))
    except (TypeError, ValueError):
        old_line = None
    if new_line is not None and (old_line is None or abs(new_line - old_line) > 1e-9):
        leg["line"] = new_line
        changed = True
    side = str(row.get("side") or leg.get("direction") or "OVER").upper()
    cover = row.get("cover")
    if cover is not None:
        try:
            cover_f = float(cover)
            leg["edge"] = cover_f
            leg["abs_edge"] = abs(cover_f)
            leg["cover"] = cover_f
        except (TypeError, ValueError):
            pass
    l5 = row.get("l5_over") if side == "OVER" else row.get("l5_under")
    if l5 is not None:
        try:
            l5_f = float(l5)
            if side == "OVER":
                leg["l5_over"] = l5_f
            else:
                leg["l5_under"] = l5_f
            leg["l5_side_hit_rate"] = l5_f / 5.0
        except (TypeError, ValueError):
            pass
    if row.get("def") is not None:
        leg["def_tier"] = str(row.get("def") or "")
    if row.get("matchup"):
        leg["matchup"] = str(row.get("matchup"))
    return changed


def patch_mixer_groups(
    groups: list[dict],
    board: list[dict],
) -> tuple[list[dict], dict[str, int]]:
    """Update mixer legs when the fetch moved a line. Keep the slip if it is off-board.

    Live /tickets must keep Goblin-70 and graded-main together. Dropping unmatched
    legs emptied the mixer after afternoon games left the PP board.
    """
    idx = index_board_legs(board)
    stats = {"updated": 0, "dropped": 0, "unchanged": 0}
    out: list[dict] = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        kept: list[dict] = []
        for ticket in group.get("tickets") or []:
            if not isinstance(ticket, dict):
                continue
            legs = ticket.get("legs") or []
            if not isinstance(legs, list) or not legs:
                kept.append(ticket)
                stats["unchanged"] += 1
                continue
            new_legs: list[dict] = []
            changed = False
            for leg in legs:
                if not isinstance(leg, dict):
                    new_legs.append(leg)
                    continue
                k = _board_leg_key(
                    leg.get("player"),
                    leg.get("sport"),
                    leg.get("prop_type") or leg.get("prop"),
                    leg.get("pick_type"),
                    leg.get("direction") or leg.get("side"),
                )
                rows = idx.get(k) or []
                try:
                    old_line = float(leg.get("line"))
                except (TypeError, ValueError):
                    old_line = None
                row = _pick_board_row(rows, old_line)
                if row is None:
                    new_legs.append(leg)
                    continue
                patched = dict(leg)
                if _apply_board_row_to_leg(patched, row):
                    changed = True
                new_legs.append(patched)
            nxt = dict(ticket)
            nxt["legs"] = new_legs
            kept.append(nxt)
            if changed:
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
        if kept:
            nxt_g = dict(group)
            nxt_g["tickets"] = kept
            out.append(nxt_g)
    return out, stats


def merge_web_payload(
    g70: dict,
    main_payload: dict | None = None,
    main_groups: list[dict] | None = None,
) -> dict:
    """Goblin-70 groups first, then the graded-main mixer. Both stay on /tickets."""
    g70_groups = list(g70.get("groups") or [])
    mixer = list(main_groups or [])
    out = dict(main_payload) if main_payload else {}
    out.update({k: v for k, v in g70.items() if k != "groups"})
    out["groups"] = g70_groups + mixer
    out["ticket_track"] = "goblin70"
    out["mode"] = "goblin70+graded_main" if mixer else "goblin70"
    out["tracks"] = ["goblin70", "graded_main"] if mixer else ["goblin70"]
    return out


def write_web(payload: dict, board: list[dict] | None = None) -> list[Path]:
    g70 = to_web_payload(payload)
    date = str(g70.get("date") or "")[:10]
    main_payload, main_groups = load_graded_main(date)
    rows = board if board is not None else load_today_board(date)
    if rows:
        main_groups, patch_stats = patch_mixer_groups(main_groups, rows)
        print(
            "mixer patch from fetch: "
            f"updated={patch_stats['updated']} dropped={patch_stats['dropped']} "
            f"unchanged={patch_stats['unchanged']}"
        )
    web = merge_web_payload(g70, main_payload, main_groups)
    print(
        f"web merge goblin70_groups={len(g70.get('groups') or [])} "
        f"graded_main_groups={len(main_groups)}"
    )
    if not main_groups:
        print(
            "WARN: mixer groups empty — /tickets would be Goblin-70 only. "
            "Need ui_runner/data/combined_slate_tickets_{date}.json (or same-date "
            "tickets_latest) with graded_main groups."
        )
    text = json.dumps(web, ensure_ascii=False, indent=2, allow_nan=False)
    written: list[Path] = []
    paths = list(WEB_JSON_PATHS)
    main_cp = _REPO.parent / "PropORACLE_main_cp"
    if main_cp.is_dir():
        paths.extend(
            [
                main_cp / "ui_runner" / "templates" / "tickets_latest.json",
                main_cp / "ui_runner" / "data" / "tickets_latest.json",
                main_cp / "mobile" / "www" / "tickets_latest.json",
            ]
        )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
        print("web", path)
    return written


def publish_live(date: str) -> int:
    """Commit/push tickets JSON to origin/main so Railway + GitHub raw stay current."""
    ps1 = _REPO / "scripts" / "Publish-LiveSite.ps1"
    if not ps1.is_file():
        print("WARN: Publish-LiveSite.ps1 missing — live site not updated")
        return 1
    msg = f"chore: Goblin-70 tickets {date}"
    cmd = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(ps1),
        "-RepoRoot",
        str(_REPO),
        "-CommitMessage",
        msg,
    ]
    print("publish-live", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(_REPO))
    print(f"publish-live exit {proc.returncode}")
    return int(proc.returncode)


def make_ticket(
    tid: str,
    legs: list[dict],
    product: str,
    family: str,
    note: str,
    *,
    web_group: str = "",
    date: str = "",
) -> dict:
    n = len(legs)
    out = {
        "id": tid,
        "name": f"{product} {n} · {family}",
        "note": note,
        "n_legs": n,
        "product": product,
        "family": family,
        "play": product,
        "mix": f"{sum(1 for x in legs if x.get('pick_type')=='Goblin')} Goblin / "
        f"{sum(1 for x in legs if x.get('pick_type')=='Standard')} Standard",
        **ticket_math(legs, product, family, date=date),
        "sports": sorted({str(x.get("sport")) for x in legs}),
        "legs": legs,
    }
    if web_group:
        out["web_group"] = web_group
    return out


def build(date: str, *, l5_eq_5: bool = False) -> dict:
    board = load_today_board(date)
    gob_raw = [
        r
        for r in board
        if goblin_70_eligible(r) and fold_name(r.get("player")) not in SKIP_PLAYERS
    ]
    if l5_eq_5:
        gob_raw = [r for r in gob_raw if int(directional_l5(r) or 0) == 5]
    std_raw = []
    for r in board:
        kind = standard_flex_kind(r)
        if not kind:
            continue
        rec = dict(r)
        rec["std_kind"] = kind
        rec["p"] = standard_ticket_p(kind)
        std_raw.append(rec)
    for r in gob_raw:
        r["p"] = goblin_ticket_p(r)

    gob = unique_by_player(gob_raw, goblin_sort_key)
    std = unique_by_player(std_raw, standard_sort_key)

    taken: set[str] = set()
    tickets: list[dict] = []

    def _ticket(*args, **kwargs):
        kwargs.setdefault("date", date)
        return make_ticket(*args, **kwargs)

    for tid, n, product, family in MAIN_CARD:
        combo = pack(gob, n, taken, mix_sports=True, wnba_cap=1)
        note = (
            "L5=5 Goblin juice cut + sport cover floor. Power OK."
            if l5_eq_5
            else "All-Goblin 70% pool (L5>=4 + sport cover floor). Power OK."
        )
        if len(combo) != n and l5_eq_5:
            combo = pack(gob, n, taken, mix_sports=True, wnba_cap=2)
            if len(combo) == n:
                note += " Thin slate: two WNBA legs from the same game."
        if len(combo) != n:
            continue
        for r in combo:
            taken.add(fold_name(r.get("player")))
        tickets.append(
            _ticket(
                tid,
                [compact(x) for x in combo],
                product,
                family,
                note,
            )
            )

    # Named sport groups so /tickets WNBA and NFL pills are not empty.
    # Mixed X-Sport slips tag as CROSS; these groups use the sport in the title.
    for sport, n, product, n_tickets in SPORT_PURE:
        pool = [r for r in gob if str(r.get("sport")) == sport]
        local_taken: set[str] = set()
        cap = 2 if sport == "WNBA" else 1
        for i in range(1, n_tickets + 1):
            combo = pack(pool, n, local_taken, mix_sports=False, wnba_cap=cap)
            n_use = n
            prod = product
            if len(combo) != n:
                combo = pack(pool, 2, local_taken, mix_sports=False, wnba_cap=cap)
                n_use, prod = 2, "Power"
            if len(combo) < 2:
                break
            for r in combo:
                local_taken.add(fold_name(r.get("player")))
            tickets.append(
                _ticket(
                    f"{sport[:3].upper()}{n_use}-{i}",
                    [compact(x) for x in combo],
                    prod,
                    "goblin",
                    f"{sport} Goblin-70 (L5>=4 + sport cover floor). Power OK.",
                    web_group=f"{sport} Goblin-70 {prod} {n_use}",
                )
            )

    nfl_raw = [r for r in board if nflp_ticket_eligible(r)]
    nfl_family = "nflp"
    if not nfl_raw:
        nfl_raw = [r for r in board if nflp_std_over_eligible(r)]
        nfl_family = "nflp_std"
    for r in nfl_raw:
        r["p"] = nflp_ticket_p(r)
    nfl = unique_by_player(nfl_raw, goblin_sort_key)
    nfl_taken: set[str] = set()
    for i in range(1, 4):
        combo = pack(nfl, 3, nfl_taken, mix_sports=False, wnba_cap=2)
        n_use = 3
        if len(combo) != 3:
            combo = pack(nfl, 2, nfl_taken, mix_sports=False, wnba_cap=2)
            n_use = 2
        if len(combo) < 2:
            break
        for r in combo:
            nfl_taken.add(fold_name(r.get("player")))
        note = (
            "NFLP week-3 Goblin OVER. Kickers L5>=4; backup skill needs D. Not the 70% book."
            if nfl_family == "nflp"
            else "NFLP week-3 Standard OVER. Backup skill with D; kickers L5>=4. Not mixed onto Goblin-70."
        )
        tickets.append(
            _ticket(
                f"NFL{n_use}-{i}",
                [compact(x) for x in combo],
                "Power",
                nfl_family,
                note,
                web_group=f"NFL Power {n_use}",
            )
        )

    leftover = [r for r in gob if fold_name(r.get("player")) not in taken]
    std_left = [] if l5_eq_5 else [r for r in std if fold_name(r.get("player")) not in taken]
    if leftover and std_left:
        g3 = pack(leftover, 3, taken, mix_sports=True, wnba_cap=1)
        std_leg = next((s for s in std_left if len(g3) == 3 and can_add(g3, s, wnba_cap=1)), None)
        if g3 and std_leg:
            mix = g3 + [std_leg]
            for r in mix:
                taken.add(fold_name(r.get("player")))
            tickets.append(
                _ticket(
                    "SF4-1",
                    [compact(x, std=x.get("pick_type") == "Standard") for x in mix],
                    "Flex",
                    "mix",
                    "Flex only. One Standard allowlist leg + three Goblin-70 leftovers.",
                )
            )
            std_left = [r for r in std_left if fold_name(r.get("player")) not in taken]

    if len(std_left) >= 3:
        s3 = pack(std_left, 3, taken, mix_sports=True, wnba_cap=1)
        if len(s3) == 3:
            for r in s3:
                taken.add(fold_name(r.get("player")))
            tickets.append(
                _ticket(
                    "SF3-1",
                    [compact(x, std=True) for x in s3],
                    "Flex",
                    "standard",
                    "Flex only. Standard allowlist (steals / WNBA combo / assists U / HRRBI U L5=5).",
                )
            )

    choose = getattr(R, "_choose_step8_root", None)
    root = choose([_REPO, _REPO.parent / "PropORACLE_main_cp"], date) if callable(choose) else _REPO
    return {
        "date": date,
        "built_at": datetime.now(ET).isoformat(timespec="seconds"),
        "step8_root": str(root) if root else None,
        "payout_note": (
            "N-correct / To Win only. Ignore 1st place. "
            "Rates: slip pin → same-day CDP (matching Goblin-Δ) → mix_by_delta → fallback."
        ),
        "pool": {
            "goblin_70": len(gob),
            "goblin_70_raw": len(gob_raw),
            "standard_allowlist": len(std),
            "standard_allowlist_raw": len(std_raw),
            "nflp_goblin": len(nfl),
            "nflp_goblin_raw": len(nfl_raw),
        },
        "goblin_pool": [compact(r) for r in gob],
        "standard_pool": [compact(r, std=True) for r in std],
        "nflp_pool": [compact(r) for r in nfl],
        "tickets": tickets,
        "_board": board,
    }


def print_card(payload: dict) -> None:
    print(f"date {payload['date']}  root {payload.get('step8_root')}")
    pool = payload["pool"]
    print(
        f"Goblin-70 unique {pool['goblin_70']} (raw {pool['goblin_70_raw']})  "
        f"Standard allowlist unique {pool['standard_allowlist']} "
        f"(raw {pool['standard_allowlist_raw']})  "
        f"NFLP Goblin unique {pool.get('nflp_goblin', 0)} "
        f"(raw {pool.get('nflp_goblin_raw', 0)})"
    )
    print("\nGOBLIN-70 TOP SEEDS")
    for r in payload["goblin_pool"][:12]:
        print(
            f"  {r['tier']}/{r['badge']}  {r['sport']:6} {r['player']:22} "
            f"{r['prop']:18} O{r['line']}  L5 {r['l5']}  cov {r['cover']:+.1f}"
        )
    print("\nSTANDARD ALLOWLIST")
    if not payload["standard_pool"]:
        print("  (none tonight)")
    for r in payload["standard_pool"]:
        print(
            f"  {r.get('std_kind'):22} {r['sport']:6} {r['player']:22} "
            f"{r['prop']:18} {r['side'][0]}{r['line']}  L5 {r['l5']}  "
            f"p={r['p']:.3f}  {r['matchup']}"
        )
    print("\nTICKETS")
    for t in payload["tickets"]:
        print(
            f"  {t['id']} {t['product']} {t['n_legs']}  {t['mix']}  "
            f"N-correct {t['n_correct']}  sweep {t['sweep_pct']}%  "
            f"EV {t['ev_n_correct']}x  {t['payout_note']}"
        )
        for leg in t["legs"]:
            print(
                f"    [{leg['pick_type'][0]}] {leg['sport']} {leg['player']} "
                f"{leg['prop']} {leg['side'][0]}{leg['line']}"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(ET).strftime("%Y-%m-%d"))
    ap.add_argument(
        "--write-web",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Merge Goblin-70 onto /tickets (Goblin-70 first, mixer under). Default: on.",
    )
    ap.add_argument(
        "--l5-eq-5",
        action="store_true",
        help="Restrict Goblin pool to directional L5 = 5 (juice cut).",
    )
    ap.add_argument(
        "--publish-live",
        action="store_true",
        help="After --write-web, run Publish-LiveSite.ps1 (origin/main / Railway).",
    )
    args = ap.parse_args()
    payload = build(args.date, l5_eq_5=args.l5_eq_5)
    board = payload.pop("_board", None)
    suffix = "_l5eq5" if args.l5_eq_5 else ""
    out = OUT_DIR / f"goblin70_tickets_{args.date}{suffix}.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.l5_eq_5:
        latest = OUT_DIR / "goblin70_tickets_latest.json"
        latest.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    print_card(payload)
    print("\nwrote", out)
    if args.write_web and not args.l5_eq_5:
        write_web(payload, board=board)
        if args.publish_live:
            rc = publish_live(args.date)
            if rc != 0:
                return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
