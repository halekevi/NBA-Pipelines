#!/usr/bin/env python3
"""
Collect exact PrizePicks payout samples from a logged-in Chrome CDP session.

Read-only: builds/clears slips and reads multipliers; never submits entries.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
import time
from collections import Counter
from difflib import get_close_matches
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "payout_samples"
PAYOUT_LADDER_LIVE_CDP_PATH = ROOT / "ui_runner" / "data" / "payout_ladder_live_cdp.json"
DEBUG_DIR = ROOT / "data" / "debug"

VALID_PROP_KEYWORDS = [
    "Points",
    "Assists",
    "Rebounds",
    "Steals",
    "Blocks",
    "Turnovers",
    "3-PT Made",
    "Points+Assists",
    "Pts+Asts",
    "Pts+Reb+Ast",
    "Fantasy Score",
    "Points+Rebounds",
    "Rebounds+Assists",
    "Points+Rebounds+Assists",
    "FG Attempted",
    "Free Throws Made",
    "Minutes",
    # MLB
    "Hits",
    "Total Bases",
    "Runs",
    "RBIs",
    "Stolen Bases",
    "Strikeouts",
    "Pitcher Strikeouts",
    "Hits Allowed",
    "Walks",
    "Earned Runs",
    "Outs",
    # Soccer / World Cup / tennis-ish board text
    "Shots",
    "SOT",
    "Shots On Target",
    "Goalie Saves",
    "Goals",
    "Goals Allowed",
    "Goal",
    "Aces",
    "Double Faults",
    "Games Won",
    "Break Points Won",
]
_TEAM_POS_RE = re.compile(
    r"(?i).+\s[-–]\s*(attacker|midfielder|defender|goalkeeper|forward|guard|center|"
    r"pitcher|catcher|infielder|outfielder|shortstop|baseman|designated hitter|"
    r"sp|rp|c|1b|2b|3b|ss|lf|cf|rf|dh|g|f|c)\b"
)
# Live board clock overlays (e.g. "Q2 9:08") are not player names.
_GAME_CLOCK_RE = re.compile(r"^(?:Q[1-4]|OT|HT|H[12])\s+\d{1,2}:\d{2}$", re.I)
_PERIOD_LABEL_RE = re.compile(r"^(?:halftime|half\s*time|overtime|end of \w+|final)$", re.I)
_LOOKUP_DIAG_PRINTED = False
_POPULAR_READY = False


def parse_card_lines(lines: list[str]) -> tuple[str | None, float | None, str | None]:
    player_name = None
    line_value = None
    prop_type = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^\d+\.?\d*[KkMm]$", line):
            continue
        if re.match(r"^[A-Z]{2,3}\s*[-–]\s*[A-Z]", line):
            continue
        if _TEAM_POS_RE.match(line):
            continue
        if _GAME_CLOCK_RE.match(line) or _PERIOD_LABEL_RE.match(line):
            continue
        if line.startswith("vs ") or line.startswith("@ "):
            continue
        if line in ["More", "Less", "More\nLess"]:
            continue
        if "+" in line and re.search(r"[A-Za-z].*\+.*[A-Za-z]", line) and line_value is None:
            # Combo player cards — skip for calibration pool
            return None, None, None

        if player_name is None and not re.match(r"^\d", line) and len(line) > 2:
            player_name = line
            continue

        # Line number only after we have a player (avoids heat counts like "208")
        if player_name is not None and line_value is None and re.match(r"^\d+\.?\d*$", line):
            try:
                line_value = float(line)
            except Exception:
                pass
            continue

        if player_name is not None and line_value is not None and prop_type is None:
            if any(vp.lower() in line.lower() for vp in VALID_PROP_KEYWORDS):
                prop_type = line
                continue
            # Fallback: any non-junk label after the line number (multi-sport boards)
            if re.search(r"[A-Za-z]", line) and len(line) >= 2:
                prop_type = line
                continue

    return player_name, line_value, prop_type


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _pick_col(df: pd.DataFrame, names: list[str]) -> str | None:
    m = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if n.lower() in m:
            return m[n.lower()]
    return None


def _line_key(v: Any) -> str:
    try:
        return f"{float(v):.3f}"
    except Exception:
        return ""


def load_nba_legs(top_n: int = 30) -> list[dict]:
    step8 = ROOT / "Sports" / "NBA" / "data" / "outputs" / "step8_all_direction_clean.xlsx"
    step1 = ROOT / "Sports" / "NBA" / "data" / "outputs" / "step1_pp_props_today.csv"
    if not step8.exists() or not step1.exists():
        raise FileNotFoundError("Missing NBA step8/step1 files.")

    xls = pd.ExcelFile(step8)
    sh = "ALL" if "ALL" in xls.sheet_names else xls.sheet_names[0]
    df8 = pd.read_excel(step8, sheet_name=sh)
    df1 = pd.read_csv(step1, low_memory=False)

    p8 = _pick_col(df8, ["player"])
    team8 = _pick_col(df8, ["team"])
    prop8 = _pick_col(df8, ["prop_type", "prop"])
    line8 = _pick_col(df8, ["line"])
    dir8 = _pick_col(df8, ["direction", "final_bet_direction"])
    tier8 = _pick_col(df8, ["tier"])
    blend8 = _pick_col(df8, ["blended_score", "blended score"])
    pick8 = _pick_col(df8, ["pick_type"])
    proj8 = _pick_col(df8, ["projection_id", "pp_projection_id"])
    req = [p8, prop8, line8, dir8, tier8, blend8]
    if any(x is None for x in req):
        raise RuntimeError("NBA step8 missing required columns for sample build.")

    p1 = _pick_col(df1, ["player"])
    team1 = _pick_col(df1, ["team"])
    prop1 = _pick_col(df1, ["prop_type", "prop"])
    line1 = _pick_col(df1, ["line"])
    pick1 = _pick_col(df1, ["pick_type"])
    proj1 = _pick_col(df1, ["projection_id", "pp_projection_id"])
    if any(x is None for x in [p1, prop1, line1, proj1]):
        raise RuntimeError("NBA step1 missing required columns for pp_id mapping.")

    idx: dict[tuple[str, str, str, str], dict] = {}
    for _, r in df1.iterrows():
        key = (
            _norm(r.get(p1)),
            _norm(r.get(prop1)),
            _line_key(r.get(line1)),
            _norm(r.get(team1)) if team1 else "",
        )
        idx[key] = {
            "projection_id": str(r.get(proj1, "") or "").strip(),
            "pick_type": str(r.get(pick1, "Standard") or "Standard"),
            "line": r.get(line1),
        }

    d = df8.copy()
    tier = d[tier8].astype(str).str.upper().str.strip()
    direction = d[dir8].astype(str).str.upper().str.strip()
    blend = pd.to_numeric(d[blend8], errors="coerce")
    d = d[tier.isin(["A", "B", "C"]) & direction.ne("") & blend.notna()].copy()
    d["__blend"] = blend.loc[d.index]
    d = d.sort_values("__blend", ascending=False).head(top_n)

    out: list[dict] = []
    for _, r in d.iterrows():
        player = str(r.get(p8, "") or "").strip()
        prop = str(r.get(prop8, "") or "").strip()
        team = str(r.get(team8, "") or "").strip() if team8 else ""
        line = r.get(line8)
        ddir = str(r.get(dir8, "") or "").strip().upper()
        proj = str(r.get(proj8, "") or "").strip() if proj8 else ""
        ptype = str(r.get(pick8, "") or "").strip()
        if not proj:
            k1 = (_norm(player), _norm(prop), _line_key(line), _norm(team))
            k2 = (_norm(player), _norm(prop), _line_key(line), "")
            m = idx.get(k1) or idx.get(k2)
            if m:
                proj = str(m.get("projection_id", "") or "").strip()
                if not ptype:
                    ptype = str(m.get("pick_type", "Standard"))
        if not proj:
            continue
        out.append(
            {
                "player": player,
                "sport": "NBA",
                "prop_type": prop,
                "line": float(line) if str(line).strip() != "" else None,
                "pick_type": str(ptype or "Standard").strip().lower(),
                "direction": ddir if ddir in ("OVER", "UNDER") else "OVER",
                "pp_id": proj,
                "team": team,
                "blended_score": float(r.get("__blend") or 0.0),
            }
        )
    return out


def connect_existing_browser(cdp_url: str, *, cdp_timeout_ms: int = 45_000):
    try:
        p = sync_playwright().start()
        browser = p.chromium.connect_over_cdp(cdp_url, timeout=cdp_timeout_ms)
        if not browser.contexts:
            raise RuntimeError("No contexts found in CDP Chrome.")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        for pg in context.pages:
            if "prizepicks" in (pg.url or "").lower():
                page = pg
                break
        return p, browser, context, page
    except Exception as e:
        print("Could not attach to Chrome CDP (timed out or refused).")
        print("Close every Chrome window, then start debug Chrome:")
        print(
            r'  & "C:\Program Files\Google\Chrome\Application\chrome.exe" '
            r"--remote-debugging-port=9222 --user-data-dir=C:\chrome_debug"
        )
        print("Open https://app.prizepicks.com/ , log in, NBA board with props visible.")
        print(f"Retry with: py -3.14 scripts\\collect_payout_data.py --cdp-url http://127.0.0.1:9222")
        raise RuntimeError(str(e))


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s or "").strip())[:80]


def _scroll_board_for_lazy_load(page):
    # Load additional projection cards before lookup.
    for _ in range(3):
        try:
            page.mouse.wheel(0, 4000)
        except Exception:
            pass
        page.wait_for_timeout(1000)


def find_prizepicks_frame(page):
    """Find the frame that contains the actual projection board content."""
    for frame in page.frames:
        try:
            text = frame.evaluate("() => (document.body && document.body.innerText) ? document.body.innerText : ''")
            if any(x in text for x in ["Turnovers", "Points", "Assists", "Rebounds", "More", "Less", "Popular"]):
                print(f"[FRAME] Found content in frame: {frame.url}")
                return frame
        except Exception:
            pass
    print("[FRAME] Falling back to main page")
    return page


def ensure_popular_filter(frame, page):
    global _POPULAR_READY
    if _POPULAR_READY:
        return
    clicked = False
    chosen = None
    for primary in ("Points", "Popular"):
        try:
            frame.get_by_text(primary, exact=True).first.click(timeout=1200)
            clicked = True
            chosen = primary
            break
        except Exception:
            for sel in [f"text={primary}", f"[data-testid='{primary.lower()}-filter']"]:
                try:
                    loc = frame.locator(sel).first
                    if loc.count() > 0:
                        loc.click(timeout=1200)
                        clicked = True
                        chosen = primary
                        break
                except Exception:
                    continue
            if clicked:
                break
    frame.wait_for_timeout(1500)
    _scroll_board_for_lazy_load(page)
    cards = _extract_cards_data_js(frame)
    print(f"[LOOKUP] Primary filter ({chosen or 'Points/Popular'}) click: {'OK' if clicked else 'NOT FOUND'}")
    print(f"[LOOKUP] Cards visible after primary filter click: {len(cards)}")
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        shot = DEBUG_DIR / f"after_primary_filter_{ts}.png"
        page.screenshot(path=str(shot), full_page=True)
        print(f"[LOOKUP] Primary filter screenshot saved: {shot}")
    except Exception:
        pass
    _POPULAR_READY = True


def _extract_cards_data_js(page) -> list[dict]:
    # PP cards use newline-prefixed matchups ("\\n@ WAS", "\\nvs SEA"), not " @ "/" vs ".
    return page.evaluate(
        """
        () => {
          const allElements = document.querySelectorAll('*');
          const cards = [];
          const hasMatchup = (text) =>
            /(^|\\n|\\s)@\\s/.test(text) || /(^|\\n|\\s)vs\\s/i.test(text)
            || text.includes(' vs ') || text.includes(' @ ');
          for (const el of allElements) {
            const text = (el.innerText || '').trim();
            if (!text) continue;
            if (hasMatchup(text)
                && /\\d+\\.?\\d*/.test(text)
                && text.length < 400
                && text.length > 20) {
              const r = el.getBoundingClientRect();
              cards.push({
                text,
                tag: el.tagName,
                rect: {x: r.x, y: r.y, w: r.width, h: r.height}
              });
            }
          }
          const seen = new Set();
          return cards.filter(c => {
            if (seen.has(c.text)) return false;
            seen.add(c.text);
            return true;
          }).slice(0, 200);
        }
        """
    )


def _player_name_from_card_text(text: str) -> str | None:
    lines = [l.strip() for l in str(text or "").split("\n") if l.strip()]
    player, _line, _prop = parse_card_lines(lines)
    return player


def prop_type_to_board_filter(prop: str) -> str:
    """Map ticket prop labels onto PrizePicks board filter chip text."""
    raw = str(prop or "").strip()
    key = re.sub(r"\s+", "", raw.lower()).replace("–", "-").replace("—", "-")
    mapping = {
        "points": "Points",
        "assists": "Assists",
        "rebounds": "Rebounds",
        "steals": "Steals",
        "blocks": "Blocks",
        "blockedshots": "Blocks",
        "turnovers": "Turnovers",
        "3-ptmade": "3-PT Made",
        "3ptmade": "3-PT Made",
        "threes": "3-PT Made",
        "pts+rebs": "Pts+Rebs",
        "points+rebounds": "Pts+Rebs",
        "pts+asts": "Pts+Asts",
        "points+assists": "Pts+Asts",
        "rebs+asts": "Reb+Asts",
        "rebounds+assists": "Reb+Asts",
        "pts+reb+ast": "Pts+Reb+Ast",
        "pts+reb+asts": "Pts+Reb+Ast",
        "pra": "Pts+Reb+Ast",
        "points+rebounds+assists": "Pts+Reb+Ast",
        "fantasyscore": "Fantasy Score",
        "fgmade": "FG Made",
        "fgattempted": "FG Attempted",
        "freethrowsmade": "Free Throws Made",
    }
    if key in mapping:
        return mapping[key]
    # Already looks like a chip label (Pts+Rebs, 3-PT Made, …).
    if raw:
        return raw
    return "Points"


def _switch_board_filter(frame, page, tab: str) -> bool:
    tab = str(tab or "").strip()
    if not tab:
        return False
    try:
        dismiss_modal(frame, page)
        tloc = frame.get_by_text(tab, exact=True).first
        if tloc.count() == 0:
            tloc = frame.get_by_text(tab, exact=False).first
        tloc.click(force=True, timeout=2000)
        frame.wait_for_timeout(900)
        _scroll_board_for_lazy_load(page)
        print(f"[FILTER] switched to {tab}")
        return True
    except Exception as e:
        print(f"[FILTER] could not switch to {tab}: {e}")
        return False


def _resolve_ticket_leg_card(
    player: str,
    prop: str,
    line: Any,
    pick_type: str,
    cards: list[dict],
    *,
    strict: bool = False,
    require_line: bool | None = None,
) -> dict | None:
    """Pick the best live board card for a generated MAIN/STRONG leg.

    strict=True: require pick_type; never fall back to a different badge.
    require_line defaults to strict; set False to allow board line drift while
    still requiring the requested Goblin/Demon/Standard badge (ladder validation).
    """
    if require_line is None:
        require_line = bool(strict)
    nt = _norm(player)
    np = _norm(prop)
    pt = str(pick_type or "standard").strip().lower()
    if pt not in ("goblin", "demon", "standard"):
        pt = "standard"
    nl = _line_key(line) if line is not None and str(line).strip() != "" else None

    def _name_hit(c: dict) -> bool:
        cn = _norm(c.get("player"))
        return bool(cn) and (nt in cn or cn in nt or nt == cn)

    pool = [c for c in cards if _name_hit(c)]
    if not pool:
        return None

    # Require prop match when we know it.
    if np:
        prop_pool = [
            c
            for c in pool
            if (cp := _norm(c.get("prop_type"))) and (np == cp or np in cp or cp in np)
        ]
        if prop_pool:
            pool = prop_pool
        elif strict:
            print(f"[LOOKUP] STRICT miss prop={prop} for {player}")
            return None

    # Prefer requested pick_type before line matching so a moved Goblin line
    # can still resolve when require_line=False.
    typed = [c for c in pool if str(c.get("pick_type") or "").lower() == pt]
    if typed:
        pool = typed
    elif strict:
        print(
            f"[LOOKUP] STRICT miss pick_type={pt} for {player} {prop}; "
            f"candidates={[(c.get('line'), c.get('pick_type')) for c in pool[:6]]}"
        )
        return None

    # Exact line when ticket specifies one (board may have moved).
    if nl is not None:
        line_pool = [c for c in pool if _line_key(c.get("line")) == nl]
        if line_pool:
            pool = line_pool
        else:
            print(
                f"[LOOKUP] {'STRICT' if require_line else 'WARN'} no exact line {nl} "
                f"for {player} {prop}; "
                f"candidates={[(c.get('line'), c.get('pick_type')) for c in pool[:6]]}"
            )
            if require_line:
                return None

    ranked: list[tuple[int, dict]] = []
    for c in pool:
        score = 0
        cp = _norm(c.get("prop_type"))
        if np and (np == cp or np in cp or cp in np):
            score += 5
        if str(c.get("pick_type") or "").lower() == pt:
            score += 4
        if nl is not None and _line_key(c.get("line")) == nl:
            score += 3
        ranked.append((score, c))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1] if ranked else None


def _collect_visible_players(frame) -> tuple[list[str], str | None, dict[str, int]]:
    selectors_to_try = [
        "[data-testid='player-name']",
        "[data-testid='projection-player-name']",
        ".player-name",
        ".projection-card .name",
        "[class*='PlayerName']",
        "[class*='player_name']",
    ]
    selector_counts: dict[str, int] = {}
    best_sel = None
    best_vals: list[str] = []
    for sel in selectors_to_try:
        vals: list[str] = []
        try:
            loc = frame.locator(sel)
            n = loc.count()
            for i in range(min(n, 300)):
                t = str(loc.nth(i).inner_text(timeout=200) or "").strip()
                if t:
                    vals.append(t)
            vals = list(dict.fromkeys(vals))
            selector_counts[sel] = len(vals)
            if len(vals) > len(best_vals):
                best_vals = vals
                best_sel = sel
        except Exception:
            selector_counts[sel] = 0
    # JS fallback for React/hashed classes.
    cards_data = _extract_cards_data_js(frame)
    js_players: list[str] = []
    for card in cards_data:
        nm = _player_name_from_card_text(card.get("text", ""))
        if nm:
            js_players.append(nm)
    js_players = list(dict.fromkeys(js_players))
    selector_counts["__js_card_text_parse__"] = len(js_players)
    if len(js_players) > len(best_vals):
        best_vals = js_players
        best_sel = "__js_card_text_parse__"
    # print raw card text sample for diagnosis
    if cards_data:
        print("[LOOKUP] JS card text samples:")
        for c in cards_data[:10]:
            print(f"  - {str(c.get('text',''))[:100]}")
    return best_vals, best_sel, selector_counts


def get_all_cards(frame) -> list[dict]:
    """
    Anchor on More buttons and parse player/stat details from ancestor text.
    """
    cards: list[dict] = []
    try:
        import re as _re
        more_loc = frame.get_by_text("More")
        n = more_loc.count()
        print(f"[CARDS] Found {n} More buttons")
        debug_unparsed = 0
        for i in range(min(n, 200)):
            btn = more_loc.nth(i)
            try:
                card_info = btn.evaluate(
                    """
                    el => {
                      let p = el;
                      let best = null;
                      for (let i = 0; i < 10; i++) {
                        p = p ? p.parentElement : null;
                        if (!p) break;
                        const t = (p.innerText || '');
                        const hasGame = /\\s(vs|@)\\s/i.test(t);
                        const hasStat = /\\b\\d+(?:\\.\\d+)?\\s*[A-Za-z]/.test(t);
                        const moreCount = (t.match(/\\bMore\\b/g) || []).length;
                        const lessCount = (t.match(/\\bLess\\b/g) || []).length;
                        // Tight card root: one More (avoid board/grid ancestors).
                        if (hasGame && hasStat && moreCount === 1 && lessCount <= 1) {
                          best = p;
                          break;
                        }
                      }
                      if (!best) {
                        p = el;
                        for (let i = 0; i < 10; i++) {
                          p = p ? p.parentElement : null;
                          if (!p) break;
                          const t = (p.innerText || '');
                          if (/\\bMore\\b/.test(t) && /\\s(vs|@)\\s/i.test(t) && /\\b\\d+(?:\\.\\d+)?/.test(t)) {
                            best = p; break;
                          }
                        }
                      }
                      if (!best) return null;
                      const html = (best.innerHTML || '');
                      const text = best.innerText || '';
                      // Prefer explicit badge image alts — cards also contain a shared
                      // "Demons and Goblins" help button that would false-positive a blob search.
                      const badgeImgs = Array.from(best.querySelectorAll('img[alt]'));
                      let pickType = 'standard';
                      for (const img of badgeImgs) {
                        const alt = (img.getAttribute('alt') || '').trim().toLowerCase();
                        if (alt === 'goblin') { pickType = 'goblin'; break; }
                        if (alt === 'demon') { pickType = 'demon'; break; }
                      }
                      if (pickType === 'standard') {
                        for (const img of badgeImgs) {
                          const src = (img.getAttribute('src') || '').toLowerCase();
                          const alt = (img.getAttribute('alt') || '').toLowerCase();
                          if (alt.includes('goblin') && !alt.includes('demon')) {
                            pickType = 'goblin'; break;
                          }
                          if (alt.includes('demon') && !alt.includes('goblin')) {
                            pickType = 'demon'; break;
                          }
                          if (/goblin/.test(src) && !/demon/.test(src)) {
                            pickType = 'goblin'; break;
                          }
                          if (/demon/.test(src) && !/goblin/.test(src)) {
                            pickType = 'demon'; break;
                          }
                        }
                      }
                      const hasAltBtn = Array.from(best.querySelectorAll('button')).some(b => {
                        const cls = (b.className || '').toString();
                        const bt = (b.innerText || '').trim();
                        if (/more|less/i.test(bt)) return false;
                        return /soFresh/.test(cls) && !!b.querySelector('svg');
                      });
                      return {
                        text: text,
                        html: html.slice(0, 2500),
                        pickType: pickType,
                        hasAltLines: hasAltBtn || /[↔⇄⟷⇆↕]/.test(text),
                        badges: badgeImgs.slice(0, 6).map(img => ({
                          alt: img.getAttribute('alt'),
                          src: (img.getAttribute('src') || '').slice(0, 80),
                        })),
                      };
                    }
                    """
                )
                if not card_info or not card_info.get("text"):
                    continue
                text = str(card_info["text"])
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                if len(lines) < 3:
                    continue
                player_name, line_value, prop_type = parse_card_lines(lines)
                pick_type = str(card_info.get("pickType") or "standard").lower()
                if pick_type not in ("goblin", "demon", "standard"):
                    pick_type = "standard"
                has_alt_lines = bool(card_info.get("hasAltLines"))
                if player_name and line_value is not None and prop_type:
                    card = {
                        "player": player_name,
                        "prop_type": prop_type,
                        "line": line_value,
                        "pick_type": pick_type,
                        "has_alt_lines": has_alt_lines,
                        "more_btn": btn,
                        "raw_text": text[:200],
                        "badges": card_info.get("badges") or [],
                    }
                    if _is_valid_board_card(card):
                        cards.append(card)
                elif debug_unparsed < 5:
                    debug_unparsed += 1
                    print(f"[CARDS][UNPARSED] sample {debug_unparsed}: {' | '.join(lines[:6])}")
            except Exception:
                continue
    except Exception as e:
        print(f"[CARDS] Error: {e}")
        return []
    print(f"[CARDS] Parsed {len(cards)} cards")
    for c in cards[:10]:
        print(f"[CARD] {c['player']} | {c['line']} {c['prop_type']} | {c['pick_type']}")
    return cards


_CARD_STATE_FROM_MORE_JS = """
el => {
  let p = el;
  let best = null;
  for (let i = 0; i < 10; i++) {
    p = p ? p.parentElement : null;
    if (!p) break;
    const t = (p.innerText || '');
    const hasGame = /\\s(vs|@)\\s/i.test(t);
    const hasStat = /\\b\\d+(?:\\.\\d+)?/.test(t);
    const moreCount = (t.match(/\\bMore\\b/g) || []).length;
    const lessCount = (t.match(/\\bLess\\b/g) || []).length;
    if (hasGame && hasStat && moreCount === 1 && lessCount <= 1) { best = p; break; }
  }
  if (!best) return null;
  const badgeImgs = Array.from(best.querySelectorAll('img[alt]'));
  let pickType = 'standard';
  for (const img of badgeImgs) {
    const alt = (img.getAttribute('alt') || '').trim().toLowerCase();
    if (alt === 'goblin') { pickType = 'goblin'; break; }
    if (alt === 'demon') { pickType = 'demon'; break; }
  }
  const lines = (best.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
  let lineVal = null;
  for (const line of lines) {
    const m = line.match(/^(\\d+(?:\\.\\d+)?)$/);
    if (m) { lineVal = parseFloat(m[1]); break; }
  }
  if (lineVal == null) {
    for (const line of lines) {
      const m = line.match(/(\\d+(?:\\.\\d+)?)\\s*(?:Points|Assists|Rebounds|Steals|Blocks)/i);
      if (m) { lineVal = parseFloat(m[1]); break; }
    }
  }
  const hasAltBtn = Array.from(best.querySelectorAll('button')).some(b => {
    const cls = (b.className || '').toString();
    const text = (b.innerText || '').trim();
    if (/more|less/i.test(text)) return false;
    return /soFresh/.test(cls) && !!b.querySelector('svg');
  });
  return { text: lines.slice(0, 12), pickType, line: lineVal, hasAltLines: hasAltBtn };
}
"""

_CLICK_ALT_SWAP_JS = """
el => {
  let p = el;
  let best = null;
  for (let i = 0; i < 10; i++) {
    p = p ? p.parentElement : null;
    if (!p) break;
    const t = (p.innerText || '');
    const hasGame = /\\s(vs|@)\\s/i.test(t);
    const hasStat = /\\b\\d+(?:\\.\\d+)?/.test(t);
    const moreCount = (t.match(/\\bMore\\b/g) || []).length;
    const lessCount = (t.match(/\\bLess\\b/g) || []).length;
    if (hasGame && hasStat && moreCount === 1 && lessCount <= 1) { best = p; break; }
  }
  if (!best) return {ok: false, reason: 'no_root'};
  const btns = Array.from(best.querySelectorAll('button')).filter(b => {
    const text = (b.innerText || '').trim();
    if (/more|less/i.test(text)) return false;
    return !!b.querySelector('svg');
  });
  let target = null;
  for (const b of btns) {
    const cls = (b.className || '').toString();
    if (/soFresh/.test(cls) && !/absolute left-2 top-2/.test(cls)) { target = b; break; }
  }
  if (!target) {
    for (const b of btns) {
      const cls = (b.className || '').toString();
      if (!/absolute left-2 top-2/.test(cls)) { target = b; break; }
    }
  }
  if (!target) return {ok: false, reason: 'no_swap_btn', n: btns.length};
  target.click();
  return {ok: true};
}
"""


def _read_card_state_from_more(more_btn) -> dict | None:
    try:
        st = more_btn.evaluate(_CARD_STATE_FROM_MORE_JS)
        return st if isinstance(st, dict) else None
    except Exception:
        return None


def _click_alt_line_swap(more_btn) -> bool:
    try:
        res = more_btn.evaluate(_CLICK_ALT_SWAP_JS)
        return bool(isinstance(res, dict) and res.get("ok"))
    except Exception as e:
        print(f"[ALT] swap click failed: {e}")
        return False


def _rebind_more_btn(frame, player: str, prop: str):
    """Re-find a live More button after the board re-renders from an alt-line swap."""
    nt = _norm(player)
    np = _norm(prop)
    cards = get_all_cards(frame)
    for c in cards:
        if nt not in _norm(c.get("player")) and _norm(c.get("player")) not in nt:
            continue
        if np and _norm(c.get("prop_type")) not in (np,) and np not in _norm(c.get("prop_type") or ""):
            # allow loose prop containment
            cp = _norm(c.get("prop_type"))
            if not (np == cp or np in cp or cp in np):
                continue
        return c.get("more_btn"), c
    # name-only fallback
    for c in cards:
        if nt in _norm(c.get("player")) or _norm(c.get("player")) in nt:
            return c.get("more_btn"), c
    return None, None


def cycle_card_to_pick_type(
    frame,
    more_btn,
    *,
    player: str,
    prop: str,
    want_pick: str,
    want_line: Any = None,
    require_line: bool = False,
    max_clicks: int = 14,
) -> dict | None:
    """
    Click the dual-arrow (soFresh) control to cycle Standard ↔ Goblin ↔ Demon
    lines on the same player+prop card until the requested badge appears.
    """
    want = str(want_pick or "standard").strip().lower()
    if want not in ("goblin", "demon", "standard"):
        want = "standard"
    want_lk = (
        _line_key(want_line)
        if want_line is not None and str(want_line).strip() != ""
        else None
    )

    seen: set[tuple[str, str | None]] = set()
    best_badge_match: dict | None = None
    btn = more_btn

    for i in range(max(1, int(max_clicks))):
        if btn is None:
            btn, _ = _rebind_more_btn(frame, player, prop)
        if btn is None:
            return best_badge_match

        st = _read_card_state_from_more(btn)
        if not st:
            btn2, card = _rebind_more_btn(frame, player, prop)
            btn = btn2
            if card:
                st = {
                    "pickType": card.get("pick_type"),
                    "line": card.get("line"),
                    "hasAltLines": card.get("has_alt_lines"),
                }
            else:
                return best_badge_match

        pt = str(st.get("pickType") or "standard").lower()
        lk = _line_key(st.get("line")) if st.get("line") is not None else None
        key = (pt, lk)
        if key in seen and i > 0:
            print(f"[ALT] cycle wrapped without exact match want={want} line={want_lk}")
            return best_badge_match
        seen.add(key)

        if pt == want:
            if want_lk is None or lk == want_lk:
                print(f"[ALT] matched {want} line={lk} after {i} swap(s)")
                return {"pick_type": pt, "line": st.get("line"), "more_btn": btn, **st}
            if not require_line and best_badge_match is None:
                best_badge_match = {
                    "pick_type": pt,
                    "line": st.get("line"),
                    "more_btn": btn,
                    **st,
                }

        if not st.get("hasAltLines", True):
            # Still try once — button detection can lag.
            pass
        if not _click_alt_line_swap(btn):
            print("[ALT] swap button missing/failed")
            return best_badge_match
        try:
            frame.wait_for_timeout(500)
        except Exception:
            time.sleep(0.5)
        # Rebind after React re-render.
        btn, _ = _rebind_more_btn(frame, player, prop)

    if best_badge_match is not None:
        print(
            f"[ALT] nearest {want} line={best_badge_match.get('line')} "
            f"(wanted {want_lk}, require_line={require_line})"
        )
    return best_badge_match


def _click_player_direction(frame, matched_name: str, direction: str, prop: str) -> bool:
    # Rebuild current cards each attempt to avoid stale elements.
    cards = get_all_cards(frame)
    lname = _norm(matched_name)
    lprop = _norm(prop)
    target = None
    for c in cards:
        if lname in _norm(c.get("player", "")):
            if lprop and lprop not in _norm(c.get("card_text", "")):
                continue
            target = c
            break
    if target is None:
        return False
    try:
        if str(direction).upper() == "OVER":
            target["more_btn"].click(timeout=900)
        else:
            try:
                target["more_btn"].locator("xpath=../..//button[contains(., 'Less')]").first.click(timeout=900)
            except Exception:
                frame.get_by_text("Less", exact=True).first.click(timeout=900)
        frame.wait_for_timeout(500)
        return True
    except Exception as e:
        print(f"[CLICK] Failed: {e}")
        return False


def click_leg(frame, card: dict, direction: str) -> bool:
    try:
        if direction.upper() in ["OVER", "MORE"]:
            card["more_btn"].click(timeout=1200)
        else:
            found_less = card["more_btn"].evaluate(
                """
                el => {
                  let p = el;
                  for (let i = 0; i < 4; i++) p = p?.parentElement;
                  if (!p) return false;
                  const btns = p.querySelectorAll('button');
                  for (const b of btns) {
                    if ((b.innerText || '').trim() === 'Less') { b.click(); return true; }
                  }
                  return false;
                }
                """
            )
            if not found_less:
                frame.get_by_text("Less").nth(0).click(timeout=1200)
        frame.wait_for_timeout(400)
        return True
    except Exception as e:
        print(f"[CLICK] {card.get('player', '?')} failed: {e}")
        return False


def extract_number(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def extract_multiplier_from_any(value: Any) -> float | None:
    if isinstance(value, dict):
        for k, v in value.items():
            kl = str(k).lower()
            if any(x in kl for x in ("payout_multiplier", "winning_multiplier", "multiplier", "payout", "odds")):
                m = extract_multiplier_from_any(v)
                if m is not None:
                    return m
            m = extract_multiplier_from_any(v)
            if m is not None:
                return m
    elif isinstance(value, list):
        for v in value:
            m = extract_multiplier_from_any(v)
            if m is not None:
                return m
    elif isinstance(value, (int, float)):
        f = float(value)
        if f > 1:
            return f
    elif isinstance(value, str):
        m = re.search(r"(\d+(?:\.\d+)?)\s*x", value.lower())
        if m:
            return float(m.group(1))
    return None


def clear_slip(frame):
    try:
        for txt in ["Clear", "Clear All", "Remove All"]:
            b = frame.get_by_text(txt, exact=False).first
            if b.count() > 0:
                try:
                    b.click(timeout=500)
                    frame.wait_for_timeout(600)
                    print("[SLIP] Cleared")
                    return
                except Exception:
                    pass
        for sel in [
            "button[aria-label*='remove']",
            "button[aria-label*='delete']",
            "button[aria-label*='clear']",
            "[aria-label*='Close']",
            "[data-testid*='remove']",
        ]:
            btns = frame.locator(sel)
            n = min(btns.count(), 20)
            for _ in range(n):
                try:
                    btns.nth(0).click(timeout=300)
                    frame.wait_for_timeout(250)
                except Exception:
                    break
    except Exception:
        pass


def verify_slip_empty(frame, page=None) -> tuple[bool, object]:
    try:
        text = frame.evaluate("() => document.body.innerText")
        n_selected = re.findall(r"(\d+)\s*Players?\s*Selected", text, re.IGNORECASE)
        if n_selected and int(n_selected[0]) > 0:
            print(
                f"  [WARN] Slip not empty after clear: "
                f"{n_selected[0]} players still selected"
            )
            clear_slip(frame)
            frame.wait_for_timeout(1000)
            text2 = frame.evaluate("() => document.body.innerText")
            n_selected2 = re.findall(r"(\d+)\s*Players?\s*Selected", text2, re.IGNORECASE)
            if n_selected2 and int(n_selected2[0]) > 0:
                print("  [WARN] Slip still not empty after retry; reconnecting frame")
                if page is not None:
                    try:
                        frame = find_prizepicks_frame(page)
                        ensure_popular_filter(frame, page)
                        dismiss_modal(frame, page)
                    except Exception as e:
                        print(f"  [WARN] Frame reconnect failed: {e}")
                return False, frame
        return True, frame
    except Exception:
        return True, frame


def soft_reset(frame, page):
    """Clear slip and re-verify frame without page reload."""
    try:
        clear_slip(frame)
        frame.wait_for_timeout(500)
        text = frame.evaluate("() => document.body.innerText")
        if "Points" in text or "More" in text:
            return frame
    except Exception:
        pass
    frame = find_prizepicks_frame(page)
    ensure_popular_filter(frame, page)
    dismiss_modal(frame, page)
    return frame


MIN_SAMPLES = {
    "all_standard": 8,
    "has_goblin": 10,
    "has_demon": 5,
    "flex": 5,
}


def dismiss_modal(frame, page) -> bool:
    dismissed = False
    try:
        for sel in [".MuiBackdrop-root", "[class*='MuiBackdrop']"]:
            bd = frame.locator(sel).first
            if bd.count() > 0:
                try:
                    bd.click(force=True, timeout=600)
                    frame.wait_for_timeout(400)
                    print("[MODAL] Dismissed backdrop (force)")
                    dismissed = True
                except Exception:
                    pass
    except Exception:
        pass
    try:
        backdrop = frame.locator(
            "[class*='MuiBackdrop'], [class*='backdrop'], "
            "[class*='modal'], [class*='Modal'], "
            "[class*='overlay'], [class*='Overlay']"
        ).first
        if backdrop.count() > 0 and backdrop.is_visible():
            backdrop.click(force=True, timeout=800)
            frame.wait_for_timeout(500)
            print("[MODAL] Dismissed backdrop")
            dismissed = True
    except Exception:
        pass
    try:
        for _ in range(2):
            page.keyboard.press("Escape")
            frame.wait_for_timeout(200)
    except Exception:
        pass
    for label in ["Close", "Got it", "OK", "Dismiss", "×", "✕"]:
        try:
            loc = frame.get_by_text(label, exact=True).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=600)
                frame.wait_for_timeout(300)
                print(f"[MODAL] Dismissed via '{label}' button")
                return True
        except Exception:
            continue
    return dismissed


def _card_unique_key(c: dict) -> str:
    return (
        f"{_norm(c.get('player'))}|{_norm(c.get('prop_type'))}|"
        f"{_line_key(c.get('line'))}|{c.get('pick_type', '')}"
    )


def _is_valid_board_card(c: dict) -> bool:
    p = str(c.get("player", "") or "")
    if len(p) < 2 or len(p) > 55:
        return False
    if _GAME_CLOCK_RE.match(p.strip()) or _PERIOD_LABEL_RE.match(p.strip()):
        return False
    lo = p.lower()
    if any(
        x in lo
        for x in (
            "learn more",
            "help center",
            "how to play",
            "scoring chart",
            "current lineup",
            "players selected",
            "picks must be",
            "refresh board",
        )
    ):
        return False
    if "demons & goblins" in lo and "indicate" in lo:
        return False
    raw = str(c.get("raw_text") or "").lower()
    if raw and any(
        x in raw
        for x in (
            "current lineup",
            "players selected",
            "picks must be from at least",
        )
    ):
        return False
    return True


def expand_card_pool(frame, page) -> list[dict]:
    all_cards: list[dict] = []
    seen: set[str] = set()
    for _ in range(3):
        dismiss_modal(frame, page)
        frame.wait_for_timeout(150)
    filters = [
        "Popular",
        "Hits",
        "Total Bases",
        "Home Runs",
        "Pitcher Strikeouts",
        "Hitter Fantasy Score",
        "Hits-Runs-RBIs",
        "Points",
        "Assists",
        "Rebounds",
        "3-PT Made",
        "Pts+Rebs",
        "Pts+Asts",
        "Reb+Asts",
        "Pts+Reb+Ast",
        "Steals",
        "Blocks",
        "Turnovers",
        "Fantasy Score",
    ]
    for filter_name in filters:
        try:
            dismiss_modal(frame, page)
            loc = frame.get_by_text(filter_name, exact=True).first
            if loc.count() == 0:
                loc = frame.get_by_text(filter_name, exact=False).first
            loc.click(force=True, timeout=1500)
            frame.wait_for_timeout(800)
            _scroll_board_for_lazy_load(page)
            cards = get_all_cards(frame)
            new = 0
            gobs = dens = 0
            for c in cards:
                if not _is_valid_board_card(c):
                    continue
                k = _card_unique_key(c)
                if k in seen:
                    continue
                seen.add(k)
                c2 = dict(c)
                c2["source_filter"] = filter_name
                all_cards.append(c2)
                new += 1
                if c2.get("pick_type") == "goblin":
                    gobs += 1
                elif c2.get("pick_type") == "demon":
                    dens += 1
            print(f"[FILTER] {filter_name}: +{new} unique cards ({gobs} goblins, {dens} demons)")
        except Exception as e:
            print(f"[FILTER] {filter_name}: skip ({e})")
    try:
        dismiss_modal(frame, page)
        loc = frame.get_by_text("Points", exact=True).first
        if loc.count() == 0:
            loc = frame.get_by_text("Points", exact=False).first
        loc.click(force=True, timeout=1500)
        frame.wait_for_timeout(500)
    except Exception:
        pass
    if not all_cards:
        dismiss_modal(frame, page)
        _scroll_board_for_lazy_load(page)
        for c in get_all_cards(frame):
            if not _is_valid_board_card(c):
                continue
            k = _card_unique_key(c)
            if k in seen:
                continue
            seen.add(k)
            c2 = dict(c)
            c2.setdefault("source_filter", "Points")
            all_cards.append(c2)
        print("[POOL] expand_card_pool fallback: using single-view get_all_cards")
    print(f"[POOL] Total expanded: {len(all_cards)} cards")
    print(f"  Standard: {sum(1 for c in all_cards if c['pick_type'] == 'standard')}")
    print(f"  Goblin:   {sum(1 for c in all_cards if c['pick_type'] == 'goblin')}")
    print(f"  Demon:    {sum(1 for c in all_cards if c['pick_type'] == 'demon')}")
    return all_cards


def resolve_leg_card(template: dict, fresh: list[dict]) -> dict | None:
    nt = _norm(template.get("player"))
    nl = _line_key(template.get("line"))
    np = _norm(template.get("prop_type"))
    pt = template.get("pick_type")
    for c in fresh:
        if _norm(c.get("player")) != nt:
            continue
        if _line_key(c.get("line")) != nl:
            continue
        if _norm(c.get("prop_type")) != np:
            continue
        if c.get("pick_type") != pt:
            continue
        return c
    for c in fresh:
        if nt not in _norm(c.get("player")) and _norm(c.get("player")) not in nt:
            continue
        if _line_key(c.get("line")) != nl:
            continue
        if c.get("pick_type") != pt:
            continue
        return c
    # Fallback for cards with arrow-based alternate lines where visible line
    # can differ from the template despite same player/prop/pick_type.
    for c in fresh:
        if nt not in _norm(c.get("player")) and _norm(c.get("player")) not in nt:
            continue
        if _norm(c.get("prop_type")) != np:
            continue
        if c.get("pick_type") != pt:
            continue
        return c
    return None


def click_case_legs_with_filter_switches(
    frame, page, tc: dict
) -> bool:
    """Switch stat filters as needed so each leg's More button is in the live DOM."""
    current_tab = None
    for leg in tc["legs"]:
        tab = str(leg["card"].get("source_filter") or "Popular")
        if tab != current_tab:
            try:
                dismiss_modal(frame, page)
                tloc = frame.get_by_text(tab, exact=True).first
                if tloc.count() == 0:
                    tloc = frame.get_by_text(tab, exact=False).first
                tloc.click(force=True, timeout=1500)
                frame.wait_for_timeout(800)
                _scroll_board_for_lazy_load(page)
            except Exception as e:
                print(f"[FILTER] Could not switch to {tab}: {e}")
                return False
            current_tab = tab
        dismiss_modal(frame, page)
        fresh = get_all_cards(frame)
        resolved = resolve_leg_card(leg["card"], fresh)
        if resolved is None:
            fresh = get_all_cards(frame)
            resolved = resolve_leg_card(leg["card"], fresh)
        if resolved is None:
            print(f"[CLICK] Could not resolve card for {leg['card'].get('player')}")
            return False
        if not click_leg(frame, resolved, leg["direction"]):
            return False
        frame.wait_for_timeout(300)
    return True


def case_target_buckets(tc: dict) -> set[str]:
    buckets: set[str] = set()
    if tc["ticket_type"] == "flex":
        buckets.add("flex")
    n_g = sum(1 for l in tc["legs"] if l["card"]["pick_type"] == "goblin")
    n_d = sum(1 for l in tc["legs"] if l["card"]["pick_type"] == "demon")
    if n_g > 0:
        buckets.add("has_goblin")
    elif n_d > 0:
        buckets.add("has_demon")
    else:
        buckets.add("all_standard")
    return buckets


def bucket_needs_fill(
    bucket: str,
    counts: dict[str, int],
    goblins_avail: bool,
    demons_avail: bool,
) -> bool:
    if bucket == "has_goblin" and not goblins_avail:
        return False
    if bucket == "has_demon" and not demons_avail:
        return False
    return counts[bucket] < MIN_SAMPLES[bucket]


def all_targets_met(
    counts: dict[str, int],
    goblins_avail: bool,
    demons_avail: bool,
) -> bool:
    if counts["all_standard"] < MIN_SAMPLES["all_standard"]:
        return False
    if counts["flex"] < MIN_SAMPLES["flex"]:
        return False
    if goblins_avail and counts["has_goblin"] < MIN_SAMPLES["has_goblin"]:
        return False
    if demons_avail and counts["has_demon"] < MIN_SAMPLES["has_demon"]:
        return False
    return True


def bump_counts_from_record(counts: dict[str, int], rec: dict) -> None:
    if str(rec.get("ticket_type", "")).lower() == "flex":
        counts["flex"] += 1
    n_g = int(rec.get("n_goblins", 0) or 0)
    n_d = int(rec.get("n_demons", 0) or 0)
    if n_g > 0:
        counts["has_goblin"] += 1
    elif n_d > 0:
        counts["has_demon"] += 1
    else:
        counts["all_standard"] += 1


def pick_next_test_case(
    cases: list[dict],
    counts: dict[str, int],
    cases_run: int,
    goblins_avail: bool,
    demons_avail: bool,
) -> dict | None:
    if not cases:
        return None
    # Prioritize scarce buckets first so goblin/demon evidence appears early.
    # This avoids long front-loading of all-standard cases.
    priority_weight = {
        "has_demon": 6.0,
        "has_goblin": 4.0,
        "flex": 2.0,
        "all_standard": 1.0,
    }
    best_tc = None
    best_score = -1.0
    for tc in cases:
        buckets = case_target_buckets(tc)
        score = 0.0
        needed_any = False
        for b in buckets:
            if not bucket_needs_fill(b, counts, goblins_avail, demons_avail):
                continue
            needed_any = True
            remain = max(0, MIN_SAMPLES[b] - counts[b])
            score += priority_weight.get(b, 1.0) * float(remain)
        if needed_any and score > best_score:
            best_score = score
            best_tc = tc
    if best_tc is not None:
        return best_tc
    return cases[cases_run % len(cases)]


def build_payout_test_matrix(
    standard: list[dict],
    goblins: list[dict],
    demons: list[dict],
    std_line_map: dict[tuple[str, str], float] | None = None,
) -> list[dict]:
    std_line_map = std_line_map or {}
    std_anchor_keys = {
        (_norm(c.get("player")), _norm(c.get("prop_type")))
        for c in standard
    }

    def _rank_pool(pool: list[dict], require_anchor: bool = False) -> list[dict]:
        return sorted(
            [
                c
                for c in pool
                if not require_anchor
                or (_norm(c.get("player")), _norm(c.get("prop_type"))) in std_anchor_keys
            ],
            key=lambda c: (
                # Prefer cards with known standard anchor in current board slate.
                0
                if (_norm(c.get("player")), _norm(c.get("prop_type"))) in std_anchor_keys
                else 1,
                # Prefer larger line delta vs mapped standard line from step outputs.
                -abs(
                    float(c.get("line"))
                    - float(
                        std_line_map.get(
                            (_norm(c.get("player")), _norm(c.get("prop_type"))),
                            c.get("line"),
                        )
                    )
                ),
                0 if c.get("has_alt_lines") else 1,
                _norm(c.get("player")),
                _norm(c.get("prop_type")),
            ),
        )

    def _pick_unique(
        pool: list[dict],
        n: int,
        used_players: set[str],
        require_anchor: bool = False,
    ) -> list[dict] | None:
        out: list[dict] = []
        for c in _rank_pool(pool, require_anchor=require_anchor):
            player_k = _norm(c.get("player"))
            if not player_k or player_k in used_players:
                continue
            used_players.add(player_k)
            out.append(c)
            if len(out) == n:
                return out
        return None

    def _build_case(n_legs: int, n_gob: int, n_dem: int) -> list[dict] | None:
        n_std = n_legs - n_gob - n_dem
        if n_std < 0:
            return None
        used_players: set[str] = set()
        pick_g = (
            _pick_unique(goblins, n_gob, used_players, require_anchor=True)
            if n_gob > 0
            else []
        )
        if n_gob > 0 and not pick_g:
            return None
        pick_d = (
            _pick_unique(demons, n_dem, used_players, require_anchor=True)
            if n_dem > 0
            else []
        )
        if n_dem > 0 and not pick_d:
            return None
        pick_s = _pick_unique(standard, n_std, used_players) if n_std > 0 else []
        if n_std > 0 and not pick_s:
            return None
        combo = (pick_g or []) + (pick_d or []) + (pick_s or [])
        return combo if len(combo) == n_legs else None

    cases: list[dict] = []
    priority_specs: list[tuple[str, int, int, int, str]] = [
        ("power", 3, 0, 0, "3-leg all-power standard"),
        ("power", 3, 1, 0, "3-leg 1gob-power 2std"),
        ("power", 3, 2, 0, "3-leg 2gob-power 1std"),
        ("power", 4, 0, 0, "4-leg all-power standard"),
        ("power", 4, 1, 0, "4-leg 1gob-power 3std"),
        ("power", 4, 2, 0, "4-leg 2gob-power 2std"),
        ("flex", 3, 0, 0, "3-leg all-flex standard"),
        ("flex", 3, 1, 0, "3-leg 1gob-flex 2std"),
    ]
    fallback_specs: list[tuple[str, int, int, int, str]] = [
        ("power", 2, 0, 0, "2-leg all-power standard"),
        ("power", 2, 1, 0, "2-leg 1gob-power 1std"),
        ("power", 2, 2, 0, "2-leg 2gob-power 0std"),
        ("flex", 2, 0, 0, "2-leg all-flex standard"),
        ("flex", 2, 1, 0, "2-leg 1gob-flex 1std"),
        ("flex", 2, 2, 0, "2-leg 2gob-flex 0std"),
        ("power", 5, 0, 0, "5-leg all-power standard"),
        ("flex", 4, 0, 0, "4-leg all-flex standard"),
        ("flex", 4, 1, 0, "4-leg 1gob-flex 3std"),
        ("flex", 4, 2, 0, "4-leg 2gob-flex 2std"),
        ("flex", 5, 0, 0, "5-leg all-flex standard"),
    ]
    all_specs = priority_specs + fallback_specs
    for ticket_type, n_legs, n_gob, n_dem, label in all_specs:
        combo = _build_case(n_legs=n_legs, n_gob=n_gob, n_dem=n_dem)
        if combo:
            cases.append(
                {
                    "legs": [{"card": c, "direction": "OVER"} for c in combo],
                    "ticket_type": ticket_type,
                    "label": label,
                }
            )
    return cases


def set_ticket_type(frame, ticket_type: str):
    if ticket_type == "flex":
        labels = ["Flex Play", "Flex", "Flex entry"]
    else:
        labels = ["Power Play", "Power", "Power entry"]
    for t in labels:
        try:
            b = frame.get_by_text(t, exact=False).first
            if b.count() > 0:
                b.click(timeout=800)
                frame.wait_for_timeout(150)
                return
        except Exception:
            continue


def add_leg(
    frame, page, leg: dict, *, strict_lines: bool = False, require_line: bool | None = None
) -> bool:
    global _LOOKUP_DIAG_PRINTED
    if require_line is None:
        require_line = bool(strict_lines)
    player = leg["player"]
    prop = leg["prop_type"]
    direction = str(leg["direction"]).upper()
    pick_type = str(leg.get("pick_type") or "standard").strip().lower()
    if pick_type not in ("goblin", "demon", "standard"):
        pick_type = "standard"
    line = leg.get("line")
    try:
        ensure_popular_filter(frame, page)
        tab = prop_type_to_board_filter(prop)
        _switch_board_filter(frame, page, tab)
        dismiss_modal(frame, page)
        _scroll_board_for_lazy_load(page)

        visible_players, best_sel, sel_counts = _collect_visible_players(frame)
        if not _LOOKUP_DIAG_PRINTED:
            print("[LOOKUP] Card selector counts:")
            for sel, n in sel_counts.items():
                print(f"  {sel}: {n}")
            print(f"[LOOKUP] Using selector: {best_sel or '(none)'}")
            print("[LOOKUP] First 5 visible players:")
            for nm in visible_players[:5]:
                print(f"  - {nm}")
            _LOOKUP_DIAG_PRINTED = True

        print(
            f"[LOOKUP] Target player={player} prop={prop} line={line} "
            f"pick={pick_type} dir={direction} tab={tab} "
            f"strict={strict_lines} require_line={require_line}"
        )

        cards = get_all_cards(frame)
        target = _resolve_ticket_leg_card(
            player,
            prop,
            line,
            pick_type,
            cards,
            strict=strict_lines,
            require_line=require_line,
        )

        # If we landed on the right badge but wrong line, cycle the dual-arrow swap.
        if (
            target is not None
            and pick_type in ("goblin", "demon", "standard")
            and line is not None
            and str(line).strip() != ""
            and _line_key(target.get("line")) != _line_key(line)
            and (target.get("has_alt_lines") or pick_type in ("goblin", "demon"))
            and target.get("more_btn") is not None
        ):
            print(
                f"[ALT] refining line {target.get('line')} -> {line} "
                f"on {target.get('player')} ({target.get('pick_type')})"
            )
            cycled = cycle_card_to_pick_type(
                frame,
                target["more_btn"],
                player=player,
                prop=prop,
                want_pick=pick_type,
                want_line=line,
                require_line=True,
                max_clicks=14,
            )
            cards = get_all_cards(frame)
            refined = _resolve_ticket_leg_card(
                player,
                prop,
                line,
                pick_type,
                cards,
                strict=strict_lines,
                require_line=True,
            )
            if refined is not None:
                target = refined
            elif cycled and cycled.get("more_btn") is not None:
                target = {
                    "player": player,
                    "prop_type": prop,
                    "line": cycled.get("line"),
                    "pick_type": pick_type,
                    "more_btn": cycled["more_btn"],
                    "has_alt_lines": True,
                }

        # Goblin/Demon often live behind the dual-arrow swap on the Standard card.
        # Also cycle back to Standard when a prior slip left the face on Goblin/Demon.
        if target is None and pick_type in ("goblin", "demon", "standard"):
            sibling = None
            if pick_type in ("goblin", "demon"):
                sibling = _resolve_ticket_leg_card(
                    player,
                    prop,
                    None,
                    "standard",
                    cards,
                    strict=False,
                    require_line=False,
                )
            if sibling is None:
                # Any same player+prop face card (already cycled or wrong badge).
                for c in cards:
                    if _norm(player) not in _norm(c.get("player")) and _norm(
                        c.get("player")
                    ) not in _norm(player):
                        continue
                    cp = _norm(c.get("prop_type"))
                    np = _norm(prop)
                    if np and not (np == cp or np in cp or cp in np):
                        continue
                    sibling = c
                    break
            if sibling is not None and sibling.get("more_btn") is not None:
                print(
                    f"[ALT] cycling swap on {sibling.get('player')} "
                    f"{sibling.get('prop_type')} {sibling.get('line')} "
                    f"({sibling.get('pick_type')}) -> want {pick_type} {line}"
                )
                cycled = cycle_card_to_pick_type(
                    frame,
                    sibling["more_btn"],
                    player=player,
                    prop=prop,
                    want_pick=pick_type,
                    want_line=line,
                    require_line=bool(require_line),
                    max_clicks=14,
                )
                cards = get_all_cards(frame)
                target = _resolve_ticket_leg_card(
                    player,
                    prop,
                    line if require_line else (cycled.get("line") if cycled else line),
                    pick_type,
                    cards,
                    strict=strict_lines,
                    require_line=require_line,
                )
                if target is None and cycled and cycled.get("more_btn") is not None:
                    # Build a synthetic target from the cycled face.
                    target = {
                        "player": player,
                        "prop_type": prop,
                        "line": cycled.get("line"),
                        "pick_type": pick_type,
                        "more_btn": cycled["more_btn"],
                        "has_alt_lines": True,
                    }

        if target is None:
            # Hidden Search input often exists but does not filter; still try force-fill.
            for sel in [
                "input[placeholder*='Search']",
                "input[type='search']",
                "input[aria-label*='Search']",
                "input[aria-label='search']",
            ]:
                box = frame.locator(sel).first
                if box.count() == 0:
                    continue
                try:
                    print(f"[LOOKUP] Using search selector: {sel}")
                    box.click(force=True, timeout=800)
                    box.fill(player, force=True, timeout=1200)
                    try:
                        box.press("Enter", timeout=500)
                    except Exception:
                        pass
                    page.wait_for_timeout(400)
                    break
                except Exception:
                    continue
            _scroll_board_for_lazy_load(page)
            cards = get_all_cards(frame)
            target = _resolve_ticket_leg_card(
                player,
                prop,
                line,
                pick_type,
                cards,
                strict=strict_lines,
                require_line=require_line,
            )

        # Fuzzy name click skips line/pick checks — never use in strict mode.
        if target is None and visible_players and not strict_lines:
            match = get_close_matches(player, visible_players, n=1, cutoff=0.7)
            if match:
                print(f"[LOOKUP] Fuzzy matched '{player}' -> '{match[0]}'")
                if _click_player_direction(frame, match[0], direction, prop):
                    return True

        if target is not None:
            print(
                f"[LOOKUP] Resolved {target.get('player')} "
                f"{target.get('prop_type')} {target.get('line')} "
                f"({target.get('pick_type')})"
            )
            if click_leg(frame, target, direction):
                return True

        # Last resort name-click also skips line checks — skip when strict.
        if not strict_lines:
            try:
                ploc = frame.get_by_text(str(player), exact=False).first
                if ploc.count() > 0:
                    ploc.scroll_into_view_if_needed(timeout=1500)
                    ok = ploc.evaluate(
                        """
                        (el, direction) => {
                          let p = el;
                          for (let i = 0; i < 12; i++) {
                            p = p ? p.parentElement : null;
                            if (!p) break;
                            const t = (p.innerText || '');
                            if (!/\\bMore\\b/.test(t)) continue;
                            const btns = p.querySelectorAll('button, [role="button"], div, span');
                            const want = (direction || 'OVER').toUpperCase() === 'UNDER' ? 'Less' : 'More';
                            for (const b of btns) {
                              if ((b.innerText || '').trim() === want) {
                                b.click();
                                return true;
                              }
                            }
                          }
                          return false;
                        }
                        """,
                        direction,
                    )
                    if ok:
                        frame.wait_for_timeout(400)
                        return True
            except Exception as e:
                print(f"[LOOKUP] name-click fallback failed: {e}")

        print(f"[PAYOUT] SKIP: {player} not found on board")
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            shot = DEBUG_DIR / f"lookup_fail_{_safe_name(player)}_{ts}.png"
            page.screenshot(path=str(shot), full_page=True)
            print(f"[LOOKUP] Failure screenshot saved: {shot}")
        except Exception as se:
            print(f"[LOOKUP] Screenshot failed: {se}")
        return False
    except Exception as e:
        print(f"[PAYOUT] SKIP: {player} not found on board ({e})")
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            shot = DEBUG_DIR / f"lookup_fail_{_safe_name(player)}_{ts}.png"
            page.screenshot(path=str(shot), full_page=True)
            print(f"[LOOKUP] Failure screenshot saved: {shot}")
        except Exception:
            pass
        return False


def read_payout_from_dom(frame) -> tuple[float | None, float | None, float | None]:
    # Returns (displayed_multiplier, flex_first_place, flex_miss_1)
    displayed = None
    for sel in [
        "[data-testid='multiplier']",
        "[data-testid='payout-multiplier']",
        ".payout .multiplier",
        ".entry-payout",
    ]:
        try:
            txt = frame.locator(sel).first.inner_text(timeout=600)
            m = re.search(r"(\d+(?:\.\d+)?)\s*x", txt.lower())
            if m:
                displayed = float(m.group(1))
                break
        except Exception:
            continue
    if displayed is None:
        try:
            t = frame.locator("text=/\\d+\\.?\\d*x/i").first
            if t.count() > 0:
                m = re.search(r"(\d+(?:\.\d+)?)\s*x", t.inner_text(timeout=600).lower())
                if m:
                    displayed = float(m.group(1))
        except Exception:
            pass

    flex_first = None
    flex_miss1 = None
    try:
        txt = frame.content()
        m1 = re.search(r"1st\s*place\s*pays[^0-9]*(\d+(?:\.\d+)?)\s*x", txt, flags=re.I)
        if m1:
            flex_first = float(m1.group(1))
        m2 = re.search(r"(?:\d+\s*out\s*of\s*\d+|miss\s*1)[^0-9]*(\d+(?:\.\d+)?)\s*x", txt, flags=re.I)
        if m2:
            flex_miss1 = float(m2.group(1))
    except Exception:
        pass
    try:
        slip_text = frame.evaluate(
            """
            () => {
              const all = document.querySelectorAll('*');
              for (const el of all) {
                const t = (el.innerText || '').trim();
                if (t.includes('To Win') && t.length < 200) return t;
              }
              return null;
            }
            """
        )
        print(f"[LOOKUP] Slip panel text: {slip_text}")
    except Exception:
        pass
    try:
        mult_candidates = frame.evaluate(
            """
            () => {
              const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              const out = [];
              let node;
              while (node = walker.nextNode()) {
                const t = (node.textContent || '').trim();
                if (/^\\d+\\.?\\d*x$/.test(t)) out.push(t);
              }
              return out.slice(0, 20);
            }
            """
        )
        print(f"[LOOKUP] Multiplier candidates: {mult_candidates}")
    except Exception:
        pass
    return displayed, flex_first, flex_miss1


def read_to_win_amount(frame) -> float | None:
    try:
        txt = frame.content()
        m = re.search(r"to\s*win[^0-9$]*\$?\s*([0-9][0-9,]*(?:\.\d+)?)", txt, flags=re.I)
        if m:
            return float(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


# Primary payout multipliers on PrizePicks are within this band; filters bad DOM parses.
# Goblin 2-legs routinely print Min Guarantee in the 1.3–1.9x band near tip;
# do not treat those as parse noise.
_SLIP_MULT_MIN = 1.0
_SLIP_MULT_MAX = 40.0
# Power Play standard payouts (pick multipliers near these when in Power mode).
_SLIP_BASE_BY_LEGS = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5}
# Flex "1st place pays" is often lower than Power for the same leg count — avoid
# matching Flex panel 3X when building a Power slip (same DOM slice).
_SLIP_FLEX_FIRST_BASE = {2: 3.0, 3: 3.0, 4: 6.0, 5: 10.0, 6: 20.0}


def read_slip(
    frame,
    n_legs: int | None = None,
    ticket_type: str | None = None,
) -> dict:
    try:
        text = frame.evaluate("() => document.body.innerText")
        slip_start = text.find("Current Lineup")
        if slip_start == -1:
            slip_start = text.find("Players Selected")
        if slip_start == -1:
            slip_start = text.find("Power Play")
        slip_section = text[slip_start : slip_start + 1800] if slip_start >= 0 else ""
        if slip_start >= 0:
            print("[SLIP RAW] Slip section:")
            print(slip_section[:1200])
            print("---")

        multipliers: list[str] = []
        multiplier_patterns = [
            r"(\d+\.?\d*)\s*x\b",
            r"(\d+\.?\d*)[Xx]",
            r"payout[:\s]+\$?(\d+\.?\d*)",
            r"win[s]?[:\s]+\$?(\d+\.?\d*)",
            r"\$(\d+\.?\d*)\s*prize",
            r"(\d+\.?\d*)\s*times",
        ]
        for pat in multiplier_patterns:
            found = re.findall(pat, slip_section, re.IGNORECASE)
            if found:
                print(f"[SLIP REGEX] Pattern '{pat}' found: {found}")
                for v in found:
                    sv = str(v).strip()
                    if sv:
                        multipliers.append(sv)
        multipliers = list(dict.fromkeys(multipliers))

        valid_mults: list[str] = []
        for m in multipliers:
            try:
                v = float(m)
                if _SLIP_MULT_MIN <= v <= _SLIP_MULT_MAX:
                    valid_mults.append(m)
            except (TypeError, ValueError):
                pass
        multipliers = valid_mults

        to_win_hits: list[str] = []
        to_win_patterns = [
            r"To\s*Win[\s\n]*\$?(\d+\.?\d+)",
            r"to\s*win[:\s\n]*\$?(\d+\.?\d+)",
            r"You\s*win[:\s\n]*\$?(\d+\.?\d+)",
            r"Prize[:\s\n]*\$?(\d+\.?\d+)",
            r"Payout[:\s\n]*\$?(\d+\.?\d+)",
            r"\$(\d+\.\d{2})",
        ]
        for pat in to_win_patterns:
            found = re.findall(pat, slip_section, re.IGNORECASE)
            if found:
                print(f"[SLIP REGEX] ToWin pattern '{pat}' found: {found}")
                for v in found:
                    sv = str(v).strip()
                    if sv:
                        to_win_hits.append(sv)
        to_win_clean = []
        for v in list(dict.fromkeys(to_win_hits)):
            try:
                fv = float(v)
                if fv > 0:
                    to_win_clean.append(fv)
            except Exception:
                continue
        to_win_num = to_win_clean[0] if to_win_clean else None

        n_selected = re.findall(r"(\d+)\s*Players?\s*Selected", slip_section, re.IGNORECASE)
        n_selected_int = int(n_selected[0]) if n_selected else None
        first_place = re.findall(
            r"1st\s*place\s*pays[\s\n]*(\d+\.?\d*)[Xx]",
            slip_section,
            re.IGNORECASE,
        )
        correct_pays = re.findall(
            r"(\d+)\s*correct\s*pays[\s\n]*(\d+\.?\d*)[Xx]",
            slip_section,
            re.IGNORECASE,
        )

        entry_amt: list[str] = []
        entry_patterns = [
            r"Entry[:\s\n]*\$?(\d+\.?\d+)",
            r"Entry\s*Fee[:\s\n]*\$?(\d+\.?\d+)",
            r"Wager[:\s\n]*\$?(\d+\.?\d+)",
        ]
        for pat in entry_patterns:
            found = re.findall(pat, slip_section, re.IGNORECASE)
            if found:
                print(f"[SLIP REGEX] Entry pattern '{pat}' found: {found}")
                for v in found:
                    sv = str(v).strip()
                    if sv:
                        entry_amt.append(sv)
        entry_amt = list(dict.fromkeys(entry_amt))
        entry_num = float(entry_amt[0]) if entry_amt else 10.0
        computed_mult = None
        if to_win_num is not None and entry_num > 0:
            computed_mult = round(to_win_num / entry_num, 3)
            print(f"[SLIP] Computed mult from towin/entry: {computed_mult}x")

        displayed_multiplier = None
        if multipliers:
            legs_for_base = n_legs if n_legs is not None else n_selected_int
            tt = str(ticket_type or "power").lower().strip()
            base_map = _SLIP_FLEX_FIRST_BASE if tt == "flex" else _SLIP_BASE_BY_LEGS
            base = (
                base_map.get(int(legs_for_base), 6.0)
                if legs_for_base is not None
                else 6.0
            )
            try:
                pick = min(multipliers, key=lambda x: abs(float(x) - base))
                displayed_multiplier = float(pick)
            except (TypeError, ValueError):
                displayed_multiplier = None
        if displayed_multiplier is None and computed_mult is not None:
            if _SLIP_MULT_MIN <= float(computed_mult) <= _SLIP_MULT_MAX:
                displayed_multiplier = computed_mult

        first_place_val = float(first_place[0]) if first_place else None
        min_guarantee_val = float(correct_pays[-1][1]) if correct_pays else None
        min_guarantee_hits_required = int(correct_pays[-1][0]) if correct_pays else None
        flex_first_val = first_place_val
        if flex_first_val is not None and not (
            _SLIP_MULT_MIN <= flex_first_val <= _SLIP_MULT_MAX
        ):
            flex_first_val = None
        if min_guarantee_val is not None and not (
            _SLIP_MULT_MIN <= min_guarantee_val <= _SLIP_MULT_MAX
        ):
            min_guarantee_val = None

        slip = {
            "multipliers": multipliers,
            "displayed_multiplier": displayed_multiplier,
            "to_win": to_win_num,
            "n_selected": n_selected_int,
            "first_place_payout": first_place_val,
            "min_guarantee_payout": min_guarantee_val,
            "min_guarantee_hits_required": min_guarantee_hits_required,
            "flex_first_place": flex_first_val,
            "flex_correct_pays": correct_pays,
            "flex_miss_1": correct_pays,
            "entry_amount": entry_num,
            "computed_multiplier": computed_mult,
            "has_slip": slip_start >= 0,
            "raw_slip_section": slip_section[:1200],
        }
        if slip["has_slip"]:
            print(
                f"[SLIP] n={slip['n_selected']} | mult={slip['multipliers']} | "
                f"displayed={slip['displayed_multiplier']} | towin={slip['to_win']} | "
                f"first={slip['first_place_payout']} | min_g={slip['min_guarantee_payout']}"
            )
        return slip
    except Exception as e:
        print(f"[SLIP] Read error: {e}")
        return {}


def is_valid_record(record: dict) -> tuple[bool, str]:
    n = int(pd.to_numeric(record.get("n_legs"), errors="coerce") or 0)
    first = pd.to_numeric(record.get("first_place_payout"), errors="coerce")
    min_g = pd.to_numeric(record.get("min_guarantee_payout"), errors="coerce")
    mult = pd.to_numeric(record.get("displayed_multiplier"), errors="coerce")

    first_v = float(first) if pd.notna(first) else None
    min_g_v = float(min_g) if pd.notna(min_g) else None
    mult_v = float(mult) if pd.notna(mult) else None

    if first_v is None and min_g_v is None and mult_v is None:
        return False, "no payout data"

    if first_v is not None and min_g_v is not None and min_g_v > first_v:
        return False, f"min_g {min_g_v} > first {first_v}"

    max_min_g = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5}
    if min_g_v is not None and n in max_min_g:
        if not (0.3 <= min_g_v <= max_min_g[n]):
            return False, f"min_g {min_g_v} out of range for {n}-leg"

    return True, "ok"


def build_standard_line_map(legs: list[dict]) -> dict[tuple[str, str], float]:
    mp: dict[tuple[str, str], float] = {}
    for leg in legs:
        if "standard" in str(leg.get("pick_type", "")).lower() and leg.get("line") is not None:
            mp[(_norm(leg.get("player")), _norm(leg.get("prop_type")))] = float(leg["line"])
    return mp


def _reclassify_cards_with_std_map(
    cards: list[dict],
    std_line_map: dict[tuple[str, str], float],
) -> tuple[list[dict], int]:
    out: list[dict] = []
    floor_filtered = 0
    for c in cards:
        line_val = float(pd.to_numeric(c.get("line"), errors="coerce") or 0.0)
        if line_val <= 0.5 and c.get("pick_type") != "goblin":
            floor_filtered += 1
            continue
        player_key = _norm(c.get("player"))
        prop_key = _norm(c.get("prop_type"))
        std_line = std_line_map.get((player_key, prop_key))

        inferred = "standard"
        if std_line is not None and std_line > 0:
            if line_val < float(std_line) * 0.7:
                inferred = "goblin"
            elif line_val > float(std_line) * 1.3:
                inferred = "demon"

        final_pick_type = c.get("pick_type", "standard")
        if final_pick_type == "standard" and inferred in ("goblin", "demon"):
            final_pick_type = inferred

        c2 = dict(c)
        c2["pick_type"] = final_pick_type
        c2["standard_line"] = std_line
        c2["line_distance"] = (
            abs(line_val - float(std_line))
            if std_line is not None
            else None
        )
        out.append(c2)
    return out, floor_filtered


def choose_leg_sets(legs: list[dict], ticket_type: str) -> list[list[dict]]:
    # Build requested matrix using today's available props.
    std = [x for x in legs if "standard" in x["pick_type"]]
    gob = [x for x in legs if "goblin" in x["pick_type"]]
    dem = [x for x in legs if "demon" in x["pick_type"]]
    std = sorted(std, key=lambda x: -x.get("blended_score", 0))
    gob = sorted(gob, key=lambda x: -x.get("blended_score", 0))
    dem = sorted(dem, key=lambda x: -x.get("blended_score", 0))

    def _pick(pool: list[dict], n: int, used: set[str]) -> list[dict] | None:
        out = []
        for leg in pool:
            key = str(leg["pp_id"])
            pname = _norm(leg["player"])
            if key in used:
                continue
            if pname in { _norm(x["player"]) for x in out }:
                continue
            out.append(leg)
            used.add(key)
            if len(out) == n:
                return out
        return None

    patterns = [
        ("power", 2, 0, 0),
        ("power", 3, 0, 0),
        ("power", 4, 0, 0),
        ("power", 5, 0, 0),
        ("power", 2, 1, 0),
        ("power", 3, 1, 0),
        ("power", 3, 2, 0),
        ("power", 3, 3, 0),
        ("power", 4, 1, 0),
        ("power", 4, 2, 0),
        ("power", 4, 4, 0),
        ("power", 2, 0, 1),
        ("power", 3, 0, 1),
        ("power", 3, 0, 2),
        ("power", 4, 0, 1),
        ("power", 4, 0, 2),
        ("power", 3, 1, 1),
        ("power", 4, 1, 1),
        ("power", 4, 2, 1),
        ("flex", 2, 0, 0),
        ("flex", 3, 0, 0),
        ("flex", 4, 0, 0),
        ("flex", 2, 1, 0),
        ("flex", 3, 1, 0),
        ("flex", 3, 2, 0),
        ("flex", 4, 1, 0),
        ("flex", 4, 2, 0),
    ]

    selected: list[list[dict]] = []
    for ttype, n_legs, n_g, n_d in patterns:
        if ttype != ticket_type:
            continue
        if n_g > len(gob) or n_d > len(dem):
            continue
        n_s = n_legs - n_g - n_d
        if n_s < 0:
            continue
        used: set[str] = set()
        pick_g = _pick(gob, n_g, used) if n_g > 0 else []
        if n_g > 0 and not pick_g:
            continue
        pick_d = _pick(dem, n_d, used) if n_d > 0 else []
        if n_d > 0 and not pick_d:
            continue
        pick_s = _pick(std, n_s, used) if n_s > 0 else []
        if n_s > 0 and not pick_s:
            continue
        combo = (pick_g or []) + (pick_d or []) + (pick_s or [])
        if len(combo) == n_legs:
            selected.append(combo)
    return selected


def append_rows_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow(r)


DEFAULT_CAPTURE_FIELDS = (
    "power_min_x",
    "power_first_x",
    "min_guarantee",
    "flex_min",
)

# PrizePicks board league_id for ticket-sport navigation (ticket scrape only).
PP_BOARD_LEAGUE_IDS: dict[str, int] = {
    "MLB": 2,
    "WNBA": 3,
    "NBA": 7,
    "NBA1H": 7,
    "NBA1Q": 7,
    "NFL": 9,
    "CFB": 15,
    "CBB": 20,
    "NHL": 8,
    "SOCCER": 82,
    "SOC": 82,
    "TENNIS": 5,
    "GOLF": 6,
}


def _slip_primary_sport(slip: dict) -> str:
    """Dominant sport on a generated slip (from leg.sport)."""
    counts: Counter[str] = Counter()
    for leg in slip.get("legs") or []:
        if not isinstance(leg, dict):
            continue
        sp = str(leg.get("sport") or "").strip().upper()
        if sp:
            counts[sp] += 1
    if not counts:
        return ""
    return counts.most_common(1)[0][0]


def navigate_board_for_sport(page, sport: str, *, settle_ms: int = 2500) -> bool:
    """Open PrizePicks board for the sport of our generated tickets."""
    sp = str(sport or "").strip().upper()
    league_id = PP_BOARD_LEAGUE_IDS.get(sp)
    if league_id is None:
        print(f"[PAYOUT] no board league_id for sport={sp!r} — staying on current board")
        return False
    url = f"https://app.prizepicks.com/board?league_id={league_id}"
    print(f"[PAYOUT] navigate {sp} board -> {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(int(settle_ms))
        return True
    except Exception as e:
        print(f"[PAYOUT] WARN: navigate {sp} failed: {e}")
        return False


def _parse_fields_arg(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return list(DEFAULT_CAPTURE_FIELDS)
    out: list[str] = []
    for part in str(raw).split(","):
        key = part.strip().lower()
        if key and key not in out:
            out.append(key)
    return out or list(DEFAULT_CAPTURE_FIELDS)


def _ticket_already_has_live_cdp(ticket: dict) -> bool:
    pay = ticket.get("payout") if isinstance(ticket.get("payout"), dict) else {}
    src = str(pay.get("payout_source") or ticket.get("payout_source") or "").strip().lower()
    if src != "live_cdp":
        return False
    try:
        min_x = float(pay.get("power_min_x") or pay.get("display_min_x") or ticket.get("display_min_x") or 0)
    except (TypeError, ValueError):
        return False
    return min_x > 0


def load_main_strong_tickets(path: Path, *, only_missing_live: bool = False) -> list[dict]:
    """Load MAIN + STRONG slips from combined_slate_tickets_*.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    slips: list[dict] = []
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        group_name = str(g.get("group_name") or g.get("name") or "")
        for t in g.get("tickets") or []:
            if not isinstance(t, dict):
                continue
            if only_missing_live and _ticket_already_has_live_cdp(t):
                continue
            raw_legs = t.get("legs") or []
            if len(raw_legs) < 2:
                continue
            legs: list[dict] = []
            for leg in raw_legs:
                if not isinstance(leg, dict):
                    continue
                legs.append(
                    {
                        "player": str(leg.get("player") or "").strip(),
                        "prop_type": str(
                            leg.get("prop_type") or leg.get("prop") or ""
                        ).strip(),
                        "direction": str(
                            leg.get("direction") or leg.get("dir") or "OVER"
                        )
                        .strip()
                        .upper(),
                        "line": leg.get("line"),
                        "pick_type": str(
                            leg.get("pick_type") or leg.get("pick") or "Goblin"
                        ).strip(),
                        "sport": str(leg.get("sport") or "").strip().upper(),
                        # Keep Δ fields so ladder live_cdp rows get Goblin distances.
                        "standard_line": leg.get("standard_line") or leg.get("std_line"),
                        "line_distance": leg.get("line_distance") or leg.get("delta"),
                        "delta": leg.get("delta") or leg.get("line_distance"),
                    }
                )
            if len(legs) < 2:
                continue
            is_strong = bool(t.get("strong_builder"))
            slips.append(
                {
                    "ticket_id": str(t.get("ticket_id") or ""),
                    "group_name": group_name,
                    "strong_builder": is_strong,
                    "slip_type": "strong" if is_strong else "main",
                    "n_legs": len(legs),
                    "legs": legs,
                    "date": str(data.get("date") or "")[:10],
                }
            )
    return slips


def _project_capture_fields(rec: dict, fields: list[str]) -> dict:
    """Keep identity + requested payout fields; power_min_x listed first when present."""
    base_keys = (
        "ticket_id",
        "slip_type",
        "strong_builder",
        "group_name",
        "n_legs",
        "legs",
        "status",
        "error",
        "ticket_type_captured",
    )
    out = {k: rec.get(k) for k in base_keys if k in rec}
    if "power_min_x" in fields:
        out["power_min_x"] = rec.get("power_min_x")
    for f in fields:
        if f == "power_min_x":
            continue
        if f in rec:
            out[f] = rec.get(f)
    return out


def _leg_sig_key(legs: list[dict] | None) -> str:
    parts: list[str] = []
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        parts.append(
            "|".join(
                [
                    _norm(leg.get("player")),
                    _norm(leg.get("prop_type") or leg.get("prop")),
                    _norm(leg.get("direction") or leg.get("dir") or "over"),
                    _line_key(leg.get("line")),
                ]
            )
        )
    return "||".join(sorted(p for p in parts if p and p != "|||"))


def main_strong_tickets_fingerprint(tickets_path: Path | str) -> dict[str, Any]:
    """Stable hash of MAIN/STRONG slip identities (ticket_id + leg_sig).

    Used to skip PrizePicks CDP re-scrape when an update run regenerates the same
    ticket set and every slip already has a live min-guarantee floor.
    """
    path = Path(tickets_path)
    if not path.is_file():
        return {
            "fingerprint": "",
            "n_slips": 0,
            "n_missing_live": 0,
            "n_live": 0,
            "tickets_path": str(path),
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[str] = []
    n_live = 0
    n_missing = 0
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        for t in g.get("tickets") or []:
            if not isinstance(t, dict):
                continue
            raw_legs = t.get("legs") if isinstance(t.get("legs"), list) else []
            if len(raw_legs) < 2:
                continue
            tid = str(t.get("ticket_id") or "").strip()
            sig = _leg_sig_key(raw_legs)
            rows.append(f"{tid}\t{sig}")
            if _ticket_already_has_live_cdp(t):
                n_live += 1
            else:
                n_missing += 1
    rows_sorted = sorted(rows)
    digest = hashlib.sha256("\n".join(rows_sorted).encode("utf-8")).hexdigest()
    return {
        "fingerprint": digest,
        "n_slips": len(rows_sorted),
        "n_missing_live": n_missing,
        "n_live": n_live,
        "tickets_path": str(path),
        "date": str(data.get("date") or "")[:10],
    }


def capture_skip_decision(
    tickets_path: Path | str,
    capture_path: Path | str | None = None,
) -> dict[str, Any]:
    """Decide whether a live CDP scrape can be skipped for this ticket set."""
    fp_info = main_strong_tickets_fingerprint(tickets_path)
    prior_fp = ""
    prior_n_ok = 0
    cap = Path(capture_path) if capture_path else None
    if cap is not None and cap.is_file():
        try:
            prior = json.loads(cap.read_text(encoding="utf-8"))
            prior_fp = str(prior.get("tickets_fingerprint") or "").strip()
            summary = prior.get("summary") if isinstance(prior.get("summary"), dict) else {}
            prior_n_ok = int(summary.get("n_ok") or 0)
        except Exception:
            prior_fp = ""
            prior_n_ok = 0
    unchanged = bool(fp_info["fingerprint"]) and fp_info["fingerprint"] == prior_fp
    skip_scrape = bool(
        unchanged
        and int(fp_info.get("n_missing_live") or 0) == 0
        and int(fp_info.get("n_slips") or 0) > 0
    )
    return {
        **fp_info,
        "prior_fingerprint": prior_fp,
        "prior_n_ok": prior_n_ok,
        "unchanged": unchanged,
        "skip_scrape": skip_scrape,
        "reason": (
            "tickets_unchanged_all_live"
            if skip_scrape
            else (
                "missing_live_floors"
                if int(fp_info.get("n_missing_live") or 0) > 0
                else (
                    "tickets_changed"
                    if fp_info["fingerprint"] and fp_info["fingerprint"] != prior_fp
                    else "no_slips_or_no_prior"
                )
            )
        ),
    }


def write_payout_patch_and_apply_to_tickets(
    *,
    tickets_path: Path,
    captured: list[dict],
    date_str: str,
) -> dict[str, Any]:
    """
    Write payout_patch_<date>.json and patch combined_slate_tickets JSON in place.

    Each ok/partial capture with power_min_x sets:
      payout.power_min_x, payout.display_min_x, payout.payout_source='live_cdp'
    Uncaptured tickets keep prior live_cdp when present; otherwise mix-grid / model.
    Never wipe a prior good patch with an empty 0-ok capture.
    """
    date_str = str(date_str or "").strip()[:10]
    reports = ROOT / "data" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    patch_path = reports / f"payout_patch_{date_str or 'unknown'}.json"

    # Start from prior patch so a failed re-scrape cannot erase live floors.
    prior: dict[str, Any] = {}
    if patch_path.is_file():
        try:
            prior = json.loads(patch_path.read_text(encoding="utf-8"))
        except Exception:
            prior = {}
    prior_by_id = (
        prior.get("by_ticket_id") if isinstance(prior.get("by_ticket_id"), dict) else {}
    )
    prior_by_sig = (
        prior.get("by_leg_sig") if isinstance(prior.get("by_leg_sig"), dict) else {}
    )
    # Heal empty patch: seed gaps from any live_cdp already on the tickets file.
    if tickets_path.is_file():
        try:
            data_seed = json.loads(tickets_path.read_text(encoding="utf-8"))
            for g in data_seed.get("groups") or []:
                if not isinstance(g, dict):
                    continue
                for t in g.get("tickets") or []:
                    if not isinstance(t, dict):
                        continue
                    pay = t.get("payout") if isinstance(t.get("payout"), dict) else {}
                    if str(pay.get("payout_source") or "").strip().lower() != "live_cdp":
                        continue
                    try:
                        min_x = float(pay.get("power_min_x") or pay.get("display_min_x") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not (min_x > 0):
                        continue
                    entry = {
                        "power_min_x": min_x,
                        "power_first_x": pay.get("power_first_x"),
                        "display_min_x": min_x,
                        "payout_source": "live_cdp",
                        "ticket_id": t.get("ticket_id"),
                        "n_legs": t.get("n_legs") or len(t.get("legs") or []),
                    }
                    tid = str(t.get("ticket_id") or "").strip()
                    if tid and tid not in prior_by_id:
                        prior_by_id[tid] = entry
                    sig = _leg_sig_key(t.get("legs") if isinstance(t.get("legs"), list) else [])
                    if sig and sig not in prior_by_sig:
                        prior_by_sig[sig] = entry
        except Exception as e:
            print(f"[PAYOUT] WARN: seed from tickets failed ({e})")

    prior_by_id = dict(prior_by_id)
    prior_by_sig = dict(prior_by_sig)

    patch: dict[str, Any] = {
        "date": date_str,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "tickets_path": str(tickets_path),
        "by_ticket_id": dict(prior_by_id),
        "by_leg_sig": dict(prior_by_sig),
    }
    n_new = 0
    for rec in captured:
        if not isinstance(rec, dict):
            continue
        try:
            min_x = float(rec.get("power_min_x"))
        except (TypeError, ValueError):
            continue
        if not (min_x > 0):
            continue
        if str(rec.get("status") or "").lower() not in ("ok", "partial"):
            continue
        entry = {
            "power_min_x": min_x,
            "power_first_x": rec.get("power_first_x"),
            "display_min_x": min_x,
            "payout_source": "live_cdp",
            "ticket_id": rec.get("ticket_id"),
            "n_legs": rec.get("n_legs"),
            "slip_type": rec.get("slip_type"),
        }
        tid = str(rec.get("ticket_id") or "").strip()
        if tid:
            patch["by_ticket_id"][tid] = entry
            n_new += 1
        sig = _leg_sig_key(rec.get("legs") if isinstance(rec.get("legs"), list) else [])
        if sig:
            patch["by_leg_sig"][sig] = entry

    if n_new == 0 and not patch["by_ticket_id"] and prior_by_id:
        # Absolute last resort: keep prior file untouched.
        patch["by_ticket_id"] = dict(prior_by_id)
        patch["by_leg_sig"] = dict(prior_by_sig)
        print(
            f"[PAYOUT] WARN: 0 new live floors; keeping prior patch "
            f"({len(prior_by_id)} ids)"
        )

    patch_path.write_text(json.dumps(patch, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[PAYOUT] patch -> {patch_path} "
        f"(ids={len(patch['by_ticket_id'])} new={n_new})"
    )

    # Mix-grid composition floors (live grid overwrites seeded defaults when present).
    mix_avg = mix_avg_floors_from_grid(
        [
            s
            for s in captured
            if isinstance(s, dict) and str(s.get("status") or "").lower() in ("ok", "partial")
        ]
        or None
    )

    def _goblin_n(legs: list) -> int:
        n = 0
        for leg in legs or []:
            if not isinstance(leg, dict):
                continue
            if "goblin" in str(leg.get("pick_type") or "").lower():
                n += 1
        return n

    n_patched = 0
    n_fallback = 0
    n_kept_live = 0
    if tickets_path.is_file():
        data = json.loads(tickets_path.read_text(encoding="utf-8"))
        for g in data.get("groups") or []:
            if not isinstance(g, dict):
                continue
            for t in g.get("tickets") or []:
                if not isinstance(t, dict):
                    continue
                tid = str(t.get("ticket_id") or "").strip()
                entry = patch["by_ticket_id"].get(tid) if tid else None
                if entry is None:
                    entry = patch["by_leg_sig"].get(_leg_sig_key(t.get("legs")))
                pay = t.get("payout") if isinstance(t.get("payout"), dict) else {}
                pay = dict(pay)
                if pay.get("model_min_payout_x") is None and pay.get("min_payout_x") is not None:
                    pay["model_min_payout_x"] = pay.get("min_payout_x")
                if entry:
                    pay["power_min_x"] = entry["power_min_x"]
                    pay["display_min_x"] = entry["display_min_x"]
                    pay["payout_source"] = "live_cdp"
                    if entry.get("power_first_x") is not None:
                        pay["power_first_x"] = entry["power_first_x"]
                    try:
                        from utils.ticket_ev_tiers import refresh_ticket_ev_from_min_guarantee

                        refresh_ticket_ev_from_min_guarantee(
                            pay, float(entry["display_min_x"]), update_recommendation=False
                        )
                    except Exception:
                        pass
                    t["payout"] = pay
                    t["display_min_x"] = entry["display_min_x"]
                    n_patched += 1
                    continue

                # Do NOT downgrade an existing live_cdp floor to board-avg on miss.
                src_now = str(pay.get("payout_source") or "").strip().lower()
                live_keep = None
                try:
                    live_keep = float(pay.get("power_min_x") or pay.get("display_min_x") or 0)
                except (TypeError, ValueError):
                    live_keep = None
                if src_now == "live_cdp" and live_keep and live_keep > 0:
                    pay["display_min_x"] = float(live_keep)
                    pay["power_min_x"] = float(live_keep)
                    pay["payout_source"] = "live_cdp"
                    try:
                        from utils.ticket_ev_tiers import refresh_ticket_ev_from_min_guarantee

                        refresh_ticket_ev_from_min_guarantee(
                            pay, float(live_keep), update_recommendation=False
                        )
                    except Exception:
                        pass
                    t["payout"] = pay
                    t["display_min_x"] = float(live_keep)
                    n_kept_live += 1
                    continue

                # Uncaptured + no prior live: mix-grid average, else model estimate
                legs = t.get("legs") if isinstance(t.get("legs"), list) else []
                n_legs = len(legs) or int(t.get("n_legs") or 0)
                avg = mix_avg.get((int(n_legs), int(_goblin_n(legs))))
                if avg is not None and float(avg) > 0:
                    pay["display_min_x"] = float(avg)
                    pay["payout_source"] = "mix_grid_average"
                    try:
                        from utils.ticket_ev_tiers import refresh_ticket_ev_from_min_guarantee

                        refresh_ticket_ev_from_min_guarantee(
                            pay, float(avg), update_recommendation=False
                        )
                    except Exception:
                        pass
                    t["payout"] = pay
                    t["display_min_x"] = float(avg)
                    n_fallback += 1
                else:
                    try:
                        model = float(pay.get("min_payout_x") or t.get("power_payout") or 0)
                    except (TypeError, ValueError):
                        model = 0.0
                    if model > 0:
                        pay["display_min_x"] = model
                        pay["payout_source"] = "fallback_estimate"
                        try:
                            from utils.ticket_ev_tiers import refresh_ticket_ev_from_min_guarantee

                            refresh_ticket_ev_from_min_guarantee(
                                pay, float(model), update_recommendation=False
                            )
                        except Exception:
                            pass
                        t["payout"] = pay
                        t["display_min_x"] = model
                        n_fallback += 1
        # Re-tier after EV was recomputed from scraped/fallback min guarantees.
        try:
            from utils.ticket_ev_tiers import apply_slate_ev_tier_recommendations

            apply_slate_ev_tier_recommendations(data, log=False)
        except Exception:
            pass
        tickets_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        sync_tickets_json_mirrors(data, date_str=date_str, primary=tickets_path)
        print(
            f"[PAYOUT] write-back live_cdp={n_patched} kept_live={n_kept_live} "
            f"fallback={n_fallback} in {tickets_path}"
        )

    # Feed /payout Rate cards + ladder table with live Goblin composition floors.
    if captured:
        try:
            merge_live_floors_into_rate_card(
                captured=captured,
                date_str=date_str,
                source="ticket_capture",
            )
            sync_captures_to_payout_ladder_live(
                captured,
                date_str=date_str,
                tickets_path=tickets_path,
                keep_same_date=True,
            )
            rebuild_payout_rate_cards_deck()
        except Exception as e:
            print(f"[PAYOUT] WARN: rate-card / ladder merge failed: {e}")

    return {
        "patch_path": str(patch_path),
        "n_patched": n_patched,
        "n_fallback": n_fallback,
        "n_kept_live": n_kept_live,
        "patch": patch,
    }


def sync_tickets_json_mirrors(
    data: dict[str, Any],
    *,
    date_str: str = "",
    primary: Path | None = None,
) -> None:
    """Keep templates + docs + mobile tickets_latest.json aligned after payout write-back."""
    date_str = str(date_str or data.get("date") or "").strip()[:10]
    body = json.dumps(data, indent=2, ensure_ascii=False)
    mirrors = [
        ROOT / "ui_runner" / "templates" / "tickets_latest.json",
        ROOT / "ui_runner" / "docs" / "tickets_latest.json",
        ROOT / "mobile" / "www" / "tickets_latest.json",
    ]
    for path in mirrors:
        try:
            if primary is not None and path.resolve() == Path(primary).resolve():
                continue
        except Exception:
            pass
        if not path.parent.is_dir() and path.parent.name in ("www", "docs", "templates"):
            path.parent.mkdir(parents=True, exist_ok=True)
        if not path.parent.is_dir():
            continue
        # Only overwrite same-date live files (or empty/missing).
        try:
            if path.is_file():
                existing = json.loads(path.read_text(encoding="utf-8"))
                ex_date = str(existing.get("date") or "")[:10]
                if date_str and ex_date and ex_date != date_str:
                    continue
            path.write_text(body, encoding="utf-8")
            print(f"[PAYOUT] mirrored -> {path}")
        except Exception as e:
            print(f"[PAYOUT] WARN: mirror {path} failed ({e})")


def capture_tickets_from_board(
    *,
    tickets_path: Path,
    output_path: Path,
    fields: list[str],
    cdp_url: str,
    entry_amount: float,
    max_cases: int,
    delay_sec: float,
    write_back: bool = True,
    date_override: str = "",
    strict_lines: bool = True,
    require_line: bool | None = None,
    gentle: bool = False,
    only_missing_live: bool = False,
) -> int:
    """Build each MAIN/STRONG slip on PrizePicks and capture min/first payouts.

    strict_lines (default True): require matching pick_type (Goblin/Demon/Standard).
    require_line defaults to strict_lines; set False to allow board line drift while
    still requiring the badge (used by ladder live-board validation).
    gentle=True: human-paced delays + random cooloff between slips (less DataDome).
    only_missing_live=True: skip slips that already have payout_source=live_cdp.
    """
    if require_line is None:
        require_line = bool(strict_lines)
    if gentle:
        delay_sec = max(float(delay_sec), 2.0)
    slips = load_main_strong_tickets(tickets_path, only_missing_live=only_missing_live)
    fp_info = main_strong_tickets_fingerprint(tickets_path)
    if not slips:
        reason = (
            "missing-live pool empty (all have live_cdp)"
            if only_missing_live
            else "no slips"
        )
        print(f"[PAYOUT] No MAIN/STRONG slips to scrape in {tickets_path} ({reason})")
        date_str = (
            str(date_override or "").strip()[:10]
            or str(fp_info.get("date") or "")[:10]
            or datetime.utcnow().strftime("%Y-%m-%d")
        )
        prior_slips: list[dict] = []
        prior_summary: dict[str, Any] = {}
        if output_path.is_file():
            try:
                prior = json.loads(output_path.read_text(encoding="utf-8"))
                if isinstance(prior.get("slips"), list):
                    prior_slips = [s for s in prior["slips"] if isinstance(s, dict)]
                if isinstance(prior.get("summary"), dict):
                    prior_summary = dict(prior["summary"])
            except Exception:
                prior_slips = []
                prior_summary = {}
        payload = {
            "date": date_str,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "tickets_path": str(tickets_path),
            "tickets_fingerprint": fp_info.get("fingerprint") or "",
            "fingerprint_n_slips": int(fp_info.get("n_slips") or 0),
            "fingerprint_n_missing_live": int(fp_info.get("n_missing_live") or 0),
            "fields": fields,
            "primary_field": "power_min_x",
            "only_missing_live": bool(only_missing_live),
            "slips": prior_slips if only_missing_live else [],
            "summary": {
                "n_ok": int(prior_summary.get("n_ok") or 0) if only_missing_live else 0,
                "n_failed": int(prior_summary.get("n_failed") or 0) if only_missing_live else 0,
                "n_partial": int(prior_summary.get("n_partial") or 0) if only_missing_live else 0,
                "n_total": int(prior_summary.get("n_total") or len(prior_slips))
                if only_missing_live
                else 0,
                "n_skipped_live": int(fp_info.get("n_live") or 0),
                "skipped_reason": reason,
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 0

    slips_sorted = sorted(
        slips,
        key=lambda s: (
            _slip_primary_sport(s) or "ZZZ",
            0 if s.get("strong_builder") else 1,
            s.get("ticket_id") or "",
        ),
    )
    if max_cases > 0:
        slips_sorted = slips_sorted[:max_cases]

    sports_in_run = sorted({_slip_primary_sport(s) for s in slips_sorted if _slip_primary_sport(s)})
    print(
        f"[PAYOUT] scraping {len(slips_sorted)} generated MAIN/STRONG slips only "
        f"(sports={','.join(sports_in_run) or 'unknown'}; "
        f"strict_lines={'on' if strict_lines else 'off'} "
        f"require_line={'on' if require_line else 'off'} "
        f"gentle={'on' if gentle else 'off'} "
        f"only_missing_live={'on' if only_missing_live else 'off'} "
        f"delay={delay_sec:.1f}s)"
    )

    want_flex = "flex_min" in fields
    p, browser, context, page = connect_existing_browser(cdp_url)
    page.wait_for_timeout(1500 if gentle else 500)
    captured: list[dict] = []
    n_ok = n_failed = n_partial = 0
    active_sport = ""

    try:
        # Open the board for the first ticket sport (do not scrape unrelated leagues).
        first_sport = _slip_primary_sport(slips_sorted[0]) if slips_sorted else ""
        if first_sport:
            navigate_board_for_sport(page, first_sport)
            active_sport = first_sport
            if gentle:
                page.wait_for_timeout(int(random.uniform(2000, 4000)))
        frame = find_prizepicks_frame(page)
        ensure_popular_filter(frame, page)
        dismiss_modal(frame, page)

        for i, slip in enumerate(slips_sorted, 1):
            if gentle and i > 1:
                cool = random.uniform(2.5, 5.5)
                print(f"[PAYOUT] gentle cooloff {cool:.1f}s before next slip...")
                page.wait_for_timeout(int(cool * 1000))
            tid = slip.get("ticket_id") or f"slip_{i}"
            slip_sport = _slip_primary_sport(slip)
            if slip_sport and slip_sport != active_sport:
                navigate_board_for_sport(page, slip_sport)
                active_sport = slip_sport
                if gentle:
                    page.wait_for_timeout(int(random.uniform(2500, 4500)))
                frame = find_prizepicks_frame(page)
                ensure_popular_filter(frame, page)
                dismiss_modal(frame, page)
            print(
                f"\n[PAYOUT] ({i}/{len(slips_sorted)}) {slip.get('slip_type')} "
                f"n={slip.get('n_legs')} sport={slip_sport or '?'} id={tid}"
            )
            for leg in slip.get("legs") or []:
                print(
                    f"  leg: {leg.get('player')} {leg.get('prop_type')} "
                    f"{leg.get('direction')} {leg.get('line')} ({leg.get('pick_type')})"
                )

            rec: dict[str, Any] = {
                "ticket_id": tid,
                "slip_type": slip.get("slip_type"),
                "strong_builder": bool(slip.get("strong_builder")),
                "group_name": slip.get("group_name"),
                "n_legs": slip.get("n_legs"),
                "legs": slip.get("legs"),
                "status": "failed",
                "error": None,
                "ticket_type_captured": "power",
                "power_min_x": None,
                "power_first_x": None,
                "min_guarantee": None,
                "flex_min": None,
            }

            try:
                clear_slip(frame)
                _, frame = verify_slip_empty(frame, page)
                dismiss_modal(frame, page)
                set_ticket_type(frame, "power")
                frame.wait_for_timeout(
                    int(max(0.1, delay_sec) * 1000)
                    + (int(random.uniform(200, 800)) if gentle else 0)
                )

                clicked = 0
                for leg in slip.get("legs") or []:
                    if add_leg(
                        frame,
                        page,
                        leg,
                        strict_lines=strict_lines,
                        require_line=require_line,
                    ):
                        clicked += 1
                    else:
                        print(f"  [WARN] could not click {leg.get('player')}")
                    leg_pause = max(0.05, delay_sec * (0.85 if gentle else 0.5))
                    if gentle:
                        leg_pause += random.uniform(0.4, 1.2)
                    frame.wait_for_timeout(int(leg_pause * 1000))

                n_need = int(slip.get("n_legs") or len(slip.get("legs") or []) or 2)
                if clicked < n_need:
                    rec["error"] = f"only_clicked_{clicked}_of_{n_need}_legs"
                    n_failed += 1
                    captured.append(_project_capture_fields(rec, fields))
                    clear_slip(frame)
                    continue

                power_slip = read_slip(frame, n_legs=clicked, ticket_type="power")
                if not power_slip:
                    rec["error"] = "power_slip_not_detected"
                    n_failed += 1
                    captured.append(_project_capture_fields(rec, fields))
                    clear_slip(frame)
                    continue

                power_min = power_slip.get("min_guarantee_payout")
                power_first = power_slip.get("first_place_payout") or power_slip.get(
                    "displayed_multiplier"
                )
                rec["power_min_x"] = power_min
                rec["power_first_x"] = power_first
                rec["min_guarantee"] = power_min
                print(
                    f"  [POWER] first_x={power_first} min_x={power_min} "
                    f"(primary=power_min_x)"
                )

                if want_flex:
                    try:
                        set_ticket_type(frame, "flex")
                        frame.wait_for_timeout(int(max(0.1, delay_sec) * 1000))
                        flex_slip = read_slip(frame, n_legs=clicked, ticket_type="flex")
                        if flex_slip:
                            flex_min = flex_slip.get("min_guarantee_payout")
                            if flex_min is None:
                                flex_min = flex_slip.get("flex_miss_1")
                            rec["flex_min"] = flex_min
                            print(f"  [FLEX] min={flex_min}")
                    except Exception as fe:
                        print(f"  [FLEX] skip: {fe}")

                if rec.get("power_min_x") is None and rec.get("power_first_x") is None:
                    rec["status"] = "partial"
                    rec["error"] = "missing_power_multipliers"
                    n_partial += 1
                elif rec.get("power_min_x") is None:
                    rec["status"] = "partial"
                    rec["error"] = "missing_power_min_x"
                    n_partial += 1
                else:
                    rec["status"] = "ok"
                    n_ok += 1

                print(
                    f"  [RECORDED] slip_type={rec['slip_type']} "
                    f"power_min_x={rec.get('power_min_x')} "
                    f"power_first_x={rec.get('power_first_x')} "
                    f"min_guarantee={rec.get('min_guarantee')} "
                    f"flex_min={rec.get('flex_min')}"
                )
                captured.append(_project_capture_fields(rec, fields))
            except Exception as e:
                rec["error"] = str(e)
                n_failed += 1
                captured.append(_project_capture_fields(rec, fields))
                print(f"  [ERROR] {e}")
            finally:
                try:
                    clear_slip(frame)
                    _, frame = verify_slip_empty(frame, page)
                    dismiss_modal(frame, page)
                except Exception:
                    pass
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass

    date_str = (
        str(date_override or "").strip()[:10]
        or (slips[0].get("date") if slips else "")
        or datetime.utcnow().strftime("%Y-%m-%d")
    )
    if not str(date_str or "").strip():
        m = re.search(r"(\d{4}-\d{2}-\d{2})", tickets_path.name)
        date_str = m.group(1) if m else datetime.utcnow().strftime("%Y-%m-%d")
    payload = {
        "date": date_str,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "cdp_url": cdp_url,
        "tickets_path": str(tickets_path),
        "tickets_fingerprint": fp_info.get("fingerprint") or "",
        "fingerprint_n_slips": int(fp_info.get("n_slips") or 0),
        "fingerprint_n_missing_live": int(fp_info.get("n_missing_live") or 0),
        "fields": fields,
        "primary_field": "power_min_x",
        "entry_amount": entry_amount,
        "only_missing_live": bool(only_missing_live),
        "slips": captured,
        "summary": {
            "n_total": len(captured),
            "n_ok": n_ok,
            "n_partial": n_partial,
            "n_failed": n_failed,
            "n_strong": sum(1 for s in captured if s.get("slip_type") == "strong"),
            "n_main": sum(1 for s in captured if s.get("slip_type") == "main"),
            "n_skipped_live": int(fp_info.get("n_live") or 0) if only_missing_live else 0,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[PAYOUT] Saved -> {output_path}")
    print(
        f"[PAYOUT] ok={n_ok} partial={n_partial} failed={n_failed} "
        f"(primary field=power_min_x)"
    )
    if write_back and captured:
        try:
            write_payout_patch_and_apply_to_tickets(
                tickets_path=tickets_path,
                captured=captured,
                date_str=str(date_str or "")[:10],
            )
        except Exception as e:
            print(f"[PAYOUT] WARN: write-back failed: {e}")
    return 0 if (n_ok + n_partial) > 0 or not captured else 1


# ── Mix-grid calibration (Goblin/Standard × deviation buckets) ────────────────

MIX_GRID_DEV_BUCKETS = (1.0, 1.5, 2.0)
# Recipe order = capture priority. Baselines first, then key EV floors (3G / 2G),
# then mixed 2- and 3-leg. Each Goblin recipe expands × MIX_GRID_DEV_BUCKETS.
MIX_GRID_RECIPES: list[tuple[str, int, int]] = [
    # (type_label, n_goblin, n_standard)  → n_legs = n_goblin + n_standard
    ("2S", 0, 2),  # 2-leg all-Standard baseline (~3x)
    ("3S", 0, 3),  # 3-leg all-Standard baseline (~6x)
    ("2G", 2, 0),  # 2-leg all-Goblin floor (known ~2.2x @dev1.0)
    ("3G", 3, 0),  # KEY: 3-leg all-Goblin floor vs ~5–6x display
    ("1G+1S", 1, 1),  # 2-leg mixed
    ("1G+2S", 1, 2),  # 3-leg mixed (1G+2S)
    ("2G+1S", 2, 1),  # 3-leg mixed (2G+1S)
    ("2G+3S", 2, 3),  # 5-leg stretch (optional)
]

# Critical EV cells — retry once on n_selected mismatch / click shortfall.
MIX_GRID_PRIORITY_TYPES = frozenset({"3G", "3S", "2G", "2G+1S", "1G+2S", "2S", "1G+1S"})


def _nearest_dev_bucket(dist: float | None, tol: float = 0.75) -> float | None:
    if dist is None:
        return None
    try:
        d = float(dist)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    best = min(MIX_GRID_DEV_BUCKETS, key=lambda t: abs(d - t))
    if abs(d - best) <= tol:
        return float(best)
    return None


def _build_std_map_from_board_cards(cards: list[dict]) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for c in cards:
        if str(c.get("pick_type") or "").lower() != "standard":
            continue
        try:
            line = float(pd.to_numeric(c.get("line"), errors="coerce"))
        except Exception:
            continue
        if not (line >= 0.5):
            continue
        key = (_norm(c.get("player")), _norm(c.get("prop_type")))
        if key[0] and key[1]:
            # Prefer higher standard line when duplicates exist
            prev = out.get(key)
            if prev is None or line > prev:
                out[key] = line
    return out


def _goblins_by_dev_bucket(goblins: list[dict]) -> dict[float, list[dict]]:
    buckets: dict[float, list[dict]] = {b: [] for b in MIX_GRID_DEV_BUCKETS}
    for c in goblins:
        dist = c.get("line_distance")
        if dist is None and c.get("standard_line") is not None:
            try:
                dist = abs(float(c.get("line")) - float(c.get("standard_line")))
            except Exception:
                dist = None
        bucket = _nearest_dev_bucket(dist)
        if bucket is None:
            # Still calibrate unknown-distance goblins into the +1.0 bucket
            bucket = float(MIX_GRID_DEV_BUCKETS[0])
            dist = float(dist) if dist is not None else bucket
        c2 = dict(c)
        c2["dev_bucket"] = bucket
        c2["line_distance"] = float(dist) if dist is not None else bucket
        buckets[bucket].append(c2)
    for b in buckets:
        buckets[b].sort(
            key=lambda c: (
                abs(float(c.get("line_distance") or 0.0) - b),
                _norm(c.get("player")),
            )
        )
    return buckets


def build_mix_grid_plan(
    standard: list[dict],
    goblins: list[dict],
    *,
    max_slips: int,
) -> list[dict]:
    """Plan synthetic slips: recipe × deviation bucket (when Goblins present)."""
    by_dev = _goblins_by_dev_bucket(goblins)
    std_pool = sorted(
        [
            c
            for c in standard
            if float(pd.to_numeric(c.get("line"), errors="coerce") or 0.0) >= 1.0
        ],
        key=lambda c: _norm(c.get("player")),
    )
    plans: list[dict] = []

    def _pick(pool: list[dict], n: int, used: set[str]) -> list[dict] | None:
        out: list[dict] = []
        for c in pool:
            pk = _norm(c.get("player"))
            if not pk or pk in used:
                continue
            used.add(pk)
            out.append(c)
            if len(out) == n:
                return out
        return None

    for label, n_g, n_s in MIX_GRID_RECIPES:
        if n_g <= 0:
            used: set[str] = set()
            pick_s = _pick(std_pool, n_s, used)
            if not pick_s:
                continue
            n_legs = int(n_s)
            plans.append(
                {
                    "type": label,
                    "n_goblin": 0,
                    "n_standard": n_s,
                    "n_legs": n_legs,
                    "dev_bucket": None,
                    "target_deviations": [],
                    "cards": [{"card": c, "direction": "OVER", "role": "standard"} for c in pick_s],
                }
            )
            if len(plans) >= max_slips:
                return plans
            continue

        for bucket in MIX_GRID_DEV_BUCKETS:
            g_pool = by_dev.get(bucket) or []
            if len(g_pool) < n_g:
                continue
            used = set()
            pick_g = _pick(g_pool, n_g, used)
            if not pick_g:
                continue
            pick_s = _pick(std_pool, n_s, used) if n_s > 0 else []
            if n_s > 0 and not pick_s:
                continue
            deviations = [
                round(float(c.get("line_distance") or bucket), 2) for c in pick_g
            ]
            cards = [{"card": c, "direction": "OVER", "role": "goblin"} for c in pick_g]
            cards += [{"card": c, "direction": "OVER", "role": "standard"} for c in (pick_s or [])]
            n_legs = int(n_g) + int(n_s)
            plans.append(
                {
                    "type": label,
                    "n_goblin": n_g,
                    "n_standard": n_s,
                    "n_legs": n_legs,
                    "dev_bucket": bucket,
                    "target_deviations": deviations,
                    "cards": cards,
                }
            )
            if len(plans) >= max_slips:
                return plans

    return plans


def summarize_mix_grid_floors(slips: list[dict]) -> dict[str, Any]:
    """Aggregate live floors by composition: n_legs × n_goblin (and slip type)."""
    by_comp: dict[str, list[float]] = {}
    by_type: dict[str, list[float]] = {}
    for s in slips:
        if not isinstance(s, dict):
            continue
        try:
            min_x = float(s.get("min_x") if s.get("min_x") is not None else s.get("power_min_x"))
        except (TypeError, ValueError):
            continue
        if not (min_x > 0) or str(s.get("status") or "").lower() not in ("ok", "partial"):
            continue
        n_g = int(s.get("n_goblin") or 0)
        n_s = int(s.get("n_standard") or 0)
        n_legs = int(s.get("n_legs") or (n_g + n_s) or 0)
        if n_legs <= 0:
            continue
        comp = f"{n_legs}L_{n_g}G"
        by_comp.setdefault(comp, []).append(min_x)
        label = str(s.get("type") or s.get("slip_type") or "").strip() or comp
        bucket = s.get("dev_bucket")
        type_key = f"{label}@dev{bucket}" if bucket is not None else label
        by_type.setdefault(type_key, []).append(min_x)

    def _avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 4)

    return {
        "by_composition": {k: {"n": len(v), "avg_min_x": _avg(v), "min_x_vals": v} for k, v in sorted(by_comp.items())},
        "by_type_bucket": {k: {"n": len(v), "avg_min_x": _avg(v), "min_x_vals": v} for k, v in sorted(by_type.items())},
    }


def mix_avg_floors_from_grid(slips: list[dict] | None = None) -> dict[tuple[int, int], float]:
    """
    Map (n_legs, n_goblin) -> avg power_min_x from mix-grid slips.
    Falls back to seeded defaults when a cell has no live obs.
    """
    # Seeded defaults (display-ish / prior captures). Live grid overwrites when present.
    seeded: dict[tuple[int, int], float] = {
        (2, 0): 3.0,  # 2S
        (2, 1): 2.7,  # 1G+1S
        (2, 2): 2.2,  # 2G
        (3, 0): 6.0,  # 3S
        (3, 1): 4.75,  # 1G+2S (Jul 11 live)
        (3, 2): 4.0,  # 2G+1S (Jul 11 live)
        # (3, 3) 3G — unknown until live capture succeeds
    }
    if slips is None:
        return dict(seeded)
    live: dict[tuple[int, int], list[float]] = {}
    for s in slips:
        if not isinstance(s, dict):
            continue
        try:
            min_x = float(s.get("min_x") if s.get("min_x") is not None else s.get("power_min_x"))
        except (TypeError, ValueError):
            continue
        if not (min_x > 0) or str(s.get("status") or "").lower() not in ("ok", "partial"):
            continue
        n_g = int(s.get("n_goblin") or 0)
        n_s = int(s.get("n_standard") or 0)
        n_legs = int(s.get("n_legs") or (n_g + n_s) or 0)
        if n_legs <= 0:
            continue
        live.setdefault((n_legs, n_g), []).append(min_x)
    out = dict(seeded)
    for key, vals in live.items():
        if vals:
            out[key] = round(sum(vals) / len(vals), 4)
    return out


def _slip_power_min_x(rec: dict) -> float | None:
    """Read power_min_x / min_x from a capture or ticket slip record."""
    if not isinstance(rec, dict):
        return None
    for key in ("power_min_x", "min_x", "display_min_x"):
        try:
            v = float(rec.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and v > 0:
            return v
    pay = rec.get("payout")
    if isinstance(pay, dict):
        for key in ("power_min_x", "display_min_x", "min_payout_x"):
            try:
                v = float(pay.get(key))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v) and v > 0:
                return v
    return None


def _normalize_slips_for_floor_summary(slips: list[dict]) -> list[dict]:
    """Normalize ticket-capture or mix-grid slips for summarize_mix_grid_floors."""
    out: list[dict] = []
    for rec in slips or []:
        if not isinstance(rec, dict):
            continue
        if str(rec.get("status") or "").lower() not in ("ok", "partial"):
            continue
        min_x = _slip_power_min_x(rec)
        if min_x is None:
            continue
        legs = rec.get("legs") if isinstance(rec.get("legs"), list) else []
        n_g = int(rec.get("n_goblin") or 0)
        n_s = int(rec.get("n_standard") or 0)
        if legs and (n_g + n_s) <= 0:
            n_g = sum(
                1
                for leg in legs
                if isinstance(leg, dict)
                and "goblin" in str(leg.get("pick_type") or "").lower()
            )
            n_s = max(0, len(legs) - n_g)
        n_legs = int(rec.get("n_legs") or (n_g + n_s) or len(legs) or 0)
        if n_legs <= 0:
            continue
        deviations: list[float] = []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            if "goblin" not in str(leg.get("pick_type") or "").lower():
                continue
            try:
                dist = float(leg.get("line_distance") or 0.0)
            except (TypeError, ValueError):
                dist = 0.0
            if dist > 0:
                deviations.append(dist)
        row = dict(rec)
        row["min_x"] = min_x
        row["power_min_x"] = min_x
        row["n_goblin"] = n_g
        row["n_standard"] = n_s
        row["n_legs"] = n_legs
        row["deviations"] = deviations or list(rec.get("deviations") or [])
        if row.get("dev_bucket") is None and deviations:
            mean_dev = sum(deviations) / len(deviations)
            bucket = _nearest_dev_bucket(mean_dev)
            if bucket is not None:
                row["dev_bucket"] = bucket
        out.append(row)
    return out


def merge_live_floors_into_rate_card(
    *,
    captured: list[dict],
    date_str: str,
    source: str = "ticket_capture",
    rate_card_path: Path | None = None,
) -> dict[str, Any]:
    """
    Merge live power_min_x observations into data/reports/payout_rate_card.json.

    Updates composition_floors (2G, 3G, 1G+1S, …) for /payout Rate cards + ticket fallbacks.
    Preserves prior goblin_discount_per_unit when a new dev-bucket fit has 0 observations.
    """
    date_str = str(date_str or "").strip()[:10]
    rate_card_path = rate_card_path or (ROOT / "data" / "reports" / "payout_rate_card.json")
    prior: dict[str, Any] = {}
    if rate_card_path.is_file():
        try:
            prior = json.loads(rate_card_path.read_text(encoding="utf-8"))
        except Exception:
            prior = {}
    if not isinstance(prior, dict):
        prior = {}

    norm = _normalize_slips_for_floor_summary(captured)
    floors = summarize_mix_grid_floors(norm)
    by_comp = floors.get("by_composition") if isinstance(floors.get("by_composition"), dict) else {}

    comp_prior = (
        prior.get("composition_floors")
        if isinstance(prior.get("composition_floors"), dict)
        else {}
    )
    merged_comp: dict[str, Any] = dict(comp_prior)
    for comp_key, meta in by_comp.items():
        if not isinstance(meta, dict):
            continue
        merged_comp[comp_key] = {
            **meta,
            "source": source,
            "source_date": date_str,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }

    # Dev-bucket fit when line_distance is present on Goblin legs.
    grid = {"date": date_str, "path": source, "slips": norm}
    fitted = fit_payout_rate_card_from_grid(grid)

    out: dict[str, Any] = dict(prior)
    out["schema_version"] = 1
    out["generated_at"] = datetime.utcnow().isoformat() + "Z"
    out["source_date"] = date_str
    out["composition_floors"] = merged_comp
    out["composition_summary"] = {
        k: v.get("avg_min_x")
        for k, v in merged_comp.items()
        if isinstance(v, dict) and v.get("avg_min_x") is not None
    }
    out["n_slips_in_capture"] = len(norm)

    new_obs = int(fitted.get("n_observations") or 0)
    prior_obs = int(prior.get("n_observations") or 0)
    prior_dpu = prior.get("goblin_discount_per_unit") if isinstance(prior.get("goblin_discount_per_unit"), dict) else {}
    new_dpu = fitted.get("goblin_discount_per_unit") if isinstance(fitted.get("goblin_discount_per_unit"), dict) else {}

    if new_obs > 0:
        out["goblin_discount_per_unit"] = new_dpu
        out["n_observations"] = new_obs
        out["source_grid"] = fitted.get("source_grid") or source
        baselines = fitted.get("baselines_power_min_x")
        if isinstance(baselines, dict) and baselines:
            out["baselines_power_min_x"] = baselines
    elif prior_dpu:
        out["goblin_discount_per_unit"] = prior_dpu
        out["n_observations"] = prior_obs
    else:
        out["goblin_discount_per_unit"] = new_dpu or {}
        out["n_observations"] = new_obs

    if not out.get("baselines_power_min_x"):
        out["baselines_power_min_x"] = {
            "2S": 3.0,
            "3S": 6.0,
            "4S": 10.0,
            "5S": 20.0,
        }

    out["notes"] = (
        "composition_floors: live PrizePicks power_min_x by n_legs × n_goblin (ticket + mix-grid). "
        "goblin_discount_per_unit: dev-bucket fit when line_distance available."
    )
    rate_card_path.parent.mkdir(parents=True, exist_ok=True)
    rate_card_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[PAYOUT] rate card merged ({source}) -> {rate_card_path} "
        f"comps={len(merged_comp)} new_slips={len(norm)} dpu_obs={out.get('n_observations')}"
    )
    for comp, meta in sorted(merged_comp.items()):
        if isinstance(meta, dict) and meta.get("avg_min_x") is not None:
            print(f"  [floor] {comp}: avg_min_x={meta.get('avg_min_x')} n={meta.get('n')}")
    return out


def rebuild_payout_rate_cards_deck() -> None:
    """Regenerate data/payout_rate_cards.json for /payout Rate cards tab."""
    script = ROOT / "scripts" / "build_payout_rate_cards.py"
    if not script.is_file():
        print(f"[PAYOUT] WARN: {script} missing — skip rate-cards deck rebuild")
        return
    import subprocess

    try:
        subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"[PAYOUT] rebuilt -> {ROOT / 'data' / 'payout_rate_cards.json'}")
    except subprocess.CalledProcessError as exc:
        print(f"[PAYOUT] WARN: rate-cards rebuild failed: {exc.stderr or exc}")


def _composition_label_from_legs(legs: list[dict]) -> str:
    s = g = d = 0
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        pt = str(leg.get("pick_type") or "Standard").strip().lower()
        if "goblin" in pt:
            g += 1
        elif "demon" in pt:
            d += 1
        else:
            s += 1
    return f"{s}S+{g}G+{d}D"


def _capture_to_ladder_row(rec: dict, date_str: str) -> dict[str, Any] | None:
    """Map one ok CDP capture slip to a payout ladder log row."""
    if not isinstance(rec, dict):
        return None
    if str(rec.get("status") or "").lower() not in ("ok", "partial"):
        return None
    min_x = _slip_power_min_x(rec)
    if min_x is None:
        return None
    legs = rec.get("legs") if isinstance(rec.get("legs"), list) else []
    n_legs = len(legs) or int(rec.get("n_legs") or 0)
    if n_legs < 2:
        return None
    goblin_deltas: list[str] = []
    demon_deltas: list[str] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        pt = str(leg.get("pick_type") or "").strip().lower()
        dist = None
        try:
            dist = float(leg.get("line_distance") or 0.0)
            if not (dist > 0):
                dist = None
        except (TypeError, ValueError):
            dist = None
        if dist is None:
            try:
                line = float(leg.get("line") or leg.get("played_line"))
                std = float(leg.get("standard_line") or leg.get("std_line"))
                dist = abs(line - std)
                if not (dist > 0):
                    dist = None
            except (TypeError, ValueError):
                dist = None
        if dist is None:
            continue
        val = str(round(float(dist), 2))
        if "goblin" in pt:
            goblin_deltas.append(val)
        elif "demon" in pt:
            demon_deltas.append(val)
    # Stable sorted signature for grouping
    try:
        goblin_deltas = [f"{v:g}" for v in sorted(float(x) for x in goblin_deltas)]
        demon_deltas = [f"{v:g}" for v in sorted(float(x) for x in demon_deltas)]
    except (TypeError, ValueError):
        pass
    tid = str(rec.get("ticket_id") or "").strip()
    sports = sorted(
        {
            str(leg.get("sport") or "").strip().upper()
            for leg in legs
            if isinstance(leg, dict) and str(leg.get("sport") or "").strip()
        }
    )
    sport_note = ",".join(sports) if sports else "unknown"
    return {
        "date": date_str,
        "n_legs": str(n_legs),
        "leg_composition": _composition_label_from_legs(legs),
        # Store as list of numeric strings (not a joined string) so consumers
        # never character-split "1,1" into ['1', ',', '1'].
        "goblin_deltas": list(goblin_deltas),
        "demon_deltas": list(demon_deltas),
        "power_payout_x": str(round(min_x, 4)),
        "flex_payout_x": "",
        "source": "live_cdp",
        "notes": f"ticket_id={tid}; sports={sport_note}; CDP power_min_x Min Guarantee",
        "ticket_id": tid,
    }


def sync_captures_to_payout_ladder_live(
    captured: list[dict],
    *,
    date_str: str,
    output_path: Path | None = None,
    tickets_path: Path | None = None,
    keep_same_date: bool = False,
) -> dict[str, Any]:
    """
    Upsert live CDP captures into ui_runner/data/payout_ladder_live_cdp.json.

    Merged at read time with payout_ladder_log.csv for /payout/ladder table.

    keep_same_date=False (default): drop prior rows for date_str then write this
    capture batch (full ticket scrape).
    keep_same_date=True: keep prior same-date rows and upsert by dedupe key
    (ladder validation merge).
    """
    date_str = str(date_str or "").strip()[:10]
    output_path = output_path or PAYOUT_LADDER_LIVE_CDP_PATH

    # Enrich legs with standard_line / line_distance from tickets JSON when available.
    tickets_by_id: dict[str, dict] = {}
    for cand in (
        tickets_path,
        ROOT / "ui_runner" / "templates" / "tickets_latest.json",
        ROOT / "ui_runner" / "data" / "tickets_latest.json",
    ):
        if cand is None:
            continue
        p = Path(cand)
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for g in (data.get("groups") or []) if isinstance(data, dict) else []:
            if not isinstance(g, dict):
                continue
            for t in g.get("tickets") or []:
                if not isinstance(t, dict):
                    continue
                tid = str(t.get("ticket_id") or "").strip()
                if tid:
                    tickets_by_id[tid] = t
        # Keep scanning so validation tickets + tickets_latest can both enrich.

    enriched_captured: list[dict] = []
    for rec in captured or []:
        if not isinstance(rec, dict):
            continue
        row = dict(rec)
        tid = str(row.get("ticket_id") or "").strip()
        ticket = tickets_by_id.get(tid) if tid else None
        if ticket and isinstance(ticket.get("legs"), list):
            # Prefer ticket legs (often have standard_line) but keep capture payout fields.
            t_legs = ticket.get("legs") or []
            c_legs = row.get("legs") if isinstance(row.get("legs"), list) else []
            merged_legs = []
            for i, tleg in enumerate(t_legs):
                if not isinstance(tleg, dict):
                    continue
                m = dict(tleg)
                if i < len(c_legs) and isinstance(c_legs[i], dict):
                    for k, v in c_legs[i].items():
                        if k not in m or m.get(k) in (None, ""):
                            m[k] = v
                if m.get("line_distance") in (None, "", 0, 0.0):
                    try:
                        line = float(m.get("line") or m.get("played_line"))
                        std = float(m.get("standard_line") or m.get("std_line"))
                        dist = abs(line - std)
                        if dist > 0:
                            m["line_distance"] = round(dist, 2)
                    except (TypeError, ValueError):
                        pass
                merged_legs.append(m)
            if merged_legs:
                row["legs"] = merged_legs
        enriched_captured.append(row)

    prior: dict[str, Any] = {"schema_version": 1, "date": date_str, "rows": []}
    if output_path.is_file():
        try:
            loaded = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prior = loaded
        except Exception:
            pass
    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in prior.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if (not keep_same_date) and str(row.get("date") or "")[:10] == date_str:
            continue  # replace this slate date on full ticket sync
        key = str(row.get("_dedupe_key") or row.get("ticket_id") or "").strip()
        if key:
            rows_by_id[key] = row
    n_new = 0
    for rec in enriched_captured:
        row = _capture_to_ladder_row(rec, date_str)
        if not row:
            continue
        legs = rec.get("legs") if isinstance(rec.get("legs"), list) else []
        sig = _leg_sig_key(legs)
        min_x = row.get("power_payout_x") or ""
        key = f"{date_str}|{sig}|{min_x}"
        row["_dedupe_key"] = key
        if key not in rows_by_id:
            n_new += 1
        rows_by_id[key] = row
    out = {
        "schema_version": 1,
        "date": date_str,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "rows": sorted(
            rows_by_id.values(),
            key=lambda r: (r.get("leg_composition") or "", r.get("goblin_deltas") or "", r.get("ticket_id") or ""),
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    n_with_delta = sum(1 for r in out["rows"] if str(r.get("goblin_deltas") or "").strip())
    print(
        f"[PAYOUT] ladder live -> {output_path} "
        f"(rows={len(out['rows'])} new={n_new} with_goblin_delta={n_with_delta} "
        f"keep_same_date={keep_same_date})"
    )
    return out


def fit_payout_rate_card_from_grid(grid: dict) -> dict:
    """Fit goblin_discount_per_unit by deviation bucket from power_min_x observations."""
    slips = [s for s in (grid.get("slips") or []) if isinstance(s, dict)]
    ok: list[dict] = []
    for s in slips:
        min_x = _slip_power_min_x(s)
        if min_x is not None:
            row = dict(s)
            row["min_x"] = min_x
            ok.append(row)
    baselines: dict[str, float] = {}
    for s in ok:
        if int(s.get("n_goblin") or 0) == 0 and int(s.get("n_standard") or 0) > 0:
            key = f"{int(s['n_standard'])}S"
            baselines[key] = float(s["min_x"])

    # Fallback to classic Power all-standard floors if board baselines missing.
    baselines.setdefault("2S", 3.0)
    baselines.setdefault("3S", 6.0)
    baselines.setdefault("4S", 10.0)
    baselines.setdefault("5S", 20.0)

    by_bucket: dict[str, list[float]] = {f"{b:.1f}": [] for b in MIX_GRID_DEV_BUCKETS}
    used = 0
    for s in ok:
        n_g = int(s.get("n_goblin") or 0)
        if n_g <= 0:
            continue
        n_legs = int(s.get("n_goblin") or 0) + int(s.get("n_standard") or 0)
        base = baselines.get(f"{n_legs}S")
        if not base or base <= 0:
            continue
        min_x = float(s["min_x"])
        deviations = [float(x) for x in (s.get("deviations") or []) if x is not None]
        if not deviations:
            bucket = s.get("dev_bucket")
            if bucket is not None:
                deviations = [float(bucket)] * n_g
        if not deviations:
            continue
        total_dev = sum(deviations)
        if total_dev <= 0:
            continue
        # discount_total = 1 - min_x/base; per unit of line deviation
        discount_total = max(0.0, 1.0 - (min_x / base))
        per_unit = discount_total / total_dev
        # Attribute to primary (mean) bucket
        mean_dev = sum(deviations) / len(deviations)
        bucket = _nearest_dev_bucket(mean_dev) or float(MIX_GRID_DEV_BUCKETS[0])
        by_bucket[f"{bucket:.1f}"].append(per_unit)
        used += 1

    fitted: dict[str, float] = {}
    for k, vals in by_bucket.items():
        if vals:
            fitted[k] = round(sum(vals) / len(vals), 4)

    return {
        "schema_version": 1,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source_date": grid.get("date"),
        "source_grid": grid.get("path") or "",
        "n_observations": used,
        "n_slips_in_grid": len(ok),
        "baselines_power_min_x": {k: round(v, 4) for k, v in baselines.items()},
        "goblin_discount_per_unit": fitted,
        "notes": (
            "discount_per_unit ≈ (1 - power_min_x / all_standard_baseline) / sum(goblin_line_distances). "
            "Fitted from live PrizePicks floor multipliers (power_min_x)."
        ),
    }


def run_mix_grid_capture(
    *,
    date_str: str,
    cdp_url: str,
    max_slips: int,
    delay_sec: float,
    entry_amount: float,
    output_path: Path | None = None,
    rate_card_path: Path | None = None,
) -> int:
    """Build mix×deviation slips on live PP board; write grid JSON + fitted rate card."""
    date_str = str(date_str or "").strip()[:10] or datetime.utcnow().strftime("%Y-%m-%d")
    output_path = output_path or (ROOT / "data" / "reports" / f"payout_mix_grid_{date_str}.json")
    rate_card_path = rate_card_path or (ROOT / "data" / "reports" / "payout_rate_card.json")

    # Prefer board-derived standard lines; step8 map is a bonus when NBA files exist.
    std_line_map: dict[tuple[str, str], float] = {}
    try:
        legs = load_nba_legs(top_n=60)
        std_line_map = build_standard_line_map(legs)
        print(f"[mix-grid] step8 standard-line map: {len(std_line_map)} keys")
    except Exception as e:
        print(f"[mix-grid] step8 map skipped ({e}); using board standards")

    p, browser, context, page = connect_existing_browser(cdp_url)
    page.wait_for_timeout(500)
    captured: list[dict] = []

    try:
        # Prefer boards with enough Goblins for 3G and Standards for 3S baselines.
        best_cards: list[dict] | None = None
        best_score = -1
        cards: list[dict] = []
        for league_id, label in ((2, "MLB"), (3, "WNBA"), (7, "NBA")):
            try:
                url = f"https://app.prizepicks.com/board?league_id={league_id}"
                print(f"[mix-grid] navigate {label} -> {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(2500)
            except Exception as e:
                print(f"[mix-grid] navigate {label} skipped: {e}")
            frame = find_prizepicks_frame(page)
            ensure_popular_filter(frame, page)
            dismiss_modal(frame, page)
            cards = expand_card_pool(frame, page)
            n_g = sum(1 for c in cards if str(c.get("pick_type") or "").lower() == "goblin")
            n_s = sum(1 for c in cards if str(c.get("pick_type") or "").lower() == "standard")
            print(f"[mix-grid] {label} cards={len(cards)} standard={n_s} goblin={n_g}")
            # Score: prefer boards that can build 3G + 3S (need ≥3 of each).
            score = min(n_g, 3) * 10 + min(n_s, 3) * 3 + min(len(cards), 20)
            if score > best_score and len(cards) >= 4:
                best_score = score
                best_cards = list(cards)
            if n_g >= 3 and n_s >= 3 and len(cards) >= 6:
                best_cards = list(cards)
                break
        cards = best_cards or cards or []
        frame = find_prizepicks_frame(page)

        if not cards:
            print("[mix-grid] FATAL: no board cards")
            return 1

        board_std = _build_std_map_from_board_cards(cards)
        merged_std = dict(board_std)
        merged_std.update(std_line_map)
        cards, floor_filtered = _reclassify_cards_with_std_map(cards, merged_std)
        print(f"[mix-grid] cards={len(cards)} floor_filtered={floor_filtered}")

        standard = [c for c in cards if c.get("pick_type") == "standard"]
        goblins = []
        for c in cards:
            line_val = float(pd.to_numeric(c.get("line"), errors="coerce") or 0.0)
            std_line = c.get("standard_line")
            is_g = c.get("pick_type") == "goblin" or (
                std_line is not None and std_line > 0 and line_val < float(std_line) * 0.85
            )
            if is_g:
                c2 = dict(c)
                c2["pick_type"] = "goblin"
                if c2.get("line_distance") is None and std_line:
                    c2["line_distance"] = abs(line_val - float(std_line))
                goblins.append(c2)

        print(f"[mix-grid] standard={len(standard)} goblin={len(goblins)}")
        plans = build_mix_grid_plan(standard, goblins, max_slips=max(1, int(max_slips)))
        print(f"[mix-grid] planned slips={len(plans)} (cap={max_slips})")

        for i, plan in enumerate(plans, 1):
            label = plan["type"]
            n_legs = int(plan.get("n_legs") or (plan["n_goblin"] + plan["n_standard"]))
            print(
                f"\n[mix-grid] ({i}/{len(plans)}) {label} "
                f"legs={n_legs} dev={plan.get('dev_bucket')} "
                f"nG={plan['n_goblin']} nS={plan['n_standard']}"
            )
            rec: dict[str, Any] = {
                "type": label,
                "slip_type": label,
                "n_legs": n_legs,
                "n_goblin": plan["n_goblin"],
                "n_standard": plan["n_standard"],
                "dev_bucket": plan.get("dev_bucket"),
                "deviations": list(plan.get("target_deviations") or []),
                "avg_deviation": None,
                "min_x": None,
                "first_x": None,
                "power_min_x": None,
                "power_first_x": None,
                "status": "failed",
                "error": None,
                "legs": [],
            }
            if rec["deviations"]:
                rec["avg_deviation"] = round(
                    sum(rec["deviations"]) / len(rec["deviations"]), 3
                )

            max_attempts = 2 if label in MIX_GRID_PRIORITY_TYPES else 1
            for attempt in range(1, max_attempts + 1):
                try:
                    clear_slip(frame)
                    _, frame = verify_slip_empty(frame, page)
                    dismiss_modal(frame, page)
                    set_ticket_type(frame, "power")
                    frame.wait_for_timeout(int(max(0.1, delay_sec) * 1000))

                    clicked = 0
                    leg_meta: list[dict] = []
                    current_tab = None
                    for item in plan["cards"]:
                        card = item["card"]
                        direction = str(item.get("direction") or "OVER").upper()
                        tab = str(card.get("source_filter") or "Popular")
                        ok = False
                        try:
                            if tab != current_tab:
                                dismiss_modal(frame, page)
                                tloc = frame.get_by_text(tab, exact=True).first
                                if tloc.count() == 0:
                                    tloc = frame.get_by_text(tab, exact=False).first
                                tloc.click(force=True, timeout=2000)
                                frame.wait_for_timeout(900)
                                _scroll_board_for_lazy_load(page)
                                current_tab = tab
                            dismiss_modal(frame, page)
                            fresh = get_all_cards(frame)
                            resolved = resolve_leg_card(card, fresh)
                            if resolved is None:
                                print(
                                    f"  [WARN] unresolved {card.get('player')} "
                                    f"{card.get('line')} {card.get('prop_type')} "
                                    f"({card.get('pick_type')}) on tab={tab}"
                                )
                            else:
                                ok = click_leg(frame, resolved, direction)
                                if ok:
                                    card = resolved
                        except Exception as e:
                            print(f"  [WARN] resolve/click failed: {e}")
                        if not ok:
                            ok = add_leg(
                                frame,
                                page,
                                {
                                    "player": card.get("player"),
                                    "prop_type": card.get("prop_type"),
                                    "direction": direction,
                                },
                            )
                        if ok:
                            clicked += 1
                            leg_meta.append(
                                {
                                    "player": card.get("player"),
                                    "prop_type": card.get("prop_type"),
                                    "line": card.get("line"),
                                    "role": item.get("role"),
                                    "pick_type": card.get("pick_type"),
                                    "source_filter": card.get("source_filter"),
                                    "line_distance": card.get("line_distance"),
                                    "dev_bucket": card.get("dev_bucket"),
                                }
                            )
                        else:
                            print(f"  [WARN] click failed: {card.get('player')}")
                        frame.wait_for_timeout(int(max(0.05, delay_sec * 0.5) * 1000))

                    slip_probe = None
                    try:
                        slip_probe = read_slip(frame, n_legs=clicked, ticket_type="power") or {}
                        slip_txt = _norm(
                            slip_probe.get("raw_slip_section")
                            or slip_probe.get("raw_text")
                            or ""
                        )
                        if slip_txt:
                            soft_miss = []
                            for m in leg_meta:
                                name = str(m.get("player") or "").strip()
                                if not name:
                                    continue
                                parts = [p for p in re.split(r"[^A-Za-z]+", name) if len(p) >= 3]
                                surname = parts[-1] if parts else name
                                if _norm(surname) not in slip_txt:
                                    soft_miss.append(name)
                            if soft_miss:
                                print(f"  [WARN] surname soft-miss: {', '.join(soft_miss[:3])}")
                        n_sel = slip_probe.get("n_selected")
                        if n_sel is not None and int(n_sel) != int(clicked):
                            err = f"n_selected_{n_sel}_clicked_{clicked}"
                            print(f"  [WARN] attempt {attempt}/{max_attempts}: {err}")
                            if attempt < max_attempts:
                                clear_slip(frame)
                                frame.wait_for_timeout(900)
                                continue
                            if int(n_sel) != int(n_legs):
                                rec["error"] = err
                                rec["legs"] = leg_meta
                                break
                    except Exception:
                        pass

                    rec["legs"] = leg_meta
                    if clicked < n_legs:
                        err = f"clicked_{clicked}_of_{n_legs}"
                        print(f"  [WARN] attempt {attempt}/{max_attempts}: {err}")
                        if attempt < max_attempts:
                            clear_slip(frame)
                            frame.wait_for_timeout(800)
                            continue
                        rec["error"] = err
                        break

                    slip = slip_probe or read_slip(frame, n_legs=clicked, ticket_type="power")
                    if not slip:
                        err = "slip_not_detected"
                        if attempt < max_attempts:
                            clear_slip(frame)
                            continue
                        rec["error"] = err
                        break

                    min_x = slip.get("min_guarantee_payout")
                    first_x = slip.get("first_place_payout") or slip.get("displayed_multiplier")
                    rec["min_x"] = min_x
                    rec["first_x"] = first_x
                    rec["power_min_x"] = min_x
                    rec["power_first_x"] = first_x
                    rec["n_legs"] = n_legs
                    if min_x is None:
                        rec["status"] = "partial"
                        rec["error"] = "missing_min_x"
                    else:
                        rec["status"] = "ok"
                        rec["error"] = None
                    print(
                        f"  [RECORDED] legs={n_legs} nG={rec['n_goblin']} "
                        f"avg_dev={rec.get('avg_deviation')} min_x={min_x} first_x={first_x}"
                    )
                    break
                except Exception as e:
                    print(f"  [ERROR] attempt {attempt}/{max_attempts}: {e}")
                    rec["error"] = str(e)
                    if attempt < max_attempts:
                        try:
                            clear_slip(frame)
                        except Exception:
                            pass
                        continue
            captured.append(rec)
            try:
                clear_slip(frame)
                _, frame = verify_slip_empty(frame, page)
                dismiss_modal(frame, page)
            except Exception:
                pass
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass

    n_ok = sum(1 for s in captured if s.get("status") == "ok")
    floors = summarize_mix_grid_floors(captured)
    grid = {
        "date": date_str,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "cdp_url": cdp_url,
        "entry_amount": entry_amount,
        "primary_field": "power_min_x",
        "path": str(output_path),
        "recipes": [
            {"type": t, "n_goblin": g, "n_standard": s, "n_legs": g + s}
            for t, g, s in MIX_GRID_RECIPES
        ],
        "slips": captured,
        "floors": floors,
        "summary": {
            "n_planned": len(captured),
            "n_ok": n_ok,
            "n_failed": sum(1 for s in captured if s.get("status") == "failed"),
            "composition_avg_min_x": {
                k: v.get("avg_min_x") for k, v in (floors.get("by_composition") or {}).items()
            },
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(grid, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[mix-grid] Saved -> {output_path} (ok={n_ok}/{len(captured)})")
    for comp, meta in (floors.get("by_composition") or {}).items():
        print(f"  [floor] {comp}: avg_min_x={meta.get('avg_min_x')} n={meta.get('n')}")

    card = fit_payout_rate_card_from_grid(grid)
    rate_card_path.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_live_floors_into_rate_card(
        captured=captured,
        date_str=date_str,
        source=str(output_path),
        rate_card_path=rate_card_path,
    )
    # merge_live_floors already wrote the card; keep fitted dpu from grid when present.
    if int(card.get("n_observations") or 0) > int(merged.get("n_observations") or 0):
        merged["goblin_discount_per_unit"] = card.get("goblin_discount_per_unit") or {}
        merged["n_observations"] = card.get("n_observations")
        rate_card_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    rebuild_payout_rate_cards_deck()
    print(
        f"[payout-grid] fitted rate card from {merged.get('n_observations', 0)} "
        f"dev-bucket observations -> {rate_card_path}"
    )
    print(f"[payout-grid] goblin_discount_per_unit={merged.get('goblin_discount_per_unit')}")
    return 0 if n_ok > 0 else 1



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--cdp-url",
        default="http://127.0.0.1:9222",
        help="Chrome DevTools Protocol endpoint (127.0.0.1 avoids IPv6 localhost hangs on Windows).",
    )
    ap.add_argument("--entry-amount", type=float, default=1.0)
    ap.add_argument("--max-cases", type=int, default=100)
    ap.add_argument("--delay-sec", type=float, default=0.5)
    ap.add_argument(
        "--tickets",
        default="",
        help="combined_slate_tickets_YYYY-MM-DD.json — capture MAIN/STRONG slip payouts",
    )
    ap.add_argument(
        "--output",
        default="",
        help="JSON output path (ticket-capture / mix-grid mode).",
    )
    ap.add_argument(
        "--fields",
        default=",".join(DEFAULT_CAPTURE_FIELDS),
        help="Comma list: power_min_x,power_first_x,min_guarantee,flex_min",
    )
    ap.add_argument(
        "--mix-grid",
        action="store_true",
        help=(
            "Calibration matrix: 2/3-leg Standard baselines + 2G/3G + mixed "
            "(1G+1S, 1G+2S, 2G+1S) × deviation buckets → payout_mix_grid + rate card"
        ),
    )
    ap.add_argument(
        "--date",
        default="",
        help="Slate date YYYY-MM-DD for --mix-grid / --tickets patch naming (default: today UTC).",
    )
    ap.add_argument(
        "--max-slips",
        type=int,
        default=36,
        help="Max synthetic slips for --mix-grid (default 36; covers 3-leg cells × buckets).",
    )
    ap.add_argument(
        "--no-write-back",
        action="store_true",
        help="With --tickets: skip writing payout_patch + updating combined_slate_tickets JSON.",
    )
    ap.add_argument(
        "--strict-lines",
        action="store_true",
        default=True,
        help="With --tickets: require exact line+pick_type (default on).",
    )
    ap.add_argument(
        "--allow-line-fallback",
        action="store_true",
        help="With --tickets: allow nearest-line proxies when exact Goblin/line left the board.",
    )
    ap.add_argument(
        "--only-missing-live",
        action="store_true",
        help="With --tickets: scrape only slips that do not already have payout_source=live_cdp.",
    )
    ap.add_argument(
        "--check-unchanged",
        action="store_true",
        help=(
            "With --tickets: print JSON skip decision (fingerprint vs prior capture) and exit. "
            "No CDP. Used by run_live_payout_capture.ps1 to avoid re-fetching unchanged tickets."
        ),
    )
    ap.add_argument(
        "--gentle",
        action="store_true",
        help="With --tickets: slower pacing between slips (less DataDome pressure).",
    )
    ap.add_argument(
        "--rebuild-patch-from-tickets",
        default="",
        help=(
            "No CDP: rebuild payout_patch_<date>.json from live_cdp floors already on "
            "the tickets JSON, write-back + mirror templates/docs/mobile."
        ),
    )
    ap.add_argument(
        "--merge-capture-into-rate-card",
        default="",
        help=(
            "No CDP: merge payout_capture_<date>.json slips into payout_rate_card.json "
            "+ rebuild data/payout_rate_cards.json for /payout Rate cards."
        ),
    )
    args = ap.parse_args()

    if str(getattr(args, "merge_capture_into_rate_card", "") or "").strip():
        capture_path = Path(str(args.merge_capture_into_rate_card).strip())
        if not capture_path.is_file():
            raise SystemExit(f"[PAYOUT] capture file not found: {capture_path}")
        payload = json.loads(capture_path.read_text(encoding="utf-8"))
        date_override = str(args.date or payload.get("date") or "")[:10]
        if not date_override:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", capture_path.name)
            date_override = m.group(1) if m else datetime.utcnow().strftime("%Y-%m-%d")
        slips = payload.get("slips") if isinstance(payload.get("slips"), list) else []
        merge_live_floors_into_rate_card(
            captured=slips,
            date_str=date_override,
            source=str(capture_path),
        )
        sync_captures_to_payout_ladder_live(slips, date_str=date_override)
        rebuild_payout_rate_cards_deck()
        raise SystemExit(0)

    if str(getattr(args, "rebuild_patch_from_tickets", "") or "").strip():
        tickets_path = Path(str(args.rebuild_patch_from_tickets).strip())
        if not tickets_path.is_file():
            raise SystemExit(f"[PAYOUT] tickets file not found: {tickets_path}")
        date_override = str(args.date or "").strip()[:10]
        if not date_override:
            try:
                data0 = json.loads(tickets_path.read_text(encoding="utf-8"))
                date_override = str(data0.get("date") or "")[:10]
            except Exception:
                date_override = ""
            if not date_override:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", tickets_path.name)
                date_override = m.group(1) if m else datetime.utcnow().strftime("%Y-%m-%d")
        result = write_payout_patch_and_apply_to_tickets(
            tickets_path=tickets_path,
            captured=[],
            date_str=date_override,
        )
        print(
            f"[PAYOUT] rebuild-patch done: ids={len((result.get('patch') or {}).get('by_ticket_id') or {})} "
            f"patched={result.get('n_patched')} kept={result.get('n_kept_live')}"
        )
        raise SystemExit(0)

    if bool(getattr(args, "mix_grid", False)):
        date_str = str(args.date or "").strip()[:10] or datetime.utcnow().strftime("%Y-%m-%d")
        out = (
            Path(str(args.output).strip())
            if str(args.output or "").strip()
            else ROOT / "data" / "reports" / f"payout_mix_grid_{date_str}.json"
        )
        max_slips = int(args.max_slips) if int(args.max_slips) > 0 else int(args.max_cases)
        raise SystemExit(
            run_mix_grid_capture(
                date_str=date_str,
                cdp_url=args.cdp_url,
                max_slips=max_slips,
                delay_sec=float(args.delay_sec),
                entry_amount=float(args.entry_amount),
                output_path=out,
            )
        )

    if str(args.tickets or "").strip():
        tickets_path = Path(str(args.tickets).strip())
        if not tickets_path.is_file():
            raise SystemExit(f"[PAYOUT] tickets file not found: {tickets_path}")
        fields = _parse_fields_arg(args.fields)
        if str(args.output or "").strip():
            output_path = Path(str(args.output).strip())
        else:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", tickets_path.name)
            date_tag = m.group(1) if m else datetime.utcnow().strftime("%Y-%m-%d")
            output_path = ROOT / "data" / "reports" / f"payout_capture_{date_tag}.json"
        date_override = str(args.date or "").strip()[:10]
        if not date_override:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", tickets_path.name)
            date_override = m.group(1) if m else ""
        if bool(getattr(args, "check_unchanged", False)):
            decision = capture_skip_decision(tickets_path, output_path)
            print(json.dumps(decision, indent=2, ensure_ascii=False))
            raise SystemExit(0)
        raise SystemExit(
            capture_tickets_from_board(
                tickets_path=tickets_path,
                output_path=output_path,
                fields=fields,
                cdp_url=args.cdp_url,
                entry_amount=float(args.entry_amount),
                max_cases=int(args.max_cases),
                delay_sec=float(args.delay_sec),
                write_back=not bool(getattr(args, "no_write_back", False)),
                date_override=date_override,
                strict_lines=not bool(getattr(args, "allow_line_fallback", False)),
                only_missing_live=bool(getattr(args, "only_missing_live", False)),
                gentle=bool(getattr(args, "gentle", False)),
            )
        )

    legs = load_nba_legs(top_n=40)
    if len(legs) < 5:
        raise RuntimeError("Not enough NBA candidate legs to build test matrix.")
    std_line_map = build_standard_line_map(legs)

    p, browser, context, page = connect_existing_browser(args.cdp_url)
    page.wait_for_timeout(500)
    captures: dict[str, float] = {}
    current_key = {"value": ""}

    def on_response(resp):
        if "entries" in resp.url or "entry" in resp.url:
            try:
                body = resp.json()
                mult = extract_multiplier_from_any(body)
                if mult is not None and current_key["value"]:
                    captures[current_key["value"]] = mult
            except Exception:
                pass

    page.on("response", on_response)

    out_rows: list[dict] = []
    ts_now = datetime.utcnow().isoformat()
    saved_records = 0
    skipped_records = 0

    try:
        frame = find_prizepicks_frame(page)
        ensure_popular_filter(frame, page)
        dismiss_modal(frame, page)
        cards = expand_card_pool(frame, page)
        if not cards:
            print("[FATAL] No cards parsed — check board state")
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(DEBUG_DIR / "fatal_no_cards.png"), full_page=True)
            return

        cards, floor_filtered = _reclassify_cards_with_std_map(cards, std_line_map)
        print(f"[CARDS] After 0.5-line filter: {len(cards)}")
        print(f"[CARDS] Floor props filtered out (line <= 0.5): {floor_filtered}")

        standard = [
            c
            for c in cards
            if c["pick_type"] == "standard"
            and float(pd.to_numeric(c.get("line"), errors="coerce") or 0.0) >= 3.0
        ]
        goblins = []
        demons = []
        for c in cards:
            line_val = float(pd.to_numeric(c.get("line"), errors="coerce") or 0.0)
            std_line = c.get("standard_line")
            is_distance_goblin = (
                std_line is not None and std_line > 0 and line_val < float(std_line) * 0.8
            )
            is_distance_demon = (
                std_line is not None and std_line > 0 and line_val > float(std_line) * 1.3
            )
            if c.get("pick_type") == "goblin" or is_distance_goblin:
                goblins.append(c)
            if c.get("pick_type") == "demon" or is_distance_demon:
                demons.append(c)

        std_sample = ", ".join(
            [f"{c['player']} {c['line']} {c['prop_type']}" for c in standard[:3]]
        ) or "none"
        gob_sample = ", ".join(
            [
                (
                    f"{c['player']} {c['line']} {c['prop_type']} "
                    f"(std={c.get('standard_line')}, dist={c.get('line_distance')})"
                )
                for c in goblins[:3]
            ]
        ) or "none"
        print(f"[CARDS] Standard legs (line >= 3.0): {len(standard)}")
        print(f"  Sample: {std_sample}")
        print(f"[CARDS] Goblin legs (line < std*0.8): {len(goblins)}")
        print(f"  Sample: {gob_sample}")
        goblins_avail = len(goblins) > 0
        demons_avail = len(demons) > 0
        print(f"[POOL] Standard={len(standard)} Goblin={len(goblins)} Demon={len(demons)}")

        test_cases = build_payout_test_matrix(
            standard,
            goblins,
            demons,
            std_line_map=std_line_map,
        )
        print(f"[MATRIX] {len(test_cases)} test cases planned")
        print("\n=== TEST MATRIX ===")
        for i, tc in enumerate(test_cases):
            n_legs_tc = len(tc["legs"])
            n_gob_tc = sum(1 for l in tc["legs"] if l["card"]["pick_type"] == "goblin")
            n_dem_tc = sum(1 for l in tc["legs"] if l["card"]["pick_type"] == "demon")
            print(
                f"  {i + 1}. {tc['label']} | n_legs={n_legs_tc} | "
                f"n_gob={n_gob_tc} | n_dem={n_dem_tc} | ticket_type={tc['ticket_type']}"
            )
        print(f"Total: {len(test_cases)} cases\n")

        max_cases = max(1, int(args.max_cases))
        counts = {k: 0 for k in MIN_SAMPLES}
        cases_run = 0
        test_idx = 0
        case_cursor = 0
        seen_combos: set[str] = set()

        while cases_run < max_cases:
            if all_targets_met(counts, goblins_avail, demons_avail):
                print("[TARGETS] All MIN_SAMPLES satisfied.")
                break
            tc = test_cases[case_cursor % len(test_cases)] if test_cases else None
            case_cursor += 1
            if tc is None:
                break
            test_idx += 1
            case_players = [f"{l['card']['player']} {l['card']['prop_type']}" for l in tc["legs"]]
            print(
                f"[CASE {test_idx}/{len(test_cases)}] {tc['label']} | "
                f"legs={case_players}"
            )
            print(
                f"[TARGETS] std={counts['all_standard']}/{MIN_SAMPLES['all_standard']} "
                f"gob={counts['has_goblin']}/{MIN_SAMPLES['has_goblin']} "
                f"dem={counts['has_demon']}/{MIN_SAMPLES['has_demon']} "
                f"flex={counts['flex']}/{MIN_SAMPLES['flex']}"
            )
            try:
                frame = soft_reset(frame, page)
                dismiss_modal(frame, page)
                set_ticket_type(frame, tc["ticket_type"])
                clear_slip(frame)
                _, frame = verify_slip_empty(frame, page)
                dismiss_modal(frame, page)
                ok = click_case_legs_with_filter_switches(frame, page, tc)
                if not ok:
                    print("  [SKIP] Leg click sequence failed")
                    clear_slip(frame)
                    _, frame = verify_slip_empty(frame, page)
                    dismiss_modal(frame, page)
                    cases_run += 1
                    continue
                frame.wait_for_timeout(1000)
                slip = read_slip(
                    frame,
                    n_legs=len(tc["legs"]),
                    ticket_type=tc["ticket_type"],
                )
                if slip.get("has_slip"):
                    n_selected = slip.get("n_selected")
                    if n_selected is not None and int(n_selected) != len(tc["legs"]):
                        print(f"  [SKIP] n_selected={n_selected} != n_legs={len(tc['legs'])}")
                        skipped_records += 1
                        clear_slip(frame)
                        _, frame = verify_slip_empty(frame, page)
                        dismiss_modal(frame, page)
                        frame.wait_for_timeout(600)
                        cases_run += 1
                        continue
                    combo_key = (
                        f"{len(tc['legs'])}L_"
                        f"{sum(1 for l in tc['legs'] if l['card']['pick_type'] == 'goblin')}G_"
                        f"{sum(1 for l in tc['legs'] if l['card']['pick_type'] == 'demon')}D_"
                        f"{tc['ticket_type']}"
                    )
                    if combo_key in seen_combos:
                        print(f"  [SKIP] Duplicate combo: {combo_key}")
                        skipped_records += 1
                        clear_slip(frame)
                        _, frame = verify_slip_empty(frame, page)
                        dismiss_modal(frame, page)
                        frame.wait_for_timeout(600)
                        cases_run += 1
                        continue
                    legs_payload = []
                    for leg in tc["legs"]:
                        c = leg["card"]
                        std_line = std_line_map.get((_norm(c["player"]), _norm(c["prop_type"])))
                        dist = abs(float(c["line"]) - float(std_line)) if std_line is not None else None
                        legs_payload.append({
                            "player": c["player"],
                            "prop_type": c["prop_type"],
                            "line": c["line"],
                            "pick_type": c["pick_type"],
                            "direction": leg["direction"].lower(),
                            "pp_id": "",
                            "standard_line": std_line,
                            "line_distance": dist,
                        })
                    rec = {
                        "timestamp": ts_now,
                        "ticket_type": tc["ticket_type"],
                        "n_legs": len(tc["legs"]),
                        "legs": json.dumps(legs_payload, ensure_ascii=False),
                        "n_goblins": sum(1 for l in tc["legs"] if l["card"]["pick_type"] == "goblin"),
                        "n_demons": sum(1 for l in tc["legs"] if l["card"]["pick_type"] == "demon"),
                        "n_standard": sum(1 for l in tc["legs"] if l["card"]["pick_type"] == "standard"),
                        "displayed_multiplier": slip.get("displayed_multiplier"),
                        "first_place_payout": slip.get("first_place_payout"),
                        "min_guarantee_payout": slip.get("min_guarantee_payout"),
                        "min_guarantee_hits_required": slip.get("min_guarantee_hits_required"),
                        "flex_first_place": slip.get("flex_first_place"),
                        "flex_miss_1": slip.get("flex_miss_1"),
                        "entry_amount": float(slip.get("entry_amount") or args.entry_amount),
                        "to_win_amount": slip.get("to_win"),
                        "raw_slip_section": slip.get("raw_slip_section"),
                    }
                    valid, reason = is_valid_record(rec)
                    if not valid:
                        print(f"  [SKIP] Bad record: {reason}")
                        if "min_g" in reason:
                            print("  [DEBUG SLIP TEXT]:")
                            print((rec.get("raw_slip_section") or "not captured")[:400])
                        skipped_records += 1
                    else:
                        seen_combos.add(combo_key)
                        out_rows.append(rec)
                        bump_counts_from_record(counts, rec)
                        saved_records += 1
                        print(
                            "  [RECORDED] "
                            f"mult={rec['displayed_multiplier']} "
                            f"first={rec['first_place_payout']} "
                            f"min_g={rec['min_guarantee_payout']} "
                            f"towin={rec['to_win_amount']}"
                        )
                else:
                    print("  [NO SLIP] Slip panel not detected")
                clear_slip(frame)
                _, frame = verify_slip_empty(frame, page)
                dismiss_modal(frame, page)
                frame.wait_for_timeout(600)
            except Exception as e:
                print(f"  [ERROR] {e}")
                try:
                    clear_slip(frame)
                    _, frame = verify_slip_empty(frame, page)
                    dismiss_modal(frame, page)
                except Exception:
                    pass
            cases_run += 1
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass

    date_tag = datetime.utcnow().strftime("%Y-%m-%d")
    out_csv = SAMPLES_DIR / f"payout_log_{date_tag}.csv"
    append_rows_csv(out_csv, out_rows)
    print(f"[PAYOUT] Collected samples: {len(out_rows)}")
    print(f"[PAYOUT] Saved -> {out_csv}")
    print(f"[PAYOUT] Saved records: {saved_records} | Skipped records: {skipped_records}")


if __name__ == "__main__":
    main()

