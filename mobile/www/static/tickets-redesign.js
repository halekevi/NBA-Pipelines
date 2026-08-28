(function () {
  if (!document.body.classList.contains('page-tickets')) return;

  var SPORT_COLORS = {
    NBA: '#3B82F6', WNBA: '#FF8AC6', MLB: '#EF4444',
    NHL: '#06B6D4', Tennis: '#22C55E', Soccer: '#7DFF6B',
    CBB: '#F59E0B', NFL: '#6366F1', STRONG: '#D4AF37'
  };

  function sportFromTitle(title) {
    var t = (title || '').toUpperCase();
    if (t.indexOf('STRONG') !== -1) return 'STRONG';
    if (t.indexOf('WNBA') !== -1) return 'WNBA';
    if (t.indexOf('NBA') !== -1) return 'NBA';
    if (t.indexOf('MLB') !== -1) return 'MLB';
    if (t.indexOf('NHL') !== -1) return 'NHL';
    if (t.indexOf('TENNIS') !== -1) return 'Tennis';
    if (t.indexOf('SOCCER') !== -1) return 'Soccer';
    if (t.indexOf('CBB') !== -1) return 'CBB';
    if (t.indexOf('NFL') !== -1) return 'NFL';
    return null;
  }

  function waitForTickets(cb) {
    var el = document.querySelector('.tickets-built');
    if (el) { cb(el); return; }
    var obs = new MutationObserver(function () {
      var found = document.querySelector('.tickets-built');
      if (found) { obs.disconnect(); cb(found); }
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function kpiCard(val, lbl) {
    return '<div class="rd-kpi-card"><div class="rd-kpi-val">' + val + '</div><div class="rd-kpi-lbl">' + lbl + '</div></div>';
  }

  function rdSortTickets(built, sortBy) {
    built.querySelectorAll('.ticket-group-section').forEach(function (sec) {
      var body = sec.querySelector('.ticket-group-body');
      if (!body) return;
      var items = Array.from(body.children);
      var ticketItems = items.filter(function(el) {
        return el.classList.contains('ticket') || el.querySelector('.ticket');
      });
      if (!ticketItems.length) return;

      function getKpi(el, re) {
        var val = NaN;
        el.querySelectorAll('.kpi').forEach(function (kpi) {
          var lbl = kpi.querySelector('.kpi-label');
          var v   = kpi.querySelector('.kpi-val');
          if (lbl && v && re.test(lbl.textContent)) val = parseFloat(v.textContent);
        });
        return val;
      }

      ticketItems.sort(function (a, b) {
        var ta = a.classList.contains('ticket') ? a : a.querySelector('.ticket');
        var tb = b.classList.contains('ticket') ? b : b.querySelector('.ticket');
        if (!ta || !tb) return 0;
        if (sortBy === 'ev')   return getKpi(tb, /ev/i) - getKpi(ta, /ev/i);
        if (sortBy === 'pwin') return getKpi(tb, /p.win|pwin/i) - getKpi(ta, /p.win|pwin/i);
        if (sortBy === 'legs') return getKpi(tb, /legs|leg\b/i) - getKpi(ta, /legs|leg\b/i);
        return 0;
      });

      ticketItems.forEach(function (el) { body.appendChild(el); });
    });
  }

  waitForTickets(function (built) {

    /* 1. Tag sections with sport */
    built.querySelectorAll('.ticket-group-section').forEach(function (sec) {
      var header = sec.querySelector('.group-title');
      var sport = sportFromTitle(header ? header.textContent : '');
      if (sport) {
        sec.setAttribute('data-sport', sport);
        var color = SPORT_COLORS[sport] || '';
        if (color) sec.style.setProperty('--rd-sport-color', color);
      }
      /* count badge */
      var tickets = sec.querySelectorAll('.ticket');
      var hdr = sec.querySelector('.ticket-group-header');
      if (hdr && tickets.length && !hdr.querySelector('.rd-group-count')) {
        var badge = document.createElement('span');
        badge.className = 'rd-group-count';
        badge.textContent = tickets.length + ' ticket' + (tickets.length !== 1 ? 's' : '');
        var evBadge = hdr.querySelector('.group-ev-badge');
        if (evBadge) hdr.insertBefore(badge, evBadge); else hdr.appendChild(badge);
      }
    });

    /* 2. Sport dot + rec badge on each ticket */
    built.querySelectorAll('.ticket').forEach(function (t) {
      var sec = t.closest('.ticket-group-section');
      var sport = sec ? sec.getAttribute('data-sport') : null;
      var color = sport ? (SPORT_COLORS[sport] || '') : '';
      if (color) t.style.setProperty('--rd-sport-color', color);
      var hdr = t.querySelector('.ticket-hdr');
      if (hdr && sport && !hdr.querySelector('.rd-sport-dot')) {
        var dot = document.createElement('span');
        dot.className = 'rd-sport-dot';
        dot.style.background = color;
        dot.title = sport;
        hdr.insertBefore(dot, hdr.firstChild);
      }
      if (hdr && !hdr.querySelector('.rd-rec-badge')) {
        var recText = '';
        var recKpi = t.querySelector('[data-kpi="recommendation"]');
        if (recKpi) recText = recKpi.textContent.trim();
        if (!recText) {
          t.querySelectorAll('.kpi').forEach(function (kpi) {
            var lbl = kpi.querySelector('.kpi-label');
            var val = kpi.querySelector('.kpi-val');
            if (lbl && val && /rec/i.test(lbl.textContent)) recText = val.textContent.trim();
          });
        }
        if (recText) {
          var rbadge = document.createElement('span');
          var upper = recText.toUpperCase();
          rbadge.className = 'rd-rec-badge ' +
            (upper === 'STRONG' ? 'rd-rec-badge--strong' : upper === 'OK' ? 'rd-rec-badge--ok' : 'rd-rec-badge--skip');
          rbadge.textContent = upper;
          hdr.appendChild(rbadge);
        }
      }
    });

    /* 3. Summary KPI strip */
    var allTickets = built.querySelectorAll('.ticket');
    var strongCount = Array.from(allTickets).filter(function(t) {
      var r = t.querySelector('[data-kpi="recommendation"]');
      return r && /strong/i.test(r.textContent);
    }).length;
    var filterBar = built.querySelector('.ticket-filter-bar');
    if (filterBar && !built.querySelector('.rd-summary-strip')) {
      var strip = document.createElement('div');
      strip.className = 'rd-summary-strip';
      strip.innerHTML = kpiCard(built.querySelectorAll('.ticket-group-section').length, 'Groups') +
                        kpiCard(allTickets.length, 'Slips') +
                        kpiCard(strongCount, 'Strong EV');
      filterBar.parentNode.insertBefore(strip, filterBar);
    }

    /* 4. Hero strip removed — showed ticket # not props; EV sort is in filter bar. */

    /* 5. Copy slip / copy group — paste into PrizePicks search; does not submit. */
    function ticketCopyText(ticketEl) {
      if (!ticketEl) return '';
      var no = (ticketEl.getAttribute('data-ticket-no') || '').trim();
      var group = (ticketEl.getAttribute('data-group-name') || '').trim();
      var header = (group ? group : 'Ticket') + (no ? '  #' + no : '');
      var lines = [];
      ticketEl.querySelectorAll('tr.leg-row').forEach(function (row) {
        var player = (row.getAttribute('data-player') || '').trim();
        var prop = (row.getAttribute('data-prop') || '').trim();
        var dir = (row.getAttribute('data-dir') || '').trim();
        var line = (row.getAttribute('data-line') || '').trim();
        var pick = (row.getAttribute('data-pick') || '').trim();
        if (!player) return;
        var parts = [player];
        if (prop) parts.push(prop);
        if (dir) parts.push(dir);
        if (line && line !== '—') parts.push(line);
        if (pick) parts.push('(' + pick + ')');
        lines.push(parts.join('  '));
      });
      if (!lines.length) return header;
      return header + '\n' + lines.join('\n');
    }

    function groupCopyText(section) {
      if (!section) return '';
      var blocks = [];
      section.querySelectorAll('.ticket').forEach(function (t) {
        var txt = ticketCopyText(t);
        if (txt) blocks.push(txt);
      });
      return blocks.join('\n\n');
    }

    function markCopied(btn) {
      if (!btn) return;
      var prev = btn.getAttribute('data-label') || btn.textContent;
      btn.setAttribute('data-label', prev);
      btn.classList.add('is-copied');
      btn.textContent = 'Copied';
      setTimeout(function () {
        btn.classList.remove('is-copied');
        btn.textContent = btn.getAttribute('data-label') || prev;
      }, 1400);
    }

    function writeClipboard(text, btn) {
      if (!text) return;
      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); markCopied(btn); } catch (e) {}
        document.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { markCopied(btn); }).catch(fallback);
      } else {
        fallback();
      }
    }

    built.addEventListener('click', function (ev) {
      var btn = ev.target.closest('.ticket-copy-btn');
      if (!btn || !built.contains(btn)) return;
      if (btn.getAttribute('data-placed') || btn.classList.contains('ticket-placed-all')) return;
      ev.preventDefault();
      ev.stopPropagation();
      var kind = btn.getAttribute('data-copy');
      var text = '';
      if (kind === 'group') {
        text = groupCopyText(btn.closest('.ticket-group-section'));
      } else {
        text = ticketCopyText(btn.closest('.ticket'));
      }
      writeClipboard(text, btn);
    });

    /* 6. Account: placed checkboxes + My Groups filter. */
    function slateDate() {
      return (built.getAttribute('data-slate-date') || '').trim().slice(0, 10);
    }
    function loginUrl() {
      return '/account?next=' + encodeURIComponent('/tickets');
    }
    function applyPlacedSet(fps) {
      var set = {};
      (fps || []).forEach(function (fp) { if (fp) set[fp] = true; });
      built.querySelectorAll('.ticket').forEach(function (t) {
        var fp = t.getAttribute('data-fp') || '';
        var on = !!set[fp];
        t.classList.toggle('is-placed', on);
        var cb = t.querySelector('.ticket-placed-cb');
        if (cb) cb.checked = on;
      });
    }
    function postPlaced(body) {
      return fetch('/api/account/placed', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      }).then(function (res) {
        if (res.status === 401) {
          window.location.href = loginUrl();
          return null;
        }
        return res.json();
      });
    }
    function ensureMinePill(prefs) {
      window.__ACCOUNT_PREFERRED_GROUPS = prefs || [];
      var bar = built.querySelector('.ticket-filter-bar');
      if (!bar || !prefs || !prefs.length) return;
      if (!bar.querySelector('[data-filter="mine"]')) {
        var pill = document.createElement('button');
        pill.type = 'button';
        pill.className = 'ticket-filter-pill';
        pill.setAttribute('data-filter', 'mine');
        pill.textContent = 'MY GROUPS';
        var all = bar.querySelector('[data-filter="all"]');
        if (all && all.nextSibling) bar.insertBefore(pill, all.nextSibling);
        else bar.insertBefore(pill, bar.firstChild);
      }
      if (typeof window.__ticketsSetFilter === 'function') {
        window.__ticketsSetFilter('mine');
      }
    }
    fetch('/api/account/me?slate=' + encodeURIComponent(slateDate()), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (me) {
        if (!me) return;
        if (me.logged_in) {
          applyPlacedSet(me.placed || []);
          ensureMinePill(me.preferred_groups || []);
        }
      })
      .catch(function () {});

    built.addEventListener('change', function (ev) {
      var cb = ev.target.closest('.ticket-placed-cb');
      if (!cb || !built.contains(cb)) return;
      var fp = cb.getAttribute('data-fp') || (cb.closest('.ticket') && cb.closest('.ticket').getAttribute('data-fp')) || '';
      postPlaced({ slate_date: slateDate(), fingerprint: fp, placed: !!cb.checked }).then(function (data) {
        if (data && data.placed) applyPlacedSet(data.placed);
      });
    });

    built.addEventListener('click', function (ev) {
      var mark = ev.target.closest('.ticket-placed-all');
      if (!mark || !built.contains(mark)) return;
      ev.preventDefault();
      ev.stopPropagation();
      var sec = mark.closest('.ticket-group-section');
      var fps = [];
      if (sec) {
        sec.querySelectorAll('.ticket').forEach(function (t) {
          var fp = t.getAttribute('data-fp') || '';
          if (fp) fps.push(fp);
        });
      }
      postPlaced({ slate_date: slateDate(), fingerprints: fps, placed: true }).then(function (data) {
        if (data && data.placed) applyPlacedSet(data.placed);
        var prev = mark.getAttribute('data-label') || mark.textContent;
        mark.setAttribute('data-label', prev);
        mark.classList.add('is-copied');
        mark.textContent = 'Marked';
        setTimeout(function () {
          mark.classList.remove('is-copied');
          mark.textContent = mark.getAttribute('data-label') || prev;
        }, 1400);
      });
    });

  }); /* end waitForTickets */

})();
