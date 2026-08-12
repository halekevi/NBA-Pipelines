"""CBB / WCBB prop-specific opponent defense ranks (allowed PTS/REB/AST/…).

Men's CBB: Sports/CBB/cbb_boxscore_cache.csv (or data/cache/) with opp_team_abbr.
The men's box cache often stores ESPN team_id digits in ``opp_team_abbr`` for
many opponents; rebuild maps those ids → abbrs, ranks by abbr (not team_id),
and fills any remaining D1 gaps from cbb_def_rankings / Torvik adj_d
(``stat_source`` = box | ppg_rank | torvik_adj_d).

Women's WCBB: Sports/CBB/data/cache/wcbb_boxscore_cache.csv + team_id→abbr from
step5b/step3 (player match), optional ESPN teams cache, and team_id keys when
abbr is unknown.

Ranks: 1 = stingiest (lowest opp-allowed) = HARD for OVER.
"""
from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from utils.prop_defense_common import (
    attach_lookup_columns,
    coarse_bucket_from_rank,
    empty_stat_def,
)

PROP_TO_CAT: dict[str, str] = {
    "Points": "pts",
    "points": "pts",
    "Points (Combo)": "pts",
    "Rebounds": "reb",
    "rebounds": "reb",
    "Rebounds (Combo)": "reb",
    "Assists": "ast",
    "assists": "ast",
    "Assists (Combo)": "ast",
    "3-PT Made": "fg3m",
    "3-PT Made (Combo)": "fg3m",
    "Steals": "stl",
    "Blocked Shots": "blk",
    "Blks+Stls": "bs",
    "Pts+Rebs+Asts": "pra",
    "Pts+Rebs": "pr",
    "Pts+Asts": "pa",
    "Rebs+Asts": "ra",
    "Turnovers": "tov",
    "FG Made": "pts",
    "FG Attempted": "pts",
    "Free Throws Made": "pts",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cbb_root() -> Path:
    return _repo_root() / "Sports" / "CBB"


def default_csv_path(sport: str) -> Path:
    sport_u = str(sport or "").strip().upper()
    if sport_u == "WCBB":
        return _cbb_root() / "data" / "wcbb_defense_by_stat.csv"
    return _cbb_root() / "data" / "cbb_defense_by_stat.csv"


def prop_category(prop: object) -> str:
    p = str(prop or "").strip()
    if p in PROP_TO_CAT:
        return PROP_TO_CAT[p]
    key = " ".join(p.replace("_", " ").replace("-", " ").split())
    for label, cat in PROP_TO_CAT.items():
        if label.lower() == key.lower():
            return cat
    return PROP_TO_CAT.get(key.lower().replace(" ", "_"), "")


def _tier_label(rank: float, n_teams: int) -> str:
    q = max(n_teams / 5.0, 1.0)
    if rank <= q:
        return "HARD"
    if rank <= 2 * q:
        return "HARD_MID"
    if rank <= 3 * q:
        return "MID"
    if rank <= 4 * q:
        return "EASY_MID"
    return "EASY"


def _pick_box_cache(sport: str) -> Path:
    root = _cbb_root()
    if str(sport).upper() == "WCBB":
        cands = [
            root / "data" / "cache" / "wcbb_boxscore_cache.csv",
            root / "wcbb_boxscore_cache.csv",
        ]
    else:
        cands = [
            root / "data" / "cache" / "cbb_boxscore_cache.csv",
            root / "cbb_boxscore_cache.csv",
        ]
    existing = [p for p in cands if p.is_file()]
    if not existing:
        return cands[0]
    return max(existing, key=lambda p: p.stat().st_size)


def _wcbb_espn_team_cache_path() -> Path:
    return _cbb_root() / "data" / "reference" / "wcbb_espn_team_ids.csv"


def _load_espn_wcbb_team_map(*, refresh: bool = False) -> dict[str, str]:
    """ESPN team_id -> abbreviation for women's college basketball."""
    cache = _wcbb_espn_team_cache_path()
    out: dict[str, str] = {}
    if cache.is_file() and not refresh:
        try:
            df = pd.read_csv(cache, encoding="utf-8-sig")
            if {"team_id", "team_abbr"}.issubset(df.columns):
                for _, r in df.iterrows():
                    tid = str(r["team_id"]).strip()
                    abbr = str(r["team_abbr"]).strip().upper()
                    if tid and abbr and abbr not in ("NAN", "NONE", ""):
                        out[tid] = abbr
                if out:
                    return out
        except Exception:
            out = {}

    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/"
        "womens-college-basketball/teams?limit=400"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PropORACLE/1.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rows = []
        for sport in data.get("sports") or []:
            for league in sport.get("leagues") or []:
                for entry in league.get("teams") or []:
                    team = entry.get("team") or entry
                    tid = str(team.get("id") or "").strip()
                    abbr = str(team.get("abbreviation") or "").strip().upper()
                    name = str(team.get("displayName") or team.get("name") or "").strip()
                    if tid and abbr:
                        out[tid] = abbr
                        rows.append({"team_id": tid, "team_abbr": abbr, "team_name": name})
        if rows:
            cache.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_csv(cache, index=False)
    except Exception:
        pass
    return out


def _infer_id_abbr_from_players(sport: str) -> dict[str, str]:
    """Match boxscore player_norm to step slate abbrs to recover team_id→abbr."""
    sport_u = str(sport).upper()
    root = _cbb_root()
    box_path = _pick_box_cache(sport_u)
    if not box_path.is_file():
        return {}
    step_paths = (
        [root / "step5b_wcbb.csv", root / "step3_wcbb.csv", root / "step3b_with_def_rankings_wcbb.csv"]
        if sport_u == "WCBB"
        else [root / "step5b_cbb.csv", root / "step3_cbb.csv"]
    )
    try:
        box = pd.read_csv(box_path, encoding="utf-8-sig", low_memory=False)
    except Exception:
        return {}
    if "player_norm" not in box.columns or "team_id" not in box.columns:
        return {}
    box_pn = box[["player_norm", "team_id"]].copy()
    box_pn["player_norm"] = box_pn["player_norm"].astype(str).str.strip().str.lower()
    box_pn["team_id"] = box_pn["team_id"].astype(str).str.strip()
    box_pn = box_pn[(box_pn["player_norm"] != "") & (box_pn["team_id"] != "") & (box_pn["team_id"] != "nan")]
    box_pn = box_pn.drop_duplicates("player_norm")

    votes: dict[str, list[str]] = {}
    for path in step_paths:
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        except Exception:
            continue
        abbr_col = next(
            (c for c in ("team_abbr", "pp_team", "team") if c in df.columns),
            None,
        )
        pn_col = next((c for c in ("player_norm", "player") if c in df.columns), None)
        if not abbr_col or not pn_col:
            continue
        step = df[[pn_col, abbr_col]].copy()
        step["player_norm"] = step[pn_col].astype(str).str.strip().str.lower()
        step["team_abbr"] = step[abbr_col].astype(str).str.strip().str.upper()
        step = step[(step["player_norm"] != "") & (step["team_abbr"] != "") & (step["team_abbr"] != "NAN")]
        merged = step.merge(box_pn, on="player_norm", how="inner")
        for tid, abbr in zip(merged["team_id"], merged["team_abbr"], strict=False):
            votes.setdefault(str(tid).strip(), []).append(str(abbr).strip().upper())

    out: dict[str, str] = {}
    for tid, abbrs in votes.items():
        if not abbrs:
            continue
        # majority vote
        mode = pd.Series(abbrs).mode()
        out[tid] = str(mode.iloc[0] if len(mode) else abbrs[0]).upper()
    return out


def _team_id_abbr_map(sport: str) -> dict[str, str]:
    """Build ESPN team_id -> abbr for WCBB/CBB from step files / masters / ESPN."""
    root = _cbb_root()
    sport_u = str(sport).upper()
    paths: list[Path] = []
    if sport_u == "WCBB":
        paths = [
            root / "step5b_wcbb.csv",
            root / "step3_wcbb.csv",
            root / "step3b_with_def_rankings_wcbb.csv",
            _wcbb_espn_team_cache_path(),
        ]
    else:
        paths = [
            root / "data" / "reference" / "ncaa_mbb_athletes_master.csv",
            root / "step5b_cbb.csv",
            root / "step3_cbb.csv",
            root / "data" / "reference" / "pp_to_espn_id_map.csv",
        ]
    out: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        except Exception:
            continue
        id_col = next((c for c in ("team_id", "espn_team_id") if c in df.columns), None)
        abbr_col = next(
            (c for c in ("team_abbr", "pp_team", "team", "opp_team_abbr") if c in df.columns),
            None,
        )
        if not id_col or not abbr_col:
            continue
        pair = df[[id_col, abbr_col]].dropna()
        for _, r in pair.iterrows():
            tid = str(r[id_col]).strip()
            abbr = str(r[abbr_col]).strip().upper()
            if tid and tid.lower() != "nan" and abbr and abbr not in ("NAN", "NONE", ""):
                # Prefer non-numeric-looking abbrs; skip blank ids
                out.setdefault(tid, abbr)
        # also opp side if present
        if "opp_team_id" in df.columns and "opp_team_abbr" in df.columns:
            for _, r in df[["opp_team_id", "opp_team_abbr"]].dropna().iterrows():
                tid = str(r["opp_team_id"]).strip()
                abbr = str(r["opp_team_abbr"]).strip().upper()
                if tid and tid.lower() != "nan" and abbr and abbr not in ("NAN", "NONE", ""):
                    out.setdefault(tid, abbr)

    # Slate step files often lack team_id for WCBB — recover via player_norm match.
    inferred = _infer_id_abbr_from_players(sport_u)
    for tid, abbr in inferred.items():
        out.setdefault(tid, abbr)

    if sport_u == "WCBB" and len(out) < 50:
        espn = _load_espn_wcbb_team_map()
        for tid, abbr in espn.items():
            out.setdefault(tid, abbr)

    return out


def _resolve_team_key(raw_key: object, team_id: object, id_map: dict[str, str]) -> str:
    """Resolve box opp key to a team abbr when possible.

    Men's CBB cache often stores ESPN team_id digits in ``opp_team_abbr`` for
    many D1 opponents; map those via id_map so we do not drop ~400 teams.
    """
    key = str(raw_key or "").strip().upper()
    tid = str(team_id or "").strip()
    if key and key not in ("NAN", "NONE") and not key.isdigit():
        return key
    for candidate in (tid, key):
        if not candidate or candidate.lower() == "nan":
            continue
        mapped = id_map.get(str(candidate).strip())
        if mapped:
            return str(mapped).strip().upper()
    return key if key and key not in ("NAN", "NONE") else (tid if tid.lower() != "nan" else "")


def _normalize_box(df: pd.DataFrame, sport: str) -> pd.DataFrame:
    work = df.copy()
    rename = {
        "PTS": "pts",
        "REB": "reb",
        "AST": "ast",
        "STL": "stl",
        "BLK": "blk",
        "TO": "tov",
        "3PM": "fg3m",
    }
    work = work.rename(columns={k: v for k, v in rename.items() if k in work.columns})
    id_map = _team_id_abbr_map(sport)
    work["offense_team_id"] = work["team_id"].astype(str).str.strip()
    if "opp_team_id" in work.columns:
        work["defense_team_id"] = work["opp_team_id"].astype(str).str.strip()
    elif "opp_team_abbr" in work.columns:
        # When abbr column holds ESPN ids, keep them as defense_team_id metadata.
        raw_abbr = work["opp_team_abbr"].astype(str).str.strip()
        work["defense_team_id"] = raw_abbr.where(raw_abbr.str.fullmatch(r"\d+"), "")
    else:
        work["defense_team_id"] = ""

    if "opp_team_abbr" in work.columns:
        raw_keys = work["opp_team_abbr"].astype(str).str.strip().str.upper()
        tids = work["defense_team_id"]
        work["defense_team_key"] = [
            _resolve_team_key(k, tid, id_map) for k, tid in zip(raw_keys, tids, strict=False)
        ]
    else:
        work["defense_team_key"] = work["defense_team_id"].map(
            lambda x: id_map.get(str(x).strip(), str(x).strip())
        )
        work["defense_team_key"] = work["defense_team_key"].astype(str).str.strip().str.upper()
    # Stash map for rebuild aliasing / fills
    work.attrs["id_abbr_map"] = id_map
    return work


def _norm_team_name(name: object) -> str:
    s = str(name or "").strip().upper()
    if not s or s in ("NAN", "NONE"):
        return ""
    s = (
        s.replace("&AMP;", "&")
        .replace(".", "")
        .replace("'", "")
        .replace("-", " ")
        .replace("(", " ")
        .replace(")", " ")
    )
    s = " ".join(s.split())
    # Common Torvik / Sports-Reference shortenings ("Iowa St." → "IOWA STATE")
    if s.endswith(" ST"):
        s = s[:-3] + " STATE"
    s = s.replace(" N C ", " NC ").replace("N C STATE", "NC STATE")
    return s


def _load_abbr_to_sr() -> dict[str, str]:
    """PrizePicks abbr → Sports-Reference sr_name from step3b map (AST parse)."""
    path = _cbb_root() / "scripts" / "pipeline" / "step3b_attach_def_rankings.py"
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "ABBR_TO_SR":
                    raw = ast.literal_eval(node.value)
                    if isinstance(raw, dict):
                        for abbr, sr in raw.items():
                            a = str(abbr).strip().upper()
                            if a:
                                out[a] = str(sr).strip()
                    return out
    except Exception:
        return out
    return out


def _cbb_name_to_abbr() -> dict[str, str]:
    """Build normalized team-name → abbr from athletes master + ABBR_TO_SR."""
    out: dict[str, str] = {}
    abbr_to_sr = _load_abbr_to_sr()
    for abbr, sr in abbr_to_sr.items():
        key = _norm_team_name(sr)
        if key:
            out.setdefault(key, abbr)

    ath_path = _cbb_root() / "data" / "reference" / "ncaa_mbb_athletes_master.csv"
    if ath_path.is_file():
        try:
            ath = pd.read_csv(ath_path, encoding="utf-8-sig", low_memory=False)
        except Exception:
            ath = pd.DataFrame()
        if not ath.empty and {"team_abbr", "team_name"}.issubset(ath.columns):
            for _, r in ath[["team_abbr", "team_name"]].drop_duplicates().iterrows():
                abbr = str(r["team_abbr"]).strip().upper()
                if not abbr or abbr in ("NAN", "NONE"):
                    continue
                full = _norm_team_name(r["team_name"])
                if full:
                    out.setdefault(full, abbr)
                    parts = full.split()
                    # Strip trailing mascot token(s): "ALABAMA AM BULLDOGS" → "ALABAMA AM"
                    if len(parts) >= 2:
                        out.setdefault(" ".join(parts[:-1]), abbr)
                    if len(parts) >= 3:
                        out.setdefault(" ".join(parts[:-2]), abbr)
    return out


def _cbb_d1_universe() -> set[str]:
    """D1 abbr set from athletes master (+ any real abbrs from step3/step5b).

    Does **not** add every ABBR_TO_SR key — that map includes aliases (NOVA/VILL,
    FSU/FLST, …) which would invent phantom teams and inflate fills.
    """
    root = _cbb_root()
    out: set[str] = set()
    ath = root / "data" / "reference" / "ncaa_mbb_athletes_master.csv"
    if ath.is_file():
        try:
            df = pd.read_csv(ath, encoding="utf-8-sig", low_memory=False)
            if "team_abbr" in df.columns:
                for v in df["team_abbr"].dropna().astype(str).str.strip().str.upper():
                    if v and v not in ("NAN", "NONE") and not v.isdigit() and len(v) <= 8:
                        out.add(v)
        except Exception:
            pass
    for path in (
        root / "step5b_cbb.csv",
        root / "step3_cbb.csv",
        root / "step3b_with_def_rankings_cbb.csv",
    ):
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        except Exception:
            continue
        for col in ("team_abbr", "pp_team", "opp_team_abbr", "pp_opp_team"):
            if col not in df.columns:
                continue
            for v in df[col].dropna().astype(str).str.strip().str.upper():
                if v and v not in ("NAN", "NONE") and not v.isdigit() and len(v) <= 8:
                    out.add(v)
    return out


def _cbb_fill_missing_d1(missing: set[str], name_to_abbr: dict[str, str]) -> pd.DataFrame:
    """Fill D1 teams absent from box cache via PPG rankings, else Torvik adj_d.

    ``stat_source`` is ``ppg_rank`` or ``torvik_adj_d``. Prop-specific reb/ast/…
    are left blank (pts/overall only).
    """
    if not missing:
        return pd.DataFrame()

    abbr_to_sr = _load_abbr_to_sr()
    ppg_by_name: dict[str, float] = {}
    def_path = _cbb_root() / "data" / "reference" / "cbb_def_rankings.csv"
    if def_path.is_file():
        try:
            ddef = pd.read_csv(def_path, encoding="utf-8-sig")
            if "sr_name" in ddef.columns and "opp_ppg" in ddef.columns:
                for _, r in ddef.iterrows():
                    key = _norm_team_name(r.get("sr_name"))
                    ppg = pd.to_numeric(r.get("opp_ppg"), errors="coerce")
                    if key and pd.notna(ppg):
                        ppg_by_name.setdefault(key, float(ppg))
        except Exception:
            pass

    torvik_by_name: dict[str, float] = {}
    torvik_path = _cbb_root() / "data" / "reference" / "torvik_team_ratings.csv"
    if torvik_path.is_file():
        try:
            tv = pd.read_csv(torvik_path, encoding="utf-8-sig")
            if {"team", "adj_d"}.issubset(tv.columns):
                for _, r in tv.iterrows():
                    key = _norm_team_name(r.get("team"))
                    adj = pd.to_numeric(r.get("adj_d"), errors="coerce")
                    if key and pd.notna(adj):
                        torvik_by_name.setdefault(key, float(adj))
        except Exception:
            pass

    def _names_for_abbr(abbr: str) -> list[str]:
        names: list[str] = []
        sr = abbr_to_sr.get(abbr)
        if sr:
            names.append(_norm_team_name(sr))
        # Reverse lookup: any normalized name that maps to this abbr
        for nm, ab in name_to_abbr.items():
            if ab == abbr and nm not in names:
                names.append(nm)
        return [n for n in names if n]

    rows: list[dict] = []
    for abbr in sorted(missing):
        names = _names_for_abbr(abbr)
        filled = False
        for nm in names:
            if nm in ppg_by_name:
                rows.append(
                    {
                        "team": abbr,
                        "opp_pts": ppg_by_name[nm],
                        "games": 0,
                        "stat_source": "ppg_rank",
                        "team_id": "",
                    }
                )
                filled = True
                break
        if filled:
            continue
        for nm in names:
            if nm in torvik_by_name:
                rows.append(
                    {
                        "team": abbr,
                        "opp_pts": torvik_by_name[nm],
                        "games": 0,
                        "stat_source": "torvik_adj_d",
                        "team_id": "",
                    }
                )
                break
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _reaggregate_by_team(summary: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """Collapse duplicate team keys (e.g. after id→abbr resolve) weighting by games."""
    if summary.empty or "team" not in summary.columns:
        return summary
    summary = summary.copy()
    summary["team"] = summary["team"].astype(str).str.strip().str.upper()
    if not summary["team"].duplicated().any():
        return summary
    summary["games"] = pd.to_numeric(summary.get("games", 0), errors="coerce").fillna(0.0)
    pieces = []
    for team, grp in summary.groupby("team", sort=False):
        if len(grp) == 1:
            pieces.append(grp.iloc[0].to_dict())
            continue
        w = grp["games"].astype(float)
        wsum = float(w.sum())
        row = {"team": team, "games": wsum}
        for m in metrics:
            if m not in grp.columns:
                continue
            vals = pd.to_numeric(grp[m], errors="coerce")
            if wsum > 0 and vals.notna().any():
                row[m] = float((vals.fillna(0.0) * w).sum() / wsum)
            else:
                row[m] = float(vals.mean()) if vals.notna().any() else None
        if "team_id" in grp.columns:
            # Prefer non-empty metadata id
            ids = [
                str(x).strip()
                for x in grp["team_id"].tolist()
                if str(x).strip() and str(x).strip().lower() not in ("nan", "none", "")
            ]
            row["team_id"] = ids[0] if ids else ""
        if "stat_source" in grp.columns:
            row["stat_source"] = "box" if (grp["stat_source"] == "box").any() else grp["stat_source"].iloc[0]
        pieces.append(row)
    return pd.DataFrame(pieces)


def rebuild_defense_by_stat(sport: str = "CBB", out_path: Optional[Path] = None) -> pd.DataFrame:
    sport_u = str(sport or "CBB").strip().upper()
    if sport_u not in ("CBB", "WCBB"):
        sport_u = "CBB"
    out_path = Path(out_path or default_csv_path(sport_u))
    cache = _pick_box_cache(sport_u)
    if not cache.is_file():
        return pd.DataFrame()

    raw = pd.read_csv(cache, encoding="utf-8-sig", low_memory=False)
    if raw.empty or "event_id" not in raw.columns:
        return pd.DataFrame()

    work = _normalize_box(raw, sport_u)
    id_map: dict[str, str] = dict(work.attrs.get("id_abbr_map") or {})
    # Reverse abbr → id for metadata when defense_team_id was blank
    abbr_to_id = {v: k for k, v in id_map.items()}
    stat_cols = [c for c in ("pts", "reb", "ast", "stl", "blk", "tov", "fg3m") if c in work.columns]
    for c in stat_cols:
        work[c] = pd.to_numeric(work[c], errors="coerce").fillna(0.0)

    # Offense produced by team_id in each game
    gcols = ["event_id", "game_date", "offense_team_id", "defense_team_id", "defense_team_key"] + stat_cols
    gcols = [c for c in gcols if c in work.columns]
    group_keys = [c for c in ("event_id", "offense_team_id", "defense_team_key") if c in gcols]
    team_game = (
        work[gcols]
        .groupby(group_keys, as_index=False)
        .agg(
            **{c: (c, "sum") for c in stat_cols},
            **(
                {"game_date": ("game_date", "first")}
                if "game_date" in gcols
                else {}
            ),
            **(
                {"defense_team_id": ("defense_team_id", "first")}
                if "defense_team_id" in gcols
                else {}
            ),
        )
    )
    # Opp-allowed for defense_team_key = offense produced by the other team
    allowed = team_game.rename(columns={"defense_team_key": "team"})
    for c in stat_cols:
        allowed[f"opp_{c}"] = allowed[c]
    if {"opp_pts", "opp_reb", "opp_ast"}.issubset(allowed.columns):
        allowed["opp_pra"] = allowed["opp_pts"] + allowed["opp_reb"] + allowed["opp_ast"]
        allowed["opp_pr"] = allowed["opp_pts"] + allowed["opp_reb"]
        allowed["opp_pa"] = allowed["opp_pts"] + allowed["opp_ast"]
        allowed["opp_ra"] = allowed["opp_reb"] + allowed["opp_ast"]
    if {"opp_stl", "opp_blk"}.issubset(allowed.columns):
        allowed["opp_bs"] = allowed["opp_stl"] + allowed["opp_blk"]

    metrics = [c for c in allowed.columns if c.startswith("opp_")]
    if "game_date" not in allowed.columns:
        allowed["game_date"] = allowed["event_id"]
    agg_kwargs = {m: (m, "mean") for m in metrics}
    agg_kwargs["games"] = ("game_date", "nunique")
    if "defense_team_id" in allowed.columns:
        agg_kwargs["team_id"] = ("defense_team_id", "first")
    summary = allowed.groupby("team", as_index=False).agg(**agg_kwargs)

    # Belt-and-suspenders: resolve any remaining numeric keys via id_map
    summary["team"] = [
        _resolve_team_key(t, tid if "team_id" in summary.columns else "", id_map)
        for t, tid in zip(
            summary["team"],
            summary["team_id"] if "team_id" in summary.columns else [""] * len(summary),
            strict=False,
        )
    ]
    summary = _reaggregate_by_team(summary, metrics)

    # Prefer abbreviation keys; when map is sparse keep team_id keys too.
    team_s = summary["team"].astype(str)
    is_numeric_id = team_s.str.fullmatch(r"\d+")
    abbr_rows = summary[~is_numeric_id].copy()
    id_rows = summary[is_numeric_id].copy()

    if sport_u == "CBB":
        # Men's CBB: keep abbr rows (mapped D1 + real abbrs). Drop unresolved numeric ids.
        summary = abbr_rows if not abbr_rows.empty else summary
        summary = summary[summary["team"].astype(str).str.len() <= 8].copy()
        summary["stat_source"] = "box"

        d1 = _cbb_d1_universe()
        name_to_abbr = _cbb_name_to_abbr()
        # Prefer D1 box teams; also keep high-volume box abbrs missing from master
        in_d1 = summary["team"].isin(d1)
        high_vol = pd.to_numeric(summary.get("games", 0), errors="coerce").fillna(0) >= 10
        keep = summary[in_d1 | high_vol].copy()
        if keep.empty:
            keep = summary.copy()
        summary = keep

        missing = d1 - set(summary["team"].astype(str).str.upper())
        fills = _cbb_fill_missing_d1(missing, name_to_abbr)
        if not fills.empty:
            # Ensure fill rows have metric columns present (blank except opp_pts)
            for m in metrics:
                if m not in fills.columns:
                    fills[m] = pd.NA
            if "team_id" not in fills.columns:
                fills["team_id"] = ""
            summary = pd.concat([summary, fills], ignore_index=True, sort=False)

        # team_id is metadata only — fill from abbr map when blank
        if "team_id" not in summary.columns:
            summary["team_id"] = ""
        summary["team_id"] = summary.apply(
            lambda r: (
                str(r["team_id"]).strip()
                if str(r.get("team_id", "")).strip()
                and str(r.get("team_id", "")).strip().lower() not in ("nan", "none")
                else abbr_to_id.get(str(r["team"]).strip().upper(), "")
            ),
            axis=1,
        )
    elif len(abbr_rows) >= 20:
        # Dense abbr coverage: drop unresolved numeric ids.
        summary = abbr_rows if not abbr_rows.empty else summary
        summary = summary[summary["team"].astype(str).str.len() <= 8].copy()
    else:
        # Sparse abbr map (common WCBB): keep team_id keys AND emit abbr aliases.
        pieces = [id_rows]
        if not abbr_rows.empty:
            pieces.append(abbr_rows)
        # Alias: for each numeric id with a known abbr, duplicate the row under abbr.
        if not id_rows.empty and id_map:
            aliases = []
            for _, row in id_rows.iterrows():
                tid = str(row["team"]).strip()
                abbr = id_map.get(tid) or id_map.get(str(row.get("team_id", "")).strip())
                if not abbr:
                    continue
                alias = row.copy()
                alias["team"] = str(abbr).strip().upper()
                if "team_id" not in alias.index or pd.isna(alias.get("team_id")):
                    alias["team_id"] = tid
                aliases.append(alias)
            if aliases:
                pieces.append(pd.DataFrame(aliases))
        summary = pd.concat(pieces, ignore_index=True) if pieces else summary
        summary = summary.drop_duplicates(subset=["team"], keep="first")

    if summary.empty:
        return pd.DataFrame()

    summary = summary.copy()
    summary["team"] = summary["team"].astype(str).str.strip().str.upper()
    summary = summary.drop_duplicates(subset=["team"], keep="first")

    # Rank by team abbreviation (CBB must NOT collapse on team_id).
    # WCBB may still use team_id keys when abbr map is sparse.
    if sport_u == "CBB":
        rank_units = summary.copy()
        rank_units["_rk"] = rank_units["team"].astype(str)
    elif "team_id" in summary.columns and summary["team_id"].notna().any():
        rank_base = summary.copy()
        rank_base["_rk"] = rank_base["team_id"].astype(str).where(
            rank_base["team_id"].notna() & (rank_base["team_id"].astype(str).str.strip() != ""),
            rank_base["team"].astype(str),
        )
        rank_units = rank_base.drop_duplicates(subset=["_rk"], keep="first")
    else:
        rank_units = summary.drop_duplicates(subset=["team"], keep="first").copy()
        rank_units["_rk"] = rank_units["team"].astype(str)

    n_teams = len(rank_units)
    for m in metrics:
        cat = m.replace("opp_", "")
        # Prop-specific ranks only among teams with a real sample for that metric
        vals = pd.to_numeric(rank_units[m], errors="coerce")
        if sport_u == "CBB" and cat != "pts":
            # Fill-only rows have blank reb/ast/… — leave those ranks empty
            ranked = vals.rank(method="min", ascending=True)
            rank_units[f"{cat}_rank"] = ranked
            # Do not assign tiers for null ranks
            rank_units[f"{cat}_tier"] = rank_units[f"{cat}_rank"].map(
                lambda r: _tier_label(float(r), int(vals.notna().sum()) or n_teams)
                if pd.notna(r)
                else pd.NA
            )
        else:
            # pts / overall: rank all teams that have a value (box + fill)
            ranked = vals.rank(method="min", ascending=True)
            rank_units[f"{cat}_rank"] = ranked
            rank_n = int(vals.notna().sum()) or n_teams
            rank_units[f"{cat}_tier"] = rank_units[f"{cat}_rank"].map(
                lambda r: _tier_label(float(r), rank_n) if pd.notna(r) else pd.NA
            )
            if cat == "pts":
                # n_teams for pts/overall reflects the ranked universe size
                n_teams = rank_n

    rank_units["n_teams"] = n_teams
    if sport_u == "CBB":
        summary = summary.copy()
        summary["_rk"] = summary["team"].astype(str)
    elif "team_id" in summary.columns and summary["team_id"].notna().any():
        summary = summary.copy()
        summary["_rk"] = summary["team_id"].astype(str).where(
            summary["team_id"].notna() & (summary["team_id"].astype(str).str.strip() != ""),
            summary["team"].astype(str),
        )
    else:
        summary = summary.copy()
        summary["_rk"] = summary["team"].astype(str)
    summary = summary.drop(
        columns=[c for c in summary.columns if c.endswith("_rank") or c.endswith("_tier")],
        errors="ignore",
    )
    summary = summary.merge(
        rank_units[
            ["_rk"]
            + [c for c in rank_units.columns if c.endswith("_rank") or c.endswith("_tier")]
            + ["n_teams"]
        ],
        on="_rk",
        how="left",
    )
    summary = summary.drop(columns=["_rk"], errors="ignore")
    summary["overall_rank"] = summary["pts_rank"] if "pts_rank" in summary.columns else pd.NA
    summary["n_teams"] = n_teams
    if "stat_source" not in summary.columns:
        summary["stat_source"] = "box"

    # Optional: Torvik adj_d overlay flag for CBB
    if sport_u == "CBB":
        torvik = _cbb_root() / "data" / "reference" / "torvik_team_ratings.csv"
        if torvik.is_file():
            try:
                tv = pd.read_csv(torvik, encoding="utf-8-sig")
                if "adj_d" in tv.columns and "team" in tv.columns:
                    summary["torvik_available"] = 1
            except Exception:
                pass

    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_path, index=False)
    return summary


@lru_cache(maxsize=8)
def load_defense_table(sport: str, csv_path: str = "") -> pd.DataFrame:
    sport_u = str(sport or "CBB").strip().upper()
    path = Path(csv_path) if csv_path else default_csv_path(sport_u)
    if not path.is_file() or path.stat().st_size < 50:
        rebuild_defense_by_stat(sport_u, out_path=path)
    if not path.is_file():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()
    if "team" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["team"] = df["team"].astype(str).str.strip().str.upper()
    return df


def clear_defense_cache() -> None:
    load_defense_table.cache_clear()


def lookup_stat_defense(
    sport: str,
    opp: object,
    prop: object,
    *,
    csv_path: str = "",
) -> dict:
    cat = prop_category(prop)
    team = str(opp or "").strip().upper()
    empty = empty_stat_def(cat)
    if not cat or not team:
        return empty
    df = load_defense_table(sport, csv_path)
    if df.empty:
        return empty
    sub = df[df["team"] == team]
    if sub.empty and "team_id" in df.columns:
        sub = df[df["team_id"].astype(str).str.strip() == team]
    if sub.empty:
        return empty
    row = sub.iloc[0]
    rank_col = f"{cat}_rank"
    rank = None
    if rank_col in row.index and pd.notna(row[rank_col]):
        try:
            rank = int(float(row[rank_col]))
        except (TypeError, ValueError):
            rank = None
    n_teams = int(row["n_teams"]) if "n_teams" in row.index and pd.notna(row.get("n_teams")) else len(df)
    coarse = coarse_bucket_from_rank(rank, n_teams) if rank is not None else "UNK"
    return {
        "stat_def_category": cat,
        "stat_def_rank": rank,
        "stat_def_tier": coarse,
        "stat_def_coarse": coarse,
    }


def attach_stat_defense_columns(
    df: pd.DataFrame,
    *,
    sport: str,
    csv_path: str = "",
) -> pd.DataFrame:
    sport_u = str(sport).upper()

    def _lookup(opp, prop):
        return lookup_stat_defense(sport_u, opp, prop, csv_path=csv_path)

    return attach_lookup_columns(df, sport=sport_u, lookup_fn=_lookup)
