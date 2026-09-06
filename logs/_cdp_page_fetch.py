"""In-page PrizePicks fetch via a page debugger socket (skips Playwright browser attach)."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPR = r"""
(async () => {
  const leagueId = %s;
  const url = `https://api.prizepicks.com/projections?league_id=${leagueId}&per_page=250&single_stat=true&in_game=false&game_mode=pickem&page=1`;
  const r = await fetch(url, {
    credentials: "include",
    headers: {
      accept: "application/json, text/plain, */*",
      referer: window.location.href,
      "x-requested-with": "XMLHttpRequest",
    },
  });
  const j = r.ok ? await r.json() : {};
  return { status: r.status, rows: Array.isArray(j.data) ? j.data.length : 0, href: window.location.href };
})()
"""


def pick_ws() -> str:
    tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=8).read())
    for t in tabs:
        if t.get("type") == "page" and "app.prizepicks.com/board" in (t.get("url") or ""):
            ws = t.get("webSocketDebuggerUrl") or ""
            if ws:
                return ws
    raise SystemExit("no PP board tab")


def main() -> int:
    ws_url = pick_ws()
    print("ws", ws_url)
    ws = websocket.create_connection(ws_url, timeout=30)
    try:
        for lid, name in (("2", "MLB"), ("3", "WNBA"), ("82", "SOCCER"), ("5", "TENNIS"), ("9", "NFL")):
            msg = {
                "id": int(lid) + 100,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": EXPR % json.dumps(lid),
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            }
            ws.send(json.dumps(msg))
            raw = ws.recv()
            payload = json.loads(raw)
            val = (payload.get("result") or {}).get("result") or {}
            print(name, json.dumps(val.get("value") or payload)[:300])
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
