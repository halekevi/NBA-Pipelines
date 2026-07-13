#!/usr/bin/env python3
"""
Validate payout ladder rates by building synthetic (fake) tickets on live PrizePicks.

For each ladder recipe (mix and/or Goblin-distance signature):
  1) Pick real board cards matching Standard/Goblin/Demon counts (+ target deltas)
  2) Build the slip via CDP and read power_min_x (Min Guarantee)
  3) Compare live floor vs ladder Avg / Min–Max

Usage:
  # Dry-run: print recipes + write fake ticket stubs (no CDP)
  py -3.14 scripts/validate_payout_ladder.py --dry-run

  # Full live validation (Chrome CDP on 9222, logged into PrizePicks)
  pwsh -File scripts/launch_prizepicks_chrome_cdp.ps1 -OpenBoard
  py -3.14 scripts/validate_payout_ladder.py --run --max-cases 40

Outputs:
  data/reports/payout_ladder_validation_<date>.json
  ui_runner/data/payout_ladder_validation_tickets.json  (fake tickets used)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "ui_runner"))

import collect_payout_data as cpd  # noqa: E402

LADDER_LOG = ROOT / "ui_runner" / "data" / "payout_ladder_log.csv"
LADDER_LIVE = ROOT / "ui_runner" / "data" / "payout_ladder_live_cdp.json"
FAKE_TICKETS_PATH = ROOT / "ui_runner" / "data" / "payout_ladder_validation_tickets.json"
REPORTS_DIR = ROOT / "data" / "reports"


def _norm_delta_sig(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    vals: list[float] = []
    for part in text.replace("|", ",").replace("+", ",").split(","):
        part = part.strip()
        if not part or part in {"—", "-"}:
            continue
        try:
            vals.append(float(part))
        except (TypeError, ValueError):
            continue
    if not vals:
        return ""
    vals.sort()
    return "+".join(f"{v:g}" for v in vals)


def _parse_sgd(comp: str) -> tuple[int, int, int]:
    s = g = d = 0
    for part in str(comp or "").split("+"):
        part = part.strip().upper()
        if not part:
            continue
        try:
            if part.endswith("S"):
                s = int(part[:-1] or 0)
            elif part.endswith("G"):
                g = int(part[:-1] or 0)
            elif part.endswith("D"):
                d = int(part[:-1] or 0)
        except ValueError:
            continue
    return s, g, d


def _card_distance(card: dict) -> float | None:
    try:
        dist = float(card.get("line_distance") or 0.0)
        if dist > 0:
            return dist
    except (TypeError, ValueError):
        pass
    try:
        line = float(card.get("line"))
        std = float(card.get("standard_line") or card.get("std_line"))
        dist = abs(line - std)
        return dist if dist > 0 else None
    except (TypeError, ValueError):
        return None


def load_ladder_recipes(*, include_mix: bool = True, include_delta: bool = True) -> list[dict[str, Any]]:
    """Load unique recipes from ladder CSV + live CDP file."""
    rows: list[dict[str, Any]] = []
    if LADDER_LOG.is_file():
        with LADDER_LOG.open("r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if isinstance(row, dict):
                    rows.append(row)
    if LADDER_LIVE.is_file():
        try:
            live = json.loads(LADDER_LIVE.read_text(encoding="utf-8"))
            for row in live.get("rows") or []:
                if isinstance(row, dict):
                    rows.append(row)
        except (OSError, json.JSONDecodeError):
            pass

    # Aggregate expected ranges
    buckets: dict[tuple, list[float]] = {}
    meta: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        try:
            n = int(float(r.get("n_legs") or 0))
        except (TypeError, ValueError):
            continue
        comp = str(r.get("leg_composition") or "").strip()
        if n < 2 or not comp:
            continue
        try:
            px = float(r.get("power_payout_x") or 0)
        except (TypeError, ValueError):
            continue
        if not (px > 0):
            continue
        g_sig = _norm_delta_sig(r.get("goblin_deltas"))
        d_sig = _norm_delta_sig(r.get("demon_deltas"))
        s_c, g_c, d_c = _parse_sgd(comp)

        if include_mix:
            key_m = ("mix", n, comp, "", "")
            buckets.setdefault(key_m, []).append(px)
            meta[key_m] = {"n_legs": n, "composition": comp, "n_standard": s_c, "n_goblin": g_c, "n_demon": d_c}

        if include_delta and (g_c or d_c):
            if g_c and (not g_sig or len(g_sig.split("+")) != g_c):
                continue
            if d_c and (not d_sig or len(d_sig.split("+")) != d_c):
                continue
            key_d = ("delta", n, comp, g_sig, d_sig)
            buckets.setdefault(key_d, []).append(px)
            meta[key_d] = {
                "n_legs": n,
                "composition": comp,
                "n_standard": s_c,
                "n_goblin": g_c,
                "n_demon": d_c,
                "goblin_delta_sig": g_sig,
                "demon_delta_sig": d_sig,
            }

    recipes: list[dict[str, Any]] = []
    for key, vals in sorted(buckets.items(), key=lambda kv: kv[0]):
        kind, n, comp, g_sig, d_sig = key
        info = dict(meta[key])
        info.update(
            {
                "kind": kind,
                "recipe_id": f"{kind}|{n}|{comp}|{g_sig}|{d_sig}".rstrip("|"),
                "samples": len(vals),
                "ladder_min_x": round(min(vals), 4),
                "ladder_max_x": round(max(vals), 4),
                "ladder_avg_x": round(sum(vals) / len(vals), 4),
            }
        )
        recipes.append(info)
    return recipes


def _pick_cards_for_recipe(
    recipe: dict[str, Any],
    *,
    standard: list[dict],
    goblins: list[dict],
    demons: list[dict],
    tol: float = 0.35,
) -> dict[str, Any] | None:
    """Choose unique-player board cards for a recipe. Prefer exact Goblin distances."""
    n_s = int(recipe.get("n_standard") or 0)
    n_g = int(recipe.get("n_goblin") or 0)
    n_d = int(recipe.get("n_demon") or 0)
    target_g = []
    if recipe.get("goblin_delta_sig"):
        target_g = [float(x) for x in str(recipe["goblin_delta_sig"]).split("+") if x]
    target_d = []
    if recipe.get("demon_delta_sig"):
        target_d = [float(x) for x in str(recipe["demon_delta_sig"]).split("+") if x]

    used: set[str] = set()
    picked: list[dict] = []
    matched_deltas: list[float] = []
    proxy = False

    def take(pool: list[dict], n: int, role: str, targets: list[float] | None = None) -> bool:
        nonlocal proxy
        if n <= 0:
            return True
        remaining = list(pool)
        for i in range(n):
            want = targets[i] if targets and i < len(targets) else None
            best = None
            best_score = 1e9
            for c in remaining:
                pk = cpd._norm(c.get("player"))
                if not pk or pk in used:
                    continue
                dist = _card_distance(c)
                if want is not None:
                    if dist is None:
                        score = 100.0
                    else:
                        score = abs(float(dist) - float(want))
                    if score > tol and score < 100:
                        # keep as fallback but prefer closer
                        pass
                else:
                    score = 0.0 if dist is not None else 1.0
                if score < best_score:
                    best_score = score
                    best = c
            if best is None:
                return False
            if want is not None and best_score > tol:
                proxy = True
            used.add(cpd._norm(best.get("player")))
            remaining = [c for c in remaining if c is not best]
            dist = _card_distance(best)
            leg = {
                "player": best.get("player"),
                "prop_type": best.get("prop_type"),
                "direction": "OVER",
                "line": best.get("line"),
                "pick_type": "Goblin" if role == "goblin" else ("Demon" if role == "demon" else "Standard"),
                "sport": str(best.get("league") or best.get("sport") or "WNBA").upper(),
                "line_distance": dist,
                "standard_line": best.get("standard_line"),
                "role": role,
            }
            picked.append(leg)
            if role == "goblin" and dist is not None:
                matched_deltas.append(float(dist))
        return True

    # Prefer goblins/demons first so standards don't steal players.
    if not take(goblins, n_g, "goblin", target_g or None):
        return None
    if not take(demons, n_d, "demon", target_d or None):
        return None
    if not take(standard, n_s, "standard", None):
        return None

    return {
        "legs": picked,
        "matched_goblin_deltas": matched_deltas,
        "proxy_match": proxy,
    }


def build_fake_tickets_payload(
    recipes: list[dict[str, Any]],
    *,
    standard: list[dict],
    goblins: list[dict],
    demons: list[dict],
    date_str: str,
    max_cases: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build tickets_latest-shaped payload of synthetic validation slips."""
    tickets: list[dict] = []
    plan_rows: list[dict] = []
    for i, recipe in enumerate(recipes, 1):
        if max_cases > 0 and len(tickets) >= max_cases:
            break
        # Prefer delta recipes when available; mix recipes fill gaps.
        pick = _pick_cards_for_recipe(recipe, standard=standard, goblins=goblins, demons=demons)
        if not pick:
            plan_rows.append({**recipe, "status": "unbuildable", "error": "no_matching_board_cards"})
            continue
        tid = f"{date_str}|LADDER_VAL|{recipe.get('kind')}|{i}"
        ticket = {
            "ticket_id": tid,
            "strong_builder": True,
            "n_legs": int(recipe["n_legs"]),
            "legs": pick["legs"],
            "ladder_recipe": {
                "kind": recipe.get("kind"),
                "composition": recipe.get("composition"),
                "goblin_delta_sig": recipe.get("goblin_delta_sig", ""),
                "demon_delta_sig": recipe.get("demon_delta_sig", ""),
                "ladder_avg_x": recipe.get("ladder_avg_x"),
                "ladder_min_x": recipe.get("ladder_min_x"),
                "ladder_max_x": recipe.get("ladder_max_x"),
                "samples": recipe.get("samples"),
                "proxy_match": pick["proxy_match"],
                "matched_goblin_deltas": pick["matched_goblin_deltas"],
            },
        }
        tickets.append(ticket)
        plan_rows.append(
            {
                **recipe,
                "status": "planned",
                "ticket_id": tid,
                "proxy_match": pick["proxy_match"],
                "matched_goblin_deltas": pick["matched_goblin_deltas"],
                "legs": [
                    {
                        "player": lg.get("player"),
                        "prop": lg.get("prop_type"),
                        "line": lg.get("line"),
                        "pick_type": lg.get("pick_type"),
                        "line_distance": lg.get("line_distance"),
                    }
                    for lg in pick["legs"]
                ],
            }
        )

    payload = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "purpose": "payout_ladder_validation",
        "groups": [
            {
                "name": "LADDER VALIDATION",
                "group_name": "LADDER VALIDATION",
                "tickets": tickets,
            }
        ],
    }
    return payload, plan_rows


def _verdict(live_x: float, recipe: dict[str, Any], *, rel_tol: float = 0.15, abs_tol: float = 0.5) -> str:
    lo = float(recipe.get("ladder_min_x") or 0)
    hi = float(recipe.get("ladder_max_x") or 0)
    avg = float(recipe.get("ladder_avg_x") or 0)
    if lo > 0 and hi > 0 and lo <= live_x <= hi:
        return "in_range"
    if avg > 0 and (abs(live_x - avg) <= abs_tol or abs(live_x - avg) / avg <= rel_tol):
        return "near_avg"
    return "mismatch"


def compare_capture_to_recipes(
    captured: list[dict],
    plan_rows: list[dict],
) -> list[dict[str, Any]]:
    by_tid = {str(c.get("ticket_id") or ""): c for c in captured if isinstance(c, dict)}
    out: list[dict[str, Any]] = []
    for plan in plan_rows:
        tid = str(plan.get("ticket_id") or "")
        row = dict(plan)
        cap = by_tid.get(tid)
        if not cap:
            if row.get("status") == "unbuildable":
                row["verdict"] = "skipped"
            else:
                row["verdict"] = "missing_capture"
            out.append(row)
            continue
        row["capture_status"] = cap.get("status")
        try:
            live_x = float(cap.get("power_min_x") or cap.get("min_x") or 0)
        except (TypeError, ValueError):
            live_x = 0.0
        row["live_power_min_x"] = live_x if live_x > 0 else None
        row["live_power_first_x"] = cap.get("power_first_x")
        if live_x > 0 and str(cap.get("status") or "").lower() in ("ok", "partial"):
            row["verdict"] = _verdict(live_x, plan)
            avg = float(plan.get("ladder_avg_x") or 0)
            row["delta_vs_ladder_avg"] = round(live_x - avg, 4) if avg else None
        else:
            row["verdict"] = "capture_failed"
            row["error"] = cap.get("error")
        out.append(row)
    return out


def scrape_board_pools(cdp_url: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Open PP boards and return (standard, goblin, demon) card pools with distances."""
    p, browser, context, page = cpd.connect_existing_browser(cdp_url)
    try:
        best_cards: list[dict] = []
        best_score = -1
        for league_id, label in ((3, "WNBA"), (7, "NBA"), (2, "MLB")):
            try:
                url = f"https://app.prizepicks.com/board?league_id={league_id}"
                print(f"[validate] navigate {label} -> {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(2500)
            except Exception as e:
                print(f"[validate] navigate {label} skipped: {e}")
                continue
            frame = cpd.find_prizepicks_frame(page)
            cpd.ensure_popular_filter(frame, page)
            cpd.dismiss_modal(frame, page)
            cards = cpd.expand_card_pool(frame, page)
            n_g = sum(1 for c in cards if str(c.get("pick_type") or "").lower() == "goblin")
            n_s = sum(1 for c in cards if str(c.get("pick_type") or "").lower() == "standard")
            n_d = sum(1 for c in cards if str(c.get("pick_type") or "").lower() == "demon")
            print(f"[validate] {label} cards={len(cards)} S={n_s} G={n_g} D={n_d}")
            score = min(n_g, 4) * 10 + min(n_s, 4) * 3 + min(n_d, 2) * 5
            if score > best_score and len(cards) >= 4:
                best_score = score
                # stamp league for sport routing
                stamped = []
                for c in cards:
                    c2 = dict(c)
                    c2["league"] = label
                    c2["sport"] = label
                    stamped.append(c2)
                best_cards = stamped
            if n_g >= 3 and n_s >= 2:
                break

        board_std = cpd._build_std_map_from_board_cards(best_cards)
        standard: list[dict] = []
        goblins: list[dict] = []
        demons: list[dict] = []
        for c in best_cards:
            try:
                line_val = float(c.get("line") or 0)
            except (TypeError, ValueError):
                continue
            pt = str(c.get("pick_type") or "").lower()
            key = (cpd._norm(c.get("player")), cpd._norm(c.get("prop_type")))
            std_line = board_std.get(key)
            c2 = dict(c)
            if std_line is not None:
                c2["standard_line"] = std_line
                c2["line_distance"] = abs(line_val - float(std_line))
            if "demon" in pt:
                demons.append(c2)
            elif "goblin" in pt:
                if c2.get("line_distance") is None and std_line:
                    c2["line_distance"] = abs(line_val - float(std_line))
                goblins.append(c2)
            else:
                if line_val >= 1.0:
                    standard.append(c2)
        print(f"[validate] pools standard={len(standard)} goblin={len(goblins)} demon={len(demons)}")
        return standard, goblins, demons
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate payout ladder rates with synthetic tickets")
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    ap.add_argument("--max-cases", type=int, default=40, help="Max synthetic tickets to build/capture")
    ap.add_argument("--mix-only", action="store_true", help="Only mix-level recipes (ignore exact deltas)")
    ap.add_argument("--delta-only", action="store_true", help="Only Goblin-distance recipes")
    ap.add_argument("--dry-run", action="store_true", help="List recipes / write stubs without CDP")
    ap.add_argument("--run", action="store_true", help="Full CDP build + capture + compare")
    ap.add_argument("--rel-tol", type=float, default=0.15)
    ap.add_argument("--abs-tol", type=float, default=0.5)
    args = ap.parse_args()
    date_str = str(args.date)[:10]

    include_mix = not bool(args.delta_only)
    include_delta = not bool(args.mix_only)
    recipes = load_ladder_recipes(include_mix=include_mix, include_delta=include_delta)
    # Prefer delta recipes first (more informative), then mix
    recipes.sort(key=lambda r: (0 if r.get("kind") == "delta" else 1, r.get("n_legs") or 99, r.get("composition") or ""))
    print(f"[validate] loaded {len(recipes)} ladder recipes (mix={include_mix} delta={include_delta})")

    if args.dry_run and not args.run:
        # Write recipe checklist without board matching
        out = {
            "date": date_str,
            "mode": "dry_run",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_recipes": len(recipes),
            "recipes": recipes[: max(1, int(args.max_cases)) ] if args.max_cases else recipes,
            "note": "Start Chrome CDP then re-run with --run to build fake tickets and capture live floors.",
        }
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"payout_ladder_validation_{date_str}.json"
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"[validate] dry-run plan -> {path}")
        for r in out["recipes"][:25]:
            print(
                f"  {r['kind']:5} {r['n_legs']}L {r['composition']:12} "
                f"GΔ={r.get('goblin_delta_sig') or '—':12} "
                f"avg={r['ladder_avg_x']} [{r['ladder_min_x']}-{r['ladder_max_x']}] n={r['samples']}"
            )
        if len(out["recipes"]) > 25:
            print(f"  ... +{len(out['recipes']) - 25} more")
        return 0

    if not args.run and not args.dry_run:
        print("[validate] pass --dry-run or --run")
        return 2

    # Live path
    try:
        import urllib.request

        urllib.request.urlopen(f"{args.cdp_url.rstrip('/')}/json/version", timeout=3)
    except Exception as e:
        print(f"[validate] CDP not reachable at {args.cdp_url}: {e}")
        print("  Launch: pwsh -File scripts/launch_prizepicks_chrome_cdp.ps1 -OpenBoard")
        return 1

    standard, goblins, demons = scrape_board_pools(args.cdp_url)
    if len(standard) + len(goblins) < 4:
        print("[validate] FATAL: not enough board cards")
        return 1

    payload, plan_rows = build_fake_tickets_payload(
        recipes,
        standard=standard,
        goblins=goblins,
        demons=demons,
        date_str=date_str,
        max_cases=int(args.max_cases),
    )
    FAKE_TICKETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAKE_TICKETS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    n_planned = sum(1 for p in plan_rows if p.get("status") == "planned")
    n_skip = sum(1 for p in plan_rows if p.get("status") == "unbuildable")
    print(f"[validate] fake tickets -> {FAKE_TICKETS_PATH} planned={n_planned} unbuildable={n_skip}")

    capture_path = REPORTS_DIR / f"payout_ladder_validation_capture_{date_str}.json"
    print(f"[validate] capturing live floors for {n_planned} synthetic tickets...")
    rc = cpd.capture_tickets_from_board(
        tickets_path=FAKE_TICKETS_PATH,
        output_path=capture_path,
        fields=["power_min_x", "power_first_x", "min_guarantee"],
        cdp_url=args.cdp_url,
        entry_amount=1.0,
        max_cases=int(args.max_cases),
        delay_sec=0.5,
        write_back=False,
        date_override=date_str,
        strict_lines=False,  # validation may use nearest-line proxies when deltas are sparse
    )
    captured = []
    if capture_path.is_file():
        try:
            captured = json.loads(capture_path.read_text(encoding="utf-8")).get("slips") or []
        except (OSError, json.JSONDecodeError):
            captured = []

    # Attach recipe meta onto plan rows that were planned
    recipe_by_tid = {}
    for t in payload["groups"][0]["tickets"]:
        recipe_by_tid[t["ticket_id"]] = {**(t.get("ladder_recipe") or {}), "ticket_id": t["ticket_id"]}
    for p in plan_rows:
        tid = p.get("ticket_id")
        if tid and tid in recipe_by_tid:
            p.update({k: v for k, v in recipe_by_tid[tid].items() if k not in p or p.get(k) in (None, "")})

    results = compare_capture_to_recipes(captured, plan_rows)
    # Override verdicts with CLI tols
    for r in results:
        live = r.get("live_power_min_x")
        if live and r.get("verdict") in ("in_range", "near_avg", "mismatch"):
            r["verdict"] = _verdict(float(live), r, rel_tol=float(args.rel_tol), abs_tol=float(args.abs_tol))

    counts = {
        "in_range": 0,
        "near_avg": 0,
        "mismatch": 0,
        "capture_failed": 0,
        "unbuildable": 0,
        "skipped": 0,
        "missing_capture": 0,
    }
    for r in results:
        v = str(r.get("verdict") or "skipped")
        counts[v] = counts.get(v, 0) + 1

    report = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cdp_url": args.cdp_url,
        "fake_tickets_path": str(FAKE_TICKETS_PATH),
        "capture_path": str(capture_path),
        "capture_exit": rc,
        "summary": counts,
        "n_results": len(results),
        "results": results,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"payout_ladder_validation_{date_str}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== LADDER VALIDATION SUMMARY ===")
    for k, v in counts.items():
        if v:
            print(f"  {k}: {v}")
    print(f"report -> {report_path}")
    print("\nMismatches / failures:")
    shown = 0
    for r in results:
        if r.get("verdict") in ("mismatch", "capture_failed", "unbuildable"):
            print(
                f"  [{r.get('verdict')}] {r.get('composition')} "
                f"GΔ={r.get('goblin_delta_sig') or '—'} "
                f"ladder_avg={r.get('ladder_avg_x')} live={r.get('live_power_min_x')} "
                f"err={r.get('error')}"
            )
            shown += 1
            if shown >= 30:
                break
    if shown == 0:
        print("  (none)")

    # Soft success if we validated anything in-range/near
    ok_n = counts.get("in_range", 0) + counts.get("near_avg", 0)
    return 0 if ok_n > 0 else (1 if counts.get("mismatch", 0) else rc)


if __name__ == "__main__":
    raise SystemExit(main())
