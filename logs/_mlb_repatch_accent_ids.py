#!/usr/bin/env python3
"""Re-patch MLB slate L5 using accent-insensitive player ID matching."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

PROP_MAP = {
    "hits": "hits", "total bases": "total_bases", "home runs": "home_runs", "rbis": "rbi", "rbi": "rbi",
    "runs": "runs", "walks": "walks", "stolen bases": "stolen_bases", "fantasy score": "fantasy_score",
    "hits+runs+rbis": "hits_runs_rbi", "singles": "singles", "doubles": "doubles", "triples": "triples",
    "hitter strikeouts": "hitter_strikeouts", "plate appearances": "plate_appearances",
    "pitcher strikeouts": "strikeouts", "pitching outs": "pitching_outs", "innings pitched": "innings_pitched",
    "hits allowed": "hits_allowed", "earned runs": "earned_runs", "earned runs allowed": "earned_runs",
    "walks allowed": "walks_allowed", "batters faced": "batters_faced", "pitches thrown": "pitches_thrown",
}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s\.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main() -> None:
    ids = pd.read_csv(ROOT / "Sports/MLB/mlb_id_cache.csv")
    name_to_id = {}
    for _, r in ids.iterrows():
        norm = fold(r["player_norm"])
        name_to_id[norm] = str(r["mlb_player_id"]).strip()
        # also raw lower
        name_to_id[str(r["player_norm"]).strip().lower()] = str(r["mlb_player_id"]).strip()

    # manual extras if missing
    extras = {
        "bryan de la cruz": "650559",  # common MLB id; verify via cache presence
    }
    # verify bryan id from cache if present under any prop
    cache = pd.read_csv(ROOT / "Sports/MLB/mlb_stats_cache.csv", low_memory=False)
    # try find bryan via existing cache players - skip if unknown

    print("loading slate…", flush=True)
    slate_path = ROOT / "ui_runner/templates/slate_latest.json"
    raw = json.loads(slate_path.read_text(encoding="utf-8"))
    mlb = raw["sports"]["mlb"]

    # resolve ids for all slate names
    unresolved = set()
    resolved = 0
    for r in mlb:
        name = str(r.get("player") or "")
        pid = name_to_id.get(fold(name)) or name_to_id.get(name.lower())
        if not pid:
            unresolved.add(name)
        else:
            resolved += 1
    print(f"rows with id={resolved} unresolved_names={len(unresolved)}", flush=True)
    print("unresolved sample", sorted(unresolved)[:30], flush=True)

    print("indexing cache…", flush=True)
    cache["GAME_DATE"] = pd.to_datetime(cache["GAME_DATE"], errors="coerce")
    cache["STAT_VALUE"] = pd.to_numeric(cache["STAT_VALUE"], errors="coerce")
    cache = cache.dropna(subset=["STAT_VALUE", "GAME_DATE"]).sort_values("GAME_DATE", ascending=False)
    vals_map = defaultdict(list)
    for pid, prop, val in zip(
        cache["MLB_PLAYER_ID"].astype(str),
        cache["PROP_NORM"].astype(str),
        cache["STAT_VALUE"].astype(float),
    ):
        key = (pid, prop)
        if len(vals_map[key]) < 10:
            vals_map[key].append(float(val))

    patched = skipped_no_id = skipped_no_prop = skipped_no_vals = 0
    for r in mlb:
        name = str(r.get("player") or "")
        pid = name_to_id.get(fold(name)) or name_to_id.get(name.lower())
        if not pid:
            skipped_no_id += 1
            continue
        pn = PROP_MAP.get(str(r.get("prop") or "").strip().lower())
        if not pn:
            skipped_no_prop += 1
            continue
        vals = vals_map.get((pid, pn)) or []
        if not vals:
            skipped_no_vals += 1
            continue
        try:
            line_f = float(r.get("line"))
        except Exception:
            continue
        for i, v in enumerate(vals, 1):
            r[f"stat_g{i}"] = v
            r[f"g{i}"] = v
        r["actual_series"] = list(vals)
        r["line_series"] = [line_f] * len(vals)
        o5 = sum(1 for v in vals[:5] if v > line_f)
        u5 = sum(1 for v in vals[:5] if v < line_f)
        o10 = sum(1 for v in vals[:10] if v > line_f)
        u10 = sum(1 for v in vals[:10] if v < line_f)
        r["l5_over"], r["l5_under"] = o5, u5
        r["l10_over"], r["l10_under"] = o10, u10
        d = str(r.get("dir") or "OVER").upper()
        n5 = max(1, min(5, len(vals)))
        hr = (o5 / n5) if d != "UNDER" else (u5 / n5)
        r["l5_side_hit_rate"] = hr
        r["hit_rate"] = hr
        patched += 1

    raw["sports"]["mlb"] = mlb
    payload = json.dumps(raw, ensure_ascii=False, default=str)
    slate_path.write_text(payload, encoding="utf-8")
    (ROOT / "mobile/www/slate_latest.json").write_text(payload, encoding="utf-8")
    sport = json.dumps({"ok": True, "sport": "mlb", "rows": mlb}, ensure_ascii=False, default=str)
    (ROOT / "ui_runner/templates/slate_sport_mlb.json").write_text(sport, encoding="utf-8")
    (ROOT / "mobile/www/slate_sport_mlb.json").write_text(sport, encoding="utf-8")
    print(
        f"patched={patched} no_id={skipped_no_id} no_prop={skipped_no_prop} no_vals={skipped_no_vals}",
        flush=True,
    )

    for name in ["Ronald Acuña Jr.", "Julio Rodríguez", "Jasson Domínguez", "James Wood", "Brayan Rocchio", "Jordan Walker"]:
        for r in mlb:
            if r.get("player") != name:
                continue
            if str(r.get("prop")) not in ("Hits+Runs+RBIs", "Runs", "Hits"):
                continue
            if str(r.get("pick_type") or "").lower() not in ("standard", "goblin"):
                continue
            print(
                name,
                r.get("pick_type"),
                f"O{r.get('line')}",
                r.get("prop"),
                f"L5 {r.get('l5_over')}/5",
                "series",
                r.get("actual_series")[:5],
                flush=True,
            )


if __name__ == "__main__":
    main()
