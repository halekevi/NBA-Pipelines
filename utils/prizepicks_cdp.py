"""Shared PrizePicks CDP (Chrome DevTools) in-page fetch helpers.

Used when HTTP is blocked by DataDome. Attach to an already-warmed Chrome on
--remote-debugging-port (default 9222), then call api.prizepicks.com via the
page's authenticated fetch().
"""
from __future__ import annotations

from typing import Any


def connect_over_cdp(playwright: Any, cdp_url: str, *, timeout_ms: int = 30_000):
    """Attach to Chrome. Explicit timeout avoids Playwright's 180s default hang."""
    cdp = (cdp_url or "").strip()
    if not cdp:
        raise ValueError("cdp_url is required")
    print(f"🌐 Connecting to existing Chrome via CDP: {cdp} (timeout={timeout_ms}ms)")
    return playwright.chromium.connect_over_cdp(cdp, timeout=int(timeout_ms))


def align_cdp_context_for_datadome(context: Any) -> None:
    try:
        context.grant_permissions(
            ["geolocation", "notifications"],
            origin="https://app.prizepicks.com",
        )
    except Exception:
        pass
    try:
        context.set_geolocation({"latitude": 33.7490, "longitude": -84.3880})
    except Exception:
        pass


def pick_cdp_warmed_page(context: Any, league_id: str | None = None) -> Any | None:
    try:
        pages = list(context.pages)
    except Exception:
        return None
    league_needle = f"league_id={league_id}" if league_id else ""
    scored: list[tuple[int, Any]] = []
    for pg in pages:
        try:
            url = (pg.url or "").lower()
        except Exception:
            continue
        if "prizepicks.com" not in url:
            continue
        score = 10 if "app.prizepicks.com" in url else 0
        if "/board" in url:
            score += 20
        if league_needle and league_needle in url:
            score += 50
        scored.append((score, pg))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored[0][1]


def cdp_board_ready(page: Any, league_id: str | None = None) -> bool:
    try:
        url = (page.url or "").lower()
    except Exception:
        return False
    if "app.prizepicks.com" not in url:
        return False
    if league_id and f"league_id={league_id}" in url:
        return True
    return "/board" in url


def fetch_projections_inpage(
    page: Any,
    league_id: str,
    *,
    per_page: int = 250,
    request_timeout_ms: int = 25_000,
    max_pages: int = 20,
) -> tuple[list[dict], list[dict], int, str]:
    """In-page fetch for one league_id. Returns (data, included, status, url).

    Merges pregame (in_game=false) and live (in_game=true) boards and paginates
    each. Returning the first non-empty URL used to drop FG/FT/2PT markets that
    only exist on the pregame board after Popular/core stats.
    """
    payload = page.evaluate(
        """async ({ leagueId, perPage, timeoutMs, maxPages }) => {
            const hdrs = () => ({
                "accept": "application/json, text/plain, */*",
                "accept-language": (navigator.languages && navigator.languages.length)
                    ? navigator.languages.join(",") : "en-US,en;q=0.9",
                "referer": window.location.href,
                "x-requested-with": "XMLHttpRequest",
            });
            const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const fetchJson = async (url) => {
                const ctrl = new AbortController();
                const timer = setTimeout(() => ctrl.abort(), timeoutMs);
                try {
                    const r = await fetch(url, {
                        credentials: "include",
                        headers: hdrs(),
                        mode: "cors",
                        signal: ctrl.signal,
                    });
                    clearTimeout(timer);
                    if (!r.ok) return { ok: false, status: r.status, data: [], included: [], url };
                    const j = await r.json();
                    return {
                        ok: true,
                        status: r.status,
                        data: Array.isArray(j?.data) ? j.data : [],
                        included: Array.isArray(j?.included) ? j.included : [],
                        url,
                    };
                } catch (e) {
                    clearTimeout(timer);
                    return { ok: false, status: 0, data: [], included: [], url, error: String(e) };
                }
            };

            const seen = new Set();
            const allData = [];
            const allIncluded = [];
            let lastStatus = 0;
            let lastUrl = '';
            // Pregame first: FG Made/Attempted, FT, 2PT live on in_game=false.
            const flags = ["false", "true"];
            for (const inGame of flags) {
                for (let pageNum = 1; pageNum <= maxPages; pageNum++) {
                    const url = `https://api.prizepicks.com/projections?league_id=${leagueId}`
                        + `&per_page=${perPage}&single_stat=true&in_game=${inGame}`
                        + `&game_mode=pickem&page=${pageNum}&page[number]=${pageNum}`
                        + `&page[size]=${perPage}`;
                    const res = await fetchJson(url);
                    lastStatus = res.status || lastStatus;
                    lastUrl = res.url || lastUrl;
                    if (!res.ok) {
                        if (pageNum === 1) break;
                        break;
                    }
                    const data = res.data || [];
                    const included = res.included || [];
                    let added = 0;
                    for (const row of data) {
                        const id = row && row.id != null ? String(row.id) : '';
                        if (!id || seen.has(id)) continue;
                        seen.add(id);
                        allData.push(row);
                        added += 1;
                    }
                    for (const obj of included) allIncluded.push(obj);
                    if (data.length === 0 || added === 0) break;
                    if (data.length < perPage) break;
                    await sleep(350);
                }
            }
            return { data: allData, included: allIncluded, status: lastStatus || (allData.length ? 200 : 0), url: lastUrl };
        }""",
        {
            "leagueId": str(league_id),
            "perPage": int(per_page),
            "timeoutMs": int(request_timeout_ms),
            "maxPages": int(max_pages),
        },
    )
    data = list((payload or {}).get("data") or [])
    included = list((payload or {}).get("included") or [])
    status = int((payload or {}).get("status") or 0)
    url = str((payload or {}).get("url") or "")
    return data, included, status, url
