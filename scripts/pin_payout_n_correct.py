#!/usr/bin/env python3
"""Pin tonight's PrizePicks N-correct / To Win rates from a live slip.

Never pin 1st-place. Example:

  py -3.14 scripts/pin_payout_n_correct.py --date 2026-08-27 --legs 3 --goblins 3 --product Power --pays 3=2.0
  py -3.14 scripts/pin_payout_n_correct.py --date 2026-08-27 --legs 3 --goblins 3 --product Flex --pays 3=1.7,2=0.5
  py -3.14 scripts/pin_payout_n_correct.py --date 2026-08-27 --legs 4 --goblins 4 --product Power --pays 4=2.4

Then rebuild:

  py -3.14 scripts/build_goblin70_tickets.py --date 2026-08-27 --write-web --publish-live
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
OUT_DIR = ROOT / "data" / "reports"


def _parse_pays(raw: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        hits, mult = part.split("=", 1)
        out[str(int(hits.strip()))] = float(mult.strip())
    if not out:
        raise SystemExit("Need --pays like 3=2.0 or 3=1.7,2=0.5")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(ET).strftime("%Y-%m-%d"))
    ap.add_argument("--legs", type=int, required=True)
    ap.add_argument("--goblins", type=int, required=True)
    ap.add_argument("--standards", type=int, default=None)
    ap.add_argument("--product", choices=("Power", "Flex"), required=True)
    ap.add_argument("--pays", required=True, help="N-correct map, e.g. 3=2.0 or 4=1.9,3=0.5")
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    n_s = args.standards if args.standards is not None else max(0, args.legs - args.goblins)
    pays = _parse_pays(args.pays)
    dated = OUT_DIR / f"payout_overrides_{args.date}.json"
    latest = OUT_DIR / "payout_overrides_latest.json"
    payload = {"date": args.date, "source": "prizepicks_slip", "note": "N-correct / To Win. Never 1st place.", "entries": []}
    if dated.is_file():
        try:
            payload = json.loads(dated.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    payload["date"] = args.date
    entries = [e for e in (payload.get("entries") or []) if isinstance(e, dict)]
    key = (args.legs, n_s, args.goblins, args.product)
    entries = [
        e
        for e in entries
        if (
            int(e.get("n_legs") or 0),
            int(e.get("n_s") or 0),
            int(e.get("n_g") or 0),
            str(e.get("product") or ""),
        )
        != key
    ]
    note = args.note or (
        f"{n_s}S+{args.goblins}G {args.product} "
        + " / ".join(f"{k}-correct {v}x" for k, v in sorted(pays.items(), reverse=True))
        + " (live slip)"
    )
    entries.append(
        {
            "n_legs": args.legs,
            "n_s": n_s,
            "n_g": args.goblins,
            "product": args.product,
            "n_correct": pays,
            "note": note,
        }
    )
    payload["entries"] = entries
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    dated.write_text(text, encoding="utf-8")
    shutil.copyfile(dated, latest)
    print("wrote", dated)
    print("wrote", latest)
    for e in entries:
        print(
            f"  {e['n_s']}S+{e['n_g']}G {e['product']} {e['n_legs']}  {e['n_correct']}"
        )
    print("Rebuild: py -3.14 scripts/build_goblin70_tickets.py --date", args.date, "--write-web --publish-live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
