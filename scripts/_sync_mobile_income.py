#!/usr/bin/env python3
"""Sync mobile/www/income.html from dashboard_income.html for offline bundle."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ui_runner" / "templates" / "dashboard_income.html"
DST = ROOT / "mobile" / "www" / "income.html"
OLD = DST
GRADES = ROOT / "mobile" / "www" / "grades.html"

src = SRC.read_text(encoding="utf-8")
old = OLD.read_text(encoding="utf-8") if OLD.exists() else ""
if '<nav class="snav' not in old and GRADES.exists():
    old = GRADES.read_text(encoding="utf-8")

nav_m = re.search(
    r'(<nav class="snav[\s\S]*?</nav>\s*(?:<div class="mobile-menu"[\s\S]*?</div>)?)',
    old,
)
bnav_m = re.search(r'(<nav class="mobile-bottom-nav"[\s\S]*?</nav>)', old)
nav = nav_m.group(1) if nav_m else ""
bnav = bnav_m.group(1) if bnav_m else ""
if nav:
    nav = re.sub(r'(href="income\.html" class=")[^"]*(")', r"\1active\2", nav)

content = src
content = re.sub(r"\{\%\s*set nav_active = 'income'\s*\%\}", "", content)
content = re.sub(r"\{\%\s*include\s+'_site_nav.html'\s*\%\}", nav, content)
content = content.replace('href="/static/', 'href="static/')
content = content.replace('src="/static/', 'src="static/')
content = content.replace(
    "fetch('/income/health')",
    "Promise.resolve({ ok: true, json: async () => ({ status: 'ok' }) })",
)
content = re.sub(r"\{\{.*?\}\}", "", content, flags=re.DOTALL)
content = re.sub(r"\{%.*?%\}", "", content, flags=re.DOTALL)
content = re.sub(r"\{#.*?#\}", "", content, flags=re.DOTALL)
content = re.sub(
    r'(<script id="income-daily-data" type="application/json">)[\s\S]*?(</script>)',
    r"\1[]\2",
    content,
)
content = re.sub(
    r'(<script id="income-monthly-data" type="application/json">)[\s\S]*?(</script>)',
    r"\1[]\2",
    content,
)
content = re.sub(
    r'(<script id="income-sport-all-data" type="application/json">)[\s\S]*?(</script>)',
    r"\1[]\2",
    content,
)
content = re.sub(
    r'(<script id="income-sport-daily-data" type="application/json">)[\s\S]*?(</script>)',
    r"\1[]\2",
    content,
)
content = re.sub(
    r'(<tbody id="sport-breakdown-tbody">)[\s\S]*?(</tbody>)',
    r"\1\2",
    content,
)
if bnav and "mobile-bottom-nav" not in content:
    content = content.replace("</body>", bnav + "\n</body>")

bootstrap = r"""
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
        }).filter((r) => /^\d{4}-\d{2}-\d{2}$/.test(r.date));
      }

      Promise.all([
        fetch(HISTORY_URL, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : [])).catch(() => []),
        fetch(SPORT_BREAKDOWN_URL, { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : { rows: [], monthly_rows: [], daily_rows: [] }))
          .catch(() => ({ rows: [], monthly_rows: [], daily_rows: [] })),
      ]).then(([hist, sport]) => {
        const daily = parseRows(hist);
        const monthly = Array.isArray(sport.monthly_rows) ? sport.monthly_rows : [];
        const sportAll = Array.isArray(sport.rows) ? sport.rows : [];
        const sportDaily = Array.isArray(sport.daily_rows) ? sport.daily_rows : [];
        const boot = () => {
          if (typeof window.__proporacleIncomeBoot === 'function') {
            window.__proporacleIncomeBoot(daily, monthly, sportAll, sportDaily);
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
content = content.replace("</body>", bootstrap + "\n</body>")
DST.write_text(content, encoding="utf-8")
print(f"Wrote {DST} ({len(content)} bytes)")
