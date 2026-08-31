"""Live site JSON paths: runtime disk vs GitHub-raw templates mirror.

Railway polls ``ui_runner/templates/<name>`` from origin/main (GitHub raw).
That path is the live *publish* contract and must not move without a cutover.

``ui_runner/runtime/`` is the canonical *disk* copy so hand-edited Jinja HTML
in ``templates/`` is not the only home for generated latest JSON.

``ui_runner/data/`` is dated / snapshot history.
``mobile/www/`` is not a live path — the Android app loads Railway remotely.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_STATUS_SPORTS = (
    "nba",
    "nba1h",
    "nba1q",
    "cbb",
    "cfb",
    "nhl",
    "soccer",
    "mlb",
    "nfl",
    "tennis",
    "golf",
    "wnba",
    "wnba1h",
    "wnba1q",
    "combined",
)

_SYNC_PAIR_NAMES = (
    "tickets_latest.json",
    "slate_latest.json",
    "slate_display_date.json",
    "pipeline_status.json",
    "tickets_winrate_latest.json",
    "sport_breakdown.json",
)

_LIVE_JSON_NAMES = frozenset(
    {
        "tickets_latest.json",
        "tickets_winrate_latest.json",
        "slate_latest.json",
        "slate_display_date.json",
        "pipeline_status.json",
        "sport_breakdown.json",
        "ticket_eval_slate_latest.json",
    }
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def runtime_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "ui_runner" / "runtime"


def github_mirror_dir(root: Path | None = None) -> Path:
    """GitHub raw / Railway poll path. Do not change without a coordinated cutover."""
    return (root or repo_root()) / "ui_runner" / "templates"


def data_snapshot_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "ui_runner" / "data"


def is_live_json_name(name: str) -> bool:
    n = Path(str(name or "")).name
    if n in _LIVE_JSON_NAMES:
        return True
    return n.startswith("slate_sport_") and n.endswith(".json")


def disk_path(name: str, root: Path | None = None) -> Path:
    """Prefer runtime; fall back to the GitHub-raw templates copy."""
    n = Path(str(name or "")).name
    rt = runtime_dir(root) / n
    if rt.is_file():
        return rt
    return github_mirror_dir(root) / n


def existing_path(name: str, root: Path | None = None) -> Path | None:
    """First existing copy: runtime, templates, then data snapshot."""
    n = Path(str(name or "")).name
    for p in (
        runtime_dir(root) / n,
        github_mirror_dir(root) / n,
        data_snapshot_dir(root) / n,
    ):
        if p.is_file():
            return p
    return None


def write_paths(
    name: str,
    root: Path | None = None,
    *,
    include_data_snapshot: bool = False,
) -> list[Path]:
    """Disk targets for a live JSON file. Does not include mobile/www or docs/."""
    n = Path(str(name or "")).name
    paths = [runtime_dir(root) / n, github_mirror_dir(root) / n]
    if include_data_snapshot:
        paths.append(data_snapshot_dir(root) / n)
    return paths


def maybe_mirror_to_runtime(
    src_path: str | Path,
    text: str | None = None,
    root: Path | None = None,
) -> Path | None:
    """Copy a live JSON write into ``ui_runner/runtime/`` when the basename matches."""
    p = Path(src_path)
    if not is_live_json_name(p.name):
        return None
    dest = runtime_dir(root) / p.name
    try:
        if dest.resolve() == p.resolve():
            return dest
    except OSError:
        pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        dest.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        dest.write_text(text, encoding="utf-8")
    return dest


def _load_json_obj(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _is_g70_group(group: dict) -> bool:
    name = str(group.get("group_name") or "")
    if "Goblin-70" in name:
        return True
    tickets = group.get("tickets") or []
    if tickets and isinstance(tickets[0], dict):
        return str(tickets[0].get("ticket_track") or "").lower() == "goblin70"
    return False


def tickets_card_kind(payload: dict | None) -> str:
    """dual | goblin70_only | mixer_only | empty | missing."""
    if not isinstance(payload, dict):
        return "missing"
    groups = [g for g in (payload.get("groups") or []) if isinstance(g, dict)]
    if not groups:
        return "empty"
    has_g70 = any(_is_g70_group(g) for g in groups)
    has_mixer = any(not _is_g70_group(g) for g in groups)
    if has_g70 and has_mixer:
        return "dual"
    if has_g70:
        return "goblin70_only"
    if has_mixer:
        return "mixer_only"
    return "empty"


def json_payload_date(path: Path) -> str:
    data = _load_json_obj(path)
    if not data:
        return ""
    return str(data.get("date") or "").strip()[:10]


def _freshness_key(path: Path) -> tuple:
    data = _load_json_obj(path)
    gen = str((data or {}).get("generated_at") or "")
    d = str((data or {}).get("date") or "")[:10]
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (gen, d, mtime)


def sync_runtime_templates_pair(name: str, root: Path | None = None) -> str | None:
    """Copy the newer runtime/templates copy onto the older one. Returns the winner path."""
    n = Path(str(name or "")).name
    rt = runtime_dir(root) / n
    tmpl = github_mirror_dir(root) / n
    rt_ok = rt.is_file()
    tmpl_ok = tmpl.is_file()
    if not rt_ok and not tmpl_ok:
        return None
    if rt_ok and not tmpl_ok:
        tmpl.parent.mkdir(parents=True, exist_ok=True)
        tmpl.write_text(rt.read_text(encoding="utf-8"), encoding="utf-8")
        return str(rt)
    if tmpl_ok and not rt_ok:
        rt.parent.mkdir(parents=True, exist_ok=True)
        rt.write_text(tmpl.read_text(encoding="utf-8"), encoding="utf-8")
        return str(tmpl)
    if _freshness_key(rt) >= _freshness_key(tmpl):
        winner, loser = rt, tmpl
    else:
        winner, loser = tmpl, rt
    text = winner.read_text(encoding="utf-8")
    if loser.read_text(encoding="utf-8") != text:
        loser.write_text(text, encoding="utf-8")
    return str(winner)


def sync_live_json_pairs(root: Path | None = None) -> list[str]:
    synced: list[str] = []
    for name in _SYNC_PAIR_NAMES:
        if sync_runtime_templates_pair(name, root):
            synced.append(name)
    rt = runtime_dir(root)
    tmpl = github_mirror_dir(root)
    sport_names = {p.name for p in rt.glob("slate_sport_*.json")} | {
        p.name for p in tmpl.glob("slate_sport_*.json")
    }
    for name in sorted(sport_names):
        if sync_runtime_templates_pair(name, root):
            synced.append(name)
    return synced


def refresh_pipeline_status_from_slate(root: Path | None = None) -> Path | None:
    """Stamp pipeline_status.json from slate_latest row counts + generated_at."""
    slate_path = existing_path("slate_latest.json", root)
    if slate_path is None:
        return None
    slate = _load_json_obj(slate_path)
    if not slate:
        return None
    sports = slate.get("sports") if isinstance(slate.get("sports"), dict) else {}
    gen = str(slate.get("generated_at") or "").replace(" UTC", "").strip()
    payload: dict = {}
    any_rows = False
    for key in _STATUS_SPORTS:
        if key == "combined":
            exists = any_rows
            payload[key] = {"slate": {"exists": exists, "modified": gen if exists else "", "no_slate": not exists}}
            continue
        rows = sports.get(key) if isinstance(sports, dict) else None
        n = len(rows) if isinstance(rows, list) else 0
        exists = n > 0
        if exists:
            any_rows = True
        payload[key] = {"slate": {"exists": exists, "modified": gen if exists else "", "no_slate": not exists}}
    # combined uses any_rows computed while iterating; rewrite after the loop
    payload["combined"] = {"slate": {"exists": any_rows, "modified": gen if any_rows else "", "no_slate": not any_rows}}
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    dest = None
    for path in write_paths("pipeline_status.json", root):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        dest = path
    return dest


def dual_card_errors(root: Path | None = None) -> list[str]:
    """Errors if tickets_latest is Goblin-only or mixer-only (live /tickets contract)."""
    if os.environ.get("PROPORACLE_ALLOW_PARTIAL_TICKETS", "").strip() in ("1", "true", "yes"):
        return []
    errors: list[str] = []
    for name in ("tickets_latest.json",):
        for path in write_paths(name, root):
            if not path.is_file():
                continue
            kind = tickets_card_kind(_load_json_obj(path))
            if kind in ("goblin70_only", "mixer_only", "empty"):
                errors.append(f"{path}: tickets card is {kind} (need Goblin-70 then mixer)")
    for label, name in (("tickets", "tickets_latest.json"), ("slate", "slate_latest.json")):
        rt = runtime_dir(root) / name
        tmpl = github_mirror_dir(root) / name
        if rt.is_file() and tmpl.is_file():
            d_rt = json_payload_date(rt)
            d_tmpl = json_payload_date(tmpl)
            if d_rt and d_tmpl and d_rt != d_tmpl:
                errors.append(f"{label} date mismatch runtime={d_rt} templates={d_tmpl}")
    return errors
