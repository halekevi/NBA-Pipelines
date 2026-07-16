#!/usr/bin/env python3
"""
Paired Standard ↔ Goblin edge analysis from graded_props_*.json archives.

For each slate day, join decided Standard and Goblin rows on
(sport, player, prop). Compare hit rates and a payout-adjusted EV proxy
using goblin_demon_multiplier.leg_factor(delta_pct).

Also tags pairs by prior Standard consistency (rolling HR on Standard for
the same player+prop before the slate day).

Outputs:
  data/reports/standard_goblin_paired_edge_latest.json
  data/reports/standard_goblin_paired_edge_pairs.csv
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.goblin_demon_multiplier import goblin_factor, leg_delta_pct, load_params  # noqa: E402


def _norm_name(s: object) -> str:
    t = str(s or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def _norm_prop(s: object) -> str:
    t = str(s or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = t.replace("(combo)", "").strip()
    return t


def _f(v: object) -> float | None:
    try:
        if v is None or str(v).strip() in ("", "—", "-", "nan", "None"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _hit(result: object) -> int | None:
    r = str(result or "").strip().upper()
    if r == "HIT":
        return 1
    if r == "MISS":
        return 0
    return None


def _load_day(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    date = str(raw.get("date") or path.stem.replace("graded_props_", ""))[:10]
    out: list[dict[str, Any]] = []
    for row in raw.get("props") or []:
        pt = str(row.get("pick_type") or "").strip().lower()
        if pt not in ("standard", "goblin"):
            continue
        # Goblin UNDER is not a real PP market side.
        direction = str(row.get("direction") or row.get("over_under") or "").strip().upper()
        if pt == "goblin" and direction == "UNDER":
            continue
        h = _hit(row.get("result"))
        if h is None:
            continue
        player = _norm_name(row.get("player"))
        prop = _norm_prop(row.get("prop") or row.get("prop_type"))
        if not player or not prop or "+" in player:
            continue  # skip combos for clean pairing
        line = _f(row.get("line"))
        if line is None:
            continue
        out.append(
            {
                "date": date,
                "sport": str(row.get("sport") or "").strip(),
                "player": player,
                "player_display": str(row.get("player") or "").strip(),
                "prop": prop,
                "prop_display": str(row.get("prop") or "").strip(),
                "pick_type": pt,
                "direction": direction or "OVER",
                "line": line,
                "hit": h,
                "tier": str(row.get("tier") or "").strip().upper(),
                "ml_prob": _f(row.get("ml_prob")),
                "edge": _f(row.get("edge")),
                "l10_streak": str(row.get("l10_streak") or "").strip().upper(),
            }
        )
    return out


def _distance_bucket(delta: float | None) -> str:
    if delta is None or delta <= 0:
        return "unknown"
    # Goblin lines are typically below Standard (OVER discount).
    if delta >= 0.95:
        return "near_std_(≥0.95)"
    if delta >= 0.85:
        return "0.85–0.95"
    if delta >= 0.75:
        return "0.75–0.85"
    if delta >= 0.65:
        return "0.65–0.75"
    return "<0.65"


def _hr(hits: list[int]) -> float | None:
    if not hits:
        return None
    return sum(hits) / len(hits)


def build_pairs(
    rows: list[dict[str, Any]],
    *,
    min_std_prior_n: int,
    high_std_hr: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = load_params()
    g_exp = float(params.get("G_EXP", 1.0))

    # Chronological Standard history for consistency prior.
    std_hist: dict[tuple[str, str, str], list[tuple[str, int]]] = defaultdict(list)
    by_day_key: dict[tuple[str, str, str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"standard": [], "goblin": []}
    )
    for r in sorted(rows, key=lambda x: x["date"]):
        key = (r["sport"], r["player"], r["prop"], r["date"])
        by_day_key[key][r["pick_type"]].append(r)

    pairs: list[dict[str, Any]] = []
    for (sport, player, prop, date), bags in sorted(by_day_key.items()):
        stds = bags["standard"]
        gobs = bags["goblin"]
        if not stds or not gobs:
            continue

        # Prefer one Standard + one Goblin: best Standard by |edge|, Goblin by easiest line for OVER.
        std = max(stds, key=lambda r: (r.get("edge") is not None, r.get("edge") or -999))
        gob = min(gobs, key=lambda r: r["line"])  # lower OVER line = easier Goblin

        hist_key = (sport, player, prop)
        prior = [h for d, h in std_hist[hist_key] if d < date]
        prior_n = len(prior)
        prior_hr = _hr(prior)

        delta = leg_delta_pct(gob["line"], std["line"])
        g_fac = goblin_factor(float(delta), g_exp) if delta is not None else None

        # Single-leg relative EV proxies (stake=1): p * factor − (1−p).
        # Standard factor = 1.0; Goblin uses curve factor.
        std_ev = float(std["hit"]) * 1.0 - (1.0 - float(std["hit"]))
        gob_ev = (
            float(gob["hit"]) * float(g_fac) - (1.0 - float(gob["hit"]))
            if g_fac is not None
            else None
        )

        same_dir = std["direction"] == gob["direction"]
        pair = {
            "date": date,
            "sport": sport,
            "player": std["player_display"] or player,
            "prop": std["prop_display"] or prop,
            "std_dir": std["direction"],
            "gob_dir": gob["direction"],
            "same_direction": same_dir,
            "pair_kind": (
                "same_over"
                if same_dir and std["direction"] == "OVER"
                else "std_under_gob_over"
                if std["direction"] == "UNDER" and gob["direction"] == "OVER"
                else "other"
            ),
            "std_line": std["line"],
            "gob_line": gob["line"],
            "delta_pct": round(float(delta), 4) if delta is not None else None,
            "distance_bucket": _distance_bucket(float(delta) if delta is not None else None),
            "gob_factor": round(float(g_fac), 4) if g_fac is not None else None,
            "std_hit": int(std["hit"]),
            "gob_hit": int(gob["hit"]),
            "std_tier": std["tier"],
            "gob_tier": gob["tier"],
            "std_ml_prob": std.get("ml_prob"),
            "gob_ml_prob": gob.get("ml_prob"),
            "prior_std_n": prior_n,
            "prior_std_hr": round(prior_hr, 4) if prior_hr is not None else None,
            "high_std_consistent": bool(
                prior_n >= min_std_prior_n and prior_hr is not None and prior_hr >= high_std_hr
            ),
            "std_ev_realized": round(std_ev, 4),
            "gob_ev_realized": round(gob_ev, 4) if gob_ev is not None else None,
            "ev_uplift_realized": (
                round(float(gob_ev) - float(std_ev), 4) if gob_ev is not None else None
            ),
        }
        pairs.append(pair)

        # Update Standard history after pairing this day.
        for s in stds:
            std_hist[hist_key].append((date, int(s["hit"])))

    meta = {
        "n_rows": len(rows),
        "n_pairs": len(pairs),
        "min_std_prior_n": min_std_prior_n,
        "high_std_hr": high_std_hr,
        "g_exp": g_exp,
    }
    return pairs, meta


def _agg(pairs: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not pairs:
        return {"label": label, "n": 0}
    std_hr = sum(p["std_hit"] for p in pairs) / len(pairs)
    gob_hr = sum(p["gob_hit"] for p in pairs) / len(pairs)
    deltas = [p["delta_pct"] for p in pairs if p.get("delta_pct") is not None]
    factors = [p["gob_factor"] for p in pairs if p.get("gob_factor") is not None]
    uplifts = [p["ev_uplift_realized"] for p in pairs if p.get("ev_uplift_realized") is not None]
    # Expected EV using empirical rates × mean factor (out-of-sample style summary).
    mean_fac = sum(factors) / len(factors) if factors else None
    ev_std = std_hr * 1.0 - (1.0 - std_hr)
    ev_gob = (gob_hr * mean_fac - (1.0 - gob_hr)) if mean_fac is not None else None
    return {
        "label": label,
        "n": len(pairs),
        "std_hr": round(std_hr, 4),
        "gob_hr": round(gob_hr, 4),
        "delta_hr_pp": round((gob_hr - std_hr) * 100, 2),
        "mean_delta_pct": round(sum(deltas) / len(deltas), 4) if deltas else None,
        "mean_gob_factor": round(mean_fac, 4) if mean_fac is not None else None,
        "mean_realized_ev_uplift": round(sum(uplifts) / len(uplifts), 4) if uplifts else None,
        "ev_std_from_hr": round(ev_std, 4),
        "ev_gob_from_hr": round(ev_gob, 4) if ev_gob is not None else None,
        "ev_edge_from_hr": round(ev_gob - ev_std, 4) if ev_gob is not None else None,
        "gob_beats_std_hr_share": round(
            sum(1 for p in pairs if p["gob_hit"] > p["std_hit"]) / len(pairs), 4
        ),
        "both_hit_share": round(
            sum(1 for p in pairs if p["std_hit"] == 1 and p["gob_hit"] == 1) / len(pairs), 4
        ),
        "std_hit_gob_miss_share": round(
            sum(1 for p in pairs if p["std_hit"] == 1 and p["gob_hit"] == 0) / len(pairs), 4
        ),
        "std_miss_gob_hit_share": round(
            sum(1 for p in pairs if p["std_hit"] == 0 and p["gob_hit"] == 1) / len(pairs), 4
        ),
    }


def summarize(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    cohorts: list[dict[str, Any]] = [
        _agg(pairs, "all_pairs"),
        _agg([p for p in pairs if p["pair_kind"] == "same_over"], "same_over"),
        _agg(
            [p for p in pairs if p["pair_kind"] == "std_under_gob_over"],
            "std_under_gob_over",
        ),
        _agg([p for p in pairs if p["high_std_consistent"]], "high_std_consistent"),
        _agg(
            [p for p in pairs if p["high_std_consistent"] and p["pair_kind"] == "same_over"],
            "high_std_consistent_same_over",
        ),
        _agg(
            [
                p
                for p in pairs
                if p["high_std_consistent"] and p["pair_kind"] == "std_under_gob_over"
            ],
            "high_std_consistent_std_under_gob_over",
        ),
    ]

    by_bucket: list[dict[str, Any]] = []
    for b in ("near_std_(≥0.95)", "0.85–0.95", "0.75–0.85", "0.65–0.75", "<0.65", "unknown"):
        sub = [p for p in pairs if p["distance_bucket"] == b and p["pair_kind"] == "same_over"]
        if sub:
            by_bucket.append(_agg(sub, f"same_over::{b}"))

    by_sport: list[dict[str, Any]] = []
    sports = sorted({p["sport"] for p in pairs})
    for sp in sports:
        sub = [p for p in pairs if p["sport"] == sp and p["pair_kind"] == "same_over"]
        if len(sub) >= 20:
            by_sport.append(_agg(sub, f"same_over::{sp}"))

    # Top players by EV edge among high-consistency same-OVER (min 3 pairs).
    player_rows: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for p in pairs:
        if not p["high_std_consistent"] or p["pair_kind"] != "same_over":
            continue
        grouped[(p["sport"], p["player"], p["prop"])].append(p)
    for (sport, player, prop), g in grouped.items():
        if len(g) < 3:
            continue
        a = _agg(g, f"{sport}|{player}|{prop}")
        a.update({"sport": sport, "player": player, "prop": prop})
        player_rows.append(a)
    player_rows.sort(key=lambda r: (r.get("ev_edge_from_hr") is not None, r.get("ev_edge_from_hr") or -9), reverse=True)

    return {
        "cohorts": cohorts,
        "by_distance_bucket_same_over": by_bucket,
        "by_sport_same_over": by_sport,
        "top_high_std_players_same_over": player_rows[:25],
        "bottom_high_std_players_same_over": list(reversed(player_rows[-10:])) if len(player_rows) >= 10 else [],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45, help="Lookback days of graded_props JSON")
    ap.add_argument("--min-std-prior-n", type=int, default=8)
    ap.add_argument("--high-std-hr", type=float, default=0.60)
    ap.add_argument(
        "--dir",
        type=str,
        default="",
        help="Directory of graded_props_*.json (default: ui_runner/templates)",
    )
    args = ap.parse_args()

    src = Path(args.dir) if args.dir else _REPO / "ui_runner" / "templates"
    files = sorted(src.glob("graded_props_*.json"))
    if args.days > 0 and len(files) > args.days:
        files = files[-args.days :]
    if not files:
        print(f"No graded_props JSON in {src}")
        return 1

    rows: list[dict[str, Any]] = []
    for fp in files:
        try:
            rows.extend(_load_day(fp))
        except Exception as e:
            print(f"skip {fp.name}: {e}")

    pairs, meta = build_pairs(
        rows,
        min_std_prior_n=int(args.min_std_prior_n),
        high_std_hr=float(args.high_std_hr),
    )
    summary = summarize(pairs)
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_dir": str(src),
        "files": [f.name for f in files],
        "date_span": {
            "first": files[0].stem.replace("graded_props_", ""),
            "last": files[-1].stem.replace("graded_props_", ""),
            "n_files": len(files),
        },
        "meta": meta,
        "summary": summary,
        "method": {
            "pair_key": "sport + player + prop + date (no combos)",
            "goblin_line": "lowest Goblin line that day",
            "standard_line": "Standard with max edge that day",
            "ev_proxy": "p*factor - (1-p); Standard factor=1.0; Goblin uses goblin_factor(delta_pct)",
            "high_std_consistent": f"prior Standard n>={args.min_std_prior_n} and HR>={args.high_std_hr}",
        },
    }

    report_dir = _REPO / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "standard_goblin_paired_edge_latest.json"
    # Keep JSON lean (no full pair dump).
    json_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    csv_path = report_dir / "standard_goblin_paired_edge_pairs.csv"
    pd.DataFrame(pairs).to_csv(csv_path, index=False)

    print(f"Files: {len(files)}  rows: {len(rows)}  pairs: {len(pairs)}")
    for c in summary["cohorts"]:
        if c["n"]:
            print(
                f"  {c['label']}: n={c['n']}  std_hr={c['std_hr']:.1%}  "
                f"gob_hr={c['gob_hr']:.1%}  Δhr={c['delta_hr_pp']:+.1f}pp  "
                f"ev_edge={c.get('ev_edge_from_hr')}"
            )
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    return 0


if __name__ == "__main__":
    # fix shebang typo guard
    raise SystemExit(main())
