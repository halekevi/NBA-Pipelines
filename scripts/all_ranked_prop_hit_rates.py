#!/usr/bin/env python3
"""Every graded sport × book × prop, with L5 / L10 / D hit rates.

Reads every graded_props_*.json (main_cp first, then OPEN). Demons included
as their own books. Live list books = Goblin OVER / Standard OVER / Standard UNDER.
D = opponent def aligned (OVER Weak|Below Avg; UNDER Elite|Above Avg; Avg/unknown
fail; MLB hitter Ks invert). Tennis opponent D is ATP/WTA rank (1–10 Elite …
101+ Weak) from the row or Sackmann winner/loser rank. Joints are L5/L10 ∩ D.

  py -3.14 scripts/all_ranked_prop_hit_rates.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
MAIN = _REPO.parent / "PropORACLE_main_cp"
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import prop_hit_tiers as T  # noqa: E402
from utils.defense_tiers import d_aligned, normalize_def_tier_label  # noqa: E402
from utils.fantasy_prop_filter import is_fantasy_prop_label  # noqa: E402
from utils.prop_norm import display_prop  # noqa: E402
from utils.tennis_rank_d import TennisOppRankIndex, rank_to_tier, tennis_opp_tier  # noqa: E402

OUT = _REPO / "data" / "reports" / "all_ranked_prop_hit_rates.json"
LIVE_BOOKS = ("Goblin OVER", "Standard OVER", "Standard UNDER")
GRADED_DIRS = [
    MAIN / "ui_runner" / "templates",
    MAIN / "mobile" / "www",
    _REPO / "ui_runner" / "templates",
    _REPO / "mobile" / "www",
]


def empty():
    return {
        "n": 0,
        "hits": 0,
        "listed_n": 0,
        "listed_hits": 0,
        "l5eq5_n": 0,
        "l5eq5_hits": 0,
        "l5_known": 0,
        "l10_known": 0,
        "l10ge8_n": 0,
        "l10ge8_hits": 0,
        "l10eq10_n": 0,
        "l10eq10_hits": 0,
        "l5ge4_l10ge8_n": 0,
        "l5ge4_l10ge8_hits": 0,
        "l5eq5_l10ge8_n": 0,
        "l5eq5_l10ge8_hits": 0,
        "l5ge4_l10eq10_n": 0,
        "l5ge4_l10eq10_hits": 0,
        "l5eq5_l10eq10_n": 0,
        "l5eq5_l10eq10_hits": 0,
        "d_known": 0,
        "d_n": 0,
        "d_hits": 0,
        "l5ge4_d_n": 0,
        "l5ge4_d_hits": 0,
        "l5eq5_d_n": 0,
        "l5eq5_d_hits": 0,
        "l5ge4_l10ge8_d_n": 0,
        "l5ge4_l10ge8_d_hits": 0,
        "l5eq5_l10ge8_d_n": 0,
        "l5eq5_l10ge8_d_hits": 0,
        "l5ge4_l10eq10_d_n": 0,
        "l5ge4_l10eq10_d_hits": 0,
        "l5eq5_l10eq10_d_n": 0,
        "l5eq5_l10eq10_d_hits": 0,
    }


def num(v) -> float | None:
    if v is None or v == "":
        return None
    s = str(v).strip()
    if s in ("", "—", "–", "-", "nan", "None", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def l5_dir(row: dict, side: str) -> float | None:
    if side == "OVER":
        keys = ("l5_over", "last5_over", "L5 Over", "line_hits_over_5")
    else:
        keys = ("l5_under", "last5_under", "L5 Under", "line_hits_under_5")
    for k in keys:
        v = num(row.get(k))
        if v is not None:
            return v
    return None


def l10_dir(row: dict, side: str) -> float | None:
    if side == "OVER":
        keys = (
            "l10_over",
            "last10_over",
            "L10 Over",
            "line_hits_over_10",
            "over_L10",
        )
    else:
        keys = (
            "l10_under",
            "last10_under",
            "L10 Under",
            "line_hits_under_10",
            "under_L10",
        )
    for k in keys:
        v = num(row.get(k))
        if v is not None:
            return v
    return None


def row_def_tier(row: dict, *, sport: str = "", slate: object = None, tennis_idx=None) -> str:
    for k in ("def_tier", "opp_def_tier", "stat_def_tier", "DEF_TIER", "def"):
        v = row.get(k)
        if v is None or v == "":
            continue
        s = str(v).strip()
        if s and s.lower() not in ("nan", "none", "n/a", "na", "—", "-"):
            return s
    sport_u = str(sport or "").strip().upper()
    if sport_u in ("TENNIS", "ATP", "WTA"):
        for k in ("opponent_rank", "Opponent Rank", "opp_rank", "opp_atp_rank"):
            tier = rank_to_tier(row.get(k))
            if tier:
                return tier
        from datetime import date as _date

        sd = slate
        if isinstance(sd, str) and len(sd) >= 10:
            try:
                sd = _date.fromisoformat(sd[:10])
            except ValueError:
                sd = None
        return tennis_opp_tier(row, slate=sd, index=tennis_idx) or ""
    return ""


def pick_book(pick: str, side: str) -> str | None:
    return T.book_label(pick, side) or None


def graded_paths() -> list[Path]:
    by_date: dict[str, Path] = {}
    for d in GRADED_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("graded_props_20*.json")):
            if ".bak_" in p.name:
                continue
            date = p.stem.replace("graded_props_", "")[:10]
            if date not in by_date:
                by_date[date] = p
    return [by_date[k] for k in sorted(by_date)]


def fmt(h: int, n: int) -> str:
    if n <= 0:
        return "--"
    return f"{100.0 * h / n:5.1f}%  {h}/{n}"


def main() -> None:
    paths = graded_paths()
    tennis_idx = TennisOppRankIndex.from_repo(_REPO)
    cells: dict[tuple[str, str, str], dict] = defaultdict(empty)
    sports: dict[str, dict] = defaultdict(lambda: {"n": 0, "hits": 0, "dates": set()})
    n_raw = 0
    n_decided = 0
    dates: list[str] = []
    for path in paths:
        date = path.stem.replace("graded_props_", "")[:10]
        dates.append(date)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print("skip", path, exc)
            continue
        props = raw.get("props") or raw.get("rows") or []
        if not isinstance(props, list):
            continue
        for r in props:
            if not isinstance(r, dict):
                continue
            n_raw += 1
            res = str(r.get("result") or "").strip().upper()
            if res not in ("HIT", "MISS"):
                continue
            sport = T.norm_sport(str(r.get("sport") or ""))
            if not sport or sport == "UNKNOWN":
                continue
            side = str(r.get("direction") or r.get("over_under") or "").strip().upper()
            if side in ("O", "OVER"):
                side = "OVER"
            elif side in ("U", "UNDER"):
                side = "UNDER"
            else:
                continue
            book = pick_book(str(r.get("pick_type") or ""), side)
            if not book:
                continue
            prop = T.canon_prop(sport, str(r.get("prop") or r.get("prop_type") or ""))
            if not prop:
                continue
            if is_fantasy_prop_label(prop) or prop == "fantasy":
                continue
            hit = 1 if res == "HIT" else 0
            n_decided += 1
            key = (sport, book, prop)
            c = cells[key]
            c["n"] += 1
            c["hits"] += hit
            sports[sport]["n"] += 1
            sports[sport]["hits"] += hit
            sports[sport]["dates"].add(date)
            l5 = l5_dir(r, side)
            l10 = l10_dir(r, side)
            if l5 is not None:
                c["l5_known"] += 1
                if l5 >= 4:
                    c["listed_n"] += 1
                    c["listed_hits"] += hit
                if l5 == 5:
                    c["l5eq5_n"] += 1
                    c["l5eq5_hits"] += hit
            if l10 is not None:
                c["l10_known"] += 1
                if l10 >= 8:
                    c["l10ge8_n"] += 1
                    c["l10ge8_hits"] += hit
                if l10 == 10:
                    c["l10eq10_n"] += 1
                    c["l10eq10_hits"] += hit
            if l5 is not None and l10 is not None:
                if l5 >= 4 and l10 >= 8:
                    c["l5ge4_l10ge8_n"] += 1
                    c["l5ge4_l10ge8_hits"] += hit
                if l5 == 5 and l10 >= 8:
                    c["l5eq5_l10ge8_n"] += 1
                    c["l5eq5_l10ge8_hits"] += hit
                if l5 >= 4 and l10 == 10:
                    c["l5ge4_l10eq10_n"] += 1
                    c["l5ge4_l10eq10_hits"] += hit
                if l5 == 5 and l10 == 10:
                    c["l5eq5_l10eq10_n"] += 1
                    c["l5eq5_l10eq10_hits"] += hit
            d_raw = row_def_tier(r, sport=sport, slate=date, tennis_idx=tennis_idx)
            d_label = normalize_def_tier_label(d_raw)
            d_ok = d_aligned(sport, side, d_raw, prop)
            if d_label:
                c["d_known"] += 1
            if d_ok:
                c["d_n"] += 1
                c["d_hits"] += hit
                if l5 is not None and l5 >= 4:
                    c["l5ge4_d_n"] += 1
                    c["l5ge4_d_hits"] += hit
                if l5 is not None and l5 == 5:
                    c["l5eq5_d_n"] += 1
                    c["l5eq5_d_hits"] += hit
                if l5 is not None and l10 is not None:
                    if l5 >= 4 and l10 >= 8:
                        c["l5ge4_l10ge8_d_n"] += 1
                        c["l5ge4_l10ge8_d_hits"] += hit
                    if l5 == 5 and l10 >= 8:
                        c["l5eq5_l10ge8_d_n"] += 1
                        c["l5eq5_l10ge8_d_hits"] += hit
                    if l5 >= 4 and l10 == 10:
                        c["l5ge4_l10eq10_d_n"] += 1
                        c["l5ge4_l10eq10_d_hits"] += hit
                    if l5 == 5 and l10 == 10:
                        c["l5eq5_l10eq10_d_n"] += 1
                        c["l5eq5_l10eq10_d_hits"] += hit

    rows = []
    for (sport, book, prop), c in cells.items():
        info = T.assign_tier(
            sport=sport,
            pick_type=book.split()[0] if book else "",
            side=book.split()[-1] if book else "",
            prop=prop,
        )
        use = T.preferred_hr(
            n=c["n"],
            hits=c["hits"],
            listed_n=c["listed_n"],
            listed_hits=c["listed_hits"],
        )
        rec = {
            "sport": sport,
            "book": book,
            "prop": prop,
            "prop_display": display_prop(prop),
            "n": c["n"],
            "hits": c["hits"],
            "hr": round(c["hits"] / c["n"], 4) if c["n"] else None,
            "listed_n": c["listed_n"],
            "listed_hits": c["listed_hits"],
            "listed_hr": round(c["listed_hits"] / c["listed_n"], 4) if c["listed_n"] else None,
            "l5eq5_n": c["l5eq5_n"],
            "l5eq5_hits": c["l5eq5_hits"],
            "l5eq5_hr": round(c["l5eq5_hits"] / c["l5eq5_n"], 4) if c["l5eq5_n"] else None,
            "l5_known": c["l5_known"],
            "l10_known": c["l10_known"],
            "l10ge8_n": c["l10ge8_n"],
            "l10ge8_hits": c["l10ge8_hits"],
            "l10ge8_hr": round(c["l10ge8_hits"] / c["l10ge8_n"], 4) if c["l10ge8_n"] else None,
            "l10eq10_n": c["l10eq10_n"],
            "l10eq10_hits": c["l10eq10_hits"],
            "l10eq10_hr": round(c["l10eq10_hits"] / c["l10eq10_n"], 4) if c["l10eq10_n"] else None,
            "l5ge4_l10ge8_n": c["l5ge4_l10ge8_n"],
            "l5ge4_l10ge8_hits": c["l5ge4_l10ge8_hits"],
            "l5ge4_l10ge8_hr": round(c["l5ge4_l10ge8_hits"] / c["l5ge4_l10ge8_n"], 4)
            if c["l5ge4_l10ge8_n"]
            else None,
            "l5eq5_l10ge8_n": c["l5eq5_l10ge8_n"],
            "l5eq5_l10ge8_hits": c["l5eq5_l10ge8_hits"],
            "l5eq5_l10ge8_hr": round(c["l5eq5_l10ge8_hits"] / c["l5eq5_l10ge8_n"], 4)
            if c["l5eq5_l10ge8_n"]
            else None,
            "l5ge4_l10eq10_n": c["l5ge4_l10eq10_n"],
            "l5ge4_l10eq10_hits": c["l5ge4_l10eq10_hits"],
            "l5ge4_l10eq10_hr": round(c["l5ge4_l10eq10_hits"] / c["l5ge4_l10eq10_n"], 4)
            if c["l5ge4_l10eq10_n"]
            else None,
            "l5eq5_l10eq10_n": c["l5eq5_l10eq10_n"],
            "l5eq5_l10eq10_hits": c["l5eq5_l10eq10_hits"],
            "l5eq5_l10eq10_hr": round(c["l5eq5_l10eq10_hits"] / c["l5eq5_l10eq10_n"], 4)
            if c["l5eq5_l10eq10_n"]
            else None,
            "d_known": c["d_known"],
            "d_n": c["d_n"],
            "d_hits": c["d_hits"],
            "d_hr": round(c["d_hits"] / c["d_n"], 4) if c["d_n"] else None,
            "l5ge4_d_n": c["l5ge4_d_n"],
            "l5ge4_d_hits": c["l5ge4_d_hits"],
            "l5ge4_d_hr": round(c["l5ge4_d_hits"] / c["l5ge4_d_n"], 4) if c["l5ge4_d_n"] else None,
            "l5eq5_d_n": c["l5eq5_d_n"],
            "l5eq5_d_hits": c["l5eq5_d_hits"],
            "l5eq5_d_hr": round(c["l5eq5_d_hits"] / c["l5eq5_d_n"], 4) if c["l5eq5_d_n"] else None,
            "l5ge4_l10ge8_d_n": c["l5ge4_l10ge8_d_n"],
            "l5ge4_l10ge8_d_hits": c["l5ge4_l10ge8_d_hits"],
            "l5ge4_l10ge8_d_hr": round(c["l5ge4_l10ge8_d_hits"] / c["l5ge4_l10ge8_d_n"], 4)
            if c["l5ge4_l10ge8_d_n"]
            else None,
            "l5eq5_l10ge8_d_n": c["l5eq5_l10ge8_d_n"],
            "l5eq5_l10ge8_d_hits": c["l5eq5_l10ge8_d_hits"],
            "l5eq5_l10ge8_d_hr": round(c["l5eq5_l10ge8_d_hits"] / c["l5eq5_l10ge8_d_n"], 4)
            if c["l5eq5_l10ge8_d_n"]
            else None,
            "l5ge4_l10eq10_d_n": c["l5ge4_l10eq10_d_n"],
            "l5ge4_l10eq10_d_hits": c["l5ge4_l10eq10_d_hits"],
            "l5ge4_l10eq10_d_hr": round(c["l5ge4_l10eq10_d_hits"] / c["l5ge4_l10eq10_d_n"], 4)
            if c["l5ge4_l10eq10_d_n"]
            else None,
            "l5eq5_l10eq10_d_n": c["l5eq5_l10eq10_d_n"],
            "l5eq5_l10eq10_d_hits": c["l5eq5_l10eq10_d_hits"],
            "l5eq5_l10eq10_d_hr": round(c["l5eq5_l10eq10_d_hits"] / c["l5eq5_l10eq10_d_n"], 4)
            if c["l5eq5_l10eq10_d_n"]
            else None,
            "hr_window": use["window"],
            "hr_use": use["hr"],
            "hr_use_n": use["n"],
            "prop_tier": info.get("prop_tier") or "",
            "shadow": bool(info.get("prop_shadow")),
            "live_book": book in LIVE_BOOKS,
        }
        rows.append(rec)
    rows.sort(key=lambda r: (r["sport"], 0 if r["live_book"] else 1, r["book"], -(r["listed_n"] or 0), -r["n"], r["prop"]))

    payload = {
        "generated_from": str(paths[0].parent) if paths else None,
        "from": dates[0] if dates else None,
        "to": dates[-1] if dates else None,
        "n_days": len(dates),
        "n_raw": n_raw,
        "n_decided": n_decided,
        "n_categories": len(rows),
        "note": (
            "Every HIT/MISS on graded_props_*.json. Fantasy markets dropped. "
            "Category = sport × book × canon prop. all = ungated. listed = L5>=4. "
            "l5eq5 = L5==5. Joint: L5>=4|L5==5 with L10>=8 and L10==10. "
            "D = opponent def aligned (OVER Weak|Below Avg; UNDER Elite|Above Avg; "
            "Avg/unknown fail; MLB hitter Ks invert). Tennis D uses opponent ATP/WTA "
            "rank (1-10 Elite, 11-25 Above Avg, 26-50 Avg, 51-100 Below Avg, 101+ Weak) "
            "from the graded row or Sackmann winner/loser rank on that match. "
            "Live list books are Goblin OVER / Standard OVER / Standard UNDER; Demons "
            "are included for the full catalog."
        ),
        "by_sport": {
            sp: {
                "n": v["n"],
                "hits": v["hits"],
                "hr": round(v["hits"] / v["n"], 4) if v["n"] else None,
                "n_dates": len(v["dates"]),
            }
            for sp, v in sorted(sports.items())
        },
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)
    write_prop_sd_canvas(payload)
    print("days", payload["from"], "->", payload["to"], "decided", n_decided, "categories", len(rows))
    print()
    for sport in sorted(sports):
        srows = [r for r in rows if r["sport"] == sport]
        print(f"########## {sport}  n={sports[sport]['n']}  {fmt(sports[sport]['hits'], sports[sport]['n'])} ##########")
        books = []
        for r in srows:
            if r["book"] not in books:
                books.append(r["book"])
        for book in books:
            brows = [r for r in srows if r["book"] == book]
            print(f"\n  === {book} ===")
            print(
                f"  {'prop':24} {'all':16} {'L5=5':14} {'L5=5+D':16} "
                f"{'L5=5+L10>=8':16} {'L5=5+L10>=8+D':18} {'D':16} tier"
            )
            for r in brows:
                if r["n"] < 5 and (r["listed_n"] or 0) < 5:
                    continue
                tag = r["prop_tier"] or ""
                if r["shadow"]:
                    tag = (tag + " W").strip()
                label = (r.get("prop_display") or r["prop"])[:24]
                print(
                    f"  {label:24} {fmt(r['hits'], r['n']):16} "
                    f"{fmt(r['l5eq5_hits'], r['l5eq5_n']):14} "
                    f"{fmt(r['l5eq5_d_hits'], r['l5eq5_d_n']):16} "
                    f"{fmt(r['l5eq5_l10ge8_hits'], r['l5eq5_l10ge8_n']):16} "
                    f"{fmt(r['l5eq5_l10ge8_d_hits'], r['l5eq5_l10ge8_d_n']):18} "
                    f"{fmt(r['d_hits'], r['d_n']):16} {tag}"
                )
        print()


CANVAS_PATH = Path.home() / ".cursor" / "projects" / "h-PropORACLE" / "canvases" / "prop-sd-hit-rates.canvas.tsx"


def write_prop_sd_canvas(payload: dict) -> None:
    """Refresh the inline CELLS snapshot on the prop-catalog canvas."""
    if not CANVAS_PATH.is_file():
        print("skip canvas; missing", CANVAS_PATH)
        return
    live = [r for r in payload.get("rows") or [] if r.get("live_book")]
    seen = []
    for r in live:
        s = r["sport"]
        if s not in seen:
            seen.append(s)
    preferred = [
        "WNBA",
        "MLB",
        "Soccer",
        "Tennis",
        "NBA",
        "NBA1Q",
        "NBA1H",
        "CBB",
        "NHL",
        "NFL",
        "CFB",
        "Golf",
        "WCBB",
        "WNBA1Q",
        "WNBA1H",
    ]
    sports = [s for s in preferred if s in seen]
    sports.extend(s for s in seen if s not in preferred)
    cells = []
    for r in live:
        cells.append(
            {
                "s": r["sport"],
                "b": r["book"],
                "p": r.get("prop_display") or r["prop"],
                "t": r.get("prop_tier") or "",
                "n": r["n"],
                "h": r["hits"],
                "l4n": r["listed_n"] or 0,
                "l4h": r["listed_hits"] or 0,
                "l5n": r["l5eq5_n"] or 0,
                "l5h": r["l5eq5_hits"] or 0,
                "j8n": r["l5eq5_l10ge8_n"] or 0,
                "j8h": r["l5eq5_l10ge8_hits"] or 0,
                "dn": r["d_n"] or 0,
                "dh": r["d_hits"] or 0,
                "l5dn": r["l5eq5_d_n"] or 0,
                "l5dh": r["l5eq5_d_hits"] or 0,
                "j8dn": r["l5eq5_l10ge8_d_n"] or 0,
                "j8dh": r["l5eq5_l10ge8_d_hits"] or 0,
            }
        )
    meta = {
        "from": payload.get("from"),
        "to": payload.get("to"),
        "days": payload.get("n_days"),
        "decided": payload.get("n_decided"),
        "cats": len(live),
    }
    text = CANVAS_PATH.read_text(encoding="utf-8")
    text = _replace_ts_const(text, "META", json.dumps(meta, separators=(",", ":")))
    text = _replace_ts_const(
        text, "SPORTS", json.dumps(sports), type_ann="string[]"
    )
    text = _replace_ts_const(
        text, "CELLS", json.dumps(cells, separators=(",", ":")), type_ann="Cell[]"
    )
    # Keep JSX free of >=  (canvas checker).
    text = text.replace(
        "NBA/NHL/CBB have no pins so they show that fallback. CFB, NFL, and golf are not in the graded archive yet.",
        "S-D pins now cover WNBA/MLB/Soccer/Tennis plus NBA/NBA1Q. CFB/NFL/Golf appear after those grades land in graded_props.",
    )
    CANVAS_PATH.write_text(text, encoding="utf-8")
    print("wrote canvas", CANVAS_PATH)


def retier_existing() -> None:
    """Re-pin S-D on the existing catalog JSON without a full graded_props scan."""
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    n = 0
    for r in payload.get("rows") or []:
        book = str(r.get("book") or "")
        parts = book.split()
        info = T.assign_tier(
            sport=r.get("sport") or "",
            pick_type=parts[0] if parts else "",
            side=parts[-1] if parts else "",
            prop=r.get("prop") or "",
        )
        r["prop_tier"] = info.get("prop_tier") or ""
        r["shadow"] = bool(info.get("prop_shadow"))
        n += 1
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("retiered", n, "rows ->", OUT)
    write_prop_sd_canvas(payload)


def _replace_ts_const(src: str, name: str, rhs: str, *, type_ann: str = "") -> str:
    m = re.search(rf"const {name}(?:\s*:[^=]+)?\s*=\s*", src)
    if not m:
        raise ValueError(f"const {name} assignment not found")
    j = m.end()
    opener = src[j]
    if opener not in "{[":
        raise ValueError(f"const {name} rhs does not start with [ or {{")
    closer = "}" if opener == "{" else "]"
    depth = 0
    k = j
    in_str = False
    esc = False
    quote = ""
    while k < len(src):
        ch = src[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            k += 1
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
            k += 1
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                k += 1
                break
        k += 1
    prefix = f"const {name}: {type_ann} = " if type_ann else f"const {name} = "
    return src[: m.start()] + prefix + rhs + src[k:]


if __name__ == "__main__":
    if "--retier" in sys.argv:
        retier_existing()
    else:
        main()
