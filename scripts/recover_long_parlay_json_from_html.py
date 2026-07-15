"""Recover long-parlay ticket JSON from baked ticket_eval HTML, then usable by build_ticket_eval."""
from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

ROOT = Path(r"H:/halek/ProfileFromC/Desktop/PropORACLE_main_cp")
TEMPLATES = ROOT / "ui_runner" / "templates"
DATA = ROOT / "ui_runner" / "data"


def clean(s: str) -> str:
    s = unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def parse_pwr_flex(banner: str) -> tuple[float | None, float | None]:
    pow_m = re.search(r"PWR\s*([\d.]+)", banner or "", re.I)
    flex_m = re.search(r"FLEX\s*([\d.]+)", banner or "", re.I)
    p = float(pow_m.group(1)) if pow_m else None
    f = float(flex_m.group(1)) if flex_m else None
    return p, f


def parse_legs(card: str) -> list[dict]:
    legs = []
    for lm in re.finditer(
        r'<div class="legrow([^"]*)">([\s\S]*?)(?=<div class="legrow|<div class="ticket-grade|$)',
        card,
    ):
        cls, row = lm.group(1), lm.group(2)
        mark = "HIT"
        if "miss" in cls:
            mark = "MISS"
        elif "void" in cls:
            mark = "VOID"
        elif "pend" in cls:
            mark = "UNGRADED"
        sport_m = re.search(r'class="pill[^"]*">([^<]*)</span>', row)
        sport = clean(sport_m.group(1)) if sport_m else ""
        player = ""
        pm = re.search(r'class="pl-name">([^<]+)</span>', row)
        if pm:
            player = clean(pm.group(1))
        if not player:
            for c in ("pl-hit", "pl-miss", "pl-void", "pl-pend"):
                pm = re.search(rf'class="{c}[^"]*">([^<]+)<', row)
                if pm:
                    player = clean(pm.group(1))
                    break
        prop, matchup = "", ""
        pcm = re.search(
            r'class="leg-prop-col[^"]*">\s*<div>([^<]*)</div>(?:\s*<div class="meta-muted">([^<]*)</div>)?',
            row,
        )
        if pcm:
            prop = clean(pcm.group(1))
            matchup = clean(pcm.group(2) or "")
        extras = [clean(x) for x in re.findall(r'class="leg-extra[^"]*">([\s\S]*?)</div>', row)]
        line_side = extras[0] if extras else ""
        actual = extras[1] if len(extras) > 1 else ""
        edge = extras[2] if len(extras) > 2 else ""
        direction = "OVER" if "OVER" in line_side.upper() else ("UNDER" if "UNDER" in line_side.upper() else "")
        line_m = re.search(r"([\d.]+)", line_side)
        line = float(line_m.group(1)) if line_m else None
        team, opp = "", ""
        if " vs " in matchup.lower():
            parts = re.split(r"\s+vs\s+", matchup, flags=re.I)
            if len(parts) == 2:
                team, opp = parts[0].strip(), parts[1].strip()
        pick = "Goblin" if "Goblin" in (card[:400]) else "Standard"
        # Prefer group title signal later; default Standard then overwrite
        legs.append(
            {
                "sport": sport,
                "player": player,
                "prop_type": prop,
                "direction": direction,
                "line": line,
                "team": team,
                "opp": opp,
                "pick_type": pick,
                "edge": float(edge) if edge not in ("", "—") and re.match(r"^-?[\d.]+$", edge) else None,
                "actual": actual if actual not in ("", "—") else None,
                "_grade_hint": mark,
            }
        )
    return legs


def recover_date(date: str) -> Path:
    html_path = TEMPLATES / f"ticket_eval_long_parlay_{date}.html"
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    groups: dict[str, list] = {}
    for m in re.finditer(r'<article class="ticket-card[^"]*">([\s\S]*?)</article>', html):
        card = m.group(1)
        tgs = [clean(x) for x in re.findall(r'<span class="tg(?:\s[^"]*)?">([\s\S]*?)</span>', card)]
        title = next((t for t in tgs if "RESULT" not in t.upper() and "✓" not in t and "✗" not in t), "Unknown")
        banner_m = re.search(r'class="payout">([^<]+)</span>', card)
        banner = clean(banner_m.group(1)) if banner_m else ""
        pwr, flex = parse_pwr_flex(banner)
        # Predicted from payout table (audit only — not the Grades Actual lock).
        pred_m = re.search(r"<td>Payout</td><td>([\d.]+)x</td><td>([\d.]+)x</td>", card)
        pred_x = float(pred_m.group(1)) if pred_m else None
        # Scraped PWR / FLEX banner is the permanent min-guarantee lock.
        min_x = float(pwr) if pwr and pwr > 0 else (float(flex) if flex and flex > 0 else (pred_x or 0.0))
        legs = parse_legs(card)
        is_goblin = "Goblin" in title
        for leg in legs:
            leg["pick_type"] = "Goblin" if is_goblin else "Standard"
        ticket = {
            "ticket_no": len(groups.get(title, [])) + 1,
            "power_payout": pwr or min_x,
            "flex_payout": flex or (min_x * 0.5 if min_x else None),
            "display_min_x": min_x,
            "legs": [{k: v for k, v in leg.items() if k != "_grade_hint"} for leg in legs],
            "payout": {
                "ticket_type": "power",
                "payout": min_x,
                "min_guarantee": min_x,
                "min_payout_x": min_x,
                "display_min_x": min_x,
                "power_min_x": min_x,
                "sweep_payout": min_x,
                "sweep_payout_x": min_x,
                "audit_all_hit_x": pred_x,
            },
            "_leg_grade_hints": [leg.get("_grade_hint") for leg in legs],
        }
        groups.setdefault(title, []).append(ticket)

    payload = {
        "date": date,
        "ticket_track": "long_parlay",
        "pool_mode": "long_parlay",
        "groups": [
            {"group_name": gname, "tickets": tix} for gname, tix in groups.items()
        ],
    }
    out = DATA / f"combined_slate_tickets_long_parlay_{date}.json"
    DATA.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    n = sum(len(t) for t in groups.values())
    print(f"Wrote {out} groups={len(groups)} tickets={n}")
    return out


def main():
    for d in ("2026-07-13", "2026-07-14"):
        recover_date(d)


if __name__ == "__main__":
    main()
