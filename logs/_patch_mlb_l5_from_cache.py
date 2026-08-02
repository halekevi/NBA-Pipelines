import json
from pathlib import Path
from collections import defaultdict
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

def main():
    print("loading cache…", flush=True)
    cache = pd.read_csv(ROOT / "Sports/MLB/mlb_stats_cache.csv", low_memory=False)
    cache["GAME_DATE"] = pd.to_datetime(cache["GAME_DATE"], errors="coerce")
    cache["STAT_VALUE"] = pd.to_numeric(cache["STAT_VALUE"], errors="coerce")
    cache = cache.dropna(subset=["STAT_VALUE", "GAME_DATE"])
    cache = cache.sort_values("GAME_DATE", ascending=False)
    print("indexing…", flush=True)
    vals_map = defaultdict(list)
    for pid, prop, val in zip(
        cache["MLB_PLAYER_ID"].astype(str),
        cache["PROP_NORM"].astype(str),
        cache["STAT_VALUE"].astype(float),
    ):
        key = (pid, prop)
        if len(vals_map[key]) < 10:
            vals_map[key].append(float(val))
    print("keys", len(vals_map), flush=True)

    ids = pd.read_csv(ROOT / "Sports/MLB/mlb_id_cache.csv")
    name_to_id = {str(r["player_norm"]).strip().lower(): str(r["mlb_player_id"]).strip() for _, r in ids.iterrows()}

    slate_path = ROOT / "ui_runner/templates/slate_latest.json"
    print("loading slate…", flush=True)
    raw = json.loads(slate_path.read_text(encoding="utf-8"))
    mlb = raw["sports"]["mlb"]
    patched = 0
    for r in mlb:
        pid = name_to_id.get(str(r.get("player") or "").strip().lower())
        if not pid:
            continue
        pn = PROP_MAP.get(str(r.get("prop") or "").strip().lower())
        if not pn:
            continue
        vals = vals_map.get((pid, pn)) or []
        if not vals:
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
        recent5 = vals[:5]
        recent10 = vals[:10]
        o5 = sum(1 for v in recent5 if v > line_f)
        u5 = sum(1 for v in recent5 if v < line_f)
        o10 = sum(1 for v in recent10 if v > line_f)
        u10 = sum(1 for v in recent10 if v < line_f)
        r["l5_over"], r["l5_under"] = o5, u5
        r["l10_over"], r["l10_under"] = o10, u10
        d = str(r.get("dir") or "OVER").upper()
        n5 = len(recent5) or 1
        hr = (o5 / n5) if d != "UNDER" else (u5 / n5)
        r["l5_side_hit_rate"] = hr
        r["hit_rate"] = hr
        patched += 1

    raw["sports"]["mlb"] = mlb
    print("writing slate…", flush=True)
    payload = json.dumps(raw, ensure_ascii=False, default=str)
    slate_path.write_text(payload, encoding="utf-8")
    (ROOT / "mobile/www/slate_latest.json").write_text(payload, encoding="utf-8")
    sport = json.dumps({"ok": True, "sport": "mlb", "rows": mlb}, ensure_ascii=False, default=str)
    (ROOT / "ui_runner/templates/slate_sport_mlb.json").write_text(sport, encoding="utf-8")
    (ROOT / "mobile/www/slate_sport_mlb.json").write_text(sport, encoding="utf-8")
    print("patched", patched, flush=True)
    print("=== trio ===", flush=True)
    for name in ["James Wood", "Brayan Rocchio", "Jordan Walker"]:
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
