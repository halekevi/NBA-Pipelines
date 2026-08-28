"""Live site JSON paths: runtime disk vs GitHub-raw templates mirror.

Railway polls ``ui_runner/templates/<name>`` from origin/main (GitHub raw).
That path is the live *publish* contract and must not move without a cutover.

``ui_runner/runtime/`` is the canonical *disk* copy so hand-edited Jinja HTML
in ``templates/`` is not the only home for generated latest JSON.

``ui_runner/data/`` is dated / snapshot history.
``mobile/www/`` is not a live path — the Android app loads Railway remotely.
"""

from __future__ import annotations

from pathlib import Path

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
