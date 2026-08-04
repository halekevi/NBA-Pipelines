#!/usr/bin/env python3
"""
Build season-window consistency leaders by line-class (GOB / STD / UND).

Each leader row is keyed by sport × player × prop × pick_class:
  goblin_over      → badge GOB xx%   (% OVER Goblin line)
  standard_over    → badge STD xx%   (% OVER Standard line)
  standard_under   → badge UND xx%   (% UNDER Standard line)
  goblin_under     → badge UND xx%   (only when sample is material)

Demon is never mixed into Goblin/Standard rates.

Reads graded_props_*.json from each sport's season opener (or 2026-01-01 when
unclear) through latest graded day. MLB ASG 2026-07-13..15 excluded.

Artifacts:
  data/slate_consistency/consistency_leaders_latest.json
  data/reports/consistency_leaders_tables_latest.json
  ui_runner/data/consistency_leaders_latest.json
  ui_runner/templates/consistency_leaders_latest.json
  mobile/www/consistency_leaders_latest.json

CLI:
  py -3.14 scripts/build_consistency_leaders.py
  py -3.14 scripts/build_consistency_leaders.py --to 2026-08-03 --top 8
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utils.allstar_filter import is_allstar_date  # noqa: E402
from utils.sport_season_windows import (  # noqa: E402
    ACTIVE_SPORTS,
    MLB_ASG_HARD,
    SPORT_FROM_NOTES,
    from_dates_payload,
    sport_from_date,
)

BASES = [REPO / "ui_runner" / "templates", REPO / "mobile" / "www"]
OUT_PRIMARY = REPO / "data" / "slate_consistency" / "consistency_leaders_latest.json"
OUT_TABLES = REPO / "data" / "reports" / "consistency_leaders_tables_latest.json"
OUT_UI = REPO / "ui_runner" / "data" / "consistency_leaders_latest.json"
OUT_TEMPLATES = REPO / "ui_runner" / "templates" / "consistency_leaders_latest.json"
OUT_MOBILE = REPO / "mobile" / "www" / "consistency_leaders_latest.json"

# Minimum decided legs to surface a leader (Standard slightly higher).
MIN_N_STANDARD = 12
MIN_N_GOBLIN = 10
# Goblin UNDER is rare — require a material sample before surfacing UND.
MIN_N_GOBLIN_UNDER = 12
MIN_HR = 0.62
LINE_BAND = 0.5  # ± band for matching slate lines
TOP_PER_CELL = 8

# Badge-facing pick classes only (Demon / Other excluded).
PICK_CLASS_GOBLIN_OVER = "goblin_over"
PICK_CLASS_STANDARD_OVER = "standard_over"
PICK_CLASS_STANDARD_UNDER = "standard_under"
PICK_CLASS_GOBLIN_UNDER = "goblin_under"

PICK_CLASS_BADGE = {
    PICK_CLASS_GOBLIN_OVER: "GOB",
    PICK_CLASS_STANDARD_OVER: "STD",
    PICK_CLASS_STANDARD_UNDER: "UND",
    PICK_CLASS_GOBLIN_UNDER: "UND",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(x: Any) -> float | None:
    try:
        if x in (None, ""):
            return None
        v = float(x)
        if math.isnan(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _is_hit(r: dict) -> bool | None:
    h = r.get("hit")
    if h in (True, 1, "1", "true", "True", "HIT", "hit", "W", "w"):
        return True
    if h in (False, 0, "0", "false", "False", "MISS", "miss", "L", "l"):
        return False
    res = str(r.get("result") or r.get("grade") or "").upper()
    if res in ("HIT", "W", "WIN"):
        return True
    if res in ("MISS", "L", "LOSS"):
        return False
    return None


def _norm_pick(pt: Any) -> str:
    s = str(pt or "").lower()
    if "goblin" in s:
        return "Goblin"
    if "demon" in s:
        return "Demon"
    if "standard" in s:
        return "Standard"
    return "Other"


def _norm_name(name: Any) -> str:
    s = str(name or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", " ", s)


def _norm_prop(p: Any) -> str:
    s = re.sub(r"\s+", " ", str(p or "").strip().lower().replace("_", " "))
    s = s.replace("+", " + ")
    s = re.sub(r"\s+", " ", s).strip()
    aliases = {
        "pts": "points",
        "reb": "rebounds",
        "rebs": "rebounds",
        "ast": "assists",
        "asts": "assists",
        "stl": "steals",
        "blk": "blocked shots",
        "blocks": "blocked shots",
        "3pm": "3-pt made",
        "3 pointers made": "3-pt made",
        "three pointers made": "3-pt made",
        "pra": "pts+rebs+asts",
        "pr": "pts+rebs",
        "pa": "pts+asts",
        "ra": "rebs+asts",
        "pts + rebs + asts": "pts+rebs+asts",
        "pts + rebs": "pts+rebs",
        "pts + asts": "pts+asts",
        "rebs + asts": "rebs+asts",
        "goal + assist": "goals+assists",
        "goals + assists": "goals+assists",
        "g+a": "goals+assists",
        "sot": "shots on target",
        "games won": "games won",
        "total games": "total games",
    }
    return aliases.get(s, s)


def _prop_display(prop_key: str) -> str:
    special = {
        "3-pt made": "3-PT Made",
        "pts+rebs+asts": "Pts+Rebs+Asts",
        "pts+rebs": "Pts+Rebs",
        "pts+asts": "Pts+Asts",
        "rebs+asts": "Rebs+Asts",
        "goals+assists": "Goals+Assists",
        "shots on target": "Shots on Target",
        "games won": "Games Won",
        "total games": "Total Games",
        "double faults": "Double Faults",
        "break points won": "Break Points Won",
    }
    if prop_key in special:
        return special[prop_key]
    return prop_key.title() if prop_key else "?"


def _dir_l5(r: dict, direction: str) -> float | None:
    lo, lu = _num(r.get("l5_over")), _num(r.get("l5_under"))
    if direction == "OVER" and lo is not None:
        return lo
    if direction == "UNDER" and lu is not None:
        return lu
    hr5 = _num(r.get("hit_rate_l5"))
    if hr5 is not None:
        if 0.0 <= hr5 <= 1.0:
            return round(hr5 * 5.0, 4)
        if 0.0 <= hr5 <= 5.0:
            return hr5
    return None


def _dir_l10(r: dict, direction: str) -> float | None:
    lo, lu = _num(r.get("l10_over")), _num(r.get("l10_under"))
    if direction == "OVER" and lo is not None:
        return lo
    if direction == "UNDER" and lu is not None:
        return lu
    hr10 = _num(r.get("hit_rate_l10"))
    if hr10 is not None:
        if 0.0 <= hr10 <= 1.0:
            return round(hr10 * 10.0, 4)
        if 0.0 <= hr10 <= 10.0:
            return hr10
    return None


def _pick_class(pick: str, direction: str) -> str | None:
    """Map graded pick_type + direction → badge pick_class (None = skip)."""
    if pick == "Goblin" and direction == "OVER":
        return PICK_CLASS_GOBLIN_OVER
    if pick == "Standard" and direction == "OVER":
        return PICK_CLASS_STANDARD_OVER
    if pick == "Standard" and direction == "UNDER":
        return PICK_CLASS_STANDARD_UNDER
    if pick == "Goblin" and direction == "UNDER":
        return PICK_CLASS_GOBLIN_UNDER
    return None  # Demon / Other never enter leaders


def _min_n_for_class(pick_class: str) -> int:
    if pick_class == PICK_CLASS_STANDARD_OVER:
        return MIN_N_STANDARD
    if pick_class == PICK_CLASS_STANDARD_UNDER:
        return MIN_N_STANDARD
    if pick_class == PICK_CLASS_GOBLIN_OVER:
        return MIN_N_GOBLIN
    if pick_class == PICK_CLASS_GOBLIN_UNDER:
        return MIN_N_GOBLIN_UNDER
    return MIN_N_STANDARD


def _iter_dates(d0: str, d1: str) -> list[str]:
    out = []
    cur = datetime.strptime(d0, "%Y-%m-%d").date()
    end = datetime.strptime(d1, "%Y-%m-%d").date()
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _find_graded(day: str) -> Path | None:
    for base in BASES:
        p = base / f"graded_props_{day}.json"
        if p.exists():
            return p
    return None


def _discover_to(default: str) -> str:
    days: list[str] = []
    for base in BASES:
        for p in base.glob("graded_props_*.json"):
            m = re.match(r"graded_props_(\d{4}-\d{2}-\d{2})\.json$", p.name)
            if m:
                days.append(m.group(1))
    return max(days) if days else default


def _line_key(line: float | None) -> str:
    if line is None:
        return "na"
    # Snap to .0 / .5 style for grouping
    return f"{round(line * 2) / 2:.1f}"


class Agg:
    __slots__ = (
        "hits",
        "n",
        "lines",
        "l5_vals",
        "l10_vals",
        "player",
        "prop_raw",
        "dates",
    )

    def __init__(self, player: str, prop_raw: str) -> None:
        self.hits = 0
        self.n = 0
        self.lines: Counter[str] = Counter()
        self.l5_vals: list[float] = []
        self.l10_vals: list[float] = []
        self.player = player
        self.prop_raw = prop_raw
        self.dates: list[str] = []

    def add(
        self,
        *,
        hit: bool,
        line: float | None,
        l5: float | None,
        l10: float | None,
        date: str,
    ) -> None:
        self.n += 1
        if hit:
            self.hits += 1
        if line is not None:
            self.lines[_line_key(line)] += 1
        if l5 is not None:
            self.l5_vals.append(l5)
        if l10 is not None:
            self.l10_vals.append(l10)
        self.dates.append(date)

    @property
    def hr(self) -> float:
        return self.hits / self.n if self.n else 0.0

    def mode_line(self) -> float | None:
        if not self.lines:
            return None
        lk = self.lines.most_common(1)[0][0]
        try:
            return float(lk)
        except ValueError:
            return None

    def to_row(
        self,
        *,
        sport: str,
        prop: str,
        direction: str,
        pick_type: str,
        pick_class: str,
        window_from: str,
        window_to: str,
    ) -> dict[str, Any]:
        ml = self.mode_line()
        # Modal-line share: how often the most common offered line appears.
        modal_share = (self.lines.most_common(1)[0][1] / self.n) if self.lines and self.n else 0.0
        l5_avg = sum(self.l5_vals) / len(self.l5_vals) if self.l5_vals else None
        l10_avg = sum(self.l10_vals) / len(self.l10_vals) if self.l10_vals else None
        # Score: prioritize HR, then sample, then recent L5/L10 when present
        score = self.hr
        score += min(self.n, 40) * 0.0015
        if l5_avg is not None:
            score += (l5_avg / 5.0) * 0.05
        if l10_avg is not None:
            score += (l10_avg / 10.0) * 0.03
        badge = PICK_CLASS_BADGE[pick_class]
        return {
            "sport": sport,
            "player": self.player,
            "player_norm": _norm_name(self.player),
            "prop": _prop_display(prop),
            "prop_key": prop,
            "direction": direction,
            "pick_type": pick_type,
            "pick_class": pick_class,
            "badge_prefix": badge,
            "line": ml,
            "reference_line": ml,
            "line_band": LINE_BAND,
            "lines_seen": dict(self.lines.most_common(5)),
            "modal_line_share": round(modal_share, 4),
            "hit_rate": round(self.hr, 4),
            "sample_n": self.n,
            "hits": self.hits,
            "l5_avg": round(l5_avg, 3) if l5_avg is not None else None,
            "l10_avg": round(l10_avg, 3) if l10_avg is not None else None,
            "first_date": min(self.dates) if self.dates else None,
            "last_date": max(self.dates) if self.dates else None,
            "window": {"from": window_from, "to": window_to},
            "score": round(score, 5),
        }


def scan(
    date_from: str,
    date_to: str,
) -> tuple[dict[tuple, Agg], dict[str, Any]]:
    """Aggregate (sport, player_norm, prop, dir, pick) → Agg."""
    bags: dict[tuple, Agg] = {}
    meta: dict[str, Any] = {
        "days_used": [],
        "mlb_asg_skipped": [],
        "by_sport_days": defaultdict(set),
        "n_legs": 0,
    }
    for d in _iter_dates(date_from, date_to):
        path = _find_graded(d)
        if not path:
            continue
        mlb_asg = d in MLB_ASG_HARD or is_allstar_date(d, sport="MLB")
        if mlb_asg and d not in meta["mlb_asg_skipped"]:
            meta["mlb_asg_skipped"].append(d)
        try:
            props = json.loads(path.read_text(encoding="utf-8")).get("props") or []
        except (OSError, json.JSONDecodeError):
            continue
        n_day = 0
        for r in props:
            sport = str(r.get("sport") or "").upper()
            if sport not in ACTIVE_SPORTS:
                continue
            if d < sport_from_date(sport):
                continue
            if sport == "MLB" and mlb_asg:
                continue
            hit = _is_hit(r)
            if hit is None:
                continue
            player = str(r.get("player") or "").strip()
            if not player:
                continue
            direction = str(r.get("direction") or r.get("over_under") or "").upper()
            if direction in ("O", "MORE"):
                direction = "OVER"
            if direction in ("U", "LESS", "LOWER"):
                direction = "UNDER"
            if direction not in ("OVER", "UNDER"):
                continue
            pick = _norm_pick(r.get("pick_type"))
            prop = _norm_prop(r.get("prop") or r.get("prop_type") or "")
            if not prop:
                continue
            pn = _norm_name(player)
            key = (sport, pn, prop, direction, pick)
            agg = bags.get(key)
            if agg is None:
                agg = Agg(player, prop)
                bags[key] = agg
            agg.add(
                hit=hit,
                line=_num(r.get("line")),
                l5=_dir_l5(r, direction),
                l10=_dir_l10(r, direction),
                date=d,
            )
            meta["by_sport_days"][sport].add(d)
            n_day += 1
            meta["n_legs"] += 1
        if n_day:
            meta["days_used"].append(d)
    meta["by_sport_days"] = {k: sorted(v) for k, v in meta["by_sport_days"].items()}
    return bags, meta


def _qualify(row: dict, pick_class: str) -> bool:
    return row["sample_n"] >= _min_n_for_class(pick_class) and row["hit_rate"] >= MIN_HR


def build_leaders(
    bags: dict[tuple, Agg],
    meta: dict,
    date_to: str,
    *,
    top: int,
) -> dict[str, Any]:
    sport_from = from_dates_payload()
    leaders: list[dict] = []
    tables: dict[str, Any] = {}

    # Group by sport × prop × pick_class (direction implied by class)
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for (sport, pn, prop, direction, pick), agg in bags.items():
        pick_class = _pick_class(pick, direction)
        if pick_class is None:
            continue  # Demon / Other excluded
        w_from = sport_from_date(sport)
        row = agg.to_row(
            sport=sport,
            prop=prop,
            direction=direction,
            pick_type=pick,
            pick_class=pick_class,
            window_from=w_from,
            window_to=date_to,
        )
        if not _qualify(row, pick_class):
            continue
        cells[(sport, prop, pick_class)].append(row)

    for cell_key, rows in cells.items():
        rows.sort(key=lambda r: (-r["score"], -r["sample_n"], -r["hit_rate"]))
        top_rows = rows[:top]
        leaders.extend(top_rows)
        sport, prop, pick_class = cell_key
        direction = top_rows[0]["direction"] if top_rows else ""
        tables.setdefault(sport, {}).setdefault(prop, {}).setdefault(pick_class, {
            "direction": direction,
            "badge": PICK_CLASS_BADGE[pick_class],
            "rows": [],
        })
        tables[sport][prop][pick_class]["rows"] = [
            {
                "player": r["player"],
                "line": r["line"],
                "reference_line": r["reference_line"],
                "hit_rate": r["hit_rate"],
                "sample_n": r["sample_n"],
                "l5_avg": r["l5_avg"],
                "l10_avg": r["l10_avg"],
                "window": r["window"],
            }
            for r in top_rows
        ]

    # Flat match index: one row per sport|player|prop|pick_class
    match_index: list[dict] = []
    seen_match: set[tuple] = set()
    for r in sorted(leaders, key=lambda x: (-x["score"], -x["sample_n"])):
        mk = (r["sport"], r["player_norm"], r["prop_key"], r["pick_class"])
        if mk in seen_match:
            continue
        seen_match.add(mk)
        match_index.append(
            {
                "sport": r["sport"],
                "player": r["player"],
                "player_norm": r["player_norm"],
                "prop": r["prop"],
                "prop_key": r["prop_key"],
                "direction": r["direction"],
                "pick_type": r["pick_type"],
                "pick_class": r["pick_class"],
                "badge_prefix": r["badge_prefix"],
                "line": r["line"],
                "reference_line": r["reference_line"],
                "line_band": r["line_band"],
                "hit_rate": r["hit_rate"],
                "sample_n": r["sample_n"],
                "l5_avg": r["l5_avg"],
                "l10_avg": r["l10_avg"],
                "window": r["window"],
                "score": r["score"],
            }
        )

    by_sport_summary = {}
    for sport in ACTIVE_SPORTS:
        days = meta["by_sport_days"].get(sport) or []
        sport_leaders = [r for r in leaders if r["sport"] == sport]
        by_class = Counter(r["pick_class"] for r in sport_leaders)
        by_sport_summary[sport] = {
            "from": sport_from_date(sport),
            "from_note": SPORT_FROM_NOTES.get(sport, ""),
            "first_graded": days[0] if days else None,
            "last_graded": days[-1] if days else None,
            "days": len(days),
            "n_leaders": len(sport_leaders),
            "by_pick_class": dict(by_class),
        }

    payload = {
        "generated_at": _utc_now(),
        "to": date_to,
        "sport_from_dates": sport_from,
        "mlb_asg_skipped": meta.get("mlb_asg_skipped") or [],
        "min_hr": MIN_HR,
        "min_n": {
            "goblin_over": MIN_N_GOBLIN,
            "standard_over": MIN_N_STANDARD,
            "standard_under": MIN_N_STANDARD,
            "goblin_under": MIN_N_GOBLIN_UNDER,
        },
        "pick_classes": list(PICK_CLASS_BADGE.keys()),
        "badge_prefixes": dict(PICK_CLASS_BADGE),
        "line_band": LINE_BAND,
        "top_per_cell": top,
        "n_legs_scanned": meta.get("n_legs"),
        "n_leaders": len(leaders),
        "n_match_index": len(match_index),
        "sports": by_sport_summary,
        "leaders": leaders,
        "match_index": match_index,
        "note": (
            "Season-window consistency leaders from graded_props. "
            "Keyed by sport × player × prop × pick_class "
            "(goblin_over / standard_over / standard_under; "
            "goblin_under only when material). Demon excluded. "
            "Match slate rows via match_index on player+prop+pick_class "
            "with line within ±line_band. Badges: GOB / STD / UND."
        ),
    }
    tables_payload = {
        "generated_at": payload["generated_at"],
        "to": date_to,
        "sport_from_dates": sport_from,
        "mlb_asg_skipped": payload["mlb_asg_skipped"],
        "tables": tables,
        "sports": by_sport_summary,
        "badge_prefixes": dict(PICK_CLASS_BADGE),
    }
    return payload, tables_payload


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    print(f"Wrote {path} ({path.stat().st_size // 1024} KB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="date_from", default="2026-01-01")
    ap.add_argument("--to", dest="date_to", default=None)
    ap.add_argument("--top", type=int, default=TOP_PER_CELL)
    args = ap.parse_args()

    date_to = args.date_to or _discover_to("2026-08-03")
    date_from = args.date_from
    print(f"Scanning graded_props {date_from} → {date_to}")
    for sp, info in from_dates_payload().items():
        print(f"  {sp}: from {info['from']} — {info['note']}")

    bags, meta = scan(date_from, date_to)
    print(
        f"Aggregated {len(bags)} player×prop×dir×pick keys from "
        f"{meta['n_legs']} decided legs; MLB ASG skipped={meta['mlb_asg_skipped']}"
    )

    payload, tables = build_leaders(bags, meta, date_to, top=args.top)
    _write_json(OUT_PRIMARY, payload)
    _write_json(OUT_TABLES, tables)
    _write_json(OUT_UI, payload)
    _write_json(OUT_TEMPLATES, payload)
    _write_json(OUT_MOBILE, payload)

    # Compact console tables (top cells)
    print("\n=== TOP LINE-CLASS CONSISTENCY LEADERS (sample) ===")
    for sport in ACTIVE_SPORTS:
        sport_rows = [r for r in payload["leaders"] if r["sport"] == sport]
        sport_rows.sort(key=lambda r: (-r["score"], -r["sample_n"]))
        by_pc = payload["sports"][sport].get("by_pick_class") or {}
        print(
            f"\n--- {sport} (from {sport_from_date(sport)}) "
            f"n={len(sport_rows)} classes={by_pc} top 12 ---"
        )
        for r in sport_rows[:12]:
            line_s = f"{r['reference_line']:.1f}" if r["reference_line"] is not None else "?"
            print(
                f"  {r['badge_prefix']:3s} {r['pick_class']:15s} {r['prop']:22s} "
                f"{r['player'][:28]:28s} @{line_s:>5s}  "
                f"HR={r['hit_rate']*100:5.1f}% n={r['sample_n']:3d}"
            )


if __name__ == "__main__":
    main()
