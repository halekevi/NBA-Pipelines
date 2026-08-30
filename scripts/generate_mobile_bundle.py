import os
import sys
import shutil
import re
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import combined_slate_tickets

# Dated grade/ticket artifacts kept in mobile/www (plus always-copied *_latest.*).
MAX_DATED_DAYS = 7

_ROOT_FOR_UTILS = Path(__file__).resolve().parent.parent
if str(_ROOT_FOR_UTILS) not in sys.path:
    sys.path.insert(0, str(_ROOT_FOR_UTILS))
from utils.proporacle_data_root import (  # noqa: E402
    grade_history_read_paths,
    load_best_grade_history_runs,
)
from utils.ui_live_json import maybe_mirror_to_runtime  # noqa: E402


def _write_ota_config(mobile_www: Path) -> None:
    """OTA is bundled-fallback only. Canonical app is remote Railway — keep OTA off unless explicitly enabled."""
    raw_base = (os.environ.get("PROPORACLE_OTA_BASE_URL") or "").strip().rstrip("/")
    flag = (os.environ.get("PROPORACLE_OTA_ENABLED") or "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        enabled = False
    elif raw_base:
        enabled = True
    else:
        enabled = flag in ("1", "true", "yes", "on")
    raw_interval = (os.environ.get("PROPORACLE_OTA_CHECK_INTERVAL_MS") or "").strip()
    try:
        check_interval_ms = int(raw_interval) if raw_interval else 3_600_000
    except ValueError:
        check_interval_ms = 3_600_000
    payload = {
        "enabled": bool(enabled and raw_base),
        "baseUrl": raw_base,
        "checkIntervalMs": check_interval_ms,
    }
    (mobile_www / "ota-config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _first_existing_path(candidates):
    for p in candidates:
        if p is not None and Path(p).exists():
            return Path(p)
    return None


def _copy_dated_artifacts_capped(
    templates_dir: Path,
    mobile_www: Path,
    pattern: str,
    date_re: str,
    *,
    max_days: int = MAX_DATED_DAYS,
) -> tuple[list[str], int]:
    """Copy dated files matching pattern; keep only the newest max_days dates.

    Also deletes older matching dated files already present under mobile_www.
    Returns (kept_dates_desc, pruned_count).
    """
    dated: list[tuple[str, Path]] = []
    for src in templates_dir.glob(pattern):
        m = re.fullmatch(date_re, src.name)
        if not m:
            continue
        dated.append((m.group(1), src))
    dated.sort(key=lambda x: x[0], reverse=True)
    keep = {d for d, _ in dated[:max_days]}
    for d, src in dated:
        if d in keep:
            shutil.copy2(src, mobile_www / src.name)

    pruned = 0
    for existing in mobile_www.glob(pattern):
        m = re.fullmatch(date_re, existing.name)
        if not m:
            continue
        if m.group(1) not in keep:
            try:
                existing.unlink()
                pruned += 1
            except OSError:
                pass
    return sorted(keep, reverse=True), pruned


def _mtime_utc_string(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _modified_ts_key(mod_str: str) -> float:
    s = (mod_str or "").strip()[:19].replace("T", " ")
    if len(s) < 19:
        return 0.0
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _parse_payload_generated_at(payload: dict | None) -> str:
    """UTC wall clock YYYY-MM-DD HH:MM:SS from generated_at or slate date noon."""
    if not isinstance(payload, dict):
        return ""
    ga = (payload.get("generated_at") or "").strip()
    if ga:
        core = ga.replace(" UTC", "").strip()
        prefix = core[:19].replace("T", " ")
        try:
            datetime.strptime(prefix, "%Y-%m-%d %H:%M:%S")
            return prefix
        except ValueError:
            pass
    ds = str((payload.get("date") or "").strip())[:10]
    if len(ds) == 10 and ds[4] == "-" and ds[7] == "-":
        return f"{ds} 12:00:00"
    return ""


def _fresher_modified_str(*candidates: str) -> str:
    best = ""
    best_ts = 0.0
    for c in candidates:
        s = (c or "").strip()
        if not s:
            continue
        ts = _modified_ts_key(s)
        if ts >= best_ts:
            best_ts = ts
            best = s
    return best


def _mobile_sport_status_modified(
    sport: str,
    *,
    has_rows: bool,
    slate_build_ts: str,
    combined_build_ts: str,
    modified_default: str,
    artifact_path: Path | None,
) -> tuple[str, str]:
    """
    Prefer slate/tickets JSON build time over step8 Excel mtime (mobile status cards).
    """
    if slate_build_ts:
        return slate_build_ts, "slate_latest.generated_at"
    if combined_build_ts:
        return combined_build_ts, "combined_slate_tickets"
    if modified_default:
        return modified_default, "slate_date_default"
    if artifact_path is not None and artifact_path.exists():
        return _mtime_utc_string(artifact_path), "step8_artifact"
    return "", "none"


# Keep aligned with ui_runner/app.py page_income _SPORT_BREAKDOWN_ORDER.
SPORT_BREAKDOWN_ORDER = ("NBA", "CBB", "CFB", "WNBA", "MLB", "SOCCER", "TENNIS", "NHL", "NFL")


def _normalize_sport_label(raw):
    s = str(raw or "").strip().upper()
    aliases = {"NCAAB": "CBB", "WCBB": "CBB", "NCAAF": "CFB", "NBA1Q": "NBA", "NBA1H": "NBA"}
    return aliases.get(s, s)


def _today_et_ymd() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


_SLATE_STRICT_GAME_DAY_SPORTS = frozenset(
    {"nhl", "nfl", "mlb", "nba1h", "nba1q", "soccer", "wnba", "wnba1h", "wnba1q"}
)


def _row_game_date_et(row: dict, target_year: int) -> str:
    """Match home-page rowGameDateEt (ISO + MM/DD game_time)."""
    gd = str((row or {}).get("game_date") or "").strip()[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", gd):
        return gd
    gt = str((row or {}).get("game_time") or "").strip()
    m_iso = re.match(r"^(\d{4}-\d{2}-\d{2})", gt)
    if m_iso:
        return m_iso.group(1)
    m_md = re.match(r"^(\d{1,2})/(\d{1,2})(?:\b|[\sT])", gt)
    if m_md:
        return f"{target_year}-{int(m_md.group(1)):02d}-{int(m_md.group(2)):02d}"
    return ""


def _sport_rows_missing_game_day(rows: list, target_ymd: str) -> bool:
    if not isinstance(rows, list) or not rows:
        return False
    year = int(target_ymd[:4]) if len(target_ymd) >= 4 and target_ymd[:4].isdigit() else datetime.now().year
    return not any(_row_game_date_et(r, year) == target_ymd for r in rows if isinstance(r, dict))


def _outputs_have_slate_for_date(root_dir: Path, slate_date: str) -> bool:
    """True when at least one sport step8 exists under outputs/<date>/."""
    day_dir = root_dir / "outputs" / slate_date
    if not day_dir.is_dir():
        return False
    patterns = (
        "nba/step8_all_direction_clean.xlsx",
        "soccer/step8_soccer_direction_clean.xlsx",
        "mlb/step8_mlb_direction_clean.xlsx",
        "nhl/step8_nhl_direction_clean.xlsx",
        "wnba/step8_wnba_direction_clean.xlsx",
        "tennis/step8_tennis_direction_clean.xlsx",
    )
    return any((day_dir / p).exists() for p in patterns)


def _slate_templates_need_refresh(templates_dir: Path, target_ymd: str) -> tuple[bool, str]:
    slate_path = templates_dir / "slate_latest.json"
    if not slate_path.exists():
        return True, "missing slate_latest.json"
    try:
        payload = json.loads(slate_path.read_text(encoding="utf-8"))
    except Exception:
        return True, "unreadable slate_latest.json"
    slate_date = str((payload or {}).get("date") or "").strip()[:10]
    if slate_date and slate_date < target_ymd:
        return True, f"slate date {slate_date} < today {target_ymd}"
    sports = (payload or {}).get("sports") if isinstance(payload, dict) else {}
    if not isinstance(sports, dict):
        return True, "invalid sports payload"
    stale_sports = []
    for sid in sorted(_SLATE_STRICT_GAME_DAY_SPORTS):
        rows = sports.get(sid) or []
        if isinstance(rows, list) and rows and _sport_rows_missing_game_day(rows, target_ymd):
            stale_sports.append(sid)
    if stale_sports:
        return True, f"strict game-day sports stale: {', '.join(stale_sports)}"
    return False, ""


def _refresh_slate_web_templates(root_dir: Path, templates_dir: Path, slate_date: str) -> bool:
    script = root_dir / "scripts" / "combined_slate_tickets.py"
    if not script.exists():
        print(f"  [slate-refresh] missing {script}")
        return False
    cmd = [
        sys.executable,
        str(script),
        "--date",
        slate_date,
        "--write-slate-web-only",
        "--allow-cross-date-fallback",
        "--web-outdir",
        str(templates_dir),
        "--tennis-date",
        slate_date,
    ]
    print(f"  [slate-refresh] rebuilding slate web JSON for {slate_date} ...")
    try:
        proc = subprocess.run(cmd, cwd=str(root_dir), capture_output=True, text=True, check=False)
    except Exception as exc:
        print(f"  [slate-refresh] failed to launch combined_slate_tickets: {exc}")
        return False
    for line in (proc.stdout or "").splitlines():
        if line.strip():
            print(f"        {line}")
    for line in (proc.stderr or "").splitlines():
        if line.strip():
            print(f"        {line}")
    if proc.returncode != 0:
        print(f"  [slate-refresh] combined_slate_tickets exited {proc.returncode}")
        return False
    print("  [slate-refresh] OK")
    return True


def _ensure_fresh_slate_templates(root_dir: Path, templates_dir: Path) -> None:
    today_et = _today_et_ymd()
    needs, reason = _slate_templates_need_refresh(templates_dir, today_et)
    if not needs:
        return
    if not _outputs_have_slate_for_date(root_dir, today_et):
        print(f"  [slate-refresh] skip ({reason}); no outputs/{today_et} step8 boards yet")
        return
    print(f"  [slate-refresh] {reason}")
    _refresh_slate_web_templates(root_dir, templates_dir, today_et)


def _read_template_json_date(templates_dir: Path) -> str:
    """Prefer tickets_latest date (matches /api/slate-display-date), then slate_latest."""
    for name in ("tickets_latest.json", "slate_latest.json"):
        p = templates_dir / name
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ds = str((data or {}).get("date") or "").strip()[:10]
            if len(ds) == 10 and ds[4] == "-" and ds[7] == "-":
                return ds
        except Exception:
            continue
    return ""


def _payload_slate_date(path: Path) -> str:
    """Return YYYY-MM-DD from a tickets/slate JSON, or empty string."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ds = str((data or {}).get("date") or "").strip()[:10]
        if len(ds) == 10 and ds[4] == "-" and ds[7] == "-":
            return ds
    except Exception:
        pass
    return ""


def _resolve_tickets_latest_for_mobile(root_dir: Path, templates_dir: Path) -> Path | None:
    """
    Pick tickets_latest.json for mobile bake.

    Never let a stale ui_runner/data snapshot beat a newer templates --write-web
    board (that was the daily mobile lag: data stayed on an old preferred_min_payout
    board while templates moved forward).
    """
    templates = templates_dir / "tickets_latest.json"
    data = root_dir / "ui_runner" / "data" / "tickets_latest.json"
    candidates = [p for p in (templates, data) if p.exists()]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    t_date = _payload_slate_date(templates)
    d_date = _payload_slate_date(data)
    if t_date and d_date and t_date != d_date:
        chosen = templates if t_date > d_date else data
        print(
            f"  [tickets] using {chosen.relative_to(root_dir)} "
            f"(templates date={t_date or '?'}, data date={d_date or '?'})"
        )
        return chosen
    if t_date and not d_date:
        return templates
    if d_date and not t_date:
        return data

    # Same slate date (or undated): prefer curated preferred_min_payout data when present,
    # else newer mtime, else templates (canonical write-web path).
    try:
        dj = json.loads(data.read_text(encoding="utf-8"))
        if dj.get("preferred_min_payout_x") is not None:
            print(f"  [tickets] using {data.relative_to(root_dir)} (same-date preferred_min_payout)")
            return data
    except Exception:
        pass
    try:
        if data.stat().st_mtime > templates.stat().st_mtime:
            print(f"  [tickets] using {data.relative_to(root_dir)} (same-date newer mtime)")
            return data
    except OSError:
        pass
    return templates


def _merged_combined_rows_for_mobile(sports_payload: dict) -> list:
    """All sport rows merged + sorted by rank_score (matches app /api/slate-sport/combined)."""
    out = []
    for sk, rows in (sports_payload or {}).items():
        key = str(sk).strip().lower()
        if key == "combined":
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            row = dict(r)
            if not str(row.get("sport") or "").strip():
                row["sport"] = str(sk).strip().upper()
            out.append(row)

    def _rank(x):
        try:
            v = x.get("rank_score")
            return float(v) if v is not None else float("-inf")
        except (TypeError, ValueError):
            return float("-inf")

    out.sort(key=_rank, reverse=True)
    return out


def _build_mobile_sport_breakdown(templates_dir):
    from utils.income_sport_breakdown import (
        build_from_graded_props,
        build_monthly_from_graded_props,
        graded_props_signature,
    )

    rows = build_from_graded_props(templates_dir, stake_per_pick=10.0)
    monthly_rows = build_monthly_from_graded_props(templates_dir, stake_per_pick=10.0)
    return {
        "ok": True,
        "rows": rows,
        "monthly_rows": monthly_rows,
        "source": "graded_props_json",
        "signature": graded_props_signature(templates_dir),
    }


def _extract_series_from_row(row):
    actual = row.get("actual_series")
    line = row.get("line_series")
    if isinstance(actual, list) and actual:
        actual_vals = []
        for v in actual:
            try:
                actual_vals.append(float(v))
            except Exception:
                pass
        line_vals = []
        if isinstance(line, list):
            for v in line:
                try:
                    line_vals.append(float(v))
                except Exception:
                    pass
        return actual_vals, line_vals

    # Fallback for pipeline rows carrying G1..G10 and line_G1..line_G10.
    actual_vals = []
    line_vals = []
    for i in range(1, 11):
        av = row.get(f"g{i}")
        lv = row.get(f"line_g{i}")
        try:
            if av is not None:
                actual_vals.append(float(av))
        except Exception:
            pass
        try:
            if lv is not None:
                line_vals.append(float(lv))
        except Exception:
            pass
    return actual_vals, line_vals


# Cache-bust stamp for shell CSS after mobile polish (bump when CSS changes).
MOBILE_CSS_V = "20260719gradesm2"

NAV_ROUTE_MAP = {
    "/": "index.html",
    "/tickets": "tickets.html",
    "/grades": "grades.html",
    "/income": "income.html",
    "/payout": "payout.html",
    "/payout/log": "payout_log.html",
    "/payout/ladder": "payout_ladder.html",
    "/payout/examples": "payout_examples.html",
}

NAV_ACTIVE_BY_DEST = {
    "index.html": "home",
    "tickets.html": "tickets",
    "grades.html": "grades",
    "income.html": "income",
    "payout.html": "payout",
    "payout_ladder.html": "payout",
    "payout_log.html": "payout",
    "payout_examples.html": "payout",
}


def _rewrite_app_nav_hrefs(content: str) -> str:
    """Map Flask absolute routes → static *.html for Capacitor / file://."""
    for route, target in sorted(NAV_ROUTE_MAP.items(), key=lambda kv: -len(kv[0])):
        content = re.sub(
            rf'href\s*=\s*(["\'])\s*{re.escape(route)}((?:\?[^"\']*)?)\s*\1',
            lambda m, t=target: f'href="{t}{m.group(2)}"',
            content,
            flags=re.IGNORECASE,
        )
    content = content.replace("'/payout/log'", "'payout_log.html'")
    content = content.replace('"/payout/log"', '"payout_log.html"')
    content = content.replace("'/payout?tab=cards'", "'payout.html?tab=cards'")
    content = content.replace('"/payout?tab=cards"', '"payout.html?tab=cards"')
    return content


def _apply_nav_active_and_live_pill(content: str, dest_name: str) -> str:
    """Restore active tab + LIVE pill after Jinja strip leaves empty class/pill."""
    active_key = NAV_ACTIVE_BY_DEST.get(dest_name, "")
    # Fill empty LIVE pill suffix left by {{ _pill }}.
    content = re.sub(
        r'(<div class="live-pill"><div class="live-dot"></div><span class="live-pill-brand">PropOracle</span>\s*&nbsp;·&nbsp;\s*)(</div>)',
        r"\1LIVE\2",
        content,
        count=2,
    )
    if not active_key:
        return content
    href_for = {
        "home": "index.html",
        "tickets": "tickets.html",
        "grades": "grades.html",
        "income": "income.html",
        "payout": "payout.html",
    }.get(active_key)
    if not href_for:
        return content
    # Clear any existing active, then mark this page (top nav + mobile menu).
    content = re.sub(
        r'(href="(?:index|tickets|grades|income|payout)\.html"[^>]*?)\s+class="active"',
        r'\1 class=""',
        content,
    )
    content = re.sub(
        rf'(href="{re.escape(href_for)}")(\s+class="")?',
        rf'\1 class="active"',
        content,
        count=4,
    )
    return content


def _bump_shell_css_cache(content: str) -> str:
    """Keep shell CSS query params fresh so WebViews pick up polish."""
    for name in (
        "proporacle-page-shell.css",
        "mobile-content-width.css",
        "site-nav-unified.css",
        "site-nav-datetime.css",
        "nav-mobile-shared.css",
        "proporacle-mobile-schema.css",
        "tickets-redesign.css",
        "tickets-built-content.css",
        "global-scrollbar.css",
    ):
        content = re.sub(
            rf'({re.escape(name)}\?v=)[^"\'\s>]+',
            rf"\g<1>{MOBILE_CSS_V}",
            content,
            flags=re.IGNORECASE,
        )
        # Absolute Flask paths still present before relativization.
        content = re.sub(
            rf'(/static/{re.escape(name)}\?v=)[^"\'\s>]+',
            rf"\g<1>{MOBILE_CSS_V}",
            content,
            flags=re.IGNORECASE,
        )
    # Ensure payout satellite pages load the full nav CSS stack.
    if "site-nav-unified.css" not in content and "proporacle-page-shell.css" in content:
        content = content.replace(
            f'href="static/proporacle-page-shell.css?v={MOBILE_CSS_V}"/>',
            (
                f'href="static/proporacle-page-shell.css?v={MOBILE_CSS_V}"/>\n'
                f'  <link rel="stylesheet" href="static/site-nav-unified.css?v={MOBILE_CSS_V}"/>\n'
                f'  <link rel="stylesheet" href="static/site-nav-datetime.css?v={MOBILE_CSS_V}"/>'
            ),
            1,
        )
        content = content.replace(
            f'href="/static/proporacle-page-shell.css?v={MOBILE_CSS_V}"/>',
            (
                f'href="/static/proporacle-page-shell.css?v={MOBILE_CSS_V}"/>\n'
                f'  <link rel="stylesheet" href="/static/site-nav-unified.css?v={MOBILE_CSS_V}"/>\n'
                f'  <link rel="stylesheet" href="/static/site-nav-datetime.css?v={MOBILE_CSS_V}"/>'
            ),
            1,
        )
    return content


def process_template(file_path, templates_dir):
    """Recursively processes Jinja2 includes and strips placeholders."""
    if not file_path.exists():
        print(f"WARNING: Template file not found: {file_path}")
        return ""

    content = file_path.read_text(encoding="utf-8")

    # Handle {% include '...' %}
    def replace_include(match):
        include_name = match.group(1).strip("'\"")
        include_path = templates_dir / include_name
        return process_template(include_path, templates_dir)

    content = re.sub(r'\{%\s*include\s+(.*?)\s*%\}', replace_include, content)

    # Robust path relativization for mobile bundle (Capacitor file:// protocol)
    # Fix src and href attributes (e.g. <img src="/static/logo.png"> -> <img src="static/logo.png">)
    # Handles variations in quoting and whitespace around the '='.
    content = re.sub(
        r'(src|href)\s*=\s*(["\'])\s*/static/',
        r'\1=\2static/',
        content,
        flags=re.IGNORECASE
    )

    # Fix CSS url() references and flatten /static/css/ -> static/ (assets are copied to flat static/ dir)
    # Handles url("/static/..."), url('/static/...'), and url(/static/...) with optional leading slash.
    content = re.sub(
        r'url\(\s*(["\']?)\s*/?static/(?:css/)?',
        r'url(\1static/',
        content,
        flags=re.IGNORECASE
    )

    return content

def generate_bundle():
    # Define paths
    ROOT_DIR = Path(__file__).resolve().parent.parent
    STATIC_DIR = ROOT_DIR / "ui_runner" / "static"
    TEMPLATES_DIR = ROOT_DIR / "ui_runner" / "templates"
    MOBILE_WWW_DIR = ROOT_DIR / "mobile" / "www"
    DATA_DIR = ROOT_DIR / "data"

    # Ensure mobile/www exists and is clean
    if MOBILE_WWW_DIR.exists():
        for item in MOBILE_WWW_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    else:
        MOBILE_WWW_DIR.mkdir(parents=True, exist_ok=True)

    # Copy static assets
    print(f"Copying static assets from {STATIC_DIR} to {MOBILE_WWW_DIR / 'static'}...")
    shutil.copytree(STATIC_DIR, MOBILE_WWW_DIR / "static")

    # Process templates and write to mobile/www root
    # Tickets page source priority (Railway /tickets uses tickets_built.html).
    # Prefer the same shell for the mobile bundle so theme CSS stays in sync.
    # tickets_latest.html is a separate legacy full-page bake — do not prefer it.
    ticket_source = "tickets_built.html"
    if not (TEMPLATES_DIR / ticket_source).exists():
        if (TEMPLATES_DIR / "tickets_latest.html").exists():
            ticket_source = "tickets_latest.html"
        else:
            dated_ticket_pages = sorted(
                [p for p in TEMPLATES_DIR.glob("ticket_eval_*.html") if re.fullmatch(r"ticket_eval_\d{4}-\d{2}-\d{2}\.html", p.name)],
                reverse=True
            )
            if dated_ticket_pages:
                ticket_source = dated_ticket_pages[0].name
            elif (TEMPLATES_DIR / "ticket_eval_latest.html").exists():
                ticket_source = "ticket_eval_latest.html"

    PAGES = {
        "index.html": "index.html",
        ticket_source: "tickets.html",
        "indexGrades.html": "grades.html",
        "dashboard_income.html": "income.html",
        "payout_calculator.html": "payout.html",
        "payout_log.html": "payout_log.html",
        "payout_ladder.html": "payout_ladder.html",
        "payout_examples.html": "payout_examples.html",
    }

    for src_name, dest_name in PAGES.items():
        src_path = TEMPLATES_DIR / src_name
        dest_path = MOBILE_WWW_DIR / dest_name

        if src_path.exists():
            print(f"Processing {src_path} to {dest_path}...")

            # Process includes recursively
            content = process_template(src_path, TEMPLATES_DIR)

            # Fix navigation links for static bundle using robust regex
            # (Matches href="/", href="/tickets", etc., with flexible quoting and whitespace)
            content = _rewrite_app_nav_hrefs(content)
            content = _bump_shell_css_cache(content)

            # Mobile bundle runs from local files (not Railway routes).
            # Rewrite grades page report/API paths to local assets.
            if dest_name == "grades.html":
                content = content.replace(
                    "const REPORT_URL_TEMPLATE = '/grades/slate_eval_{date}.html';",
                    "const REPORT_URL_TEMPLATE = 'slate_eval_{date}.html';"
                )
                content = content.replace(
                    "const TICKET_EVAL_URL_TEMPLATE = '/grades/ticket_eval_{date}.html';",
                    "const TICKET_EVAL_URL_TEMPLATE = 'ticket_eval_{date}.html';"
                )
                content = content.replace(
                    "fetch('/api/grades/report_dates', { cache: 'no-store' })",
                    "fetch('grades_report_dates.json', { cache: 'no-store' })"
                )
                # Offline/mobile: shim Grades API calls to local bundled JSON files.
                grades_mobile_bootstrap = """
<script>
(function () {
  const _origFetch = window.fetch.bind(window);
  function _jsonResp(obj) {
    return new Response(JSON.stringify(obj), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  }
  function _dateParamFrom(urlStr) {
    try {
      const u = new URL(urlStr, window.location.href);
      return u.searchParams.get('date') || '';
    } catch (_e) { return ''; }
  }
  function _extractDate(raw) {
    const m = String(raw || '').match(/\\d{4}-\\d{2}-\\d{2}/);
    return m ? m[0] : '';
  }
  async function _loadGradedPropsByDate(ds) {
    const d = _extractDate(ds);
    if (!d) return null;
    const file = `graded_props_${d}.json`;
    const r = await _origFetch(file, { cache: 'no-store' });
    if (!r.ok) return null;
    return r.json();
  }
  window.fetch = async function (input, init) {
    const urlStr = (typeof input === 'string') ? input : (input && input.url ? input.url : String(input || ''));
    const path = urlStr.replace(window.location.origin, '');

    if (path.includes('/api/grades/report_dates')) {
      return _origFetch('grades_report_dates.json', init);
    }
    if (path.includes('/api/grades/insights')) {
      return _jsonResp({ calibration: [], clv_by_sport: [], edge_bucket_hit_rate: [], clv_by_prop_type: [], clv_by_tier: [] });
    }
    if (path.includes('/api/grades/archive_dates')) {
      return _origFetch('grades_archive_dates.json', init);
    }
    if (path.includes('/api/grade-history')) {
      return _origFetch('data/grade_history.json', init);
    }
    if (path.includes('/api/graded-props')) {
      const ds = _dateParamFrom(urlStr);
      const j = await _loadGradedPropsByDate(ds);
      if (j) return _jsonResp(j);
      return _jsonResp({ ok: true, date: _extractDate(ds), props: [], source: 'mobile_bundle_missing' });
    }
    if (path.includes('/api/grades/props')) {
      const ds = _dateParamFrom(urlStr);
      const j = await _loadGradedPropsByDate(ds);
      const props = Array.isArray(j && j.props) ? j.props : [];
      let nHit = 0, nMiss = 0;
      props.forEach((p) => {
        const ru = String((p && p.result) || '').toUpperCase();
        if (ru === 'HIT') nHit += 1;
        else if (ru === 'MISS') nMiss += 1;
      });
      return _jsonResp({ ok: true, props: props, n_hit: nHit, n_miss: nMiss, n: props.length, n_returned: props.length, truncated: false });
    }
    return _origFetch(input, init);
  };
})();
</script>
"""
                # Avoid double-inject if grades template already carries the offline shim.
                if "mobile_bundle_missing" not in content and "graded_props_${d}.json" not in content:
                    content = content.replace("</body>", grades_mobile_bootstrap + "\n</body>")
            elif dest_name == "index.html":
                # Home page slate data must come from bundled JSON in offline/mobile mode.
                content = content.replace(
                    'fetch("/api/slate", {cache: \'no-store\'})',
                    "fetch_smart('slate_latest.json')"
                )
                content = content.replace(
                    "fetch('/api/slate', {cache: 'no-store'})",
                    "fetch_smart('slate_latest.json')"
                )
                # Pipeline status: template spacing varies — use regex so replacement always applies.
                content = re.sub(
                    r'fetch\(\s*"/api/pipeline/status"\s*,\s*\{\s*cache\s*:\s*[\'"]no-store[\'"]\s*\}\s*\)',
                    "fetch_smart('pipeline_status.json')",
                    content,
                )
                content = content.replace(
                    'fetch(`/api/slate-sport/${encodeURIComponent(sport)}`, {cache: \'no-store\'})',
                    "fetch_smart(`slate_sport_${encodeURIComponent(sport)}.json`)"
                )
                content = content.replace(
                    "fetch('/api/slate-excel', {cache: 'no-store'})",
                    "fetch_smart('slate_excel.json')"
                )
                # Combined slate JSON (no Railway — mobile/www only).
                content = re.sub(
                    r"fetch\(\s*['\"]/api/slate-sport/combined['\"]\s*,\s*\{\s*cache\s*:\s*['\"]no-store['\"]\s*\}\s*\)",
                    "fetch_smart('slate_sport_combined.json')",
                    content,
                )

                # Inject fetch_smart and fetch logic for remote-priority
                smart_fetch_js = """
<script>
async function fetch_smart(localPath) {
  // If we have a remote override URL for this file type, prefer it
  let remoteUrl = null;
  if (localPath === 'slate_latest.json' && window.SLATE_JSON_URL) remoteUrl = window.SLATE_JSON_URL;
  if (localPath === 'tickets_latest.json' && window.TICKETS_JSON_URL) remoteUrl = window.TICKETS_JSON_URL;

  if (remoteUrl) {
    try {
      const resp = await fetch(remoteUrl, { cache: 'no-store' });
      if (resp.ok) return resp;
    } catch (e) {
      console.warn("SmartFetch remote failed, falling back to local:", localPath, e);
    }
  }
  return fetch(localPath, { cache: 'no-store' });
}
</script>
"""
                ota_js = '<script defer src="static/proporacle-ota.js"></script>'
                content = content.replace("<head>", f"<head>\n{smart_fetch_js}\n{ota_js}")
            elif dest_name == "income.html":
                # Jinja strips can leave invalid JS in static bundle.
                content = re.sub(r"const\s+points\s*=\s*;", "const points = [];", content)
                mobile_income_bootstrap = """
  <script>
    (function () {
      const HISTORY_URL = 'data/grade_history.json?v=20260522pnl';
      const SPORT_BREAKDOWN_URL = 'sport_breakdown.json?v=20260522pnl';

      function parseRows(raw) {
        const rows = Array.isArray(raw) ? raw : (raw && Array.isArray(raw.runs) ? raw.runs : []);
        return rows.map((r) => {
          const tickets = Number(r.n_tickets ?? r.tickets ?? 0);
          const wins = Number(r.wins ?? 0);
          const guarantees = Number(r.guarantees ?? 0);
          const losses = Number(r.losses ?? 0);
          const decided = Math.max(0, Number(r.decided ?? (wins + losses)));
          const paid = Math.max(0, Number(r.paid ?? (wins + guarantees)));
          const net = (r.net_dollars != null)
            ? Number(r.net_dollars)
            : (r.net_per_10 != null ? tickets * Number(r.net_per_10) : 0);
          const roi = Number(r.roi_pct ?? ((tickets > 0) ? (net / (tickets * 10) * 100) : 0));
          return {
            date: String(r.date || ''),
            track: String(r.track || r.source || 'graded_main'),
            tickets, wins, guarantees, losses, decided, paid,
            void_loss_ct: Number(r.void_loss_ct || 0),
            net_dollars: net,
            roi_pct: roi,
          };
        }).filter((r) => /^\\d{4}-\\d{2}-\\d{2}$/.test(r.date));
      }

      function renderSports(payload) {
        const body = document.getElementById('sport-breakdown-tbody');
        const rows = (payload && Array.isArray(payload.rows) ? payload.rows : [])
          .filter((r) => Number(r.decided || 0) > 0);
        if (!body) return;
        if (!rows.length) {
          body.innerHTML = '<tr><td colspan="4" class="empty-note" style="text-align:left">No decided sport rows yet.</td></tr>';
          return;
        }
        const maxAbs = Math.max(...rows.map((r) => Math.abs(Number(r.net_dollars) || 0)), 1);
        body.innerHTML = rows.map((r) => {
          const decided = Number(r.decided || 0);
          const paid = Number(r.paid || 0);
          const winRate = decided > 0 ? (paid / decided) * 100 : 0;
          const net = Number(r.net_dollars || 0);
          const w = Math.max(4, (Math.abs(net) / maxAbs) * 100).toFixed(1);
          const cls = net > 0 ? 'num-pos' : (net < 0 ? 'num-neg' : '');
          const barCls = net >= 0 ? 'pos' : 'neg';
          const money = (net < 0 ? '-$' : '$') + Math.abs(net).toFixed(2);
          return (
            '<tr data-net="' + net + '"><td>' + String(r.sport || '') + '</td><td>' + decided +
            '</td><td>' + winRate.toFixed(1) + '%</td><td><div class="sport-net-cell"><span class="' +
            cls + '">' + money + '</span><div class="sport-bar-track"><div class="sport-bar ' +
            barCls + '" style="width:' + w + '%"></div></div></div></td></tr>'
          );
        }).join('');
      }

      Promise.all([
        fetch(HISTORY_URL, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : [])).catch(() => []),
        fetch(SPORT_BREAKDOWN_URL, { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : { rows: [], monthly_rows: [] }))
          .catch(() => ({ rows: [], monthly_rows: [] })),
      ]).then(([hist, sport]) => {
        renderSports(sport);
        const daily = parseRows(hist);
        const monthly = Array.isArray(sport.monthly_rows) ? sport.monthly_rows : [];
        const boot = () => {
          if (typeof window.__proporacleIncomeBoot === 'function') {
            window.__proporacleIncomeBoot(daily, monthly);
            return true;
          }
          return false;
        };
        if (!boot()) {
          let tries = 0;
          const t = setInterval(() => {
            if (boot() || ++tries > 80) clearInterval(t);
          }, 50);
        }
      });
    })();
  </script>
"""
                content = content.replace("</body>", mobile_income_bootstrap + "\n</body>")
            elif dest_name == "tickets.html":
                # Prefer rendering the tickets generator/slips view from fresh tickets_latest.json
                # into tickets_built.html so mobile matches /tickets platform content.
                tickets_json = _resolve_tickets_latest_for_mobile(ROOT_DIR, TEMPLATES_DIR)
                if tickets_json is None:
                    tickets_json = TEMPLATES_DIR / "tickets_latest.json"
                tickets_built_tpl = TEMPLATES_DIR / "tickets_built.html"
                if tickets_json.exists() and tickets_built_tpl.exists():
                    try:
                        payload = json.loads(tickets_json.read_text(encoding="utf-8"))
                        # Apply last-filter prefer ≥2x (STRONG always kept) if not already stamped.
                        try:
                            if payload.get("preferred_min_payout_x") is None:
                                payload = combined_slate_tickets.prefer_main_min_payout_payload(payload)
                        except Exception:
                            pass
                        tickets_body_html, page_title = combined_slate_tickets.render_tickets_body_html(payload)
                        content = process_template(tickets_built_tpl, TEMPLATES_DIR)
                        content = content.replace("{{ tickets_body|safe }}", tickets_body_html)
                        content = content.replace("{{ page_title }}", page_title or "PropOracle Tickets")
                        # Body inject reintroduces Flask absolute nav — rewrite again.
                        content = _rewrite_app_nav_hrefs(content)
                        content = _bump_shell_css_cache(content)
                        # Keep mobile tickets JSON aligned with the baked board.
                        (MOBILE_WWW_DIR / "tickets_latest.json").write_text(
                            json.dumps(payload, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    except Exception as _tickets_exc:
                        print(f"  [WARN] tickets bake failed ({_tickets_exc}); using shell fallback")
                # Manual builder sport chips: keep visible on touch devices.
                content = content.replace(
                    "btn.style.opacity = active ? '1' : '.55';",
                    "btn.style.opacity = active ? '1' : '.88';"
                )
                content = content.replace(
                    "btn.style.filter = active ? 'none' : 'grayscale(0.2)';",
                    "btn.style.filter = 'none';"
                )
                # Force Tickets tab active in both top nav and mobile menu for tickets.html.
                content = content.replace(
                    'href="grades.html" class="active" title="Ticket evaluation hub"',
                    'href="grades.html" class="" title="Ticket evaluation hub"'
                )
                content = content.replace(
                    'href="grades.html" class="active"',
                    'href="grades.html" class=""'
                )
                content = content.replace(
                    'href="tickets.html" class=""',
                    'href="tickets.html" class="active"'
                )
                # Offline/mobile: shim Uniform-tickets API to local JSON files.
                tickets_mobile_bootstrap = """
<script>
(function () {
  const _origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const urlStr = (typeof input === 'string') ? input : (input && input.url ? input.url : String(input || ''));
    const path = urlStr.replace(window.location.origin, '');
    if (path.includes('/api/uniform-tickets/dates')) {
      return _origFetch('uniform_tickets_dates.json', init);
    }
    if (path.includes('/api/uniform-tickets/backtest')) {
      return _origFetch('uniform_tickets_backtest.json', init);
    }
    if (path.includes('/api/uniform-tickets/latest')) {
      return _origFetch('uniform_tickets_latest.json', init);
    }
    const m = path.match(/\\/api\\/uniform-tickets\\/(\\d{4}-\\d{2}-\\d{2})$/);
    if (m) {
      return _origFetch(`uniform_tickets_${m[1]}.json`, init);
    }
    return _origFetch(input, init);
  };
})();
</script>
"""
                if "uniform-tickets/dates" not in content:
                    content = content.replace("</body>", tickets_mobile_bootstrap + "\n</body>")
            elif dest_name == "payout_ladder.html":
                # Bake ladder tables with live CDP / mix summary (Jinja would otherwise strip empty).
                try:
                    ui_dir = str(ROOT_DIR / "ui_runner")
                    if ui_dir not in sys.path:
                        sys.path.insert(0, ui_dir)
                    from app import (  # type: ignore
                        _ladder_quality_stats,
                        _normalize_delta_signature,
                        _ladder_row_has_invalid_distance,
                        _read_payout_ladder_rows,
                        _summarize_ladder_rows,
                    )
                    from jinja2 import Environment, FileSystemLoader, select_autoescape

                    rows = _read_payout_ladder_rows()
                    quality = _ladder_quality_stats(rows)
                    n_live_cdp = int(quality.get("live_cdp") or 0)
                    n_with_deltas = sum(
                        1
                        for r in rows
                        if (
                            _normalize_delta_signature(r.get("goblin_delta_sig") or r.get("goblin_deltas"))
                            or _normalize_delta_signature(r.get("demon_delta_sig") or r.get("demon_deltas"))
                        )
                        and not _ladder_row_has_invalid_distance(r)
                    )
                    env = Environment(
                        loader=FileSystemLoader(str(TEMPLATES_DIR)),
                        autoescape=select_autoescape(["html", "xml"]),
                    )

                    def _mobile_url_for(endpoint: str, **values: object) -> str:
                        if endpoint == "static":
                            filename = str(values.get("filename") or "")
                            return f"static/{filename}"
                        # Best-effort for any leftover Flask route helpers in includes.
                        route = {
                            "index": "index.html",
                            "tickets": "tickets.html",
                            "grades": "grades.html",
                            "income": "income.html",
                            "payout": "payout.html",
                            "payout_log": "payout_log.html",
                            "payout_ladder": "payout_ladder.html",
                            "payout_examples": "payout_examples.html",
                        }.get(endpoint)
                        return route or f"{endpoint}.html"

                    env.globals["url_for"] = _mobile_url_for
                    tpl = env.get_template("payout_ladder.html")
                    content = tpl.render(
                        ladder_rows=_summarize_ladder_rows(rows, by_delta=False),
                        delta_rows=_summarize_ladder_rows(rows, by_delta=True),
                        total_rows=len(rows),
                        live_cdp_rows=n_live_cdp,
                        delta_known_rows=n_with_deltas,
                        excluded_zero_delta_rows=int(quality.get("excluded_zero_delta") or 0),
                        nav_active="payout",
                        nav_pill_suffix="LIVE",
                    )
                    content = _rewrite_app_nav_hrefs(content)
                    content = re.sub(
                        r'(src|href)\s*=\s*(["\'])\s*/static/',
                        r"\1=\2static/",
                        content,
                        flags=re.IGNORECASE,
                    )
                    content = _bump_shell_css_cache(content)
                    # Horizontal scroll on narrow phones.
                    if "table-scroll" not in content:
                        content = content.replace(
                            "<table aria-label=",
                            '<div class="table-scroll" style="overflow-x:auto;-webkit-overflow-scrolling:touch;"><table aria-label=',
                        )
                        content = content.replace("</table>\n      </section>", "</table></div>\n      </section>")
                    print(f"  [payout_ladder] baked {len(rows)} raw rows (live_cdp={n_live_cdp})")
                except Exception as _ladder_exc:
                    print(f"  [WARN] payout_ladder bake failed ({_ladder_exc})")
            elif dest_name == "payout_examples.html":
                content = content.replace("open <code>/payout</code>", "open <code>payout.html</code>")
                content = content.replace("open <code>/payout</code>", "open payout.html")
            elif dest_name == "payout.html":
                # Offline/mobile: rate cards must load from bundled JSON (no /api route in file:// mode).
                content = content.replace(
                    "fetch('/api/payout/rate-cards')",
                    "fetch('payout_rate_cards.json', { cache: 'no-store' })"
                )
                content = content.replace(
                    'fetch("/api/payout/rate-cards")',
                    "fetch('payout_rate_cards.json', { cache: 'no-store' })"
                )

            # Resolve Flask url_for('static', filename='…') before stripping {{ }} — otherwise
            # <img src="{{ url_for(...) }}?v=…"> becomes src="?v=…" and the logo 404s in the APK.
            content = re.sub(
                r"\{\{\s*url_for\s*\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
                r"static/\1",
                content,
            )

            # Strip remaining Jinja2 placeholders, control blocks, and comments
            content = re.sub(r'\{\{.*?\}\}', '', content, flags=re.DOTALL)
            content = re.sub(r'\{%.*?%\}', '', content, flags=re.DOTALL)
            content = re.sub(r'\{#.*?#\}', '', content, flags=re.DOTALL)
            if dest_name == "income.html":
                # After Jinja stripping, invalid assignment can remain.
                content = re.sub(r"const\s+points\s*=\s*;", "const points = [];", content)

            # Jinja strip clears {{ 'active' if … }} and {{ _pill }} — restore for mobile chrome.
            content = _apply_nav_active_and_live_pill(content, dest_name)
            content = _rewrite_app_nav_hrefs(content)
            content = _bump_shell_css_cache(content)

            dest_path.write_text(content, encoding="utf-8")
        else:
            print(f"WARNING: {src_path} not found, skipping...")

    # Copy dated grade report files for offline/mobile date navigation (last N days only).
    pruned_total = 0
    report_dates, n = _copy_dated_artifacts_capped(
        TEMPLATES_DIR,
        MOBILE_WWW_DIR,
        "slate_eval_*.html",
        r"slate_eval_(\d{4}-\d{2}-\d{2})\.html",
    )
    pruned_total += n

    ticket_eval_dates, n = _copy_dated_artifacts_capped(
        TEMPLATES_DIR,
        MOBILE_WWW_DIR,
        "ticket_eval_*.html",
        r"ticket_eval_(\d{4}-\d{2}-\d{2})\.html",
    )
    pruned_total += n

    graded_props_dates, n = _copy_dated_artifacts_capped(
        TEMPLATES_DIR,
        MOBILE_WWW_DIR,
        "graded_props_*.json",
        r"graded_props_(\d{4}-\d{2}-\d{2})\.json",
    )
    pruned_total += n

    archive_row_counts = {}
    for stem in graded_props_dates:
        gp = TEMPLATES_DIR / f"graded_props_{stem}.json"
        try:
            j = json.loads(gp.read_text(encoding="utf-8"))
            rows = j.get("props") if isinstance(j, dict) else []
            archive_row_counts[stem] = len(rows) if isinstance(rows, list) else 0
        except Exception:
            archive_row_counts[stem] = 0

    # Copy uniform-bucket ticket artifacts (built by build_uniform_tickets_artifacts.py).
    uniform_ticket_dates, n = _copy_dated_artifacts_capped(
        TEMPLATES_DIR,
        MOBILE_WWW_DIR,
        "uniform_tickets_*.json",
        r"uniform_tickets_(\d{4}-\d{2}-\d{2})\.json",
    )
    pruned_total += n
    # Always keep non-dated latest/backtest helpers if present in templates.
    for latest_name in (
        "uniform_tickets_latest.json",
        "uniform_tickets_dates.json",
        "uniform_tickets_backtest.json",
    ):
        src_latest = TEMPLATES_DIR / latest_name
        if src_latest.exists():
            shutil.copy2(src_latest, MOBILE_WWW_DIR / latest_name)

    if pruned_total:
        print(f"[mobile] pruned {pruned_total} old dated files (kept last {MAX_DATED_DAYS} days)")
    else:
        print(f"[mobile] dated artifacts capped to last {MAX_DATED_DAYS} days (nothing to prune)")

    if uniform_ticket_dates and not (MOBILE_WWW_DIR / "uniform_tickets_dates.json").exists():
        (MOBILE_WWW_DIR / "uniform_tickets_dates.json").write_text(
            json.dumps(
                {"dates": sorted(set(uniform_ticket_dates), reverse=True)},
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )

    # Lightweight local replacement for /api/grades/report_dates.
    report_dates_payload = {
        "ok": True,
        "slate_eval_dates": sorted(report_dates, reverse=True),
        "ticket_eval_dates": sorted(ticket_eval_dates, reverse=True)
    }
    (MOBILE_WWW_DIR / "grades_report_dates.json").write_text(
        json.dumps(report_dates_payload, ensure_ascii=True, indent=2),
        encoding="utf-8"
    )

    (MOBILE_WWW_DIR / "grades_archive_dates.json").write_text(
        json.dumps({
            "ok": True,
            "dates": sorted(set(graded_props_dates), reverse=True),
            "row_counts": archive_row_counts,
        }, ensure_ascii=True, indent=2),
        encoding="utf-8"
    )

    # Home page local slate source for mobile/offline bundle.
    _ensure_fresh_slate_templates(ROOT_DIR, TEMPLATES_DIR)
    src_slate_latest = TEMPLATES_DIR / "slate_latest.json"
    if src_slate_latest.exists():
        try:
            slate_payload = json.loads(src_slate_latest.read_text(encoding="utf-8"))
        except Exception:
            slate_payload = {}

        sports_payload = slate_payload.get("sports") if isinstance(slate_payload, dict) else {}
        if not isinstance(sports_payload, dict):
            sports_payload = {}

        # Build flat `picks` array expected by Home page JS (`d.picks` from /api/slate).
        mobile_picks = []
        for sport_key, rows in sports_payload.items():
            if not isinstance(rows, list):
                continue
            for r in rows:
                if not isinstance(r, dict):
                    continue
                player = str(r.get("player") or "").strip()
                initials = "".join([w[0] for w in player.split()[:2]]).upper() if player else "—"
                hit_rate = r.get("hit_rate")
                hit_pct = None
                try:
                    if hit_rate is not None:
                        hit_pct = float(hit_rate) * 100.0
                except Exception:
                    hit_pct = None
                actual_series, line_series = _extract_series_from_row(r)
                mobile_picks.append({
                    "sport": str(sport_key).upper(),
                    "initials": initials,
                    "player": player,
                    "team": r.get("team"),
                    "opp": r.get("opp"),
                    "prop": r.get("prop"),
                    "pick_type": r.get("pick_type"),
                    # Home code expects both `pick` and `pick_type` in different places.
                    "pick": r.get("pick_type"),
                    "line": r.get("line"),
                    "dir": r.get("dir"),
                    "edge": r.get("edge"),
                    "hit": hit_pct,
                    "hit_rate": r.get("hit_rate"),
                    "l5_over": r.get("l5_over") if r.get("l5_over") is not None else r.get("last5_over"),
                    "l5_under": r.get("l5_under") if r.get("l5_under") is not None else r.get("last5_under"),
                    "l10_over": r.get("l10_over"),
                    "l10_under": r.get("l10_under"),
                    "last5_over": r.get("last5_over") or r.get("l5_over"),
                    "last5_under": r.get("last5_under") or r.get("l5_under"),
                    "l5_avg": r.get("l5_avg"),
                    "season_avg": r.get("season_avg"),
                    "def_tier": r.get("def_tier") or r.get("DEF_TIER") or r.get("stat_def_tier"),
                    "opponent_def_rank": r.get("opponent_def_rank") or r.get("opponent_rank"),
                    "opponent_rank": r.get("opponent_rank"),
                    "model_dir": r.get("model_dir"),
                    "actual_series": actual_series,
                    "line_series": line_series,
                    "game_time": r.get("game_time"),
                })

        # Write mobile-compatible slate payload (keeps original fields + adds `picks`).
        mobile_slate_payload = dict(slate_payload) if isinstance(slate_payload, dict) else {}
        mobile_slate_payload["picks"] = mobile_picks
        (MOBILE_WWW_DIR / "slate_latest.json").write_text(
            json.dumps(mobile_slate_payload, ensure_ascii=True),
            encoding="utf-8"
        )

        # Static replacements for /api/slate-sport/<sport>
        for sport_key, rows in sports_payload.items():
            safe_rows = rows if isinstance(rows, list) else []
            (MOBILE_WWW_DIR / f"slate_sport_{sport_key}.json").write_text(
                json.dumps({"ok": True, "sport": sport_key, "rows": safe_rows}, ensure_ascii=True),
                encoding="utf-8"
            )

        merged_combined = _merged_combined_rows_for_mobile(sports_payload)
        (MOBILE_WWW_DIR / "slate_sport_combined.json").write_text(
            json.dumps({"ok": True, "sport": "combined", "rows": merged_combined}, ensure_ascii=True),
            encoding="utf-8"
        )

        # Static replacement for /api/pipeline/status (used by home status cards).
        slate_date = _today_et_ymd() or _read_template_json_date(TEMPLATES_DIR) or str(
            (slate_payload.get("date") if isinstance(slate_payload, dict) else "") or ""
        ).strip()[:10]
        modified_default = f"{slate_date} 12:00:00" if slate_date else ""
        status_sports = [
            "nba", "nba1h", "nba1q", "cbb", "cfb", "nhl", "soccer", "mlb", "nfl",
            "tennis", "golf", "wnba", "wnba1h", "wnba1q", "combined",
        ]
        R = ROOT_DIR
        combined_candidates = list(R.glob("combined_slate_tickets_*.xlsx"))
        _out_root = R / "outputs"
        if _out_root.is_dir():
            combined_candidates.extend(_out_root.glob("*/combined_slate_tickets_*.xlsx"))
        combined_artifact = (
            max(combined_candidates, key=lambda p: p.stat().st_mtime) if combined_candidates else None
        )
        artifact_by_sport = {
            "nba": _first_existing_path(
                [
                    R / "outputs" / slate_date / "nba" / "step8_all_direction_clean.xlsx",
                    R / "Sports" / "NBA" / "data" / "outputs" / "step8_all_direction_clean.xlsx",
                ]
            ),
            "nba1h": _first_existing_path(
                [
                    R / "outputs" / slate_date / "nba1h" / "step8_nba1h_direction_clean.xlsx",
                    R / "Sports" / "NBA" / "step8_nba1h_direction_clean.xlsx",
                ]
            ),
            "nba1q": _first_existing_path(
                [
                    R / "outputs" / slate_date / "nba1q" / "step8_nba1q_direction_clean.xlsx",
                    R / "Sports" / "NBA" / "step8_nba1q_direction_clean.xlsx",
                ]
            ),
            "cbb": _first_existing_path(
                [R / "Sports" / "CBB" / "step6_ranked_cbb.xlsx", R / "CBB" / "step6_ranked_cbb.xlsx"]
            ),
            "cfb": _first_existing_path(
                [
                    R / "outputs" / slate_date / "cfb" / "step6_ranked_cfb.xlsx",
                    R / "Sports" / "CFB" / "step6_ranked_cfb.xlsx",
                    R / "CFB" / "step6_ranked_cfb.xlsx",
                ]
            ),
            "nhl": _first_existing_path(
                [
                    R / "outputs" / slate_date / "nhl" / "step8_nhl_direction_clean.xlsx",
                    R / "Sports" / "NHL" / "outputs" / "step8_nhl_direction_clean.xlsx",
                ]
            ),
            "soccer": _first_existing_path(
                [
                    R / "outputs" / slate_date / "soccer" / "step8_soccer_direction_clean.xlsx",
                    R / "Sports" / "Soccer" / "outputs" / "step8_soccer_direction_clean.xlsx",
                ]
            ),
            "mlb": _first_existing_path(
                [
                    R / "outputs" / slate_date / "mlb" / "step8_mlb_direction_clean.xlsx",
                    R / "Sports" / "MLB" / "step8_mlb_direction_clean.xlsx",
                    R / "Sports" / "MLB" / "outputs" / "step8_mlb_direction_clean.xlsx",
                ]
            ),
            "nfl": _first_existing_path(
                [
                    R / "outputs" / slate_date / "nfl" / "step8_nfl_direction_clean.xlsx",
                    R / "Sports" / "NFL" / "outputs" / "step8_nfl_direction_clean.xlsx",
                ]
            ),
            "tennis": _first_existing_path(
                [
                    R / "outputs" / slate_date / "tennis" / "step8_tennis_direction_clean.xlsx",
                    R / "Sports" / "Tennis" / "outputs" / "step8_tennis_direction_clean.xlsx",
                ]
            ),
            "golf": _first_existing_path(
                [
                    R / "outputs" / slate_date / "golf" / "step8_golf_direction_clean.xlsx",
                    R / "outputs" / slate_date / "golf" / f"step8_golf_direction_clean_{slate_date}.xlsx",
                    R / "Sports" / "Golf" / "outputs" / "step8_golf_direction_clean.xlsx",
                ]
            ),
            "wnba": _first_existing_path(
                [
                    R / "outputs" / slate_date / "wnba" / "step8_wnba_direction_clean.xlsx",
                    R / "outputs" / slate_date / "step8_wnba_direction_clean_{}.xlsx".format(slate_date),
                    R / "Sports" / "WNBA" / "outputs" / "step8_wnba_direction_clean.xlsx",
                    R / "Sports" / "WNBA" / "step8_wnba_direction_clean.xlsx",
                    R / "Sports" / "WNBA" / "step8_wnba_direction.xlsx",
                    R / "WNBA" / "step8_wnba_direction_clean.xlsx",
                    R / "WNBA" / "step8_wnba_direction.xlsx",
                ]
            ),
            "wnba1h": _first_existing_path(
                [
                    R / "outputs" / slate_date / "wnba1h" / "step8_wnba1h_direction_clean.xlsx",
                    R / "Sports" / "WNBA" / "step8_wnba1h_direction_clean.xlsx",
                ]
            ),
            "wnba1q": _first_existing_path(
                [
                    R / "outputs" / slate_date / "wnba1q" / "step8_wnba1q_direction_clean.xlsx",
                    R / "Sports" / "WNBA" / "step8_wnba1q_direction_clean.xlsx",
                ]
            ),
        }
        tickets_build_ts = ""
        tickets_path = TEMPLATES_DIR / "tickets_latest.json"
        if tickets_path.exists():
            try:
                tickets_payload = json.loads(tickets_path.read_text(encoding="utf-8"))
                tickets_build_ts = _parse_payload_generated_at(tickets_payload)
            except Exception:
                tickets_build_ts = ""
        slate_build_ts = _fresher_modified_str(
            _parse_payload_generated_at(slate_payload if isinstance(slate_payload, dict) else None),
            tickets_build_ts,
        )
        combined_build_ts = _mtime_utc_string(combined_artifact) if combined_artifact else ""

        status_payload = {}
        for s in status_sports:
            art = combined_artifact if s == "combined" else artifact_by_sport.get(s)
            has_rows = bool((sports_payload.get(s) if isinstance(sports_payload, dict) else []))
            has_artifact = bool(art and art.exists())
            exists = bool(
                has_rows
                or has_artifact
                or (s == "combined" and isinstance(sports_payload, dict) and bool(sports_payload))
            )
            mod_str = ""
            source = "none"
            if exists:
                mod_str, source = _mobile_sport_status_modified(
                    s,
                    has_rows=has_rows,
                    slate_build_ts=slate_build_ts,
                    combined_build_ts=combined_build_ts,
                    modified_default=modified_default,
                    artifact_path=art,
                )
                print(f"  [pipeline_status] {s}: modified={mod_str!r} source={source}")
            status_payload[s] = {"slate": {"exists": exists, "modified": mod_str}}
        status_text = json.dumps(status_payload, ensure_ascii=True, indent=2)
        (MOBILE_WWW_DIR / "pipeline_status.json").write_text(status_text, encoding="utf-8")
        (TEMPLATES_DIR / "pipeline_status.json").write_text(status_text, encoding="utf-8")
        maybe_mirror_to_runtime(TEMPLATES_DIR / "pipeline_status.json", status_text)

        # Static replacement for /api/slate-excel used by Combined slate table.
        combined_columns = [
            "Tier", "Rank Score", "Player", "Team", "Opp", "Prop", "Pick Type",
            "Line", "Dir", "Edge", "Hit Rate", "L5 Over", "L5 Under", "Game Time"
        ]
        combined_rows = []
        for rows in sports_payload.values():
            if not isinstance(rows, list):
                continue
            for r in rows:
                if not isinstance(r, dict):
                    continue
                combined_rows.append([
                    r.get("tier"),
                    r.get("rank_score"),
                    r.get("player"),
                    r.get("team"),
                    r.get("opp"),
                    r.get("prop"),
                    r.get("pick_type"),
                    r.get("line"),
                    r.get("dir"),
                    r.get("edge"),
                    r.get("hit_rate"),
                    r.get("l5_over"),
                    r.get("l5_under"),
                    r.get("game_time"),
                ])
        combined_rows.sort(key=lambda row: abs(float(row[9] or 0.0)), reverse=True)
        (MOBILE_WWW_DIR / "slate_excel.json").write_text(
            json.dumps({"sheets": {"combined": {"columns": combined_columns, "rows": combined_rows}}}, ensure_ascii=True),
            encoding="utf-8"
        )

    # Same date field as /api/slate-display-date — bundled apps cannot call the API offline.
    _ymd = _read_template_json_date(TEMPLATES_DIR)
    _display_payload = json.dumps({"date": _ymd}, ensure_ascii=True)
    (MOBILE_WWW_DIR / "slate_display_date.json").write_text(_display_payload, encoding="utf-8")
    (TEMPLATES_DIR / "slate_display_date.json").write_text(_display_payload, encoding="utf-8")
    maybe_mirror_to_runtime(TEMPLATES_DIR / "slate_display_date.json", _display_payload)

    # Copy grade history for offline/mobile P&L (same resolution as Flask /income).
    mobile_data_dir = MOBILE_WWW_DIR / "data"
    mobile_data_dir.mkdir(parents=True, exist_ok=True)
    _gh_runs = load_best_grade_history_runs(ROOT_DIR, templates_dir=TEMPLATES_DIR)
    if _gh_runs:
        (mobile_data_dir / "grade_history.json").write_text(
            json.dumps(_gh_runs, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    # WNBA step8 clean workbook for mobile/offline consumers.
    src_wnba_step8 = ROOT_DIR / "Sports" / "WNBA" / "outputs" / "step8_wnba_direction_clean.xlsx"
    if src_wnba_step8.exists():
        shutil.copy2(src_wnba_step8, mobile_data_dir / "step8_wnba_direction_clean.xlsx")

    # Payout tab offline/mobile dependency.
    src_payout_rate_cards = DATA_DIR / "payout_rate_cards.json"
    if src_payout_rate_cards.exists():
        shutil.copy2(src_payout_rate_cards, MOBILE_WWW_DIR / "payout_rate_cards.json")
    src_payout_ladder_examples = ROOT_DIR / "ui_runner" / "data" / "payout_ladder_examples.json"
    if src_payout_ladder_examples.exists():
        shutil.copy2(src_payout_ladder_examples, MOBILE_WWW_DIR / "payout_ladder_examples.json")

    # Matchup edge JSONs for mobile slate matchup panels.
    matchup_copied = 0
    for src in sorted((TEMPLATES_DIR).glob("*_matchup_edge.json")):
        shutil.copy2(src, mobile_data_dir / src.name)
        matchup_copied += 1
    sports_root = ROOT_DIR / "Sports"
    if sports_root.is_dir():
        for src in sports_root.glob("*/data/*_matchup_edge.json"):
            dest = mobile_data_dir / src.name
            if not dest.exists():
                shutil.copy2(src, dest)
                matchup_copied += 1
    print(f"  [matchup] copied {matchup_copied} matchup edge JSON files -> data/")

    # Offline/mobile Sport Breakdown source for income page.
    (MOBILE_WWW_DIR / "sport_breakdown.json").write_text(
        json.dumps(_build_mobile_sport_breakdown(TEMPLATES_DIR), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    _write_ota_config(MOBILE_WWW_DIR)

    print("Mobile bundle generation complete.")

if __name__ == "__main__":
    generate_bundle()
