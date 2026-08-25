"""
Step 1 — Fetch PrizePicks Soccer Board
HTTP first (curl_cffi chrome131 via shared API module), urllib fallback.
Optional --cdp attaches to warmed Chrome (DataDome bypass) and fetches all boards
in one session. --fail-fast keeps HTTP from burning 30–120+ minutes on 403 cooldowns.

Usage:
    py step1_fetch_prizepicks_soccer.py --output s1_soccer_props.csv
    py step1_fetch_prizepicks_soccer.py --include_halves --output s1_soccer_props.csv
    py step1_fetch_prizepicks_soccer.py --no-world-cup   # skip WC boards when inactive
    py step1_fetch_prizepicks_soccer.py --league_id 82 --output s1_soccer_props.csv
    py step1_fetch_prizepicks_soccer.py --cdp http://127.0.0.1:9222 --fail-fast
"""

import argparse
import sys
import time
import json
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

_PROPORACLE_ROOT = Path(__file__).resolve().parents[3]
if str(_PROPORACLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROPORACLE_ROOT))

from utils.pp_fetch_stamp import extract_pp_updated_at, now_et_iso, stamp_fetched_at
from scripts.line_history_archive import try_archive_lines
from utils.prizepicks_http import fetch_pp_projections, make_pp_session, ensure_chrome131
from utils.prizepicks_cdp import (
    align_cdp_context_for_datadome,
    cdp_board_ready,
    connect_over_cdp,
    fetch_projections_inpage,
    pick_cdp_warmed_page,
)
from utils.step1_slate_date_filter import (
    apply_game_date_filter,
    eastern_today_ymd,
    no_props_log_line,
    should_preserve_append_output,
)

# PrizePicks internal soccer league IDs (from GET /leagues)
SOCCER_BOARDS = {
    "82":  "SOCCER",       # club soccer (full game)
    "242": "SOCCER1H",     # club first half
    "243": "SOCCER2H",     # club second half
    "262": "SOCCERSZN",    # club season props
}
WORLD_CUP_BOARDS = {
    "241": "WORLDCUP",     # World Cup full game
    "458": "WORLDCUP1H",   # World Cup first half
    "459": "WORLDCUP2H",   # World Cup second half
    "457": "WORLDCUPTRNY", # World Cup tournament props
}

PICKTYPE_MAP = {
    "standard": "Standard",
    "goblin":   "Goblin",
    "demon":    "Demon",
}

HEADERS = {
    "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept":      "application/json",
    "Referer":     "https://app.prizepicks.com/",
    "Origin":      "https://app.prizepicks.com",
}

DEFAULT_TZ = "America/New_York"


def _default_et_date_str() -> str:
    return datetime.now(ZoneInfo(DEFAULT_TZ)).date().isoformat()


def _fetch_board_urllib(
    league_id: str,
    league_name: str,
    per_page: int = 250,
    *,
    fail_fast: bool = False,
) -> tuple[list, list]:
    """Legacy urllib fetch (both in_game flags) — fallback when curl_cffi fails."""
    all_data = []
    all_included = []
    max_attempts = 1 if fail_fast else 3

    for in_game in ("false", "true"):
        url = (
            f"https://api.prizepicks.com/projections"
            f"?league_id={league_id}"
            f"&per_page={per_page}"
            f"&single_stat=true"
            f"&in_game={in_game}"
            f"&game_mode=pickem"
        )
        for attempt in range(1, max_attempts + 1):
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=20 if fail_fast else 30) as resp:
                    j = json.loads(resp.read())
                data = j.get("data") or []
                incl = j.get("included") or []
                all_data.extend(data)
                all_included.extend(incl)
                print(f"    urllib in_game={in_game}: {len(data)} props")
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and not fail_fast:
                    wait = 60 * attempt
                    print(f"    429 rate limit — waiting {wait}s (attempt {attempt})")
                    time.sleep(wait)
                else:
                    print(f"    HTTP {e.code} for {league_name} in_game={in_game}: {e}")
                    break
            except Exception as e:
                print(f"    Error fetching {league_name} in_game={in_game}: {e}")
                break

    return all_data, all_included


def fetch_board(
    league_id: str,
    league_name: str,
    per_page: int = 250,
    retries: int = 5,
    *,
    fail_fast: bool = False,
) -> tuple[list, list]:
    """Fetch props for a board — HTTP (curl_cffi) first, urllib fallback."""
    all_data: list = []
    all_included: list = []
    seen: set[str] = set()

    def _extend(data: list, included: list) -> int:
        added = 0
        for obj in data or []:
            oid = str(obj.get("id", "")).strip()
            if oid and oid not in seen:
                seen.add(oid)
                all_data.append(obj)
                added += 1
        all_included.extend(included or [])
        return added

    http_ok = False
    try:
        ensure_chrome131()
        # Fail-fast: one session wave, short gaps, no 90s DataDome cooldown windows.
        kw: dict = {
            "per_page": per_page,
            "max_pages": 4 if fail_fast else 10,
            "retries": max(1, min(retries, 2 if fail_fast else retries)),
        }
        if fail_fast:
            kw.update(
                fail_fast=True,
                first_page_waves=1,
                forbid_cooldown_threshold=99,
                forbid_max_cooldown_windows=0,
                inter_page_delay=(0.4, 1.0),
                session_jitter=(0.2, 0.8),
                wave_gap_seconds=(0.5, 1.0),
            )
        data, included = fetch_pp_projections(str(league_id), **kw)
        if data:
            n = _extend(data, included)
            http_ok = True
            print(f"    HTTP (curl_cffi) in_game=false: {n} props")
    except Exception as e:
        print(f"    HTTP fetch failed ({type(e).__name__}: {e})")

    if not http_ok:
        if fail_fast:
            print(f"    Fail-fast: skipping urllib long-retry fallback for {league_name}")
            return all_data, all_included
        print(f"    Falling back to urllib for {league_name}...")
        return _fetch_board_urllib(
            league_id, league_name, per_page=per_page, fail_fast=fail_fast
        )

    # Live in-game board supplement (not covered by fetch_pp_projections defaults)
    try:
        session = make_pp_session(HEADERS)
        url = (
            f"https://api.prizepicks.com/projections"
            f"?league_id={league_id}"
            f"&per_page={per_page}"
            f"&single_stat=true"
            f"&in_game=true"
            f"&game_mode=pickem"
        )
        r = session.get(url, timeout=15 if fail_fast else 30)
        if r.status_code == 200:
            j = r.json()
            n = _extend(j.get("data") or [], j.get("included") or [])
            if n:
                print(f"    HTTP in_game=true supplement: +{n} props")
        elif r.status_code == 403:
            print("    HTTP in_game=true: 403 (skipped)")
        else:
            print(f"    HTTP in_game=true: status {r.status_code}")
    except Exception as e:
        print(f"    in_game=true supplement skipped: {e}")

    return all_data, all_included


def fetch_boards_via_cdp(
    boards: list[tuple[str, str]],
    *,
    cdp_url: str,
    per_page: int = 250,
    attach_timeout_ms: int = 30_000,
    request_timeout_ms: int = 25_000,
) -> list[tuple[str, str, list, list]]:
    """Fetch many soccer boards in one CDP session. Returns (lid, lname, data, included)."""
    from playwright.sync_api import sync_playwright

    results: list[tuple[str, str, list, list]] = []
    primary_lid = boards[0][0] if boards else "82"
    with sync_playwright() as p:
        browser = connect_over_cdp(p, cdp_url, timeout_ms=attach_timeout_ms)
        if not browser.contexts:
            raise RuntimeError("CDP browser has no contexts; start Chrome with --remote-debugging-port.")
        context = browser.contexts[0]
        print("  Using browser context[0] (existing session / cookies).")
        align_cdp_context_for_datadome(context)
        opened_new = False
        page = pick_cdp_warmed_page(context, primary_lid)
        if page is not None:
            print(f"  Reusing warmed PP tab: {page.url}")
        else:
            page = context.new_page()
            opened_new = True
            print("  No warmed PP tab found — opened new page (solve DataDome in Chrome if 403).")
        page.set_default_timeout(max(30_000, int(request_timeout_ms) + 5_000))
        if not cdp_board_ready(page, primary_lid):
            print("  [CDP] No PrizePicks tab ready — not navigating (avoids DataDome). Open /board in Chrome first.")
            raise RuntimeError("CDP board not ready; skip league hop")
        else:
            try:
                page.bring_to_front()
            except Exception:
                pass
            page.wait_for_timeout(1000)

        for lid, lname in boards:
            print(f"\n  → {lname} (league_id={lid}) [CDP]")
            data, included, status, url = fetch_projections_inpage(
                page,
                lid,
                per_page=per_page,
                request_timeout_ms=request_timeout_ms,
            )
            print(f"    [CDP] status={status} rows={len(data)} url={url}")
            results.append((lid, lname, data, included))

        if opened_new:
            try:
                page.close()
            except Exception:
                pass
        browser.close()
    return results


def build_rows(data: list, included: list, league_name: str) -> list:
    players_map = {}
    games_map   = {}
    for obj in included:
        obj_id   = obj.get("id")
        obj_type = obj.get("type", "")
        attrs    = obj.get("attributes", {})
        if obj_type in ("new_player", "player"):
            players_map[obj_id] = attrs
        elif obj_type in ("game", "new_game"):
            games_map[obj_id] = attrs

    rows     = []
    seen_ids = set()
    for proj in data:
        proj_id = str(proj.get("id", ""))
        if not proj_id or proj_id in seen_ids:
            continue
        seen_ids.add(proj_id)

        attrs = proj.get("attributes", {})
        rels  = proj.get("relationships", {})

        player_id = (rels.get("new_player") or rels.get("player") or {}).get("data", {}).get("id", "")
        game_id   = (rels.get("new_game")   or rels.get("game")   or {}).get("data", {}).get("id", "")
        p = players_map.get(str(player_id), {})
        g = games_map.get(str(game_id), {})

        player_name = str(p.get("display_name", p.get("name", ""))).strip()
        team        = str(p.get("team", "")).strip().upper()
        pos         = str(p.get("position", "")).strip()
        image_url   = str(p.get("image_url") or p.get("image_url_small") or "").strip()

        home = str(
            g.get("home_team")
            or g.get("home_team_name")
            or g.get("home")
            or ""
        ).strip().upper()
        away = str(
            g.get("away_team")
            or g.get("away_team_name")
            or g.get("away")
            or ""
        ).strip().upper()
        start_time = str(g.get("start_time", attrs.get("start_time", ""))).strip()

        opp_team = ""
        if team and home and away:
            opp_team = away if team == home else (home if team == away else "")

        # Derive sub-league from game description or player league attr
        sub_league = str(attrs.get("league", p.get("league", league_name))).strip()
        if not sub_league:
            sub_league = league_name
        # PrizePicks API returns "WORLD CUP" text; keep board tag (WORLDCUP, WORLDCUP2H, …) for pipeline keys
        if str(league_name).upper().startswith("WORLDCUP"):
            sub_league = league_name

        odds_type = str(attrs.get("odds_type", "")).strip().lower()
        pick_type = PICKTYPE_MAP.get(odds_type, "Standard")
        prop_type = str(attrs.get("stat_type", attrs.get("name", ""))).strip()
        line      = attrs.get("line_score", attrs.get("line", ""))
        std_api = attrs.get("standard_line") or attrs.get("standard_score") or attrs.get("baseline")
        if pick_type == "Standard":
            standard_line = std_api if std_api is not None and str(std_api).strip() != "" else line
        else:
            standard_line = std_api if std_api is not None else ""

        rows.append({
            "projection_id":    proj_id,
            "pp_projection_id": proj_id,
            "player_id":        str(player_id),
            "pp_game_id":       str(game_id),
            "league":           sub_league,
            "start_time":       start_time,
            "player":           player_name,
            "image_url":        image_url,
            "pos":              pos,
            "team":             team,
            "opp_team":         opp_team,
            "pp_home_team":     home,
            "pp_away_team":     away,
            "prop_type":        prop_type,
            "line":             line,
            "standard_line":    standard_line,
            "pick_type":        pick_type,
            "pp_updated_at":    extract_pp_updated_at(attrs),
        })

    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output",          default="s1_soccer_props.csv")
    ap.add_argument("--include_halves",  action="store_true",
                    help="Also fetch SOCCER1H and SOCCER2H boards")
    ap.add_argument("--include_season",  action="store_true",
                    help="Also fetch SOCCERSZN board")
    ap.add_argument(
        "--no-world-cup",
        action="store_true",
        help="Skip World Cup boards (241/458/459/457). Default: include when PP has WC slate.",
    )
    ap.add_argument("--league_id", default=None, metavar="ID",
                    help="Primary board PrizePicks league_id (default 82). "
                         "Half/season extras still come from --include_halves / --include_season.")
    ap.add_argument(
        "--append",
        action="store_true",
        help="Append this fetch after existing CSV rows, then dedupe (keep='last').",
    )
    ap.add_argument(
        "--date",
        default=_default_et_date_str(),
        help=f"Target game date in {DEFAULT_TZ} (YYYY-MM-DD). Defaults to today {DEFAULT_TZ}.",
    )
    ap.add_argument("--tz", default=DEFAULT_TZ, help="Timezone used to derive game_date from start_time.")
    ap.add_argument(
        "--allow-nearest-future",
        action="store_true",
        help="Skip same-day date filter (keep full API board; explicit opt-in only).",
    )
    ap.add_argument(
        "--include-tomorrow",
        action="store_true",
        help="Also keep Eastern tomorrow's games (day-ahead Standard unders).",
    )
    ap.add_argument(
        "--board-date",
        default="",
        help="Fetch calendar YYYY-MM-DD for board_date/line_asof (default: Eastern today).",
    )
    ap.add_argument(
        "--max-retries",
        "--api-retries",
        type=int,
        default=5,
        dest="max_retries",
        help="HTTP retries per board fetch (default 5).",
    )
    ap.add_argument(
        "--fail-fast",
        action="store_true",
        help="Short HTTP path: 1 session wave, no 90s 403 cooldowns, skip urllib long retries.",
    )
    ap.add_argument(
        "--cdp",
        default="",
        help="Attach to Chrome DevTools (e.g. http://127.0.0.1:9222) and fetch boards in-page.",
    )
    ap.add_argument(
        "--cdp-attach-timeout-ms",
        type=int,
        default=30_000,
        help="CDP connect_over_cdp timeout in ms (default 30000; avoids Playwright 180s hang).",
    )
    ap.add_argument("--playwright", action="store_true", help="Launch Chromium if CDP is not used.")
    args = ap.parse_args()
    out_path = Path(args.output)
    fail_fast = bool(args.fail_fast) or bool(str(args.cdp).strip())

    primary_id = str(args.league_id).strip() if args.league_id is not None else "82"
    if not primary_id.isdigit():
        print(f"❌ --league_id must be numeric, got {args.league_id!r}")
        sys.exit(2)

    # World Cup boards first — they succeed quickly; club SOCCER (82) often hits
    # DataDome cooldowns and wastes ~20 min if fetched before live WC slate.
    boards_to_fetch: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    def _add_board(lid: str, lname: str) -> None:
        if lid not in seen_ids:
            seen_ids.add(lid)
            boards_to_fetch.append((lid, lname))

    if not args.no_world_cup:
        for lid, lname in WORLD_CUP_BOARDS.items():
            _add_board(lid, lname)
    _add_board(primary_id, SOCCER_BOARDS.get(primary_id, "SOCCER"))
    if args.include_halves:
        _add_board("242", "SOCCER1H")
        _add_board("243", "SOCCER2H")
    if args.include_season:
        _add_board("262", "SOCCERSZN")

    print(f"📡 Fetching PrizePicks Soccer | boards: {[n for _, n in boards_to_fetch]}")
    if fail_fast:
        print("  [mode] fail-fast HTTP (or CDP) — no long 403 cooldown stacks")

    all_rows = []
    cdp_url = str(args.cdp or "").strip()
    use_playwright = bool(args.playwright) and not cdp_url

    if cdp_url or use_playwright:
        try:
            if use_playwright:
                from utils.prizepicks_cdp import session_fetch_projections

                print("  [mode] Playwright Chromium — one launch per soccer board")
                cdp_results = []
                for lid, lname in boards_to_fetch:
                    data, included, _st = session_fetch_projections(
                        lid, playwright=True, per_page=250
                    )
                    cdp_results.append((lid, lname, data, included))
            else:
                cdp_results = fetch_boards_via_cdp(
                    boards_to_fetch,
                    cdp_url=cdp_url,
                    attach_timeout_ms=int(args.cdp_attach_timeout_ms),
                )
            for lid, lname, data, included in cdp_results:
                if data:
                    rows = build_rows(data, included, lname)
                    all_rows.extend(rows)
                    print(f"    ✓ {len(rows)} rows parsed")
                else:
                    print(f"    ⚠️ No data for {lname} — may not be on the board today")
        except Exception as e:
            if use_playwright:
                print(f"❌ Playwright soccer fetch failed ({type(e).__name__}: {e})")
                sys.exit(1)
            print(f"❌ CDP soccer fetch failed ({type(e).__name__}: {e})")
            print("   Falling back to fail-fast HTTP...")
            cdp_url = ""

    if not cdp_url and not use_playwright:
        for lid, lname in boards_to_fetch:
            print(f"\n  → {lname} (league_id={lid})")
            data, included = fetch_board(
                lid,
                lname,
                retries=int(args.max_retries),
                fail_fast=fail_fast,
            )
            if data:
                rows = build_rows(data, included, lname)
                all_rows.extend(rows)
                print(f"    ✓ {len(rows)} rows parsed")
            else:
                print(f"    ⚠️ No data for {lname} — may not be on the board today")

    if not all_rows:
        print("\n❌ No soccer props fetched — nothing on the board right now.")
        if args.append and out_path.is_file():
            print("   (--append: left existing output file unchanged)")
            sys.exit(0)
        pd.DataFrame().to_csv(args.output, index=False, encoding="utf-8-sig")
        sys.exit(1)

    df = pd.DataFrame(all_rows)
    df["line"] = pd.to_numeric(df["line"], errors="coerce")
    df["standard_line"] = pd.to_numeric(df["standard_line"], errors="coerce")
    _mstd = df["pick_type"].astype(str).str.lower().eq("standard")
    df.loc[_mstd, "standard_line"] = df.loc[_mstd, "standard_line"].fillna(df.loc[_mstd, "line"])
    df = df.drop_duplicates(subset=["projection_id"], keep="first").reset_index(drop=True)
    pull_ts = now_et_iso()
    df = stamp_fetched_at(df, when=pull_ts, overwrite=True)
    try_archive_lines(df, sport="SOCCER", only_fetched_at=pull_ts)

    if args.append and out_path.is_file():
        try:
            existing = pd.read_csv(out_path, encoding="utf-8-sig")
            n_existing = len(existing)
            all_cols = list(dict.fromkeys(list(existing.columns) + list(df.columns)))
            for c in all_cols:
                if c not in existing.columns:
                    existing[c] = ""
                if c not in df.columns:
                    df[c] = ""
            existing = existing[all_cols].copy()
            df = df[all_cols].copy()
            n_new_chunk = len(df)
            combined = pd.concat([existing, df], ignore_index=True)
            for col in ("player", "prop_type", "pick_type", "pp_game_id", "league"):
                if col in combined.columns:
                    combined[col] = combined[col].astype(str).str.strip()
            combined["line"] = pd.to_numeric(combined["line"], errors="coerce")
            dedup_cols = [
                c
                for c in ("player", "prop_type", "line", "pp_game_id", "pick_type", "league")
                if c in combined.columns
            ]
            if dedup_cols:
                combined = combined.drop_duplicates(subset=dedup_cols, keep="last")
            df = combined
            print(
                f"[step1 SOCCER append] {n_existing} existing + {n_new_chunk} new → "
                f"{len(df)} after dedup (subset={dedup_cols})"
            )
        except Exception as e:
            print(f"  [WARN] --append merge failed ({e}); writing this fetch only")

    fetched_rows = len(df)
    pre_filter_columns = list(df.columns)
    _raw_ts = pd.to_datetime(df.get("start_time", pd.Series([], dtype=object)), errors="coerce", utc=True)
    distinct_dates = sorted(
        {
            d
            for d in _raw_ts.dt.tz_convert(ZoneInfo(str(args.tz).strip() or DEFAULT_TZ)).dt.date.astype("string").tolist()
            if d and d != "nan"
        }
    )
    filtered, fallback_date = apply_game_date_filter(
        df,
        target_date=str(args.date).strip(),
        tz_name=str(args.tz).strip() or DEFAULT_TZ,
        allow_nearest_future=bool(args.allow_nearest_future),
        include_tomorrow=bool(getattr(args, "include_tomorrow", False)),
        board_date=str(getattr(args, "board_date", None) or "").strip()[:10] or eastern_today_ymd(),
    )
    print(
        f"[INFO] Soccer step1 fetched={fetched_rows} rows; "
        f"date_filter={args.date} ({args.tz}); survived={len(filtered)}"
    )
    if distinct_dates:
        print(f"[INFO] Soccer step1 game_dates_on_board={distinct_dates}")
    if fallback_date:
        print("[WARNING] Soccer step1 allow-nearest-future: skipping date filter")
    df = filtered

    if len(df) == 0:
        print(no_props_log_line("Soccer", str(args.date).strip()))
        if should_preserve_append_output(out_path, args.append):
            print("   (--append: left existing output file unchanged)")
            sys.exit(0)
        pd.DataFrame(
            columns=pre_filter_columns
            or ["player", "prop_type", "line", "start_time", "team", "opp_team", "pick_type", "league"]
        ).to_csv(
            args.output, index=False, encoding="utf-8-sig"
        )
        print(f"\n[INFO] Saved empty date-filtered Soccer step1 CSV -> {args.output}")
        sys.exit(0)

    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"\n✅ Saved {len(df)} rows -> {args.output}")
    league_counts = df["league"].value_counts().to_dict()
    print(f"   Leagues: {league_counts}")
    prop_counts = df["prop_type"].value_counts().head(10).to_dict()
    print(f"   Top props: {prop_counts}")


if __name__ == "__main__":
    main()
