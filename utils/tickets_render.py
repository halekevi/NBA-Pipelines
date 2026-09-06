"""Render /tickets HTML from tickets_latest.json.

Flask GET /tickets imports this module — not the 25k-line mixer.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parents[1])

VERIFIED_PAYOUT_SOURCES = frozenset({"live_cdp"})


def require_live_payout_display() -> bool:
    raw = (os.getenv("PROPORACLE_REQUIRE_LIVE_PAYOUT") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def allow_sg_delta_payout_stamps() -> bool:
    raw = (os.getenv("PROPORACLE_ALLOW_SG_DELTA_PAYOUT") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_verified_payout_source(source: str | None) -> bool:
    src = str(source or "").strip().lower()
    if src in VERIFIED_PAYOUT_SOURCES:
        return True
    if allow_sg_delta_payout_stamps() and src in ("sg_delta_live", "sg_delta_verified"):
        return True
    return False


def _safe_positive_float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f <= 0:
        return None
    return f


def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        f = float(x)
        if f != f or not math.isfinite(f):
            return default
        return f
    except Exception:
        return default


def _l10_counts_look_like_rates(over: float | None, under: float | None) -> bool:
    if over is None or under is None:
        return False
    if over > 1.0 or under > 1.0:
        return False
    total = over + under
    return 0.9 <= total <= 1.1


def compute_l10_streak_label(l10_over, l10_under, direction: str = "OVER") -> str | None:
    try:
        ov = float(l10_over) if l10_over is not None else None
        un = float(l10_under) if l10_under is not None else None
    except (TypeError, ValueError):
        return None
    if ov is None or un is None or ov != ov or un != un:
        return None
    total = ov + un
    if total <= 0:
        return None
    d = str(direction or "OVER").strip().upper()
    if d == "UNDER":
        if un >= 7:
            return "HOT"
        if ov >= 7:
            return "COLD"
        return "NEUTRAL"
    if ov >= 7:
        return "HOT"
    if un >= 7:
        return "COLD"
    return "NEUTRAL"


def sanitize_l10_streak_label(streak: object) -> str | None:
    if streak is None:
        return None
    s = str(streak).strip().upper()
    if s in ("", "NAN", "NONE"):
        return None
    return s or None


def _finalize_leg_l10_streak(leg: dict) -> None:
    line_f = _safe_float(leg.get("line"))
    lo_f = _safe_float(leg.get("l10_over"))
    lu_f = _safe_float(leg.get("l10_under"))
    need_stat = lo_f is None or lu_f is None or _l10_counts_look_like_rates(lo_f, lu_f)
    if need_stat and line_f is not None:
        stats = []
        for i in range(1, 11):
            fv = _safe_float(leg.get(f"stat_g{i}") or leg.get(f"g{i}"))
            if fv is not None:
                stats.append(float(fv))
        if stats:
            over_n = sum(1 for s in stats if s > line_f)
            under_n = sum(1 for s in stats if s < line_f)
            leg["l10_over"] = float(over_n)
            leg["l10_under"] = float(under_n)
            if leg.get("l10_games_played") is None:
                leg["l10_games_played"] = float(len(stats))
    leg["l10_streak"] = sanitize_l10_streak_label(
        compute_l10_streak_label(
            leg.get("l10_over"),
            leg.get("l10_under"),
            leg.get("direction") or leg.get("bet_direction") or leg.get("final_bet_direction"),
        )
    )


def _count_l10_streak_legs(legs: list) -> tuple[int, int]:
    hot = cold = 0
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        streak = str(leg.get("l10_streak") or "").upper()
        if streak == "HOT":
            hot += 1
        elif streak == "COLD":
            cold += 1
    return hot, cold


def _finalize_payload_l10_streaks(payload: dict) -> None:
    if not isinstance(payload, dict):
        return
    for group in payload.get("groups") or []:
        if not isinstance(group, dict):
            continue
        g_hot = g_cold = 0
        for slip in group.get("tickets") or []:
            if not isinstance(slip, dict):
                continue
            for leg in slip.get("legs") or []:
                if isinstance(leg, dict):
                    _finalize_leg_l10_streak(leg)
            hot_n, cold_n = _count_l10_streak_legs(slip.get("legs") or [])
            slip["hot_legs"] = hot_n
            slip["cold_legs"] = cold_n
            g_hot += hot_n
            g_cold += cold_n
        group["hot_legs"] = g_hot
        group["cold_legs"] = g_cold
    payload["hot_legs"] = sum(
        int(g.get("hot_legs") or 0) for g in (payload.get("groups") or []) if isinstance(g, dict)
    )
    payload["cold_legs"] = sum(
        int(g.get("cold_legs") or 0) for g in (payload.get("groups") or []) if isinstance(g, dict)
    )


def _ticket_leg_sports(ticket: dict) -> set[str]:
    legs = list(ticket.get("legs") or [])
    return {
        str(leg.get("sport") or "").strip().upper()
        for leg in legs
        if isinstance(leg, dict) and str(leg.get("sport") or "").strip()
    }


def _dominant_leg_sport(tickets: list | None) -> str:
    if not tickets:
        return ""
    counts: Counter[str] = Counter()
    for t in tickets:
        if not isinstance(t, dict):
            continue
        for sp in _ticket_leg_sports(t):
            counts[sp] += 1
    if not counts:
        return ""
    return counts.most_common(1)[0][0]


def format_hit_window_fraction(n_games: int, raw) -> str:
    try:
        x = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if not math.isfinite(x):
        return str(raw)
    xi = int(round(x))
    if abs(x - xi) < 1e-6 and 0 <= xi <= int(n_games):
        k = xi
    elif 0.0 < x <= 1.0:
        k = int(round(x * n_games))
    elif float(n_games) < x <= 100.0:
        k = int(round((x / 100.0) * n_games))
    else:
        k = int(round(x))
    k = max(0, min(int(n_games), k))
    return f"{k}/{n_games}"


def _l10_streak_hit_count(raw, n_games: int = 10) -> int | None:
    try:
        x = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    xi = int(round(x))
    if abs(x - xi) < 1e-6 and 0 <= xi <= int(n_games):
        k = xi
    elif 0.0 < x <= 1.0:
        k = int(round(x * n_games))
    elif float(n_games) < x <= 100.0:
        k = int(round((x / 100.0) * n_games))
    else:
        k = int(round(x))
    return max(0, min(int(n_games), k))


def _l10_streak_badge_html(leg: dict) -> str:
    streak = str(leg.get("l10_streak") or "").strip().upper()
    if streak not in ("HOT", "COLD"):
        return ""
    direction = str(leg.get("direction") or leg.get("dir") or "OVER").strip().upper()
    if direction == "LOWER":
        direction = "UNDER"
    over = _l10_streak_hit_count(leg.get("l10_over"))
    under = _l10_streak_hit_count(leg.get("l10_under"))
    side_hits = under if direction == "UNDER" else over
    opp_hits = over if direction == "UNDER" else under
    if streak == "HOT" and side_hits is not None:
        side = "under" if direction == "UNDER" else "over"
        return (
            f'<span class="l10-streak-badge l10-hot" '
            f'title="Last 10 games {side} today&apos;s line">🔥 {side_hits}/10</span>'
        )
    if streak == "COLD" and opp_hits is not None:
        side = "over" if direction == "UNDER" else "under"
        return (
            f'<span class="l10-streak-badge l10-cold" '
            f'title="Last 10 games {side} today&apos;s line (against pick)">❄️ {opp_hits}/10</span>'
        )
    return ""


def _cons_line_badge_html(leg: dict) -> str:
    try:
        from utils.consistency_leaders_match import cons_line_badge_html

        return cons_line_badge_html(leg if isinstance(leg, dict) else {})
    except Exception:
        return ""


def _group_max_p_win(group: dict) -> float:
    best = 0.0
    for t in group.get("tickets") or []:
        if not isinstance(t, dict):
            continue
        try:
            pw = float(t.get("p_win") or 0.0)
            if math.isfinite(pw):
                best = max(best, pw)
        except (TypeError, ValueError):
            pass
    return best


def _leg_l10_side_hits(leg: dict) -> tuple[float | None, float | None]:
    if not isinstance(leg, dict):
        return None, None
    direction = str(leg.get("direction") or leg.get("dir") or "OVER").strip().upper()
    if direction == "LOWER":
        direction = "UNDER"
    try:
        games = float(leg.get("l10_games_played"))
    except (TypeError, ValueError):
        games = None
    if games is None or not math.isfinite(games) or games <= 0:
        games = 10.0
    try:
        if direction == "UNDER":
            hits = float(leg.get("l10_under"))
        else:
            hits = float(leg.get("l10_over"))
    except (TypeError, ValueError):
        return None, None
    if not math.isfinite(hits) or hits < 0:
        return None, None
    return hits, games


def _ticket_avg_l10_hits(legs: list) -> float | None:
    vals: list[float] = []
    for leg in legs or []:
        hits, games = _leg_l10_side_hits(leg if isinstance(leg, dict) else {})
        if hits is None or games is None or games <= 0:
            continue
        vals.append(10.0 * (hits / games))
    if not vals:
        return None
    return sum(vals) / len(vals)


def _ticket_l10_kpi_html(ticket: dict, legs: list) -> str:
    is_strong = bool(ticket.get("strong_builder"))
    if is_strong:
        avg = _ticket_avg_l10_hits(legs)
        if avg is None:
            return ""
        avg_txt = f"{avg:.1f}" if abs(avg - round(avg)) > 1e-9 else f"{avg:.0f}"
        return f'''
        <div class="kpi">
          <div class="kpi-label">L10</div>
          <div class="kpi-val" style="font-size:clamp(18px,2vw,24px);" title="Average L10 hits on bet side across legs">
            <span class="l10-hot-count">🔥 {avg_txt}/10</span>
            <span style="color:var(--muted);font-size:12px;font-weight:600;"> avg</span>
          </div>
        </div>'''
    hot_legs_n = int(ticket.get("hot_legs") or 0)
    cold_legs_n = int(ticket.get("cold_legs") or 0)
    if not (hot_legs_n or cold_legs_n):
        hot_legs_n, cold_legs_n = _count_l10_streak_legs(legs)
    if not (hot_legs_n or cold_legs_n):
        return ""
    return f'''
        <div class="kpi">
          <div class="kpi-label">L10 Streak</div>
          <div class="kpi-val" style="font-size:clamp(18px,2vw,24px);">
            <span class="l10-hot-count" title="Legs labeled HOT (bet-side L10)">🔥 {hot_legs_n}</span>
            <span style="color:var(--muted);font-size:14px;"> / </span>
            <span class="l10-cold-count" title="Legs labeled COLD (against pick)">❄️ {cold_legs_n}</span>
          </div>
        </div>'''


def _winrate_leg_bench_risk(leg: dict) -> bool:
    su = str(leg.get("sport") or "").strip().upper()
    if su not in ("NBA", "WNBA", "WNBA1H", "WNBA1Q", "NBA1H", "NBA1Q"):
        return False
    mt = str(leg.get("min_tier") or leg.get("minutes_tier") or "").strip().upper()
    ur = str(leg.get("usage_role") or "").strip().upper()
    sr = str(leg.get("shot_role") or "").strip().upper()
    return mt == "LOW" and ur == "SUPPORT" and sr in ("LOW_VOL", "", "LOW")


def _winrate_ticket_construction_reject(ticket: dict) -> bool:
    # Display already-built JSON; do not re-run mixer correlation gates.
    return False


def _winrate_ticket_win_prob(ticket: dict) -> float:
    for key in ("est_win_prob", "p_win", "combined_hit_prob_curve"):
        raw = ticket.get(key)
        if raw is None or raw == "":
            continue
        try:
            v = float(raw)
            if math.isfinite(v) and v > 0:
                return max(0.0, min(1.0, v))
        except (TypeError, ValueError):
            continue
    return 0.0


def _ticket_rank_floor_x(ticket: dict) -> float:
    pay = ticket.get("payout") if isinstance(ticket.get("payout"), dict) else {}
    for raw in (
        pay.get("display_min_x"),
        ticket.get("display_min_x"),
        ticket.get("payout_multiplier"),
        ticket.get("power_payout"),
    ):
        v = _safe_positive_float(raw)
        if v is not None:
            return float(v)
    return 1.0


def _ticket_is_mlb_goblin_n(ticket: dict, n_legs: int) -> bool:
    legs = [leg for leg in (ticket.get("legs") or ticket.get("rows") or []) if isinstance(leg, dict)]
    if len(legs) != int(n_legs):
        return False
    for leg in legs:
        sport = str(leg.get("sport") or "").strip().upper()
        pt = str(leg.get("pick_type") or "").strip().lower()
        if sport != "MLB" or "goblin" not in pt:
            return False
    return True


def _winrate_ticket_rank_score(ticket: dict) -> float:
    p = _winrate_ticket_win_prob(ticket)
    floor = _ticket_rank_floor_x(ticket)
    score = float(p) * float(floor)
    boost = float(os.getenv("PROPORACLE_MLB_GOBLIN_4L_RANK_BOOST", "1.25"))
    if _ticket_is_mlb_goblin_n(ticket, 4):
        score *= boost
    return score


def _winrate_ticket_panel_pcash_optional(ticket: dict) -> float | None:
    pwin = _winrate_ticket_win_prob(ticket)
    raw = ticket.get("ticket_model_p_cash")
    if raw is None or raw == "":
        return None
    try:
        pcash = float(raw)
        if not math.isfinite(pcash) or pcash <= 0:
            return None
        pcash = max(0.0, min(1.0, pcash))
        if abs(pcash - pwin) < 0.05:
            return None
        return pcash
    except (TypeError, ValueError):
        return None


# ── Web render helper ─────────────────────────────────────────────────────────

_SPORT_ACCENT: dict[str, str] = {
    "NBA":    "#36A2FF",
    "WNBA":   "#FF8AC6",
    "CBB":    "#2ECC71",
    "NHL":    "#9B59FF",
    "SOCCER": "#7DFF6B",
    "TENNIS": "#F39C12",
    "MLB":    "#FF5A5F",
    "WCBB":   "#FF66CC",
    "NBA1Q":  "#00E5FF",
    "NBA1H":  "#1ABC9C",
    "CROSS":  "#C77DFF",
    "MIX":    "#C77DFF",
    # STRONG builder boards (not a sport) — gold, distinct from WNBA pink.
    "STRONG": "#D4AF37",
}

_PICK_COLOR: dict[str, str] = {
    "goblin":   "#39ff6e",
    "demon":    "#ff4d4d",
    "standard": "#00e5ff",
}

_TICKETS_BUILT_PAYOUT_CSS = """<style>
.tickets-built .ticket-hdr-bracket {
  font-family: "Bebas Neue", sans-serif;
  font-size: clamp(14px, 1.5vw, 17px);
  letter-spacing: 0.06em;
  color: var(--text);
  border: 1px solid rgba(255,255,255,0.14);
  border-radius: 6px;
  padding: 2px 8px;
  background: rgba(0,0,0,0.2);
}
.tickets-built .ticket-hdr-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.tickets-built .ticket-data-warn {
  font-size: 10px;
  color: var(--amber);
}
.tickets-built .ticket-copy-btn {
  font-family: Inter, sans-serif;
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid rgba(200,255,0,0.35);
  background: rgba(200,255,0,0.08);
  color: var(--accent, #c8ff00);
  cursor: pointer;
  white-space: nowrap;
}
.tickets-built .ticket-copy-btn:hover {
  background: rgba(200,255,0,0.16);
}
.tickets-built .ticket-copy-btn.is-copied {
  border-color: rgba(57,255,110,0.45);
  color: #39ff6e;
  background: rgba(57,255,110,0.1);
}
.tickets-built .ticket-copy-btn--group {
  margin-left: auto;
}
.tickets-built .ticket-placed {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted, rgba(255,255,255,.75));
  cursor: pointer;
  user-select: none;
}
.tickets-built .ticket-placed input {
  accent-color: #c8ff00;
}
.tickets-built .ticket.is-placed {
  outline: 1px solid rgba(57,255,110,.28);
}
.tickets-built .payout-rec-badge {
  font-family: "Inter", sans-serif;
  font-size: clamp(11px, 1.1vw, 13px);
  border: 1px solid rgba(255,255,255,0.16);
  border-radius: 6px;
  padding: 3px 10px;
  background: rgba(0,0,0,0.22);
}
.tickets-built .payout-x-badge {
  font-family: "Inter", sans-serif;
  font-size: clamp(11px, 1.1vw, 13px);
  color: var(--cyan);
  border: 1px solid rgba(0,229,255,0.28);
  border-radius: 6px;
  padding: 3px 10px;
  background: rgba(0,229,255,0.06);
}
.tickets-built .ev-strong { color: #00ff88; font-weight: bold; }
.tickets-built .ev-ok { color: #88ccff; }
.tickets-built .ev-marginal { color: #ffaa00; }
.tickets-built .ev-low { color: #ff8844; }
.tickets-built .ev-skip { color: #ff4444; }
.tickets-built .ticket-filter-pill[data-filter="top-payout"].active {
  border-color: rgba(255, 215, 0, 0.42);
  color: #ffd54f;
}
.tickets-built .payout-source-badge {
  font-family: "Inter", sans-serif;
  font-size: 11px;
  margin-left: 6px;
  white-space: nowrap;
}
.tickets-built .payout-source-exact { color: #4caf50; }
.tickets-built .payout-source-calibrated { color: #ffc107; }
.tickets-built .payout-source-fallback { color: #9e9e9e; }
.tickets-built .leg-game-log-wrap { flex: 1; min-width: 280px; max-width: 560px; }
.tickets-built table.leg-game-log { width: 100%; font-size: 13px; border-collapse: collapse; }
.tickets-built table.leg-game-log th {
  text-align: left; padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.14);
  color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
  font-family: "Bebas Neue", sans-serif;
}
.tickets-built table.leg-game-log td { padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); font-family: "Inter", sans-serif; }
.tickets-built table.leg-game-log tr:last-child td { border-bottom: none; }
.tickets-built .leg-game-log-empty { margin: 0; font-size: 12px; color: var(--muted); }
.tickets-built .leg-game-hit { color: #00ff88; font-weight: 600; }
.tickets-built .leg-game-miss { color: #c96a74; font-weight: 600; }
.tickets-built .ticket-filter-sort-wrap {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-right: 6px;
}
.tickets-built .ticket-filter-sort-label {
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--muted);
  text-transform: uppercase;
}
.tickets-built .ticket-filter-sort {
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.2);
  background: rgba(12,16,26,0.9);
  color: var(--text);
  font-size: 12px;
  padding: 5px 12px;
}
.tickets-built .ticket-filter-bar-action.active {
  border-color: rgba(255, 86, 86, 0.45);
  color: #ff8a8a;
}
.tickets-built .ticket-group-section.group-rec-strong .ticket-group-header { border-left: 4px solid #00ff88; }
.tickets-built .ticket-group-section.group-rec-ok .ticket-group-header { border-left: 4px solid #f0a500; }
.tickets-built .ticket-group-section.group-rec-marginal .ticket-group-header { border-left: 4px solid #ff9f43; }
.tickets-built .ticket-group-section.group-rec-skip .ticket-group-header { border-left: 4px solid #ff5c5c; opacity: 0.78; }
.tickets-built .best-ticket-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  font-size: 13px;
}
.tickets-built .best-ticket-row:last-child { border-bottom: 0; }
.tickets-built .best-ticket-name { color: var(--text); font-weight: 600; }
.tickets-built .best-ticket-meta { font-size: 12px; }
.tickets-built .winrate-best-panel {
  margin: 0 0 20px 0;
  padding: 16px 18px;
  border-radius: 12px;
  border: 1px solid rgba(255, 215, 0, 0.35);
  background: linear-gradient(145deg, rgba(18, 22, 32, 0.98), rgba(8, 12, 20, 0.98));
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35);
}
.tickets-built .winrate-best-panel .winrate-best-title {
  font-size: 11px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: #ffd54f;
  margin-bottom: 4px;
}
.tickets-built .winrate-best-panel .winrate-best-sub {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 12px;
}
.tickets-built .winrate-best-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
}
.tickets-built .winrate-best-row:last-child { border-bottom: 0; }
.tickets-built .winrate-best-row:hover { background: rgba(255, 215, 0, 0.04); }
.tickets-built .winrate-best-rank { color: #ffd54f; font-weight: 700; min-width: 28px; }
.tickets-built .winrate-best-name { color: var(--text); font-weight: 600; flex: 1; }
.tickets-built .winrate-best-legs { font-size: 12px; color: var(--muted); margin-top: 4px; }
.tickets-built .winrate-best-leg { line-height: 1.35; }
.tickets-built .winrate-best-leg + .winrate-best-leg { margin-top: 2px; }
.tickets-built .winrate-best-stats { text-align: right; font-size: 12px; white-space: nowrap; }
.tickets-built .winrate-best-pwin { color: #00ff88; font-weight: 700; font-size: 14px; }
.tickets-built .winrate-best-pwin-sub { font-size: 10px; color: var(--muted); margin-top: 2px; }
.tickets-built .winrate-best-warn { font-size: 10px; color: #f0a500; margin-top: 4px; }
.tickets-built .ticket-pwin-ev-badge {
  font-size: 12px;
  color: #00ff88;
  margin-left: 8px;
  font-weight: 600;
}
.tickets-built .l10-streak-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 6px;
  margin-left: 6px;
  vertical-align: middle;
  white-space: nowrap;
}
.tickets-built .l10-streak-badge.l10-hot {
  background: rgba(125,255,203,.12);
  color: #00ff88;
  border: 1px solid rgba(125,255,203,.35);
}
.tickets-built .l10-streak-badge.l10-cold {
  background: rgba(100,180,255,.12);
  color: #7eb8ff;
  border: 1px solid rgba(100,180,255,.35);
}
.tickets-built .cons-line-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 6px;
  margin-left: 6px;
  vertical-align: middle;
  white-space: nowrap;
  background: rgba(212,175,55,.12);
  color: #d4af37;
  border: 1px solid rgba(212,175,55,.4);
}
.tickets-built .kpi-val.l10-hot-count { color: #00ff88; }
.tickets-built .kpi-val.l10-cold-count { color: #7eb8ff; }
</style>"""


def _payout_ev_class(rec: str) -> str:
    u = (rec or "").strip().upper()
    if u == "STRONG":
        return "ev-strong"
    if u == "OK":
        return "ev-ok"
    if u == "MARGINAL":
        return "ev-marginal"
    if u == "LOW":
        return "ev-low"
    if u == "SKIP":
        return "ev-skip"
    return "ev-skip"


def _payout_rec_prefix(rec: str) -> str:
    u = (rec or "").strip().upper()
    if u == "STRONG":
        return "⚡"
    if u == "OK":
        return "✅"
    if u == "MARGINAL":
        return "⚠"
    if u == "LOW":
        return "▼"
    if u == "SKIP":
        return "⏭"
    return "•"


def _normalize_payout_source(source: str | None) -> str:
    src = str(source or "").strip().lower()
    if src == "live_cdp":
        return "live_cdp"
    if src == "sg_delta_live":
        return "sg_delta_live"
    if src == "sg_delta_verified":
        return "sg_delta_verified"
    if src == "pending_live":
        return "pending_live"
    if src == "rate_card":
        return "rate_card"
    if src == "mix_grid_average":
        return "mix_grid_average"
    if src in ("fallback_estimate", "fallback"):
        return "fallback_estimate"
    if src == "exact":
        return "exact"
    if src in ("n_correct_median", "n_correct_live", "n_correct_delta"):
        return src
    return src or "calibrated"


def _resolve_ticket_display_min_x(payout: dict | None, ticket: dict | None = None) -> float | None:
    """Board-facing payout multiplier (PP pay), not the internal EV-model min_payout_x.

    When verified lines are required, only exact live_cdp floors are shown —
    no peer SG-Δ, model, or cold-extrapolated fallback.
    """
    pay = payout if isinstance(payout, dict) else {}
    ticket = ticket if isinstance(ticket, dict) else {}
    src = str(pay.get("payout_source") or ticket.get("payout_source") or "").strip().lower()
    if src in ("n_correct_median", "n_correct_live", "n_correct_delta"):
        for raw in (
            pay.get("display_min_x"),
            ticket.get("display_min_x"),
            ticket.get("power_payout"),
            ticket.get("flex_payout"),
        ):
            v = _safe_positive_float(raw)
            if v is not None:
                return v
        return None
    if require_live_payout_display():
        if src == "pending_live":
            return None
        if src and not is_verified_payout_source(src):
            return None
        for raw in (
            pay.get("display_min_x") if is_verified_payout_source(src) or not src else None,
            ticket.get("display_min_x") if is_verified_payout_source(src) or not src else None,
            pay.get("power_min_x") if src in ("", "live_cdp", "sg_delta_live") else None,
        ):
            v = _safe_positive_float(raw)
            if v is not None:
                return v
        return None
    for raw in (
        pay.get("display_min_x"),
        ticket.get("display_min_x"),
        pay.get("power_min_x"),
        ticket.get("power_payout"),
        ticket.get("base_power_payout"),
    ):
        v = _safe_positive_float(raw)
        if v is not None:
            return v
    return None


def _fmt_payout_scrape_clock(raw: object) -> str:
    """Human clock for payout.captured_at (ET). Empty if missing/unparseable."""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        t = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        dt = dt.astimezone(ZoneInfo("America/New_York"))
        hour = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{hour}:{dt.minute:02d} {ampm} ET"
    except Exception:
        return text[:22]


def _board_payout_label(
    display_x: float | None,
    source: str | None,
    captured_at: object = None,
) -> tuple[str, str, str]:
    """
    Option A board payout copy: (mult_text, source_badge, title).
    live_cdp → "2.2x" + "✓ live"; sg_delta_verified → "2.2x" + "✓ lines";
    pending_live → "—"; estimates use a leading ~.
    """
    src = _normalize_payout_source(source)
    if src == "pending_live":
        mult_text, badge, title = (
            "—",
            "pending",
            "Waiting for verified lines (live CDP or same-line SG-Δ evidence)",
        )
    elif display_x is None:
        mult_text, badge, title = (
            "—",
            "pending" if require_live_payout_display() else "est",
            "Board payout unavailable",
        )
    else:
        mult = f"{display_x:.1f}".rstrip("0").rstrip(".") if display_x >= 10 else f"{display_x:.1f}"
        if src == "live_cdp":
            mult_text, badge, title = f"{mult}x", "✓ live", f"Live PrizePicks payout {mult}x"
        elif src == "sg_delta_live":
            mult_text, badge, title = f"{mult}x", "✓ live", f"SG-Δ live recipe floor {mult}x"
        elif src == "sg_delta_verified":
            mult_text, badge, title = (
                f"{mult}x",
                "✓ lines",
                f"SG-Δ extrapolated floor {mult}x (same lines live-verified)",
            )
        elif src == "rate_card":
            mult_text, badge, title = f"~{mult}x", "est", f"Rate-card estimate ~{mult}x"
        elif src == "mix_grid_average":
            mult_text, badge, title = f"~{mult}x", "board avg", f"Mix-grid board average ~{mult}x"
        elif src == "fallback_estimate":
            mult_text, badge, title = f"~{mult}x", "model est", f"Model estimate ~{mult}x"
        elif src == "exact":
            mult_text, badge, title = f"{mult}x", "exact", f"Exact payout {mult}x"
        elif src in ("n_correct_median", "n_correct_live", "n_correct_delta"):
            mult_text, badge, title = (
                f"{mult}x",
                "N-correct",
                f"PrizePicks N-correct / To Win {mult}x (not 1st place)",
            )
        else:
            mult_text, badge, title = f"~{mult}x", "est", f"Estimated board payout ~{mult}x"
    clock = _fmt_payout_scrape_clock(captured_at)
    if clock:
        title = f"{title} · scraped {clock}"
    return mult_text, badge, title


def _payout_source_badge_html(source: str, *, badge_label: str | None = None) -> str:
    src = _normalize_payout_source(source)
    if badge_label is None:
        if src == "live_cdp":
            badge_label = "✓ live"
        elif src == "sg_delta_live":
            badge_label = "✓ live"
        elif src == "sg_delta_verified":
            badge_label = "✓ lines"
        elif src == "pending_live":
            badge_label = "pending"
        elif src == "rate_card":
            badge_label = "est"
        elif src == "mix_grid_average":
            badge_label = "board avg"
        elif src == "fallback_estimate":
            badge_label = "model est"
        elif src == "exact":
            badge_label = "exact"
        elif src in ("n_correct_median", "n_correct_live", "n_correct_delta"):
            badge_label = "N-correct"
        else:
            badge_label = "est"
    return (
        f'<span class="payout-source-badge payout-source-{_h(src)}" title="Payout source: {_h(src)}">'
        f"{_h(badge_label)}</span>"
    )


def _board_payout_badge_html(
    display_x: float | None,
    source: str | None,
    captured_at: object = None,
) -> str:
    """Single header/footer payout chip: ~2.2x + board-avg/live badge."""
    mult_text, badge_label, title = _board_payout_label(
        display_x, source, captured_at=captured_at
    )
    src = _normalize_payout_source(source)
    return (
        f'<span class="payout-x-badge" title="{_h(title)}">[{_h(mult_text)}]</span>'
        f"{_payout_source_badge_html(src, badge_label=badge_label)}"
    )


def _h(v) -> str:
    """HTML-escape a value."""
    import html as _html
    return _html.escape(str(v)) if v is not None else ""


def _pct(v, decimals: int = 0) -> str:
    try:
        return f"{float(v) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt(v, decimals: int = 2, suffix: str = "") -> str:
    try:
        return f"{float(v):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def _sport_accent(sport: str) -> str:
    key = (sport or "").upper().split()[0]
    return _SPORT_ACCENT.get(key, "#6C3483")


def _group_sport(group_name: str, tickets: list | None = None) -> str:
    """Infer sport from group name for accent colouring; fall back to dominant leg sport."""
    name = (group_name or "").upper().replace("\u00a0", " ")
    # STRONG builder buckets first (else WNBA/SOCCER leg sport paints them pink/green).
    if name.startswith("STRONG") or " STRONG " in f" {name} ":
        return "STRONG"
    if "NBA/CBB" in name or "NBA+CBB" in name or "NBA-CBB" in name:
        return "CROSS"
    if name.startswith("CROSS") or name.startswith("MIX"):
        return "CROSS"
    if name.startswith("X-SPORT") or "X-SPORT" in name:
        return "CROSS"
    for sp in (
        "NBA1Q",
        "NBA1H",
        "WNBA",
        "WCBB",
        "TENNIS",
        "SOCCER",
        "NHL",
        "MLB",
        "CBB",
        "NFLP",
        "NFL",
        "CFB",
        "NBA",
    ):
        if sp in name:
            return sp
    dom = _dominant_leg_sport(tickets)
    if dom:
        return dom
    return "MIX"


# Align with Slate Explorer sport order; cross-sport / mix buckets sort last.
_TICKET_GROUP_SPORT_SORT_ORDER: dict[str, int] = {
    "NBA": 0,
    "NBA1Q": 1,
    "NBA1H": 2,
    "CBB": 3,
    "WCBB": 4,
    "CFB": 5,
    "NFL": 6,
    "WNBA": 7,
    "MLB": 8,
    "NHL": 9,
    "SOCCER": 10,
    "TENNIS": 11,
    "STRONG": 12,
    "CROSS": 10_000,
    "MIX": 10_000,
}


def _group_is_goblin70(group: dict | None, group_name: str = "") -> bool:
    """True for the 70% Goblin card (plus NFL Power fill from that builder)."""
    name = str(group_name or (group or {}).get("group_name") or "")
    if "Goblin-70" in name or "GOBLIN-70" in name.upper():
        return True
    if name.upper().startswith("NFL POWER"):
        return True
    for t in (group or {}).get("tickets") or []:
        if isinstance(t, dict) and str(t.get("ticket_track") or "").lower() == "goblin70":
            return True
    return False


def _ticket_group_sort_rank(group_name: str) -> int:
    name = (group_name or "").upper()
    if "GOBLIN-70" in name:
        return -300
    if name.startswith("NFL POWER"):
        return -250
    if " CORE " in f" {name} " or name.startswith("CORE ") or " CORE" in name:
        return -200
    if "PROBABILITY LADDER" in name:
        return -100
    sk = _group_sport(group_name)
    return _TICKET_GROUP_SPORT_SORT_ORDER.get(sk, 999)


def _ticket_group_picktype_rank(group_name: str) -> int:
    """Order within a sport: Core, Standard, Goblin, Mixed, then everything else."""
    name = (group_name or "").upper().replace("\u00a0", " ")
    if " CORE " in f" {name} " or "CORE POWER" in name or "CORE FLEX" in name or "CORE STANDARD" in name:
        return -1
    if " STANDARD" in name:
        return 0
    if " GOBLIN" in name:
        return 1
    if " MIXED" in name:
        return 2
    return 9


def _ticket_group_leg_count(group_name: str) -> int:
    """Extract N from labels like '... 4-Leg #12' for stable ordering."""
    m = re.search(r"(\d+)\s*-\s*LEG", str(group_name or ""), flags=re.IGNORECASE)
    if not m:
        return 99
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return 99


def _ticket_group_serial(group_name: str) -> int:
    """Extract trailing #number if present."""
    m = re.search(r"#\s*(\d+)\s*$", str(group_name or ""))
    if not m:
        return 999_999
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return 999_999


_EV_REC_RANK = {"LOW": 0, "SKIP": 0, "MARGINAL": 1, "OK": 2, "STRONG": 3}


def _group_payout_confidence_score(tickets: list) -> float:
    """Max payout_confidence_score (sweep × p_all_win) across slips in a group."""
    best = 0.0
    for t in tickets:
        if not isinstance(t, dict):
            continue
        p = t.get("payout")
        if not isinstance(p, dict):
            continue
        raw = p.get("payout_confidence_score")
        if raw is None:
            continue
        try:
            v = float(raw)
            if math.isfinite(v) and v > best:
                best = v
        except (TypeError, ValueError):
            continue
    return best


def _slip_display_payout_multiplier(
    payout: dict | None, ticket: dict, group: dict
) -> float | None:
    """
    Headline multiplier for slip UI — always the scraped / min-guarantee lock.

    Never prefer Fantasy ``sweep_payout`` jackpots (poisoned Goblin 6×/20×/40×).
    """
    if isinstance(payout, dict):
        for k in (
            "power_min_x",
            "display_min_x",
            "payout",
            "min_guarantee",
            "min_payout_x",
        ):
            v = payout.get(k)
            if v is not None:
                try:
                    vf = float(v)
                    if math.isfinite(vf) and vf > 0:
                        return vf
                except (TypeError, ValueError):
                    pass
    for k in ("display_min_x", "power_min_x", "min_payout_x", "power_payout", "flex_payout"):
        v = ticket.get(k)
        if v is None:
            v = group.get(k)
        if v is not None:
            try:
                vf = float(v)
                if math.isfinite(vf) and vf > 0:
                    return vf
            except (TypeError, ValueError):
                pass
    return None


def _ticket_group_filter_slugs(
    group_name: str,
    tickets: list | None = None,
) -> tuple[str, str, str]:
    """(data_sport, data_type, data_pick) lowercase slugs for /tickets filter pills."""
    name_u = (group_name or "").upper().replace("\u00a0", " ")
    sport_key = _group_sport(group_name, tickets)
    sports: list[str] = []
    seen: set[str] = set()
    for token in (sport_key or "").replace("/", " ").split():
        sl = token.strip().lower()
        if sl and sl not in seen:
            seen.add(sl)
            sports.append(sl)
    for t in tickets or []:
        if not isinstance(t, dict):
            continue
        for leg in t.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            sl = str(leg.get("sport") or "").strip().lower()
            if sl and sl not in seen:
                seen.add(sl)
                sports.append(sl)
    sport_sl = " ".join(sports) if sports else sport_key.lower()

    if " FLEX" in name_u or name_u.startswith("FLEX ") or " FLEX " in name_u:
        type_sl = "flex"
    elif "POWER" in name_u:
        type_sl = "power"
    else:
        type_sl = "power"

    if "GOBLIN" in name_u:
        pick_sl = "goblin"
    elif "DEMON" in name_u:
        pick_sl = "demon"
    else:
        pick_sl = "standard"

    return sport_sl, type_sl, pick_sl


def _group_ev_data_attr(tickets: list) -> str:
    """Strongest empirical payout recommendation across tickets in the group."""
    best_r = -1
    best_sl = ""
    for t in tickets:
        p = t.get("payout")
        if not isinstance(p, dict):
            continue
        rec = str(p.get("recommendation") or "").strip().upper()
        r = _EV_REC_RANK.get(rec, -1)
        if r > best_r:
            best_r = r
            best_sl = rec.lower() if rec in _EV_REC_RANK else ""
    return best_sl


def _group_ev_badge_summary_html(tickets: list) -> str:
    """Header line: best empirical EV among tickets with payout JSON."""
    best: tuple[float, str, str] | None = None
    for t in tickets:
        p = t.get("payout")
        if not isinstance(p, dict) or p.get("ev") is None:
            continue
        try:
            evf = float(p["ev"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(evf):
            continue
        rec = str(p.get("recommendation") or "")
        ev_cls = _payout_ev_class(rec)
        if best is None or evf > best[0]:
            best = (evf, rec, ev_cls)
    if best is None:
        return '<span class="group-ev-badge group-ev-badge--na">—</span>'
    evf, rec, ev_cls = best
    return f'<span class="group-ev-badge {ev_cls}">EV {_fmt(evf, 2)} — {_h(rec)}</span>'


def _group_hit_rate_score(tickets: list) -> float:
    vals: list[float] = []
    for t in tickets:
        if not isinstance(t, dict):
            continue
        v = t.get("avg_hit_rate")
        if v is None:
            continue
        try:
            vf = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(vf):
            vals.append(vf)
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))


def _tickets_filter_pills_html(attr_rows: list[dict], *, slate_date: str = "") -> str:
    """Dynamic filter bar from group-derived slugs (sport / power / flex / goblin / demon / strong)."""
    sports_seen: list[str] = []
    seen_sp: set[str] = set()
    has_power = has_flex = has_goblin = has_demon = has_strong = False
    for row in attr_rows:
        sp = str(row.get("sport") or "").strip().lower()
        for token in sp.split():
            tok = token.strip().lower()
            if tok in ("mix", "cross", "strong"):
                continue
            if tok and tok not in seen_sp:
                seen_sp.add(tok)
                sports_seen.append(tok)
        if row.get("type") == "power":
            has_power = True
        if row.get("type") == "flex":
            has_flex = True
        if row.get("pick") == "goblin":
            has_goblin = True
        if row.get("pick") == "demon":
            has_demon = True
        if row.get("ev") == "strong":
            has_strong = True

    sport_order = (
        "nba",
        "nba1q",
        "nba1h",
        "wnba",
        "cbb",
        "wcbb",
        "nfl",
        "cfb",
        "nhl",
        "mlb",
        "soccer",
        "tennis",
        "cross",
        "mix",
    )
    sports_sorted = sorted(
        sports_seen,
        key=lambda s: (sport_order.index(s) if s in sport_order else 99, s),
    )

    def _pill(
        data_filter: str,
        label: str,
        *,
        active: bool = False,
        title_attr: str = "",
    ) -> str:
        cls = "ticket-filter-pill active" if active else "ticket-filter-pill"
        return (
            f'<button type="button" class="{cls}" data-filter="{_h(data_filter)}"'
            f"{title_attr}>{label}</button>"
        )

    chunks: list[str] = [
        '<div class="ticket-filter-bar" role="toolbar" aria-label="Filter ticket groups">',
        _pill("all", "ALL", active=True),
    ]
    for sp in sports_sorted:
        chunks.append(_pill(sp, sp.upper()))
    chunks.append(_pill("pp", "PP", title_attr=' title="Any leg priced from PrizePicks row"'))
    chunks.append(_pill("ud", "UD", title_attr=' title="Any leg from Underdog-only ladder row"'))
    chunks.append(_pill("dk", "DK", title_attr=' title="Any leg from DraftKings-only ladder row"'))
    if has_power:
        chunks.append(_pill("power", "POWER"))
    if has_flex:
        chunks.append(_pill("flex", "FLEX"))
    if has_goblin:
        chunks.append(_pill("goblin", "GOBLIN"))
    if has_demon:
        chunks.append(_pill("demon", "DEMON"))
    if has_strong:
        chunks.append(_pill("strong", "⚡ STRONG"))
    chunks.append(
        _pill(
            "top-payout",
            "🏆 TOP PAYOUT",
            title_attr=' title="Highest payout × win probability (top 3 groups)"',
        )
    )
    chunks.append(
        '<label class="ticket-filter-sort-wrap" for="ticket-sort-select">'
        '<span class="ticket-filter-sort-label">Sort</span>'
        '<select id="ticket-sort-select" class="ticket-filter-sort">'
        '<option value="ev_desc" selected>EV ↓</option>'
        '<option value="ev_asc">EV ↑</option>'
        '<option value="pwin_desc">P(WIN) ↓</option>'
        '<option value="pwin_asc">P(WIN) ↑</option>'
        '<option value="legs_desc">Legs ↓</option>'
        '<option value="group">Group #</option>'
        '<option value="hit_rate">Hit Rate</option>'
        '</select>'
        '</label>'
    )
    chunks.append(
        '<button type="button" class="ticket-filter-bar-action active" id="toggle-skip" '
        'style="border-radius:999px;" aria-pressed="true">SHOW SKIP</button>'
    )
    chunks.append('<button type="button" class="ticket-filter-bar-action" id="expand-all" style="border-radius:999px;">EXPAND ALL</button>')
    chunks.append('<button type="button" class="ticket-filter-bar-action" id="collapse-all" style="border-radius:999px;">COLLAPSE ALL</button>')
    chunks.append("</div>")
    return "".join(chunks)


def _tickets_fmt_line_plain(x) -> str:
    try:
        if x is None:
            return "—"
        xf = float(x)
        if abs(xf - round(xf)) < 1e-9:
            return str(int(round(xf)))
        return f"{xf:.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(x) if x is not None else "—"


def _ticket_fingerprint(legs) -> str:
    """Stable id for Placed checkboxes: sorted player|prop|line|dir."""
    parts: list[str] = []
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        player = str(leg.get("player") or "").strip().lower()
        if not player:
            continue
        prop = str(leg.get("prop_type") or "").strip().lower()
        line = _tickets_fmt_line_plain(leg.get("line"))
        direction = str(leg.get("direction") or "").strip().upper()
        if direction == "LOWER":
            direction = "UNDER"
        parts.append(f"{player}|{prop}|{line}|{direction}")
    parts.sort()
    return ";".join(parts)


def _tickets_leg_parse_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    try:
        xf = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return xf


def _tickets_leg_game_log_table_html(leg: dict) -> str:
    """
    Per-game posted line (line_g*) + actual (stat_g* / g*) — replaces hit/miss bar chart.
    """
    dir_u = str(leg.get("direction") or "").strip().upper()
    rows_html: list[str] = []
    for gi in range(1, 11):
        raw_stat = leg.get(f"stat_g{gi}")
        if raw_stat is None:
            raw_stat = leg.get(f"g{gi}")
        act = _tickets_leg_parse_float(raw_stat)
        ln_raw = leg.get(f"line_g{gi}")
        if ln_raw is None:
            ln_raw = leg.get(f"prop_line_g{gi}")
        line_at_game = _tickets_leg_parse_float(ln_raw)
        if act is None and line_at_game is None:
            continue
        act_disp = _tickets_fmt_line_plain(act) if act is not None else "—"
        line_disp = _tickets_fmt_line_plain(line_at_game) if line_at_game is not None else "—"
        res_disp = "—"
        res_cls = ""
        if act is not None and line_at_game is not None:
            if dir_u == "UNDER":
                ok = act <= line_at_game
            elif dir_u == "OVER":
                ok = act >= line_at_game
            else:
                ok = act >= line_at_game
            res_disp = "Hit" if ok else "Miss"
            res_cls = "leg-game-hit" if ok else "leg-game-miss"
        rows_html.append(
            f"<tr><td>{_h('G' + str(gi))}</td><td>{_h(line_disp)}</td><td>{_h(act_disp)}</td>"
            f'<td class="{res_cls}">{_h(res_disp)}</td></tr>'
        )
    if not rows_html:
        return (
            '<p class="leg-game-log-empty">No per-game line / actual series saved for this leg '
            "(stat_g1.. / line_g1..).</p>"
        )
    return (
        '<table class="leg-game-log" role="grid" aria-label="Recent games vs posted line">'
        "<thead><tr>"
        "<th>Game</th><th>Posted line</th><th>Actual</th><th>vs pick</th>"
        "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )


def _tickets_leg_graph_row_html(leg: dict, row_id: str, table_cols: int) -> str:
    """Expandable row: stat pills + per-game line/actual table (tickets_built.html)."""
    l5_avg = leg.get("l5_avg")
    season_avg = leg.get("season_avg")
    l5_over = leg.get("l5_over")
    l5_under = leg.get("l5_under")
    l10_over = leg.get("l10_over")
    l10_under = leg.get("l10_under")
    line_val = leg.get("line")
    dir_txt = str(leg.get("direction") or "").upper()
    hr_val = leg.get("hit_rate")

    def _pill(label: str, val, fmt=None) -> str:
        if val is None:
            return ""
        if fmt:
            try:
                v = fmt(val)
            except Exception:
                v = str(val)
        else:
            v = str(val)
        return f'<div class="gstat"><div class="gstat-label">{_h(label)}</div><div class="gstat-val">{_h(v)}</div></div>'

    pills = "".join(
        [
            _pill("L5 Avg", l5_avg, lambda x: f"{float(x):.1f}"),
            _pill("Season Avg", season_avg, lambda x: f"{float(x):.1f}"),
            _pill("L5 Over", l5_over, lambda x: format_hit_window_fraction(5, x)),
            _pill("L5 Under", l5_under, lambda x: format_hit_window_fraction(5, x)),
            _pill("L10 Over", l10_over, lambda x: format_hit_window_fraction(10, x)),
            _pill("L10 Under", l10_under, lambda x: format_hit_window_fraction(10, x)),
            _pill("L10 Streak", leg.get("l10_streak")),
            _pill("Hit Rate", hr_val, lambda x: f"{float(x) * 100:.0f}%"),
        ]
    )

    game_log_html = _tickets_leg_game_log_table_html(leg)
    sub = f"{leg.get('player', '')} · {leg.get('prop_type', '')} · Line {_tickets_fmt_line_plain(line_val)}"
    return f"""
<tr class="leg-graph-row" id="{_h(row_id)}">
  <td class="leg-graph-cell" colspan="{table_cols}">
    <div class="graph-wrap">
      <div style="flex:1;min-width:200px;">
        <div style="font-size:11px;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px;">{_h(sub)}</div>
        <div class="graph-stats">{pills}</div>
      </div>
      <div class="leg-game-log-wrap">
        {game_log_html}
      </div>
    </div>
  </td>
</tr>"""

def _winrate_best_leg_label(leg: dict) -> str:
    """One-line leg summary for Today's Best panel: player, prop, direction, line."""
    player = str(leg.get("player") or "").strip()
    prop = str(leg.get("prop_type") or leg.get("prop") or "").strip()
    direction = str(leg.get("direction") or "").strip().upper()
    if direction == "LOWER":
        direction = "UNDER"
    line_s = _tickets_fmt_line_plain(leg.get("line"))

    detail: list[str] = []
    if prop:
        detail.append(prop)
    if direction and line_s != "—":
        dir_short = "O" if direction in ("OVER", "O") else ("U" if direction in ("UNDER", "U") else direction)
        detail.append(f"{dir_short} {line_s}")
    elif line_s != "—":
        detail.append(line_s)
    elif direction:
        detail.append(direction)

    if player and detail:
        return f"{player} — {' · '.join(detail)}"
    if player:
        return player
    if detail:
        return " · ".join(detail)
    return "—"


def _winrate_best_panel_html(winrate_payload: dict | None = None) -> str:
    """Pinned panel: top 5 win-rate tickets (sorted by est_win_prob, bench legs filtered)."""
    _placeholder = (
        '<motionless class="winrate-best-panel" id="winrate-best-panel" aria-live="polite">'
        '<motionless class="winrate-best-title">⚡ HIGH LEG HR</motionless>'
        '<motionless class="winrate-best-sub">High-leg-HR tickets generating…</motionless>'
        "</motionless>"
    ).replace("motionless", "div")
    data = winrate_payload
    if data is None:
        path = Path(REPO_ROOT) / "ui_runner" / "templates" / "tickets_winrate_latest.json"
        if not path.is_file():
            return _placeholder
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return _placeholder
    generated_at = str((data or {}).get("generated_at") or "")
    flat: list[tuple[float, dict, str]] = []
    for g in (data or {}).get("groups") or []:
        gn = str(g.get("group_name") or "Ticket")
        for t in g.get("tickets") or []:
            if not isinstance(t, dict):
                continue
            if _winrate_ticket_construction_reject(t):
                continue
            if any(_winrate_leg_bench_risk(leg) for leg in (t.get("legs") or []) if isinstance(leg, dict)):
                continue
            flat.append((_winrate_ticket_rank_score(t), t, gn))
    flat.sort(key=lambda x: -x[0])
    top = flat[:5]
    if not top:
        return (
            '<div class="winrate-best-panel" id="winrate-best-panel">'
            '<div class="winrate-best-title">⚡ HIGH LEG HR</div>'
            '<div class="winrate-best-sub">No qualifying high-leg-HR tickets for this slate '
            '(deep-bench SUPPORT legs and same-game bench stacks are excluded). '
            'These legs can still appear on graded main. Rebuild after the next ticket run.</div>'
            "</div>"
        )
    rows: list[str] = []
    for i, (rank_score, t, gn) in enumerate(top, start=1):
        legs = t.get("legs") or []
        leg_lines: list[str] = []
        for leg in legs:
            if isinstance(leg, dict):
                lbl = _winrate_best_leg_label(leg)
                if lbl and lbl != "—":
                    leg_lines.append(f'<div class="winrate-best-leg">{_h(lbl)}</div>')
        legs_html = "".join(leg_lines) if leg_lines else '<div class="winrate-best-leg">—</div>'
        n_legs = len(legs) or t.get("n_legs") or 0
        ev_v = t.get("ev_power")
        if ev_v is None and isinstance(t.get("payout"), dict):
            ev_v = (t.get("payout") or {}).get("ev")
        try:
            ev_f = float(ev_v) if ev_v is not None else 0.0
        except (TypeError, ValueError):
            ev_f = 0.0
        pay = t.get("payout_multiplier") or t.get("power_payout")
        try:
            pay_f = float(pay) if pay is not None else 0.0
        except (TypeError, ValueError):
            pay_f = 0.0
        pwin = _winrate_ticket_win_prob(t)
        pcash_opt = _winrate_ticket_panel_pcash_optional(t)
        pwin_sub = ""
        if pcash_opt is not None:
            pwin_sub = (
                f'<div class="winrate-best-pwin-sub">P(cash) {_fmt(pcash_opt * 100, 0)}%</div>'
            )
        rows.append(
            f'<div class="winrate-best-row" data-winrate-rank="{i}" role="button" tabindex="0">'
            f'<span class="winrate-best-rank">#{i}</span>'
            f'<span class="winrate-best-name">{_h(gn)}'
            f'<div class="winrate-best-legs">{legs_html}</div>'
            f'</span>'
            f'<span class="winrate-best-stats">'
            f'<div class="winrate-best-pwin">P(win) {_fmt(pwin * 100, 0)}%</div>'
            f'{pwin_sub}'
            f'<div>EV {_fmt(ev_f, 1)} · Payout {_fmt(pay_f, 1)}x · {int(n_legs)}-leg</div>'
            f"</span></div>"
        )
    sub_parts = ["High-leg HR spotlight · also eligible on graded main · sorted by modeled win probability"]
    if generated_at:
        sub_parts.append(f"Updated: {generated_at}")
    sub = _h(" · ".join(sub_parts))
    body = "".join(rows)
    return (
        '<div class="winrate-best-panel" id="winrate-best-panel">'
        '<div class="winrate-best-title">⚡ HIGH LEG HR</div>'
        f'<div class="winrate-best-sub">{sub}</div>'
        f"{body}"
        "</div>"
    )


def _group_max_ev_for_ui_cap(group: dict) -> float:
    best = float("-inf")
    for t in group.get("tickets") or []:
        if not isinstance(t, dict):
            continue
        for key in ("ev_power", "est_ev"):
            v = t.get(key)
            if v is None:
                continue
            try:
                vf = float(v)
                if math.isfinite(vf):
                    best = max(best, vf)
            except (TypeError, ValueError):
                pass
        p = t.get("payout")
        if isinstance(p, dict) and p.get("ev") is not None:
            try:
                vf = float(p["ev"])
                if math.isfinite(vf):
                    best = max(best, vf)
            except (TypeError, ValueError):
                pass
    return float(best) if math.isfinite(best) else 0.0


def _parse_ui_group_bucket(group_name: str) -> tuple[str, str, int] | None:
    """Return (sport_key, Standard|Goblin|Mixed, n_legs) for exhaustive group names."""
    gn = (group_name or "").strip()
    m = re.match(r"^(.+?)\s+(Standard|Goblin|Mixed)\s+(\d+)-Leg", gn, flags=re.I)
    if not m:
        return None
    sport_raw = m.group(1).strip()
    pool = str(m.group(2) or "").strip().title()
    n = int(m.group(3))
    su = sport_raw.upper()
    sport_key = "X-Sport" if su.startswith("X-SPORT") else sport_raw.upper()
    return (sport_key, pool, n)


def _cap_ticket_groups_for_ui(groups: list, max_per_bucket: int) -> tuple[list, int, int]:
    """
    Keep the top ``max_per_bucket`` groups per (sport, pick-type bucket, n_legs) by max slip EV.
    Groups that do not match the name pattern are kept. Full JSON is unchanged; this is HTML-only.
    """
    if max_per_bucket <= 0 or not groups:
        return list(groups), len(groups), len(groups)
    buckets: dict[tuple[str, str, int], list[tuple[float, int, dict]]] = defaultdict(list)
    unbucketed: list[dict] = []
    for i, g in enumerate(groups):
        if not isinstance(g, dict):
            continue
        gn = str(g.get("group_name") or "")
        b = _parse_ui_group_bucket(gn)
        ev = _group_max_ev_for_ui_cap(g)
        if b is None:
            unbucketed.append(g)
            continue
        buckets[b].append((ev, i, g))
    out: list[dict] = []
    for _b, items in buckets.items():
        items.sort(key=lambda x: (-x[0], x[1]))
        out.extend([t[2] for t in items[:max_per_bucket]])
    out.extend(unbucketed)

    def _orig_order(g: dict) -> int:
        try:
            return groups.index(g)
        except ValueError:
            return 0

    out.sort(
        key=lambda g: (
            _ticket_group_sort_rank(str(g.get("group_name") or "")),
            _orig_order(g),
        )
    )
    return out, len(groups), len(out)


def _ticket_group_platforms_attr(group: dict) -> str:
    """Space-separated slugs for filter bar: pp, ud, dk."""
    slugs: set[str] = set()
    for t in group.get("tickets") or []:
        for leg in t.get("legs") or []:
            plat = str(leg.get("pick_platform") or "prizepicks").lower().strip()
            if plat == "underdog":
                slugs.add("ud")
            elif plat == "draftkings":
                slugs.add("dk")
            else:
                slugs.add("pp")
    return " ".join(sorted(slugs))


def render_tickets_body_html(
    payload: dict,
    *,
    _non_ev_slips_removed: int = 0,
    winrate_payload: dict | None = None,
) -> tuple[str, str]:
    """
    Render ticket slips from tickets_latest.json payload.
    Returns (body_html, page_title) for injection into tickets_built.html.
    """
    import copy

    payload = copy.deepcopy(payload)
    _finalize_payload_l10_streaks(payload)

    def safe_str(val, default: str = "") -> str:
        if val is None:
            return default
        s = str(val).strip()
        if s.lower() in ("nan", "none", "nat", "null"):
            return default
        return s

    date_declared_raw = (payload.get("date") or "").strip()
    date_declared = date_declared_raw[:10] if len(date_declared_raw) >= 10 else date_declared_raw
    generated_at = payload.get("generated_at") or ""
    groups_all = list(payload.get("groups") or [])
    _ui_cap_raw = os.getenv("PROPORACLE_TICKETS_UI_MAX_GROUPS_PER_BUCKET", "10").strip()
    try:
        _ui_cap = int(_ui_cap_raw) if _ui_cap_raw else 0
    except ValueError:
        _ui_cap = 10
    _ui_cap_note = ""
    if _ui_cap > 0:
        groups, _n_g_full, _n_g_show = _cap_ticket_groups_for_ui(groups_all, _ui_cap)
        if _n_g_show < _n_g_full:
            _ui_cap_note = (
                f' &nbsp;·&nbsp; <span style="opacity:.85;font-size:12px;">'
                f"Showing {_n_g_show} of {_n_g_full} groups</span>"
            )
    else:
        groups = groups_all
    n_slips = sum(len(g.get("tickets") or []) for g in groups)
    n_groups = len(groups)

    def _calendar_date_from_game_time(gs: str) -> str | None:
        """Calendar YYYY-MM-DD from mixed game_time strings."""
        s = (gs or "").strip()
        if not s:
            return None
        candidates = [s]
        if " " in s and "T" not in s.split(" ", 1)[0]:
            candidates.append(s.replace(" ", "T", 1))
        for cand in candidates:
            try:
                c2 = cand.replace("Z", "+00:00") if cand.endswith("Z") else cand
                dt = datetime.fromisoformat(c2)
                return dt.date().isoformat()
            except ValueError:
                continue
        mmdd = re.match(r"^\s*(\d{1,2})/(\d{1,2})\b", s)
        if mmdd and len(date_declared) >= 4 and date_declared[:4].isdigit():
            y = int(date_declared[:4])
            m = int(mmdd.group(1))
            d = int(mmdd.group(2))
            if 1 <= m <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{m:02d}-{d:02d}"
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            head = s[:10]
            if head[0:4].isdigit() and head[5:7].isdigit() and head[8:10].isdigit():
                return head
        return None

    def _modal_slate_date_from_legs(p: dict) -> str | None:
        counts: dict[str, int] = {}
        for g in p.get("groups") or []:
            for t in g.get("tickets") or []:
                for leg in t.get("legs") or []:
                    cd = _calendar_date_from_game_time(str(leg.get("game_time") or ""))
                    if cd:
                        counts[cd] = counts.get(cd, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]

    date_from_legs = _modal_slate_date_from_legs({**payload, "groups": groups_all})
    # Header date should reflect the pipeline target date (file date),
    # not the surviving leg subset date after sport-specific fallbacks.
    date_str = date_declared or date_from_legs or "Today"
    date_note_html = ""
    if date_from_legs and date_declared and date_from_legs != date_declared:
        date_note_html = (
            f' <span style="opacity:.7;font-size:12px;">(file date {_h(date_declared)})</span>'
        )

    page_title = f"PropOracle Tickets — {date_str}"

    parts: list[str] = []
    parts.append(f'<div class="tickets-built shell" data-slate-date="{_h(date_declared or date_str)}">')
    parts.append(_TICKETS_BUILT_PAYOUT_CSS)

    # ── Hero ──────────────────────────────────────────────────────────────────
    built_html = (
        f'<span class="hero-meta-built">{_h(generated_at)}</span>' if generated_at else ""
    )
    if _non_ev_slips_removed > 0:
        counts_line = (
            f"{n_groups} groups &nbsp;·&nbsp; {n_slips} +EV slips "
            f"&nbsp;·&nbsp; <span style=\"color:var(--muted);\">{_non_ev_slips_removed} non-EV filtered</span>"
        )
    else:
        counts_line = f"{n_groups} groups &nbsp;·&nbsp; {n_slips} slips"
    counts_line += _ui_cap_note
    _track = str(payload.get("ticket_track") or payload.get("mode") or "").lower()
    _hero_eyebrow = "Today&rsquo;s Picks"
    if "goblin70" in _track and "graded_main" in _track:
        _hero_eyebrow = "Goblin-70 + Graded Main"
    elif _track in ("graded_main", "main"):
        _hero_eyebrow = "Graded Main Slate"
    elif "goblin70" in _track:
        _hero_eyebrow = "Goblin-70 + Graded Main" if payload.get("tracks") else "Goblin-70"
    parts.append(f'''
<div class="hero tickets-hero" style="margin-bottom:24px;">
  <div class="hero-copy">
    <div class="hero-eyebrow" style="font-size:11px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-bottom:8px;">{_hero_eyebrow}</div>
    <h1 class="hero-title" style="font-family:'Bebas Neue',sans-serif;font-size:clamp(32px,5vw,56px);letter-spacing:0.06em;line-height:1.05;color:var(--text);margin:0;">
      PROP<span class="hero-oracle-em">ORACLE</span>&nbsp;TICKETS
    </h1>
  </div>
  <div class="hero-meta-row" role="group" aria-label="Slate summary">
    <span class="hero-meta-date">{_h(date_str)}{date_note_html}</span>
    <span class="hero-meta-counts">{counts_line}</span>
    {built_html}
  </div>
</div>''')

    if not groups:
        exclude = [
            str(s).strip().upper()
            for s in (payload.get("main_exclude_sports") or [])
            if str(s).strip()
        ]
        legs_checked = 0
        try:
            legs_checked = int((payload.get("strong_gate_stats") or {}).get("legs_checked") or 0)
        except (TypeError, ValueError):
            legs_checked = 0
        excl_note = ""
        if exclude:
            short = ", ".join(exclude[:6])
            if len(exclude) > 6:
                short += "…"
            excl_note = f" Main track excludes {short}."
        if legs_checked == 0:
            reason = (
                f"No tickets generated for {_h(date_str)} — no eligible main-slate legs "
                f"(WNBA/NBA empty or board only had excluded sports).{excl_note}"
            )
        else:
            reason = (
                f"No tickets generated for {_h(date_str)} "
                f"({legs_checked} legs checked; none formed slips).{excl_note}"
            )
        parts.append(
            '<div class="tickets-empty-board" role="status" '
            'style="margin:8px 0 24px;padding:22px 20px;border-radius:14px;'
            "border:1px solid rgba(212,175,55,0.22);background:rgba(20,20,20,0.55);"
            'text-align:center;max-width:640px;">'
            f'<div style="font-family:\'Bebas Neue\',sans-serif;font-size:28px;letter-spacing:0.06em;'
            f'color:var(--text);margin-bottom:8px;">No tickets for {_h(date_str)}</div>'
            f'<p style="font-family:Inter,sans-serif;font-size:13px;line-height:1.45;'
            f'color:var(--muted);margin:0 0 14px;">{reason}</p>'
            '<a href="/" style="display:inline-flex;align-items:center;gap:6px;'
            "padding:9px 14px;border-radius:10px;font-size:12px;font-weight:600;"
            "letter-spacing:0.04em;text-decoration:none;color:var(--accent);"
            'border:1px solid rgba(212,175,55,0.4);background:rgba(212,175,55,0.1);">'
            "← Back to home</a>"
            "</div>"
        )
        parts.append("</div>")
        return "".join(parts), page_title

    parts.append(_winrate_best_panel_html(winrate_payload))

    # ── Groups ────────────────────────────────────────────────────────────────
    leg_graph_uid = 0
    table_cols = 13

    prepared: list[dict] = []
    for original_index, group in enumerate(groups):
        tickets = group.get("tickets") or []
        if not tickets:
            continue
        gn = group.get("group_name") or "Tickets"
        ds, dt, dpk = _ticket_group_filter_slugs(gn, tickets)
        ev_a = _group_ev_data_attr(tickets)
        pc_max = _group_payout_confidence_score(tickets)
        prepared.append(
            {
                "group": group,
                "sport": ds,
                "type": dt,
                "pick": dpk,
                "ev": ev_a,
                "ev_score": _group_max_ev_for_ui_cap(group),
                "hit_score": _group_hit_rate_score(tickets),
                "p_win_score": _group_max_p_win(group),
                "original_index": original_index,
                "payout_confidence": pc_max,
            }
        )

    prepared.sort(
        key=lambda ent: (
            _ticket_group_sort_rank(str(ent["group"].get("group_name") or "")),
            -float(ent.get("ev_score") or 0.0),
            -float(ent.get("payout_confidence") or 0.0),
            -float(ent.get("hit_score") or 0.0),
            int(ent.get("original_index", 0)),
        )
    )
    # Build filter pills from the full payload (not just UI-capped groups) so
    # sports like NBA1H/WNBA remain selectable even when not in today's top-N.
    prepared_all: list[dict] = []
    for original_index, group in enumerate(groups_all):
        tickets = group.get("tickets") or []
        if not tickets:
            continue
        gn = group.get("group_name") or "Tickets"
        ds, dt, dpk = _ticket_group_filter_slugs(gn, tickets)
        ev_a = _group_ev_data_attr(tickets)
        prepared_all.append(
            {
                "sport": ds,
                "type": dt,
                "pick": dpk,
                "ev": ev_a,
                "ev_score": _group_max_ev_for_ui_cap(group),
                "original_index": original_index,
            }
        )
    filter_attr_rows = [
        {"sport": x["sport"], "type": x["type"], "pick": x["pick"], "ev": x["ev"]}
        for x in (prepared_all or prepared)
    ]
    parts.append(_tickets_filter_pills_html(filter_attr_rows, slate_date=date_declared or date_str))

    for ent in prepared:
        group = ent["group"]
        group_name = group.get("group_name") or "Tickets"
        n_legs = group.get("n_legs") or 0
        power_pay = group.get("power_payout")
        flex_pay = group.get("flex_payout")
        tickets = group.get("tickets") or []

        sport_key = _group_sport(group_name, tickets)
        accent = _sport_accent(sport_key)

        pay_label = ""
        if power_pay and flex_pay and abs(float(power_pay) - float(flex_pay)) > 0.01:
            pay_label = f"Power {_fmt(power_pay, 1)}× &nbsp;·&nbsp; Flex {_fmt(flex_pay, 1)}×"
        elif power_pay:
            pay_label = f"{_fmt(power_pay, 1)}×"

        group_meta_html = f'{n_legs}-leg{(" &nbsp;·&nbsp; " + pay_label) if pay_label else ""}'
        ev_badge_html = _group_ev_badge_summary_html(tickets)
        d_sport = ent["sport"]
        d_type = ent["type"]
        d_pick = ent["pick"]
        d_ev = ent["ev"]
        d_ev_score = float(ent.get("ev_score") or 0.0)
        d_hit_score = float(ent.get("hit_score") or 0.0)
        d_p_win_score = float(ent.get("p_win_score") or 0.0)
        d_pc = float(ent.get("payout_confidence") or 0.0)
        d_oi = int(ent.get("original_index", 0))
        rec_cls = d_ev if d_ev in ("strong", "ok", "marginal", "low", "skip") else "skip"
        d_plat = _ticket_group_platforms_attr(group)
        d_n_legs = int(n_legs) if n_legs else _ticket_group_leg_count(group_name)
        d_track = "goblin70" if _group_is_goblin70(group, group_name) else ""

        parts.append(f'''
<div class="ticket-group-section collapsed group-rec-{_h(rec_cls)}" data-sport="{_h(d_sport)}" data-type="{_h(d_type)}" data-pick="{_h(d_pick)}" data-ev="{_h(d_ev)}" data-ev-score="{_fmt(d_ev_score, 4)}" data-p-win="{_fmt(d_p_win_score, 6)}" data-hit-score="{_fmt(d_hit_score, 4)}" data-payout-confidence="{_fmt(d_pc, 2)}" data-n-legs="{d_n_legs}" data-original-index="{d_oi}" data-platforms="{_h(d_plat)}" data-group-name="{_h(group_name)}" data-track="{_h(d_track)}">
  <div class="ticket-group-header collapsible-header" role="button" tabindex="0" aria-expanded="false">
    <span class="group-title" style="color:{accent};">{_h(group_name)}</span>
    <span class="group-meta">{group_meta_html}</span>
    {ev_badge_html}
    <button type="button" class="ticket-copy-btn ticket-copy-btn--group" data-copy="group" title="Copy every slip in this group to paste while building on PrizePicks">Copy group</button>
    <button type="button" class="ticket-copy-btn ticket-placed-all" data-placed="group" title="Mark every slip in this group as placed on PrizePicks">Mark placed</button>
    <span class="collapse-icon" aria-hidden="true">▼</span>
  </div>
  <div class="ticket-group-body">
''')

        for ticket in tickets:
            ticket_no = ticket.get("ticket_no") or ""
            win_prob = ticket.get("est_win_prob")
            try:
                p_win_val = float(ticket.get("p_win")) if ticket.get("p_win") is not None else None
            except (TypeError, ValueError):
                p_win_val = None
            if p_win_val is None:
                try:
                    p_win_val = float(win_prob) if win_prob is not None else None
                except (TypeError, ValueError):
                    p_win_val = None
            avg_hr = ticket.get("avg_hit_rate")
            ev = ticket.get("ev_power")
            t_power_pay = ticket.get("power_payout") or ticket.get("base_power_payout")
            has_warn = ticket.get("has_data_warning", False)
            legs = ticket.get("legs") or []

            ev_f = None
            if ev is not None:
                try:
                    ev_f = float(ev)
                except (TypeError, ValueError):
                    ev_f = None

            payout = ticket.get("payout")
            hdr_brackets = ""
            payout_ok = False
            ev_emp_f = None
            if isinstance(payout, dict) and payout.get("ev") is not None:
                try:
                    ev_emp_f = float(payout["ev"])
                    payout_ok = bool(math.isfinite(ev_emp_f))
                except (TypeError, ValueError):
                    ev_emp_f = None
                    payout_ok = False
            ev_for_badge = ev_emp_f if payout_ok else ev_f
            if ev_for_badge is not None and math.isfinite(ev_for_badge):
                if ev_for_badge >= 1.50:
                    sig_cls, sig_lbl = "sig-strong", "STRONG"
                elif ev_for_badge >= 1.15:
                    sig_cls, sig_lbl = "sig-lean", "OK"
                elif ev_for_badge >= 0.80:
                    sig_cls, sig_lbl = "sig-risk", "MARGINAL"
                else:
                    sig_cls, sig_lbl = "sig-risk", "LOW"
            else:
                sig_cls, sig_lbl = "sig-lean", "—"
            display_ev = ev_emp_f if payout_ok else ev_f
            if display_ev is None:
                display_ev = 0.0
            board_pay_x = _resolve_ticket_display_min_x(
                payout if isinstance(payout, dict) else None, ticket
            )
            board_pay_src = "calibrated"
            board_captured_at = None
            if isinstance(payout, dict):
                board_pay_src = str(payout.get("payout_source") or "calibrated")
                board_captured_at = payout.get("captured_at")
            board_mult_text, board_badge_label, board_title = _board_payout_label(
                board_pay_x, board_pay_src, captured_at=board_captured_at
            )
            if payout_ok:
                rec_s = str(payout.get("recommendation") or "")
                ev_cls = _payout_ev_class(rec_s)
                pre = _payout_rec_prefix(rec_s)
                hdr_brackets = f'''
        <span class="ticket-hdr-bracket">[{_h(group_name)}]</span>
        <span class="payout-rec-badge {ev_cls}">[{_h(pre)} {_h(rec_s)} — EV {_fmt(ev_emp_f, 2)}]</span>
        {_board_payout_badge_html(board_pay_x, board_pay_src, captured_at=board_captured_at)}
        <span class="{sig_cls}" title="Empirical EV tier (fallback to modeled EV when payout block is missing)">{sig_lbl}</span>'''
            if not hdr_brackets:
                hdr_brackets = (
                    f'<span class="ticket-hdr-bracket">[{_h(group_name)}]</span>'
                    f'<span class="{sig_cls}">{sig_lbl}</span>'
                )

            kpi_payout = board_pay_x
            kpi_source = board_pay_src
            # Do not substitute model power_payout when waiting on live_cdp.
            if (
                kpi_payout is None
                and not require_live_payout_display()
                and str(kpi_source or "").strip().lower() != "pending_live"
            ):
                kpi_payout = t_power_pay
                board_mult_text, board_badge_label, board_title = _board_payout_label(
                    _safe_positive_float(kpi_payout), kpi_source, captured_at=board_captured_at
                )
            elif kpi_payout is None:
                board_mult_text, board_badge_label, board_title = _board_payout_label(
                    None, kpi_source, captured_at=board_captured_at
                )

            warn_html = ('<span class="ticket-data-warn">⚠ data warning</span>'
                         if has_warn else "")

            l10_kpi_html = _ticket_l10_kpi_html(ticket, legs)
            fp = _ticket_fingerprint(legs)

            parts.append(f'''
<div class="ticket" style="border-left:4px solid {accent};" data-group-name="{_h(group_name)}" data-ticket-no="{_h(ticket_no)}" data-fp="{_h(fp)}">
  <div class="ticket-body">
      <div class="ticket-hdr">
        <span class="ticket-no">#{_h(ticket_no)}</span>
        {hdr_brackets}
        <span class="ticket-hdr-actions">
          {warn_html}
          <label class="ticket-placed">
            <input type="checkbox" class="ticket-placed-cb" data-fp="{_h(fp)}" />
            <span>Placed</span>
          </label>
          <button type="button" class="ticket-copy-btn" data-copy="ticket" title="Copy legs to paste while building this slip on PrizePicks">Copy slip</button>
        </span>
      </div>
      <div class="kpi-row">
        <div class="kpi">
          <div class="kpi-label">Avg Leg HR</div>
          <div class="kpi-val" style="color:var(--green);">{_pct(avg_hr)}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Model Win Prob</div>
          <div class="kpi-val" style="color:var(--cyan);">{_pct(win_prob)}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">EV</div>
          <div class="kpi-val" style="color:var(--accent);" title="{_h(str((payout or {}).get('ev_formula') or 'EV = P(all)*sweep + P(miss-1)*min - 1.0'))}">{_fmt(display_ev, 2)}×</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">PAYOUT</div>
          <div class="kpi-val" title="{_h(board_title)}">{_h(board_mult_text)}</div>
          <div style="font-size:11px;color:var(--muted);margin-top:2px;">{_payout_source_badge_html(kpi_source, badge_label=board_badge_label)}</div>
        </div>{l10_kpi_html}
      </div>
      <div class="ticket-legs-table-wrapper">
      <table class="ticket-legs-table">
        <thead>
          <tr>
            <th>Player</th>
            <th>Sport</th>
            <th>Prop</th>
            <th>Line</th>
            <th>Dir</th>
            <th>Pick</th>
            <th>HR</th>
            <th>ML</th>
            <th>Edge</th>
            <th>Vs Def</th>
            <th>Best Book</th>
            <th>Best Line</th>
            <th>Edge vs PP</th>
          </tr>
        </thead>
        <tbody>''')

            for leg in legs:
                player = leg.get("player") or ""
                sport = leg.get("sport") or ""
                prop_type = leg.get("prop_type") or ""
                line = leg.get("line")
                std_line = leg.get("standard_line")
                direction = (leg.get("direction") or "").upper()
                if direction == "LOWER":
                    direction = "UNDER"
                pick_type = (leg.get("pick_type") or "").strip()
                hit_rate = leg.get("hit_rate")
                ml_prob = leg.get("ml_prob")
                edge = leg.get("edge")
                def_tier = safe_str(leg.get("def_tier"), "")
                best_book = str(leg.get("best_cross_book") or "").strip()
                best_line = leg.get("best_cross_line")
                cross_edge_vs_pp = leg.get("cross_edge_vs_pp")
                line_underdog = leg.get("line_underdog")
                line_draftkings = leg.get("line_draftkings")
                line_vegas = leg.get("line_vegas")
                team = leg.get("team") or ""
                opp = leg.get("opp") or ""
                initials = leg.get("initials") or player[:2].upper()

                # Direction badge
                dir_cls = "dir-over" if direction == "OVER" else "dir-under"
                dir_axis_cls = "direction-over" if direction == "OVER" else "direction-under"
                dir_html = f'<span class="{dir_cls}">{_h(direction)}</span>'

                # Pick type badge
                pk_lower = pick_type.lower()
                pk_color = _PICK_COLOR.get(pk_lower, "#aaa")
                pick_html = f'<span style="font-size:13px;font-weight:700;color:{pk_color};">{_h(pick_type)}</span>'

                # Line display (show goblin discount if applicable)
                if std_line and line and abs(float(std_line) - float(line)) >= 0.1:
                    line_html = f'{_fmt(line, 1)} <span style="font-size:11px;color:var(--muted);text-decoration:line-through;">{_fmt(std_line, 1)}</span>'
                else:
                    line_html = _fmt(line, 1)

                # Cross-book comparison summary (PP vs UD vs DK vs LV)
                books_avail = []
                if line is not None:
                    books_avail.append(f'PP {_fmt(line, 1)}')
                if line_underdog is not None:
                    books_avail.append(f'UD {_fmt(line_underdog, 1)}')
                if line_draftkings is not None:
                    books_avail.append(f'DK {_fmt(line_draftkings, 1)}')
                if line_vegas is not None:
                    books_avail.append(f'LV {_fmt(line_vegas, 1)}')
                line_tip = " / ".join(books_avail) if books_avail else "No cross-book lines"
                best_book_html = _h(best_book) if best_book else "—"
                best_line_html = _fmt(best_line, 1) if best_line is not None else "—"
                cross_edge_html = _fmt(cross_edge_vs_pp, 2) if cross_edge_vs_pp is not None else "—"
                cross_edge_style = "color:var(--muted);"
                try:
                    if cross_edge_vs_pp is not None and float(cross_edge_vs_pp) > 0.01:
                        cross_edge_style = "color:var(--green);font-weight:700;"
                except (TypeError, ValueError):
                    pass

                plat_raw = str(leg.get("pick_platform") or "prizepicks").lower().strip()
                if plat_raw == "underdog":
                    leg_plat_slug = "ud"
                elif plat_raw == "draftkings":
                    leg_plat_slug = "dk"
                elif plat_raw == "vegas":
                    leg_plat_slug = "lv"
                else:
                    leg_plat_slug = "pp"

                # Sport accent chip
                s_accent = _sport_accent(sport)
                sport_html = f'<span style="font-size:12px;font-weight:700;color:{s_accent};background:{s_accent}22;padding:3px 8px;border-radius:4px;border:1px solid {s_accent}44;">{_h(sport)}</span>'

                # Avatar
                av_html = f'<div class="avatar">{_h(initials)}</div>'

                # Matchup sub-label
                matchup = f"{team} vs {opp}" if team and opp else (team or opp)

                hr_disp = (
                    f"Hit rate {_pct(hit_rate)} · ML {_pct(ml_prob)} · Edge {_fmt(edge, 2)}"
                    + (f" · Def {def_tier}" if def_tier else "")
                )

                parts.append(f'''
          <tr class="leg-row" data-hr-display="{_h(hr_disp)}" data-platform="{_h(leg_plat_slug)}" data-player="{_h(player)}" data-sport="{_h(sport)}" data-prop="{_h(prop_type)}" data-line="{_h(_tickets_fmt_line_plain(line))}" data-dir="{_h(direction)}" data-pick="{_h(pick_type)}">
            <td class="leg-col leg-col-player">
              <div class="pwrap">
                {av_html}
                <div>
                  <div style="font-weight:600;font-size:14px;">{_h(player)}{_l10_streak_badge_html(leg)}{_cons_line_badge_html(leg)}</div>
                  <div style="font-size:12px;color:var(--muted);">{_h(matchup)}</div>
                </div>
              </div>
            </td>
            <td class="leg-col leg-col-sport hide-mobile">{sport_html}</td>
            <td class="leg-col leg-col-prop" style="color:var(--text);font-weight:500;">{_h(prop_type)}</td>
            <td class="leg-col leg-col-line" style="font-family:'Inter',sans-serif;">{line_html}</td>
            <td class="leg-col leg-col-dir direction-cell {dir_axis_cls}">{dir_html}</td>
            <td class="leg-col leg-col-pick">{pick_html}</td>
            <td class="leg-col leg-col-hr hide-mobile" style="font-family:'Inter',sans-serif;color:var(--green);">{_pct(hit_rate)}</td>
            <td class="leg-col leg-col-ml hide-mobile" style="font-family:'Inter',sans-serif;color:var(--cyan);">{_pct(ml_prob)}</td>
            <td class="leg-col leg-col-edge hide-mobile" style="font-family:'Inter',sans-serif;color:var(--accent);">{_fmt(edge, 2)}</td>
            <td class="leg-col leg-col-def hide-mobile" style="font-size:13px;color:var(--muted);">{_h(def_tier)}</td>
            <td class="leg-col leg-col-book hide-mobile" style="font-family:'Inter',sans-serif;color:var(--cyan);" title="{_h(line_tip)}">{best_book_html}</td>
            <td class="leg-col leg-col-bl hide-mobile" style="font-family:'Inter',sans-serif;" title="{_h(line_tip)}">{best_line_html}</td>
            <td class="leg-col leg-col-ce hide-mobile" style="font-family:'Inter',sans-serif;{cross_edge_style}" title="Positive means better line than PP for this direction">{cross_edge_html}</td>
          </tr>''')
                leg_graph_uid += 1
                parts.append(_tickets_leg_graph_row_html(leg, f"lgr-{leg_graph_uid}", table_cols))

            payout_section = ""
            if payout_ok and isinstance(payout, dict):
                try:
                    p_all = float(payout["p_all_win"])
                except (TypeError, ValueError, KeyError):
                    p_all = 0.0
                rec_s2 = str(payout.get("recommendation") or "")
                ev_cls_row = _payout_ev_class(rec_s2)
                try:
                    ev_disp = float(payout["ev"])
                except (TypeError, ValueError):
                    ev_disp = 0.0
                psrc2 = str(payout.get("payout_source") or board_pay_src or "calibrated")
                board_x = _resolve_ticket_display_min_x(payout, ticket)
                if board_x is None:
                    board_x = _safe_positive_float(kpi_payout)
                mult_text, badge_label, title = _board_payout_label(
                    board_x, psrc2, captured_at=payout.get("captured_at") or board_captured_at
                )
                try:
                    e10 = round(10.0 * float(board_x), 2) if board_x is not None else None
                except (TypeError, ValueError):
                    e10 = None
                pre_ev = _payout_rec_prefix(rec_s2)
                dollar_html = (
                    f"$10 &rarr; ${_fmt(e10, 2)}"
                    if e10 is not None
                    else "$10 &rarr; —"
                )
                payout_section = f'''
      <div class="ticket-payout">
        <div class="payout-row">
          <span class="payout-label" title="{_h(title)}">Payout</span>
          <span class="payout-value" title="{_h(title)}">{_h(mult_text)}</span>
          {_payout_source_badge_html(psrc2, badge_label=badge_label)}
        </div>
        <div class="payout-row">
          <span class="payout-label">P(Win)</span>
          <span class="payout-value">{_fmt(p_all * 100, 1)}%</span>
        </div>
        <div class="payout-row">
          <span class="payout-label">EV</span>
          <span class="payout-value {ev_cls_row}">{_fmt(ev_disp, 2)} &mdash; {_h(pre_ev)} {_h(rec_s2)}</span>
        </div>
        <div class="payout-entry-guide">
          <span title="{_h(title)}">{dollar_html}</span>
        </div>
      </div>'''

            parts.append(f'''
        </tbody>
      </table>
      </div>
{payout_section}
  </div>
</div>''')

        parts.append("</div></div>")  # ticket-group-body, ticket-group-section

    parts.append('</div>')  # end .tickets-built.shell

    # Inline JS: leg graphs, filter pills, collapsible groups
    parts.append('''
<script>
(function(){
  document.querySelectorAll('.tickets-built .leg-row').forEach(function(row){
    row.addEventListener('click', function(){
      var next = row.nextElementSibling;
      if(next && next.classList.contains('leg-graph-row')){
        next.classList.toggle('open');
      }
    });
  });

  var activeFilter = 'all';
  var sortMode = 'ev_desc';
  var hideSkip = true;

  function isGoblin70(group){
    var track = (group.getAttribute('data-track') || '').toLowerCase();
    if(track === 'goblin70') return true;
    var name = (group.getAttribute('data-group-name') || '').toLowerCase();
    return name.indexOf('goblin-70') >= 0 || name.indexOf('nfl power') === 0;
  }

  function parseNum(el, attr){
    var raw = (el.getAttribute(attr) || '').trim();
    var n = parseFloat(raw);
    return Number.isFinite(n) ? n : 0;
  }

  function sortGroups(groups){
    var g70 = [];
    var rest = [];
    groups.forEach(function(g){
      if(isGoblin70(g)) g70.push(g);
      else rest.push(g);
    });
    g70.sort(function(a,b){
      return parseNum(a, 'data-original-index') - parseNum(b, 'data-original-index');
    });
    function sortRest(mode){
      if(mode === 'group'){
        rest.sort(function(a,b){
          return parseNum(a, 'data-original-index') - parseNum(b, 'data-original-index');
        });
        return;
      }
      if(mode === 'ev_asc'){
        rest.sort(function(a,b){ return parseNum(a, 'data-ev-score') - parseNum(b, 'data-ev-score'); });
        return;
      }
      if(mode === 'hit_rate'){
        rest.sort(function(a,b){ return parseNum(b, 'data-hit-score') - parseNum(a, 'data-hit-score'); });
        return;
      }
      if(mode === 'pwin_desc'){
        rest.sort(function(a,b){ return parseNum(b, 'data-p-win') - parseNum(a, 'data-p-win'); });
        return;
      }
      if(mode === 'pwin_asc'){
        rest.sort(function(a,b){ return parseNum(a, 'data-p-win') - parseNum(b, 'data-p-win'); });
        return;
      }
      if(mode === 'legs_desc'){
        rest.sort(function(a,b){
          var dl = parseNum(b, 'data-n-legs') - parseNum(a, 'data-n-legs');
          if(dl !== 0) return dl;
          return parseNum(b, 'data-ev-score') - parseNum(a, 'data-ev-score');
        });
        return;
      }
      rest.sort(function(a,b){ return parseNum(b, 'data-ev-score') - parseNum(a, 'data-ev-score'); });
    }
    sortRest(sortMode);
    groups.length = 0;
    g70.concat(rest).forEach(function(g){ groups.push(g); });
  }

  function matchesFilter(group, filter){
    if(filter === 'all') return true;
    if(filter === 'top-payout') return true;
    if(filter === 'mine'){
      if(isGoblin70(group)) return true;
      var prefs = (window.__ACCOUNT_PREFERRED_GROUPS || []);
      if(!prefs.length) return true;
      var name = (group.getAttribute('data-group-name') || '').toLowerCase();
      for(var i=0;i<prefs.length;i++){
        var tok = String(prefs[i] || '').toLowerCase();
        if(tok && name.indexOf(tok) >= 0) return true;
      }
      return false;
    }
    if(filter === 'pp' || filter === 'ud' || filter === 'dk'){
      var raw = (group.getAttribute('data-platforms') || '').toLowerCase().trim();
      if(!raw) return filter === 'pp';
      var parts = raw.split(/\\s+/).filter(Boolean);
      return parts.indexOf(filter) >= 0;
    }
    var ds = (group.getAttribute('data-sport') || '').toLowerCase();
    var dt = (group.getAttribute('data-type') || '').toLowerCase();
    var dp = (group.getAttribute('data-pick') || '').toLowerCase();
    var de = (group.getAttribute('data-ev') || '').toLowerCase();
    var dsParts = ds.split(/\\s+/).filter(Boolean);
    return dsParts.indexOf(filter) >= 0 || dt === filter || dp === filter || de === filter;
  }

  function applyGroupView(){
    var shell = document.querySelector('.tickets-built.shell');
    if(!shell) return;
    var bar = shell.querySelector('.ticket-filter-bar');
    var allGroups = Array.from(shell.querySelectorAll('.ticket-group-section'));
    var visible = allGroups.filter(function(g){
      if(!matchesFilter(g, activeFilter)) return false;
      if(hideSkip && !isGoblin70(g)){
        var rec = (g.getAttribute('data-ev') || '').toLowerCase();
        if(rec === 'skip' || rec === 'low') return false;
      }
      return true;
    });

    if(activeFilter === 'top-payout'){
      visible.sort(function(a,b){
        return parseNum(b, 'data-payout-confidence') - parseNum(a, 'data-payout-confidence');
      });
      visible = visible.slice(0, 3);
    } else {
      sortGroups(visible);
    }

    allGroups.forEach(function(g){ g.style.display = 'none'; });
    var frag = document.createDocumentFragment();
    visible.forEach(function(g){ g.style.display = ''; frag.appendChild(g); });
    if(bar){
      var insertBefore = bar.nextElementSibling;
      if(insertBefore){
        shell.insertBefore(frag, insertBefore);
      } else {
        shell.appendChild(frag);
      }
    } else {
      shell.appendChild(frag);
    }
  }

  var filterBar = document.querySelector('.ticket-filter-bar');
  if(filterBar){
    filterBar.addEventListener('click', function(ev){
      var pill = ev.target.closest('.ticket-filter-pill');
      if(!pill || !filterBar.contains(pill)) return;
      filterBar.querySelectorAll('.ticket-filter-pill').forEach(function(p){ p.classList.remove('active'); });
      pill.classList.add('active');
      activeFilter = (pill.getAttribute('data-filter') || '').toLowerCase();
      applyGroupView();
    });
  }

  var sortSel = document.getElementById('ticket-sort-select');
  if(sortSel){
    sortSel.addEventListener('change', function(){
      sortMode = (sortSel.value || 'ev_desc').toLowerCase();
      applyGroupView();
    });
  }

  var tSkip = document.getElementById('toggle-skip');
  if(tSkip){
    tSkip.addEventListener('click', function(){
      hideSkip = !hideSkip;
      tSkip.classList.toggle('active', hideSkip);
      tSkip.setAttribute('aria-pressed', hideSkip ? 'true' : 'false');
      tSkip.textContent = hideSkip ? 'SHOW SKIP' : 'HIDE SKIP';
      applyGroupView();
    });
  }

  function toggleSectionCollapsed(section){
    if(!section) return;
    section.classList.toggle('collapsed');
    var hdr = section.querySelector('.collapsible-header');
    if(hdr) hdr.setAttribute('aria-expanded', section.classList.contains('collapsed') ? 'false' : 'true');
  }

  document.querySelectorAll('.tickets-built .collapsible-header').forEach(function(header){
    header.addEventListener('click', function(ev){
      if(ev.target.closest('button, a, input, select, textarea, label')) return;
      ev.preventDefault();
      toggleSectionCollapsed(header.closest('.ticket-group-section'));
    });
    header.addEventListener('keydown', function(ev){
      if(ev.target.closest('button, a, input, select, textarea, label')) return;
      if(ev.key === 'Enter' || ev.key === ' '){
        ev.preventDefault();
        toggleSectionCollapsed(header.closest('.ticket-group-section'));
      }
    });
  });

  var ex = document.getElementById('expand-all');
  if(ex) ex.addEventListener('click', function(ev){
    ev.preventDefault();
    document.querySelectorAll('.ticket-group-section').forEach(function(s){
      s.classList.remove('collapsed');
      var h = s.querySelector('.collapsible-header');
      if(h) h.setAttribute('aria-expanded', 'true');
    });
  });
  var col = document.getElementById('collapse-all');
  if(col) col.addEventListener('click', function(ev){
    ev.preventDefault();
    document.querySelectorAll('.ticket-group-section').forEach(function(s){
      s.classList.add('collapsed');
      var h = s.querySelector('.collapsible-header');
      if(h) h.setAttribute('aria-expanded', 'false');
    });
  });

  (function(){
    // Always start collapsed so /tickets opens compact on both mobile and desktop.
    function collapseAllGroups(){
      document.querySelectorAll('.ticket-group-section').forEach(function(s){
        s.classList.add('collapsed');
        var h = s.querySelector('.collapsible-header');
        if(h) h.setAttribute('aria-expanded', 'false');
      });
    }
    collapseAllGroups();
    applyGroupView();
  })();
  window.__ticketsApplyGroupView = applyGroupView;
  window.__ticketsSetFilter = function(filter){
    activeFilter = String(filter || 'all').toLowerCase();
    var bar = document.querySelector('.ticket-filter-bar');
    if(bar){
      bar.querySelectorAll('.ticket-filter-pill').forEach(function(p){
        p.classList.toggle('active', (p.getAttribute('data-filter') || '').toLowerCase() === activeFilter);
      });
    }
    applyGroupView();
  };
})();
</script>''')

    return "".join(parts), page_title
