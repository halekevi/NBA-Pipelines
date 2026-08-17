"""Soccer HIT/MISS: directional L5 + category-specific defense ALIGN."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.matchup_edge.stat_defense import display_tier_from_stat  # noqa: E402
from utils.soccer_prop_defense import lookup_stat_defense, prop_category  # noqa: E402

EXCLUDED = {
    "passes attempted",
    "tackles",
    "fouls",
    "clearances",
    "attempted dribbles",
}
TPL = ROOT / "ui_runner" / "templates"
OUT = ROOT / "outputs"


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def graded(r) -> bool | None:
    hit = r.get("hit")
    result = str(r.get("result") or "").strip().upper()
    if hit == 1 or result in ("HIT", "WIN", "W"):
        return True
    if hit == 0 or result in ("MISS", "LOSS", "L"):
        return False
    return None


def norm_prop(p: str) -> str:
    return " ".join(str(p or "").replace("_", " ").split()).strip()


def align_from_tier(direction: str, display_tier: str) -> str | None:
    d = str(direction or "").upper()
    t = str(display_tier or "").strip().upper()
    if not t or t in ("AVG", "MID", ""):
        return None
    if d == "OVER" and t in ("WEAK", "BELOW AVG"):
        return "ALIGN"
    if d == "UNDER" and t in ("ELITE", "ABOVE AVG"):
        return "ALIGN"
    if d == "OVER" and t in ("ELITE", "ABOVE AVG"):
        return "AGAINST"
    if d == "UNDER" and t in ("WEAK", "BELOW AVG"):
        return "AGAINST"
    return None


def load_l5(date: str) -> dict[tuple, dict]:
    path = OUT / date / "soccer" / "step5_soccer_hit_rates.csv"
    if not path.exists():
        path = OUT / date / "soccer" / "step8_soccer_direction.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, low_memory=False)
    out: dict[tuple, dict] = {}
    for _, row in df.iterrows():
        player = str(row.get("player") or "").strip().lower()
        prop = norm_prop(row.get("prop_type") or row.get("prop") or "").lower()
        line = _num(row.get("line"))
        pick = str(row.get("pick_type") or "").strip().lower()
        key = (player, prop, line, pick)
        out[key] = {
            "last5_over": _num(row.get("last5_over") or row.get("l5_over")),
            "last5_under": _num(row.get("last5_under") or row.get("l5_under")),
            "opp": str(row.get("opp_team") or row.get("opp") or "").strip(),
            "def_tier": str(row.get("DEF_TIER") or row.get("def_tier") or "").strip(),
        }
    return out


def rate(hits: int, n: int) -> str:
    if n <= 0:
        return "—"
    return f"{100.0 * hits / n:.1f}% ({hits}/{n})"


def bucket_add(store, name, ok: bool):
    h, n = store[name]
    store[name] = (h + int(ok), n + 1)


def main() -> None:
    files = sorted(TPL.glob("graded_props_2026-08-*.json"))
    # Today may be ungraded; keep all August files that exist.
    seen = set()
    rows = []
    l5_cache: dict[str, dict] = {}

    for f in files:
        date = f.stem.replace("graded_props_", "")
        payload = json.loads(f.read_text(encoding="utf-8"))
        items = payload.get("props") or payload.get("rows") or payload.get("legs")
        if not items and isinstance(payload, dict):
            for v in payload.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    items = v
                    break
        if not isinstance(items, list):
            continue
        if date not in l5_cache:
            l5_cache[date] = load_l5(date)
        l5map = l5_cache[date]
        for r in items:
            if not isinstance(r, dict):
                continue
            sp = str(r.get("sport") or "").upper().strip()
            if sp not in ("SOCCER", "SOC"):
                continue
            ok = graded(r)
            if ok is None:
                continue
            player = str(r.get("player") or "").strip()
            prop = norm_prop(r.get("prop") or r.get("prop_type") or "")
            line = _num(r.get("line"))
            direction = str(r.get("direction") or r.get("over_under") or "").upper().strip()
            pick = str(r.get("pick_type") or "").strip()
            dedupe = (date, player.lower(), prop.lower(), line, direction, pick.lower())
            if dedupe in seen:
                continue
            seen.add(dedupe)
            key = (player.lower(), prop.lower(), line, pick.lower())
            st = l5map.get(key) or l5map.get((player.lower(), prop.lower(), line, "")) or {}
            l5o = st.get("last5_over")
            l5u = st.get("last5_under")
            l5_side = l5u if direction == "UNDER" else l5o
            opp = str(r.get("opp_team") or r.get("opp") or st.get("opp") or "").strip()
            lu = lookup_stat_defense(opp, prop)
            cat_tier = display_tier_from_stat(lu.get("stat_def_tier"))
            overall_raw = str(r.get("def_tier") or st.get("def_tier") or "").strip()
            cat_align = align_from_tier(direction, cat_tier)
            ov_align = align_from_tier(direction, overall_raw)
            rows.append(
                {
                    "ok": ok,
                    "prop": prop or "(blank)",
                    "pick": pick,
                    "direction": direction,
                    "l5": l5_side,
                    "cat": prop_category(prop) or "none",
                    "cat_align": cat_align,
                    "ov_align": ov_align,
                    "excluded": prop.lower() in EXCLUDED,
                    "has_cat_rank": lu.get("stat_def_rank") is not None,
                }
            )

    print(f"soccer decided unique legs: {len(rows)}")
    l5_n = sum(1 for r in rows if r["l5"] is not None)
    cat_n = sum(1 for r in rows if r["has_cat_rank"])
    print(f"joined L5: {l5_n}  category D rank: {cat_n}")

    def dump(title: str, subset):
        store = defaultdict(lambda: (0, 0))
        for r in subset:
            bucket_add(store, "all", r["ok"])
            if r["l5"] is not None and r["l5"] >= 4:
                bucket_add(store, "L5>=4", r["ok"])
            if r["l5"] is not None and r["l5"] < 4:
                bucket_add(store, "L5<4", r["ok"])
            if r["cat_align"] == "ALIGN":
                bucket_add(store, "cat ALIGN", r["ok"])
            if r["cat_align"] == "AGAINST":
                bucket_add(store, "cat AGAINST", r["ok"])
            if r["ov_align"] == "ALIGN":
                bucket_add(store, "overall ALIGN", r["ok"])
            if r["ov_align"] == "AGAINST":
                bucket_add(store, "overall AGAINST", r["ok"])
            if r["l5"] is not None and r["l5"] >= 4 and r["cat_align"] == "ALIGN":
                bucket_add(store, "L5+cat ALIGN", r["ok"])
            if "goblin" in r["pick"].lower():
                bucket_add(store, "Goblin all", r["ok"])
                if r["l5"] is not None and r["l5"] >= 4:
                    bucket_add(store, "Goblin L5>=4", r["ok"])
                if r["l5"] is not None and r["l5"] >= 4 and r["cat_align"] == "ALIGN":
                    bucket_add(store, "Goblin L5+ALIGN", r["ok"])
            elif "standard" in r["pick"].lower():
                bucket_add(store, "Standard all", r["ok"])
                if r["l5"] is not None and r["l5"] >= 4:
                    bucket_add(store, "Standard L5>=4", r["ok"])
                if r["l5"] is not None and r["l5"] >= 4 and r["cat_align"] == "ALIGN":
                    bucket_add(store, "Standard L5+ALIGN", r["ok"])
            if r["direction"] == "OVER":
                bucket_add(store, "OVER all", r["ok"])
            if r["direction"] == "UNDER":
                bucket_add(store, "UNDER all", r["ok"])
        print(f"\n=== {title} n={len(subset)} ===")
        order = [
            "all",
            "L5>=4",
            "L5<4",
            "cat ALIGN",
            "cat AGAINST",
            "overall ALIGN",
            "overall AGAINST",
            "L5+cat ALIGN",
            "Goblin all",
            "Goblin L5>=4",
            "Goblin L5+ALIGN",
            "Standard all",
            "Standard L5>=4",
            "Standard L5+ALIGN",
            "OVER all",
            "UNDER all",
        ]
        for k in order:
            h, n = store[k]
            if n:
                print(f"  {k:22s} {rate(h, n)}")

    dump("ALL SOCCER (Aug graded)", rows)
    dump("TICKET-ELIGIBLE (no tackles/fouls/passes/clearances/dribbles)", [r for r in rows if not r["excluded"]])

    print("\n=== BY PROP (ticket-eligible) ===")
    print(f"{'Prop':<22} {'All':<22} {'L5>=4':<22} {'Cat ALIGN':<22} {'Cat AGAINST':<22} {'L5+ALIGN':<22}")
    by = defaultdict(list)
    for r in rows:
        if not r["excluded"]:
            by[r["prop"]].append(r)
    for prop, subset in sorted(by.items(), key=lambda kv: -len(kv[1])):
        def hr(pred):
            xs = [x for x in subset if pred(x)]
            if not xs:
                return "—"
            h = sum(int(x["ok"]) for x in xs)
            return rate(h, len(xs))

        print(
            f"{prop:<22} {hr(lambda x: True):<22} {hr(lambda x: x['l5'] is not None and x['l5']>=4):<22} "
            f"{hr(lambda x: x['cat_align']=='ALIGN'):<22} {hr(lambda x: x['cat_align']=='AGAINST'):<22} "
            f"{hr(lambda x: x['l5'] is not None and x['l5']>=4 and x['cat_align']=='ALIGN'):<22}"
        )

    print("\n=== BY DEFENSE CATEGORY ===")
    byc = defaultdict(list)
    for r in rows:
        if not r["excluded"]:
            byc[r["cat"]].append(r)
    for cat, subset in sorted(byc.items(), key=lambda kv: -len(kv[1])):
        dump(f"category={cat}", subset)


if __name__ == "__main__":
    main()
