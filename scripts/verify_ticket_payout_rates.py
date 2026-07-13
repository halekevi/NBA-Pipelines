#!/usr/bin/env python3
"""
Verify payout rates for generated MAIN/STRONG tickets and outstanding mix+Δ coverage.

Daily use (after ticket build / live capture):
  py -3.14 scripts/verify_ticket_payout_rates.py --date 2026-07-13
  py -3.14 scripts/verify_ticket_payout_rates.py --date 2026-07-13 --fill-missing-tickets
  py -3.14 scripts/verify_ticket_payout_rates.py --date 2026-07-13 --fill-missing-tickets --rebuild-rate-card

Writes:
  data/reports/ticket_payout_verify_<date>.json
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import collect_payout_data as cpd  # noqa: E402

LIVE_CDP = ROOT / "ui_runner" / "data" / "payout_ladder_live_cdp.json"
RATE_CARD = ROOT / "ui_runner" / "data" / "sg_delta_payout_rate_card_latest.json"
REPORTS = ROOT / "data" / "reports"


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _norm_delta_sig(parts: list[float]) -> str:
    vals = sorted(float(x) for x in parts if math.isfinite(float(x)) and float(x) > 0)
    return "+".join(f"{v:g}" for v in vals)


def _parse_delta_blob(raw: Any) -> list[float]:
    """Parse goblin_deltas whether stored as list, '1+1', '1,1', or char-sploded string."""
    if raw is None:
        return []
    if isinstance(raw, (int, float)):
        f = float(raw)
        return [f] if f > 0 else []
    if isinstance(raw, list):
        # Character-sploded ["1", ",", "1"] -> treat as joined string.
        if raw and all(isinstance(x, str) and len(x) <= 1 for x in raw):
            return _parse_delta_blob("".join(raw))
        out: list[float] = []
        for x in raw:
            if isinstance(x, (int, float)):
                f = float(x)
                if f > 0:
                    out.append(f)
            else:
                out.extend(_parse_delta_blob(x))
        return out
    text = str(raw).strip()
    if not text or text in {"—", "-", "nan", "None"}:
        return []
    out = []
    for part in text.replace("|", ",").replace("+", ",").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        f = _safe_float(part)
        if f is not None and f > 0:
            out.append(f)
    return out


def _leg_delta(leg: dict) -> float | None:
    for key in ("line_distance", "delta", "goblin_delta", "distance"):
        f = _safe_float(leg.get(key))
        if f is not None and f > 0:
            return f
    line = _safe_float(leg.get("line") or leg.get("played_line"))
    std = _safe_float(leg.get("standard_line") or leg.get("std_line"))
    if line is None or std is None:
        return None
    dist = abs(line - std)
    return dist if dist > 0 else None


def ticket_recipe(ticket: dict) -> dict[str, Any]:
    legs = ticket.get("legs") if isinstance(ticket.get("legs"), list) else []
    n_s = n_g = n_d = 0
    g_deltas: list[float] = []
    d_deltas: list[float] = []
    missing_g_delta = 0
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        pt = str(leg.get("pick_type") or leg.get("pick") or "Standard").strip().lower()
        if "demon" in pt:
            n_d += 1
            dist = _leg_delta(leg)
            if dist is None:
                missing_g_delta += 0  # demons tracked separately
            else:
                d_deltas.append(dist)
        elif "goblin" in pt:
            n_g += 1
            dist = _leg_delta(leg)
            if dist is None:
                missing_g_delta += 1
            else:
                g_deltas.append(dist)
        else:
            n_s += 1
    g_sig = _norm_delta_sig(g_deltas) if len(g_deltas) == n_g and n_g else (
        "" if n_g == 0 else "unknown"
    )
    if n_g > 0 and missing_g_delta:
        g_sig = "unknown"
    return {
        "n_legs": len(legs),
        "composition": f"{n_s}S+{n_g}G+{n_d}D",
        "n_standard": n_s,
        "n_goblin": n_g,
        "n_demon": n_d,
        "goblin_delta_sig": g_sig or ("—" if n_g == 0 else "unknown"),
        "demon_delta_sig": _norm_delta_sig(d_deltas) if d_deltas else ("—" if n_d == 0 else "unknown"),
        "missing_goblin_delta": missing_g_delta,
    }


def ticket_payout_status(ticket: dict) -> dict[str, Any]:
    pay = ticket.get("payout") if isinstance(ticket.get("payout"), dict) else {}
    src = str(pay.get("payout_source") or ticket.get("payout_source") or "").strip().lower()
    min_x = (
        _safe_float(pay.get("power_min_x"))
        or _safe_float(pay.get("display_min_x"))
        or _safe_float(ticket.get("display_min_x"))
        or _safe_float(ticket.get("power_min_x"))
    )
    return {
        "payout_source": src or "none",
        "display_min_x": min_x,
        "has_live_cdp": src == "live_cdp" and min_x is not None and min_x > 0,
    }


def load_ticket_rows(path: Path) -> list[dict[str, Any]]:
    """Same ticket pool as collect_payout_data.load_main_strong_tickets (all 2+ leg slips)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    date = str(data.get("date") or "")[:10]
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        group_name = str(g.get("group_name") or g.get("name") or "")
        for t in g.get("tickets") or []:
            if not isinstance(t, dict):
                continue
            legs = t.get("legs") if isinstance(t.get("legs"), list) else []
            if len(legs) < 2:
                continue
            recipe = ticket_recipe(t)
            pay = ticket_payout_status(t)
            rows.append(
                {
                    "ticket_id": str(t.get("ticket_id") or "").strip(),
                    "group_name": group_name,
                    "strong_builder": bool(t.get("strong_builder")),
                    "date": date or str(t.get("date") or "")[:10],
                    **recipe,
                    **pay,
                }
            )
    return rows


def build_live_index(live_path: Path) -> dict[tuple, list[float]]:
    """Map (n_legs, composition, goblin_sig) -> list of power floors."""
    if not live_path.is_file():
        return {}
    payload = json.loads(live_path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    index: dict[tuple, list[float]] = defaultdict(list)
    if not isinstance(rows, list):
        return {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("source") or "").lower() not in ("", "live_cdp"):
            continue
        n = int(_safe_float(r.get("n_legs")) or 0)
        comp = str(r.get("leg_composition") or "").strip()
        g_sig = _norm_delta_sig(_parse_delta_blob(r.get("goblin_deltas")))
        if not g_sig and "G" in comp.upper() and "+0G+" not in comp and not comp.endswith("+0G+0D"):
            # keep empty as unknown coverage key only for pure-S
            pass
        if "G" not in comp.upper() or "+0G+" in comp or comp.endswith("0G+0D") or comp.count("G") == 0:
            g_sig = "—"
        elif not g_sig:
            g_sig = "unknown"
        px = _safe_float(r.get("power_payout_x"))
        if n >= 2 and comp and px and px > 0:
            index[(n, comp, g_sig)].append(px)
    return dict(index)


def build_rate_card_index(path: Path) -> dict[tuple, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    cells = payload.get("cells") if isinstance(payload, dict) else []
    out: dict[tuple, dict[str, Any]] = {}
    for c in cells or []:
        if not isinstance(c, dict):
            continue
        n = int(c.get("n_legs") or 0)
        comp = str(c.get("composition") or "").strip()
        g_sig = str(c.get("goblin_delta_sig") or "—").strip() or "—"
        out[(n, comp, g_sig)] = c
    return out


def resolve_tickets_path(date: str, explicit: str = "") -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise SystemExit(f"tickets not found: {p}")
        return p
    candidates = [
        ROOT / "ui_runner" / "data" / f"combined_slate_tickets_{date}.json",
        ROOT / "outputs" / date / f"combined_slate_tickets_{date}.json",
        ROOT / "ui_runner" / "templates" / "tickets_latest.json",
        ROOT / "ui_runner" / "data" / "tickets_latest.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise SystemExit(f"No tickets JSON found for {date}")


def audit_tickets(
    tickets: list[dict[str, Any]],
    live_index: dict[tuple, list[float]],
    rate_index: dict[tuple, dict[str, Any]],
) -> dict[str, Any]:
    missing_live: list[dict] = []
    outstanding_rates: list[dict] = []
    covered: list[dict] = []
    recipe_counts: Counter = Counter()

    for t in tickets:
        n = int(t["n_legs"])
        comp = str(t["composition"])
        g_sig = str(t["goblin_delta_sig"])
        key = (n, comp, g_sig if t["n_goblin"] else "—")
        recipe_counts[f"{n}|{comp}|{key[2]}"] += 1

        live_floors = live_index.get(key) or []
        # Also try unknown-delta key collapse for pure standard
        if not live_floors and t["n_goblin"] == 0:
            live_floors = live_index.get((n, comp, "—")) or []

        rate_cell = rate_index.get(key) or rate_index.get((n, comp, "—"))
        rate_src = str((rate_cell or {}).get("source") or "")
        rate_status = str((rate_cell or {}).get("status") or "missing")
        rate_x = _safe_float((rate_cell or {}).get("power_min_x"))

        row = {
            "ticket_id": t["ticket_id"],
            "group_name": t["group_name"],
            "n_legs": n,
            "composition": comp,
            "goblin_delta_sig": g_sig,
            "ticket_payout_source": t["payout_source"],
            "ticket_display_min_x": t["display_min_x"],
            "has_live_cdp_on_ticket": t["has_live_cdp"],
            "live_cdp_recipe_hits": len(live_floors),
            "live_cdp_recipe_min_x": round(min(live_floors), 4) if live_floors else None,
            "rate_card_source": rate_src or None,
            "rate_card_status": rate_status,
            "rate_card_min_x": rate_x,
            "missing_goblin_delta": t.get("missing_goblin_delta") or 0,
        }

        if not t["has_live_cdp"]:
            missing_live.append(row)
        recipe_outstanding = (
            t["n_goblin"] > 0
            and g_sig == "unknown"
        ) or (
            not live_floors
            and rate_status in ("missing", "extrapolated")
            and t["n_goblin"] > 0
        ) or (
            t["n_goblin"] == 0 and not live_floors and rate_src != "live_cdp"
        )
        if recipe_outstanding:
            outstanding_rates.append(row)
        else:
            covered.append(row)

    return {
        "n_tickets": len(tickets),
        "n_with_live_cdp": sum(1 for t in tickets if t["has_live_cdp"]),
        "n_missing_live_cdp": len(missing_live),
        "n_outstanding_rates": len(outstanding_rates),
        "n_covered": len(covered),
        "recipe_counts": dict(recipe_counts.most_common()),
        "missing_live_cdp": missing_live,
        "outstanding_rates": outstanding_rates,
        "covered_sample": covered[:20],
    }


def run_fill_missing_tickets(
    *,
    date: str,
    tickets_path: Path,
    cdp_url: str,
    gentle: bool,
) -> int:
    out = REPORTS / f"payout_capture_{date}.json"
    script = ROOT / "scripts" / "collect_payout_data.py"
    args = [
        "py",
        "-3.14",
        "-X",
        "utf8",
        str(script),
        "--tickets",
        str(tickets_path),
        "--output",
        str(out),
        "--date",
        date,
        "--cdp-url",
        cdp_url,
        "--fields",
        "power_min_x,power_first_x,min_guarantee,flex_min",
        "--only-missing-live",
    ]
    if gentle:
        args.append("--gentle")
    print("[verify] fill-missing-tickets:", " ".join(args))
    return int(subprocess.call(args, cwd=str(ROOT)))


def run_rebuild_rate_card() -> int:
    script = ROOT / "scripts" / "build_sg_delta_rate_card.py"
    if not script.is_file():
        print("[verify] WARN: build_sg_delta_rate_card.py missing")
        return 0
    args = ["py", "-3.14", "-X", "utf8", str(script)]
    print("[verify] rebuild-rate-card:", " ".join(args))
    return int(subprocess.call(args, cwd=str(ROOT)))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify live payout coverage for generated tickets + outstanding mix/Δ rates"
    )
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--tickets", default="", help="Override tickets JSON path")
    ap.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    ap.add_argument(
        "--fill-missing-tickets",
        action="store_true",
        help="Re-scrape only MAIN/STRONG tickets still missing live_cdp floors (needs CDP)",
    )
    ap.add_argument(
        "--rebuild-rate-card",
        action="store_true",
        help="Rebuild sg_delta_payout_rate_card_latest.json after audit/fill",
    )
    ap.add_argument(
        "--gentle",
        action="store_true",
        help="Reserved for gentler CDP pacing when filling",
    )
    ap.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit 2 if any MAIN/STRONG ticket still lacks live_cdp after fill attempt",
    )
    args = ap.parse_args()
    date = str(args.date)[:10]
    tickets_path = resolve_tickets_path(date, str(args.tickets or "").strip())

    tickets = load_ticket_rows(tickets_path)
    live_index = build_live_index(LIVE_CDP)
    rate_index = build_rate_card_index(RATE_CARD)
    audit = audit_tickets(tickets, live_index, rate_index)

    report = {
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickets_path": str(tickets_path),
        "live_cdp_path": str(LIVE_CDP),
        "rate_card_path": str(RATE_CARD),
        "summary": {
            "n_tickets": audit["n_tickets"],
            "n_with_live_cdp": audit["n_with_live_cdp"],
            "n_missing_live_cdp": audit["n_missing_live_cdp"],
            "n_outstanding_rates": audit["n_outstanding_rates"],
            "n_covered": audit["n_covered"],
        },
        "recipe_counts": audit["recipe_counts"],
        "missing_live_cdp": audit["missing_live_cdp"],
        "outstanding_rates": audit["outstanding_rates"],
        "covered_sample": audit["covered_sample"],
        "actions": [],
    }

    fill_rc = None
    if args.fill_missing_tickets and audit["n_missing_live_cdp"] > 0:
        fill_rc = run_fill_missing_tickets(
            date=date,
            tickets_path=tickets_path,
            cdp_url=str(args.cdp_url),
            gentle=bool(args.gentle),
        )
        report["actions"].append(
            {"action": "fill_missing_tickets", "exit_code": fill_rc, "attempted": audit["n_missing_live_cdp"]}
        )
        # Re-audit after fill
        tickets = load_ticket_rows(tickets_path)
        live_index = build_live_index(LIVE_CDP)
        rate_index = build_rate_card_index(RATE_CARD)
        audit = audit_tickets(tickets, live_index, rate_index)
        report["summary"] = {
            "n_tickets": audit["n_tickets"],
            "n_with_live_cdp": audit["n_with_live_cdp"],
            "n_missing_live_cdp": audit["n_missing_live_cdp"],
            "n_outstanding_rates": audit["n_outstanding_rates"],
            "n_covered": audit["n_covered"],
        }
        report["missing_live_cdp"] = audit["missing_live_cdp"]
        report["outstanding_rates"] = audit["outstanding_rates"]
        report["recipe_counts"] = audit["recipe_counts"]
    elif args.fill_missing_tickets:
        report["actions"].append({"action": "fill_missing_tickets", "skipped": "none_missing"})

    if args.rebuild_rate_card:
        rc = run_rebuild_rate_card()
        report["actions"].append({"action": "rebuild_rate_card", "exit_code": rc})

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS / f"ticket_payout_verify_{date}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    s = report["summary"]
    print(
        f"[verify] tickets={s['n_tickets']} live={s['n_with_live_cdp']} "
        f"missing_live={s['n_missing_live_cdp']} outstanding_rates={s['n_outstanding_rates']} "
        f"-> {out_path}"
    )
    if s["n_missing_live_cdp"]:
        print("[verify] missing live_cdp ticket ids:")
        for row in report["missing_live_cdp"][:15]:
            print(
                f"  - {row['ticket_id']} {row['composition']} d={row['goblin_delta_sig']} "
                f"src={row['ticket_payout_source']}"
            )
    if s["n_outstanding_rates"]:
        print("[verify] outstanding mix/Δ rate coverage (no live recipe / extrapolated):")
        shown = set()
        for row in report["outstanding_rates"]:
            key = (row["composition"], row["goblin_delta_sig"])
            if key in shown:
                continue
            shown.add(key)
            print(
                f"  - {row['n_legs']}leg {row['composition']} Δ={row['goblin_delta_sig']} "
                f"rate={row['rate_card_status']}/{row['rate_card_source']}"
            )
            if len(shown) >= 20:
                break

    if args.fail_on_missing and s["n_missing_live_cdp"] > 0:
        return 2
    if fill_rc not in (None, 0):
        return 0  # non-blocking for daily
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
