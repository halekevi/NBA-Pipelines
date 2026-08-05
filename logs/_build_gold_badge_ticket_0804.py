"""Build 2026-08-04 gold-badge max-leg no-dupe-player ticket artifact."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_rate_card_cells(card: dict) -> list[dict]:
    for key in ("cells", "rows", "rate_card", "entries", "ladder", "observations"):
        val = card.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict) and "composition" in val[0]:
            return val
    for val in card.values():
        if isinstance(val, list) and val and isinstance(val[0], dict) and "composition" in val[0]:
            return val
        if isinstance(val, dict):
            nested = _load_rate_card_cells(val)
            if nested:
                return nested
    return []


def main() -> int:
    slate = json.loads((ROOT / "mobile/www/slate_latest.json").read_text(encoding="utf-8"))
    gold = json.loads((ROOT / "logs/_gold_badge_matches_2026-08-04.json").read_text(encoding="utf-8"))
    picks = slate.get("picks") or []

    selected_specs = [
        ("Maria Conde", "Rebounds", 3.5, "OVER", "Goblin"),
        ("Marina Mabrey", "Assists", 2.5, "OVER", "Goblin"),
        ("Gabby Williams", "Pts+Asts", 16.5, "UNDER", "Standard"),
        ("Janelle Salaün", "Rebounds", 4.0, "UNDER", "Standard"),
        ("Kayla Thornton", "Offensive Rebounds", 1.5, "UNDER", "Standard"),
        ("Veronica Burton", "Pts+Asts", 19.5, "UNDER", "Standard"),
    ]

    def find_pick(player, prop, line, direction, pick_type):
        for p in picks:
            if str(p.get("sport") or "").upper() != "WNBA":
                continue
            if str(p.get("player") or "") != player:
                continue
            if str(p.get("prop") or "") != prop:
                continue
            if abs(float(p.get("line")) - float(line)) > 0.01:
                continue
            if str(p.get("dir") or "").upper() != direction:
                continue
            if str(p.get("pick_type") or "").title() != pick_type:
                continue
            return p
        return None

    def find_std_sibling(player, prop):
        cands = []
        for p in picks:
            if str(p.get("sport") or "").upper() != "WNBA":
                continue
            if str(p.get("player") or "") != player:
                continue
            if str(p.get("prop") or "") != prop:
                continue
            if str(p.get("pick_type") or "").title() != "Standard":
                continue
            if str(p.get("dir") or "").upper() != "OVER":
                continue
            cands.append(float(p["line"]))
        return min(cands) if cands else None

    badge_by_key = {}
    for m in gold.get("matches") or []:
        key = (m["player"], m["prop"], float(m["line"]), m["direction"], m["pick_type"])
        badge_by_key[key] = m

    legs = []
    for player, prop, line, direction, pick_type in selected_specs:
        row = find_pick(player, prop, line, direction, pick_type)
        if not row:
            raise SystemExit(f"MISSING SLATE ROW: {player} {prop} {line} {direction} {pick_type}")
        gm = badge_by_key.get((player, prop, float(line), direction, pick_type), {})
        std_line = None
        goblin_delta = None
        if pick_type == "Goblin":
            std_line = find_std_sibling(player, prop)
            if std_line is not None:
                goblin_delta = round(float(std_line) - float(line), 2)
        legs.append(
            {
                "sport": "WNBA",
                "player": player,
                "team": row.get("team"),
                "opp": row.get("opp"),
                "prop": prop,
                "prop_type": prop,
                "line": float(line),
                "direction": direction,
                "dir": direction,
                "pick_type": pick_type,
                "pick": pick_type,
                "badge": gm.get("badge"),
                "badge_hit_rate": gm.get("hit_rate"),
                "badge_sample_n": gm.get("sample_n"),
                "strict_05": gm.get("strict_05"),
                "leader_line": gm.get("leader_line"),
                "delta_vs_leader": gm.get("delta"),
                "pick_class": gm.get("pick_class"),
                "edge": row.get("edge"),
                "slate_hit_rate": row.get("hit_rate"),
                "game_time": row.get("game_time"),
                "std_line": std_line,
                "goblin_delta": goblin_delta,
                "initials": row.get("initials"),
            }
        )

    players = [l["player"] for l in legs]
    assert len(players) == len(set(p.lower() for p in players)), players

    g_deltas = sorted(l["goblin_delta"] for l in legs if l["goblin_delta"] is not None)

    def _fmt_delta(d: float) -> str:
        return str(int(d)) if float(d).is_integer() else str(d)

    sig = "+".join(_fmt_delta(d) for d in g_deltas)

    card = json.loads(
        (ROOT / "ui_runner/data/sg_delta_payout_rate_card_latest.json").read_text(encoding="utf-8")
    )
    cells = _load_rate_card_cells(card)
    matches = [
        c
        for c in cells
        if c.get("composition") == "4S+2G+0D" and str(c.get("goblin_delta_sig")) == sig
    ]
    live = [
        c for c in cells if c.get("composition") == "4S+2G+0D" and c.get("source") == "live_cdp"
    ]
    cell = matches[0] if matches else None
    power_x = float(cell["power_min_x"]) if cell and cell.get("power_min_x") is not None else None

    payload = {
        "date": "2026-08-04",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ticket_id": "2026-08-04|gold_badge_max_legs_nodupe|1",
        "ticket_track": "gold_badge_manual",
        "mode": "gold_badge_manual",
        "source": (
            "Gold consistency badge props (UI band floor ±1.0) — "
            "max legs, no duplicate players"
        ),
        "selection_rules": [
            "One prop per unique player (6 players → 6 legs)",
            "Prefer stricter ±0.5 matches over floor-widened ±1.0",
            "Prefer higher badge HR when choosing among same-player duplicates",
            "Marina Mabrey Assists 2.5 preferred over Rebs+Asts",
            "Maria Conde Rebounds 3.5 preferred over 2.5",
        ],
        "excluded_same_player_alts": [
            {
                "player": "Maria Conde",
                "prop": "Rebounds",
                "line": 2.5,
                "reason": "same player; prefer strict 3.5",
            },
            {
                "player": "Marina Mabrey",
                "prop": "Rebs+Asts",
                "line": 5.5,
                "reason": "same player; prefer Assists 2.5",
            },
            {
                "player": "Marina Mabrey",
                "prop": "Rebs+Asts",
                "line": 6.5,
                "reason": "same player; prefer Assists 2.5",
            },
        ],
        "slate": {
            "path": "mobile/www/slate_latest.json",
            "date": slate.get("date"),
            "generated_at": slate.get("generated_at"),
            "gold_scan": "logs/_gold_badge_matches_2026-08-04.json",
        },
        "matchup": "TOR vs GSV",
        "game_time_local": "10:00 PM",
        "n_legs": 6,
        "unique_players": players,
        "no_duplicate_players": True,
        "composition": "4S+2G+0D",
        "entry_type": "power",
        "goblin_delta_sig": sig,
        "goblin_distances": g_deltas,
        "payout_notes": {
            "board": (
                "PrizePicks-style mix board (4 Standard + 2 Goblin). "
                "Power requires all 6 legs to hit."
            ),
            "rate_card_composition": "4S+2G+0D",
            "goblin_delta_sig": sig,
            "rate_card_cell": cell,
            "approx_power_min_x": power_x,
            "approx_on_20_usd": round(20 * power_x, 2) if power_x is not None else None,
            "live_cdp_4S2G_examples": [
                {"goblin_delta_sig": c.get("goblin_delta_sig"), "power_min_x": c.get("power_min_x")}
                for c in live[:8]
            ],
            "caveat": (
                "Mix payout depends on live PrizePicks SG-Δ; this cell may be extrapolated. "
                "Confirm in-app before submit."
            ),
            "all_standard_6leg_reference": (
                "All-Standard 6-leg power is typically much higher; "
                "goblin mix pays less (often ~6x for shallow deltas)."
            ),
        },
        "groups": [
            {
                "group_name": "Gold Badge Max Legs (No Dupe)",
                "n_legs": 6,
                "tickets": [
                    {
                        "web_group_name": "Gold Badge Max Legs (No Dupe)",
                        "ticket_id": "2026-08-04|gold_badge_max_legs_nodupe|1",
                        "ticket_no": 1,
                        "ticket_track": "gold_badge_manual",
                        "manual": True,
                        "n_legs": 6,
                        "legs": legs,
                        "payout": {
                            "composition": "4S+2G+0D",
                            "goblin_delta_sig": sig,
                            "power_min_x": power_x,
                            "display_min_x": power_x,
                            "payout_source": (cell or {}).get("source") if cell else "unknown",
                            "recommendation": "POWER",
                        },
                    }
                ],
            }
        ],
        "ticket": {
            "web_group_name": "Gold Badge Max Legs (No Dupe)",
            "ticket_id": "2026-08-04|gold_badge_max_legs_nodupe|1",
            "ticket_no": 1,
            "ticket_track": "gold_badge_manual",
            "n_legs": 6,
            "legs": legs,
            "payout": {
                "composition": "4S+2G+0D",
                "goblin_delta_sig": sig,
                "power_min_x": power_x,
                "display_min_x": power_x,
                "payout_source": (cell or {}).get("source") if cell else "unknown",
                "recommendation": "POWER",
            },
        },
        "result": {
            "status": "PENDING",
            "grade_after": "2026-08-05",
            "grade_how": [
                "After WNBA games finish and mobile/www/graded_props_2026-08-04.json exists:",
                "py -3 logs/_grade_gold_badge_ticket_0804.py",
            ],
        },
        "blockers": [
            {
                "type": "timing",
                "note": (
                    "All 6 legs are TOR vs GSV listed at 10:00 PM. "
                    "If tip-off already passed, PrizePicks may lock; "
                    "artifact remains valid for next-day grading."
                ),
            }
        ],
    }

    out = ROOT / "data/reports/gold_badge_ticket_2026-08-04.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"composition=4S+2G+0D goblin_delta_sig={sig} power_min_x={power_x}")
    print(f"unique_players={players}")
    for leg in legs:
        print(
            f"  {leg['player']:18s} {leg['direction']:5s} {leg['line']:<4} "
            f"{leg['prop']:20s} {leg['pick_type']:8s} {leg['badge']} "
            f"goblin_delta={leg.get('goblin_delta')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
