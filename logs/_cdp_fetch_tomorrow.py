import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from utils.prizepicks_cdp import (
    align_cdp_context_for_datadome,
    connect_over_cdp,
    fetch_projections_inpage,
    pick_cdp_warmed_page,
)

print("connecting 120s...")
with sync_playwright() as p:
    browser = connect_over_cdp(p, "http://127.0.0.1:9222", timeout_ms=120_000)
    ctx = browser.contexts[0]
    align_cdp_context_for_datadome(ctx)
    page = pick_cdp_warmed_page(ctx, "2") or pick_cdp_warmed_page(ctx, None)
    print("page", None if page is None else page.url)
    if page is None:
        raise SystemExit("no PP page")
    for lid, name in (
        ("3", "WNBA"),
        ("82", "SOCCER"),
        ("5", "TENNIS"),
        ("9", "NFL"),
        ("44", "NFLP"),
        ("2", "MLB"),
    ):
        data, _inc, status, url = fetch_projections_inpage(
            page, lid, per_page=250, request_timeout_ms=25000, max_pages=8
        )
        print(f"{name} league={lid} status={status} rows={len(data)}")
        if url:
            print(f"  {url[:100]}")
