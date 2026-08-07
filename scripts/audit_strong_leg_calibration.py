#!/usr/bin/env python3
"""
Board-selected STRONG/MAIN leg calibration by sport.

Compares predicted leg probabilities (ml_prob / leg_prob_used / hit_rate) against
graded outcomes for legs that appeared on published tickets.

Outputs:
  data/reports/strong_leg_calibration_latest.json
  data/reports/strong_leg_calibration_<date>.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "data" / "reports"


def _norm_sport(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if s in ("SOC", "FOOTBALL"):
        return "SOCCER"
    return s


def _norm_name(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw or "").strip().lower())


def _norm_prop(raw: Any) -> str:
    return re.sub(r"[\s_\-]+", " ", str(raw or "").strip().lower())


def _safe_float(v: Any) -> float | None:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_ticket_legs(paths: list[Path]) -> list[dict[str, Any]]:
    legs: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        board_date = str(data.get("date") or "")[:10]
        for group in data.get("groups") or []:
            gname = str(group.get("group_name") or "")
            track = "STRONG" if "STRONG" in gname.upper() else "MAIN"
            for ticket in group.get("tickets") or []:
                pay = ticket.get("payout") or {}
                rec = str(pay.get("recommendation") or "").upper()
                for leg in ticket.get("legs") or []:
                    sport = _norm_sport(leg.get("sport"))
                    player = _norm_name(leg.get("player"))
                    prop = _norm_prop(leg.get("prop") or leg.get("prop_type") or leg.get("stat_type"))
                    direction = str(leg.get("direction") or leg.get("dir") or "").upper().strip()
                    if not (sport and player and direction):
                        continue
                    legs.append(
                        {
                            "board_date": str(leg.get("game_date") or board_date)[:10],
                            "track": track,
                            "recommendation": rec,
                            "sport": sport,
                            "player": player,
                            "prop": prop,
                            "direction": direction,
                            "line": _safe_float(leg.get("line")),
                            "ml_prob": _safe_float(leg.get("ml_prob")),
                            "leg_prob_used": _safe_float(leg.get("leg_prob_used")),
                            "hit_rate": _safe_float(leg.get("hit_rate") or leg.get("composite_hit_rate")),
                            "edge": _safe_float(leg.get("edge") or leg.get("abs_edge")),
                            "prop_quality_score": _safe_float(leg.get("prop_quality_score")),
                            "source_file": str(path.name),
                        }
                    )
    return legs


def _load_graded_props_json(root: Path, min_date: str) -> pd.DataFrame:
    """Primary graded source used by recalibrate_ml_prob_scalars."""
    paths = sorted((root / "mobile" / "www").glob("graded_props_*.json"))
    paths += sorted((root / "ui_runner" / "templates").glob("graded_props_*.json"))
    paths += sorted((root / "data").glob("graded_props_*.json"))
    rows: list[dict[str, Any]] = []
    for p in paths:
        stem_date = ""
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", p.name)
        if m:
            stem_date = m.group(1)
        if min_date and stem_date and stem_date < min_date:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        props = data if isinstance(data, list) else data.get("props") or data.get("rows") or []
        if not isinstance(props, list):
            continue
        for row in props:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or row.get("outcome") or row.get("grade") or "").upper()
            if result not in ("HIT", "MISS", "WIN", "LOSS", "W", "L"):
                continue
            rows.append(
                {
                    "sport": _norm_sport(row.get("sport")),
                    "player": _norm_name(row.get("player") or row.get("player_name")),
                    "prop": _norm_prop(row.get("prop") or row.get("prop_type") or row.get("stat_type")),
                    "direction": str(row.get("direction") or row.get("dir") or "").upper().strip(),
                    "result": result,
                    "game_date": str(row.get("game_date") or row.get("date") or stem_date)[:10],
                    "pred": _safe_float(row.get("ml_prob") or row.get("leg_prob_used")),
                    "_file": p.name,
                    "hit": 1 if result in ("HIT", "WIN", "W") else 0,
                }
            )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _load_graded_legs(root: Path, min_date: str) -> pd.DataFrame:
    json_df = _load_graded_props_json(root, min_date)
    if not json_df.empty:
        return json_df

    rows: list[pd.DataFrame] = []
    for p in sorted((root / "outputs").rglob("combined_tickets_graded_*.xlsx")):
        try:
            xl = pd.ExcelFile(p)
        except Exception:
            continue
        sheet = "LEG_RESULTS" if "LEG_RESULTS" in xl.sheet_names else None
        if sheet is None:
            continue
        try:
            df = pd.read_excel(p, sheet_name=sheet)
        except Exception:
            continue
        if df.empty:
            continue
        df["_file"] = p.name
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    g = pd.concat(rows, ignore_index=True)
    # Normalize columns
    colmap = {c.lower().strip().replace(" ", "_"): c for c in g.columns}
    def col(*names: str) -> str | None:
        for n in names:
            if n in colmap:
                return colmap[n]
            if n in g.columns:
                return n
        for c in g.columns:
            if str(c).lower().replace(" ", "_") in names:
                return c
        return None

    sport_c = col("sport")
    player_c = col("player", "player_name")
    prop_c = col("prop", "prop_type", "stat_type")
    dir_c = col("direction", "dir", "over_under")
    result_c = col("result", "outcome", "grade")
    date_c = col("game_date", "slate_date", "date", "file_date")
    ml_c = col("ml_prob", "leg_prob_used", "hit_prob_selected")
    if not all([sport_c, player_c, result_c]):
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "sport": g[sport_c].map(_norm_sport),
            "player": g[player_c].map(_norm_name),
            "prop": g[prop_c].map(_norm_prop) if prop_c else "",
            "direction": g[dir_c].astype(str).str.upper().str.strip() if dir_c else "",
            "result": g[result_c].astype(str).str.upper().str.strip(),
            "game_date": g[date_c].astype(str).str[:10] if date_c else "",
            "pred": pd.to_numeric(g[ml_c], errors="coerce") if ml_c else pd.NA,
            "_file": g["_file"],
        }
    )
    out = out[out["result"].isin(["HIT", "MISS", "WIN", "LOSS", "W", "L"])].copy()
    out["hit"] = out["result"].isin(["HIT", "WIN", "W"]).astype(int)
    if min_date:
        out = out[(out["game_date"] == "") | (out["game_date"] >= min_date)]
    return out


def _match_board_to_graded(
    board_legs: list[dict[str, Any]],
    graded: pd.DataFrame,
) -> list[dict[str, Any]]:
    if graded.empty or not board_legs:
        return []
    # Index graded by (sport, player, direction) then prop fuzzy
    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in graded.to_dict(orient="records"):
        by_key[(row["sport"], row["player"], row["direction"])].append(row)

    matched: list[dict[str, Any]] = []
    for leg in board_legs:
        cands = by_key.get((leg["sport"], leg["player"], leg["direction"])) or []
        if not cands:
            continue
        # Prefer prop match when available
        prop = leg.get("prop") or ""
        chosen = None
        if prop:
            for c in cands:
                if c.get("prop") and (prop in c["prop"] or c["prop"] in prop):
                    chosen = c
                    break
        if chosen is None:
            chosen = cands[0]
        pred = leg.get("leg_prob_used") or leg.get("ml_prob") or leg.get("hit_rate")
        matched.append(
            {
                **leg,
                "graded_hit": int(chosen["hit"]),
                "graded_date": chosen.get("game_date"),
                "graded_file": chosen.get("_file"),
                "pred_used": _safe_float(pred),
                "pred_source": (
                    "leg_prob_used"
                    if leg.get("leg_prob_used") is not None
                    else "ml_prob"
                    if leg.get("ml_prob") is not None
                    else "hit_rate"
                    if leg.get("hit_rate") is not None
                    else None
                ),
            }
        )
    return matched


def _summarize(matched: list[dict[str, Any]]) -> dict[str, Any]:
    by_sport: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in matched:
        by_sport[row["sport"]].append(row)

    sports: dict[str, Any] = {}
    for sport, rows in sorted(by_sport.items()):
        preds = [r["pred_used"] for r in rows if r.get("pred_used") is not None]
        hits = [r["graded_hit"] for r in rows]
        edges = [r["edge"] for r in rows if r.get("edge") is not None]
        pq = [r["prop_quality_score"] for r in rows if r.get("prop_quality_score") is not None]
        mean_pred = float(sum(preds) / len(preds)) if preds else None
        actual = float(sum(hits) / len(hits)) if hits else None
        gap = (mean_pred - actual) if (mean_pred is not None and actual is not None) else None
        sports[sport] = {
            "n_matched": len(rows),
            "n_with_pred": len(preds),
            "mean_pred": round(mean_pred, 4) if mean_pred is not None else None,
            "actual_hr": round(actual, 4) if actual is not None else None,
            "calibration_gap": round(gap, 4) if gap is not None else None,
            "overconfident": bool(gap is not None and gap > 0.08),
            "mean_edge": round(sum(edges) / len(edges), 3) if edges else None,
            "mean_prop_quality": round(sum(pq) / len(pq), 4) if pq else None,
            "strong_n": sum(1 for r in rows if r.get("recommendation") == "STRONG"),
            "ok_n": sum(1 for r in rows if r.get("recommendation") == "OK"),
        }
    return sports


def _retrain_sport_calibration(root: Path, min_date: str | None = None) -> dict[str, Any]:
    """Fallback sport-level calibration from retrain_dataset when graded ticket match is thin."""
    path = root / "data" / "retrain_dataset.csv"
    if not path.is_file():
        return {}
    usecols = ["sport", "ml_prob", "result", "hit", "pick_type", "direction", "file_date"]
    try:
        df = pd.read_csv(path, usecols=lambda c: c in usecols or c.lower() in usecols, low_memory=False)
    except ValueError:
        df = pd.read_csv(path, low_memory=False)
    df["sport"] = df["sport"].map(_norm_sport)
    df["ml_prob"] = pd.to_numeric(df.get("ml_prob"), errors="coerce")
    if "file_date" in df.columns and min_date:
        fd = df["file_date"].astype(str).str[:10]
        df = df[(fd == "") | (fd >= min_date)]
    hit = pd.to_numeric(df.get("hit"), errors="coerce")
    if "result" in df.columns:
        ru = df["result"].astype(str).str.upper().str.strip()
        hit = hit.mask(ru.isin(["HIT", "WIN", "W"]), 1)
        hit = hit.mask(ru.isin(["MISS", "LOSS", "L"]), 0)
        df = df.loc[~ru.eq("PUSH")].copy()
        hit = hit.loc[df.index]
    df["_hit"] = hit
    df = df[df["ml_prob"].notna() & df["_hit"].isin([0, 1])]
    out: dict[str, Any] = {}
    for sport, g in df.groupby("sport"):
        if len(g) < 100:
            continue
        mean_pred = float(g["ml_prob"].mean())
        actual = float(g["_hit"].mean())
        out[str(sport)] = {
            "n": int(len(g)),
            "mean_pred": round(mean_pred, 4),
            "actual_hr": round(actual, 4),
            "calibration_gap": round(mean_pred - actual, 4),
            "overconfident": (mean_pred - actual) > 0.08,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-date", default="2026-07-01", help="Graded/ticket lower bound YYYY-MM-DD")
    ap.add_argument("--out-date", default=date.today().isoformat())
    args = ap.parse_args()

    ticket_paths = [
        REPO_ROOT / "ui_runner" / "templates" / "tickets_latest.json",
        REPO_ROOT / "mobile" / "www" / "tickets_latest.json",
    ]
    # Also pull recent dated ticket JSONs if present
    for p in sorted((REPO_ROOT / "outputs").glob("**/combined_slate_tickets_*.json"))[-30:]:
        ticket_paths.append(p)
    for p in sorted((REPO_ROOT / "ui_runner" / "data").glob("combined_slate_tickets_*.json"))[-20:]:
        ticket_paths.append(p)

    board_legs = _load_ticket_legs(ticket_paths)
    # Prefer STRONG/OK only for primary audit
    focus = [x for x in board_legs if x.get("recommendation") in ("STRONG", "OK") or x.get("track") == "STRONG"]
    graded = _load_graded_legs(REPO_ROOT, args.min_date)
    matched = _match_board_to_graded(focus, graded)
    sport_summary = _summarize(matched)
    retrain = _retrain_sport_calibration(REPO_ROOT, min_date=args.min_date)

    # Recommendations
    recs: list[str] = []
    for sport, s in sport_summary.items():
        gap = s.get("calibration_gap")
        if gap is not None and gap > 0.10 and s.get("n_matched", 0) >= 20:
            recs.append(
                f"{sport}: board-matched overconfident (+{gap:.2f}); "
                f"consider raising STRONG/MAIN floors before cutting weights."
            )
        if gap is not None and gap < -0.08 and s.get("n_matched", 0) >= 20:
            recs.append(f"{sport}: underconfident ({gap:.2f}); avoid further scalar cuts.")
    for sport, s in retrain.items():
        if sport == "TENNIS" and s.get("overconfident"):
            recs.append(
                f"TENNIS retrain window overconfident (+{s['calibration_gap']:.2f}, n={s['n']}); "
                "do not compare raw edge to MLB/WNBA."
            )

    # Edge unit warning from current board
    edge_by = defaultdict(list)
    for leg in focus:
        if leg.get("edge") is not None:
            edge_by[leg["sport"]].append(float(leg["edge"]))
    edge_means = {
        sp: round(sum(v) / len(v), 3) for sp, v in edge_by.items() if v
    }
    if edge_means.get("TENNIS", 0) > 2 * max(edge_means.get("MLB", 0.01), edge_means.get("WNBA", 0.01), 0.01):
        recs.append(
            "Raw edge means are not cross-sport comparable (Tennis >> MLB/WNBA). "
            "Rank with prop_quality_score / calibrated ml_prob."
        )

    payload = {
        "generated_at": _utc_now(),
        "min_date": args.min_date,
        "board_legs_loaded": len(board_legs),
        "focus_legs": len(focus),
        "graded_rows": int(len(graded)),
        "matched_legs": len(matched),
        "board_matched_by_sport": sport_summary,
        "retrain_window_by_sport": retrain,
        "current_board_mean_edge_by_sport": edge_means,
        "recommendations": recs,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    dated = REPORT_DIR / f"strong_leg_calibration_{args.out_date}.json"
    latest = REPORT_DIR / "strong_leg_calibration_latest.json"
    text = json.dumps(payload, indent=2)
    dated.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(f"[strong-calib] wrote {dated}")
    print(f"[strong-calib] matched={len(matched)} focus={len(focus)} graded={len(graded)}")
    for sp, s in sport_summary.items():
        print(
            f"  board {sp}: n={s['n_matched']} pred={s['mean_pred']} "
            f"actual={s['actual_hr']} gap={s['calibration_gap']} edge={s['mean_edge']}"
        )
    for sp, s in sorted(retrain.items()):
        if sp in ("TENNIS", "MLB", "WNBA", "SOCCER"):
            print(
                f"  retrain {sp}: n={s['n']} pred={s['mean_pred']} "
                f"actual={s['actual_hr']} gap={s['calibration_gap']}"
            )
    for r in recs:
        print(f"  REC: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
