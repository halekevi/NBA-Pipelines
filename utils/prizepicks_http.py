"""
Shared PrizePicks HTTP helpers (curl_cffi chrome131, WNBA/MLB-style).

Used by NHL, Soccer, CBB, CFB step1 scripts and any sport that needs
Cloudflare-resistant TLS without a browser.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEFAULT_IMPERSONATE = "chrome131"
_HTTP_BACKEND_LOGGED = False


def curl_impersonate() -> str:
    return (os.environ.get("PROPORACLE_CURL_IMPERSONATE") or DEFAULT_IMPERSONATE).strip()


def ensure_chrome131() -> None:
    if not (os.environ.get("PROPORACLE_CURL_IMPERSONATE") or "").strip():
        os.environ["PROPORACLE_CURL_IMPERSONATE"] = DEFAULT_IMPERSONATE


def log_http_backend_once() -> None:
    global _HTTP_BACKEND_LOGGED
    if _HTTP_BACKEND_LOGGED:
        return
    _HTTP_BACKEND_LOGGED = True
    imp = curl_impersonate()
    try:
        from curl_cffi.requests import Session  # noqa: F401

        print(f"  [PP] HTTP transport: curl_cffi impersonate={imp!r} (browser TLS/JA3)")
    except ImportError:
        print(
            "  [PP] HTTP transport: requests (install curl-cffi for Cloudflare-resistant TLS; "
            "pip install curl-cffi)"
        )


def make_pp_session(headers: Dict[str, str] | None = None) -> Any:
    """curl_cffi Session when available, else requests.Session."""
    ensure_chrome131()
    log_http_backend_once()
    hdrs = dict(headers or {})
    try:
        from curl_cffi.requests import Session as CurlSession

        session = CurlSession(impersonate=curl_impersonate())
    except ImportError:
        import requests

        session = requests.Session()
    if hdrs:
        session.headers.update(hdrs)
    return session


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_pp_api_module():
    root = _repo_root()
    candidates = [
        root / "Sports" / "NBA" / "scripts" / "step1_fetch_prizepicks_api.py",
        root / "NBA" / "scripts" / "step1_fetch_prizepicks_api.py",
    ]
    path = next((c for c in candidates if c.exists()), candidates[0])
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("pp_fetch_api_shared", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Cannot load PrizePicks API module. Tried: "
            + ", ".join(str(c) for c in candidates)
        )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_pp_projections(
    league_id: str,
    *,
    per_page: int = 250,
    max_pages: int = 10,
    retries: int = 5,
    first_page_waves: int = 3,
    forbid_cooldown_threshold: int = 5,
    forbid_cooldown_seconds: float = 90.0,
    forbid_cooldown_jitter: Tuple[float, float] = (12.0, 40.0),
    forbid_max_cooldown_windows: int = 3,
    inter_page_delay: Tuple[float, float] | None = (2.0, 6.0),
    session_jitter: Tuple[float, float] | None = (5.0, 12.0),
    wave_gap_seconds: Tuple[float, float] | None = (22.0, 48.0),
    fail_fast: bool = False,
) -> Tuple[List[dict], List[dict]]:
    """Fetch projections via Sports/NBA/scripts/step1_fetch_prizepicks_api.py."""
    ensure_chrome131()
    log_http_backend_once()
    mod = load_pp_api_module()
    return mod.fetch_projections(
        league_id=str(league_id),
        per_page=per_page,
        max_pages=max_pages,
        retries=retries,
        inter_page_delay=inter_page_delay,
        session_jitter=session_jitter,
        first_page_waves=first_page_waves,
        wave_gap_seconds=wave_gap_seconds,
        forbid_cooldown_threshold=forbid_cooldown_threshold,
        forbid_cooldown_seconds=forbid_cooldown_seconds,
        forbid_cooldown_jitter=forbid_cooldown_jitter,
        forbid_max_cooldown_windows=forbid_max_cooldown_windows,
        fail_fast=fail_fast,
    )
