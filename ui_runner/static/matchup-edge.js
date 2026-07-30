/**
 * Multi-sport Matchup Edge panels — Slate Explorer (#sp-{sport})
 */
(function (global) {
  const ME_SPORTS = ["nba", "nba1h", "nba1q", "wnba", "nhl", "mlb", "soccer", "cbb", "cfb", "nfl", "tennis"];
  const SKIP = new Set(["combined", "wcbb"]);

  const PROP_SEARCH = {
    pts: ["points", "pts"],
    reb: ["rebounds", "reb"],
    ast: ["assists", "ast"],
    fg3m: ["3-pointer", "3pt", "fg3m"],
    stl: ["steals"],
    blk: ["blocks"],
    pra: ["pts+reb+ast", "pra"],
    goals: ["goals"],
    assists: ["assists"],
    points: ["points"],
    shots: ["shots", "sog"],
    hits: ["hits"],
    strikeouts: ["strikeout", "k's"],
    total_bases: ["total bases"],
    home_runs: ["home run"],
    pass_yds: ["pass", "passing"],
    rush_yds: ["rush"],
    rec_yds: ["receiving", "rec yds"],
    match_total_games: ["total games", "games"],
    games_won: ["games won"],
    aces: ["aces"],
    double_faults: ["double fault"],
    break_points_won: ["break points", "break points won"],
  };

  const state = {};

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function pid(sport, part) {
    const legacy = document.getElementById("wnba-me-team");
    if (sport === "wnba" && legacy) return "wnba-me-" + part;
    return "me-" + sport + "-" + part;
  }

  function panelId(sport) {
    return sport === "wnba" && document.getElementById("wnba-matchup-edge-panel")
      ? "wnba-matchup-edge-panel"
      : "matchup-edge-" + sport;
  }

  function tierClass(tier) {
    const t = String(tier || "").toLowerCase();
    if (t === "elite" || t === "above avg") return "tier-elite";
    if (t === "weak" || t === "below avg") return "tier-weak";
    return "";
  }

  function edgeLabel(edge) {
    return String(edge || "NEUTRAL").replace(/_/g, " ");
  }

  function isOverEdge(edge) {
    return edge === "TOP_EDGE" || edge === "OK_EDGE";
  }

  function isUnderEdge(edge) {
    return edge === "TOP_UNDER" || edge === "OK_UNDER";
  }

  function isFadeCandidate(p) {
    return Boolean(
      p &&
        (isUnderEdge(p.edge) ||
          p.fades_vs_elite ||
          (leaderSlice(p) === "bottom" && String(p.edge || "").toUpperCase() === "AVOID"))
    );
  }

  function underSearchPlayers(block, preferVisibleBottom) {
    let list = (block?.players || []).filter((p) => isUnderEdge(p.edge) || isFadeCandidate(p));
    if (preferVisibleBottom) {
      const bottom = list
        .filter((p) => leaderSlice(p) === "bottom")
        .sort((a, b) => (a.bottom_rank_on_team || 99) - (b.bottom_rank_on_team || 99));
      if (bottom.length) list = bottom;
      else
        list = list
          .slice()
          .sort((a, b) => edgeRank(a.edge) - edgeRank(b.edge) || String(a.player).localeCompare(String(b.player)));
    }
    return list;
  }

  function blockHasUnderSignals(block) {
    return underSearchPlayers(block).length > 0;
  }

  function slateRowsForSport(sport) {
    try {
      if (global.SLATE_DATA && Array.isArray(global.SLATE_DATA[sport])) return global.SLATE_DATA[sport];
    } catch (_) {}
    return [];
  }

  function playerHasSlateMatch(sport, playerName, opts) {
    const q = String(playerName || "")
      .trim()
      .toLowerCase();
    if (!q) return false;
    const dir = opts?.dir || null;
    const pick = opts?.pick || null;
    const propTerms = (opts?.propTerms || []).map((t) => String(t).toLowerCase()).filter(Boolean);
    return slateRowsForSport(sport).some((r) => {
      const pname = String(r.player || "").toLowerCase();
      if (!pname.includes(q)) return false;
      if (dir && r.dir !== dir) return false;
      if (pick && r.pick_type !== pick) return false;
      if (propTerms.length) {
        const prop = String(r.prop || "").toLowerCase();
        if (!propTerms.some((t) => prop.includes(t))) return false;
      }
      return true;
    });
  }

  function pickSearchName(sport, names, opts) {
    const seen = new Set();
    for (const name of names) {
      const key = String(name || "")
        .trim()
        .toLowerCase();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      if (playerHasSlateMatch(sport, name, opts)) return String(name).trim();
    }
    return "";
  }

  function setFindStatus(sport, msg) {
    const panel = document.getElementById(panelId(sport));
    const row = panel?.querySelector(".me-find-row, .wnba-me-find-row");
    if (!row) return;
    let el = row.querySelector(".me-find-status");
    if (!el) {
      el = document.createElement("div");
      el.className = "me-find-status";
      row.appendChild(el);
    }
    el.textContent = msg || "";
  }

  function edgeRank(edge) {
    if (edge === "TOP_EDGE" || edge === "TOP_UNDER") return 0;
    if (edge === "OK_EDGE" || edge === "OK_UNDER") return 1;
    if (edge === "NEUTRAL") return 2;
    return 3;
  }

  const LEADER_N = 5;

  function leaderSlice(p) {
    const ls = String(p.leader_slice || "").toLowerCase();
    if (ls === "top" || ls === "bottom") return ls;
    const br = p.bottom_rank_on_team;
    const tr = p.rank_on_team;
    if (br != null && br <= LEADER_N && (tr == null || tr > LEADER_N)) return "bottom";
    if (tr != null && tr <= LEADER_N) return "top";
    return "top";
  }

  function leaderView(sport) {
    state[sport] = state[sport] || {};
    if (!state[sport].leaderView) state[sport].leaderView = "top";
    return state[sport].leaderView;
  }

  function setLeaderView(sport, view) {
    state[sport] = state[sport] || {};
    state[sport].leaderView = view;
    updateSliceButtons(sport);
    render(sport);
  }

  function updateSliceButtons(sport) {
    const view = leaderView(sport);
    const panel = document.getElementById(panelId(sport));
    if (!panel) return;
    panel.querySelectorAll(".me-slice-btn").forEach((btn) => {
      btn.classList.toggle("me-slice-on", btn.dataset.slice === view);
    });
  }

  function filteredPlayers(players, view) {
    const list = players || [];
    if (view === "all") return list;
    if (view === "bottom") {
      return list
        .filter((p) => leaderSlice(p) === "bottom")
        .sort((a, b) => (a.bottom_rank_on_team || 99) - (b.bottom_rank_on_team || 99))
        .slice(0, LEADER_N);
    }
    return list
      .filter((p) => leaderSlice(p) === "top")
      .sort((a, b) => (a.rank_on_team || 99) - (b.rank_on_team || 99))
      .slice(0, LEADER_N);
  }

  function playerRankBadge(p) {
    const slice = leaderSlice(p);
    if (slice === "bottom") {
      const n = p.bottom_rank_on_team;
      const fade =
        p.edge === "TOP_UNDER" || p.edge === "OK_UNDER" || p.fades_vs_elite ? "FADE" : "LOW";
      return (
        ' <span class="me-rank-badge me-rank-fade" title="Fade candidate">' +
        esc(fade) +
        " #" +
        esc(n != null ? n : "?") +
        "</span>"
      );
    }
    if (p.team_rank_label) {
      return ' <span class="me-rank-badge">' + esc(p.team_rank_label) + "</span>";
    }
    if (p.bottom3_on_team) {
      return ' <span class="me-rank-badge me-rank-b3">B' + esc(p.bottom_rank_on_team || "?") + "</span>";
    }
    if (p.rank_on_team != null && p.rank_on_team <= LEADER_N) {
      return ' <span class="me-rank-badge me-rank-top">T' + esc(p.rank_on_team) + "</span>";
    }
    return "";
  }

  function apiUrl(sport) {
    return "/api/" + sport + "/matchup-edge";
  }

  function fallbackUrls(sport) {
    const name = sport + "_matchup_edge.json";
    const rel = "data/" + name;
    if (
      global.location &&
      (global.location.protocol === "file:" || global.location.pathname.includes("/mobile"))
    ) {
      return [rel];
    }
    return ["/" + rel, "/" + name];
  }

  function ensurePanel(sport) {
    const id = panelId(sport);
    let panel = document.getElementById(id);
    if (panel) return panel;
    const sp = document.getElementById("sp-" + sport);
    if (!sp) return null;

    panel = document.createElement("details");
    panel.id = id;
    panel.className = "matchup-edge-panel me-sport-" + sport;
    panel.dataset.sport = sport;
    panel.open = true;
    const label = sport.toUpperCase().replace("NBA1H", "NBA 1H").replace("NBA1Q", "NBA 1Q");
    const isPlayer = sport === "tennis";
    const teamLbl = isPlayer ? "Player" : "Team";
    const oppLbl = isPlayer ? "Opponent player" : "Opponent";
    panel.innerHTML =
      '<summary>Matchup Edge — ' +
      label +
      (isPlayer ? " — opponent player lookup" : " defense lookup") +
      "</summary>" +
      '<div class="me-body">' +
      '<div class="me-loading" id="' +
      pid(sport, "loading") +
      '">Loading matchup data…</div>' +
      '<div id="' +
      pid(sport, "content") +
      '" style="display:none">' +
      '<div class="me-controls">' +
      '<div class="me-field"><label>' +
      teamLbl +
      '</label><select id="' +
      pid(sport, "team") +
      '"></select></div>' +
      '<div class="me-field"><label>Category</label><select id="' +
      pid(sport, "cat") +
      '"></select></div>' +
      '<div class="me-field"><label>' +
      oppLbl +
      '</label><select id="' +
      pid(sport, "opp") +
      '" disabled></select></div>' +
      '<div class="me-find-row">' +
      '<button type="button" class="me-find me-find-over" id="' +
      pid(sport, "find-over") +
      '">Find overs ↗</button>' +
      '<button type="button" class="me-find me-find-under" id="' +
      pid(sport, "find-under") +
      '">Find unders ↗</button>' +
      "</div>" +
      '<div class="me-slice-row">' +
      '<span class="me-slice-label">Leaders</span>' +
      '<button type="button" class="me-slice-btn me-slice-on" data-slice="top">Top 5</button>' +
      '<button type="button" class="me-slice-btn" data-slice="bottom">Bottom 5</button>' +
      '<button type="button" class="me-slice-btn" data-slice="all">All</button>' +
      "</div>" +
      "</div>" +
      '<div class="me-cards" id="' +
      pid(sport, "cards") +
      '"></div>' +
      '<div class="me-table-wrap"><table class="me-table"><thead><tr>' +
      "<th>Player</th><th>Pos</th><th id='" +
      pid(sport, "avg-h") +
      "'>Avg</th><th>Share %</th><th>Team avg</th><th>vs line</th><th>Game score</th>" +
      "<th>Edge vs opp</th><th>Notes</th>" +
      "</tr></thead><tbody id='" +
      pid(sport, "tbody") +
      "'></tbody></table></div>" +
      '<div class="me-legend" id="' +
      pid(sport, "legend") +
      '"></div></div></div>';

    const toolbar = sp.querySelector(".slate-toolbar");
    if (toolbar) sp.insertBefore(panel, toolbar);
    else sp.prepend(panel);
    bindEvents(sport);
    return panel;
  }

  function bindEvents(sport) {
    const teamSel = document.getElementById(pid(sport, "team"));
    const catSel = document.getElementById(pid(sport, "cat"));
    const findOverBtn = document.getElementById(pid(sport, "find-over"));
    const findUnderBtn = document.getElementById(pid(sport, "find-under"));
    if (teamSel && !teamSel.dataset.meBound) {
      teamSel.dataset.meBound = "1";
      teamSel.addEventListener("change", () => onTeamChange(sport));
    }
    if (catSel && !catSel.dataset.meBound) {
      catSel.dataset.meBound = "1";
      catSel.addEventListener("change", () => render(sport));
    }
    if (findOverBtn && !findOverBtn.dataset.meBound) {
      findOverBtn.dataset.meBound = "1";
      findOverBtn.addEventListener("click", () => findProps(sport, "OVER"));
    }
    if (findUnderBtn && !findUnderBtn.dataset.meBound) {
      findUnderBtn.dataset.meBound = "1";
      findUnderBtn.addEventListener("click", () => findProps(sport, "UNDER"));
    }
    const panel = document.getElementById(panelId(sport));
    if (panel && !panel.dataset.meSliceBound) {
      panel.dataset.meSliceBound = "1";
      panel.querySelectorAll(".me-slice-btn").forEach((btn) => {
        btn.addEventListener("click", () => setLeaderView(sport, btn.dataset.slice || "top"));
      });
    }
  }

  async function loadData(sport) {
    if (state[sport]?.data) return state[sport].data;
    let data = null;
    try {
      const res = await fetch(apiUrl(sport), { cache: "no-store" });
      if (res.ok) {
        data = await res.json();
        if (!data.error) {
          state[sport] = state[sport] || {};
          state[sport].data = data;
          return data;
        }
      }
    } catch (_) {}
    for (const url of fallbackUrls(sport)) {
      try {
        const fb = await fetch(url, { cache: "no-store" });
        if (fb.ok) {
          data = await fb.json();
          if (!data.error) {
            state[sport] = state[sport] || {};
            state[sport].data = data;
            return data;
          }
        }
      } catch (_) {}
    }
    throw new Error("unavailable");
  }

  function populateSelectors(sport) {
    const data = state[sport]?.data;
    if (!data) return;
    const teamSel = document.getElementById(pid(sport, "team"));
    const catSel = document.getElementById(pid(sport, "cat"));
    if (!teamSel || !catSel) return;
    const playerMode = data.matchup_mode === "player";

    const blockKeys = Object.keys(data.players_by_team_cat || {});
    const teamsWithBlocks = new Set(blockKeys.map((k) => k.split("|")[0].toUpperCase()));
    const normAbbr = (s) => String(s || "").toUpperCase();
    const edgeRankFn = (e) => edgeRank(e);
    const bestEdgeScore = (abbr) => {
      const prefix = normAbbr(abbr);
      const blocks = data.players_by_team_cat || {};
      let best = 3;
      let maxPp = -Infinity;
      Object.keys(blocks).forEach((k) => {
        if (normAbbr(k.split("|")[0]) !== prefix) return;
        const block = blocks[k];
        const players = Array.isArray(block) ? block : block?.players || [];
        players.forEach((p) => {
          const r = edgeRankFn(p.edge);
          if (r < best) best = r;
          const pe = p.pp_edge;
          if (pe != null && !Number.isNaN(Number(pe)) && Number(pe) > maxPp) maxPp = Number(pe);
        });
      });
      return { rank: best, maxPp: maxPp === -Infinity ? -999 : maxPp };
    };
    const teams = (data.teams || [])
      .filter((t) => {
        const ab = normAbbr(t?.slate_abbr || t?.def_key);
        if (!ab) return false;
        // Prefer clubs that actually have leader blocks (tonight's slate).
        if (teamsWithBlocks.size && !teamsWithBlocks.has(ab)) return false;
        // Drop idle clubs with no opponent when matchup map is present.
        const mu = lookupMatchup(data, ab);
        const hasOpp = Boolean(nonEmptyAbbr(mu.opponent_slate) || nonEmptyAbbr(mu.opponent_name));
        if (teamsWithBlocks.size) return true;
        if (Object.keys(data.matchups || {}).length) return hasOpp;
        return true;
      })
      .slice()
      .sort((a, b) => {
        const abA = a.slate_abbr || a.def_key || "";
        const abB = b.slate_abbr || b.def_key || "";
        const scoreA = bestEdgeScore(abA);
        const scoreB = bestEdgeScore(abB);
        if (scoreA.rank !== scoreB.rank) return scoreA.rank - scoreB.rank;
        if (scoreB.maxPp !== scoreA.maxPp) return scoreB.maxPp - scoreA.maxPp;
        return String(a.name).localeCompare(String(b.name));
      });
    if (!teams.length && data.matchups) {
      Object.keys(data.matchups).forEach((k) => {
        const mu = data.matchups[k] || {};
        teams.push({
          slate_abbr: k,
          name: mu.opponent_name ? k : playerMode ? mu.opponent_name || k : k,
        });
      });
    }
    if (playerMode && !teams.length && data.players_by_team_cat) {
      const seen = new Set();
      Object.keys(data.players_by_team_cat).forEach((key) => {
        const pk = key.split("|")[0];
        if (seen.has(pk)) return;
        seen.add(pk);
        const block = data.players_by_team_cat[key];
        const nm = (block.players && block.players[0] && block.players[0].player) || pk;
        teams.push({ slate_abbr: pk, name: nm });
      });
    }
    teamSel.innerHTML = teams
      .map((t) => {
        const ab = t.slate_abbr || t.def_key;
        const label = t.name || ab;
        return '<option value="' + esc(ab) + '">' + esc(label) + "</option>";
      })
      .join("");

    catSel.innerHTML = (data.categories || [])
      .map((c) => '<option value="' + esc(c.id) + '">' + esc(c.label) + "</option>")
      .join("");

    onTeamChange(sport);
  }

  function nonEmptyAbbr(s) {
    const v = String(s == null ? "" : s).trim();
    if (!v || v === "—" || v === "-" || v.toLowerCase() === "none") return "";
    return v;
  }

  /** PrizePicks / ESPN / defense-key aliases used across sports. */
  const TEAM_ALIAS_PAIRS = [
    ["WAS", "WSH"],
    ["PDX", "POR"],
    ["LA", "LAS"],
    ["LV", "LVA"],
    ["NY", "NYL"],
    ["GS", "GSV"],
    ["PHO", "PHX"],
    ["CONN", "CON"],
    ["WSH", "WAS"], // NBA Mystics/Wizards vs NHL Caps handled via teams meta
    ["NO", "NOP"],
    ["NY", "NYK"],
    ["SA", "SAS"],
    ["UTAH", "UTA"],
    ["BRK", "BKN"],
  ];

  function teamAliasSet(data, team) {
    const seedRaw = String(team || "").trim();
    const seed = seedRaw.toUpperCase();
    const out = new Set();
    if (!seed) return out;
    out.add(seed);
    (data?.teams || []).forEach((t) => {
      const sa = String(t?.slate_abbr || "").trim().toUpperCase();
      const dk = String(t?.def_key || "").trim().toUpperCase();
      const nm = String(t?.name || "").trim().toUpperCase();
      if (sa === seed || dk === seed || nm === seed) {
        if (sa) out.add(sa);
        if (dk) out.add(dk);
        if (nm) out.add(nm);
      }
      // Full-name / nick match: "Los Angeles Sparks" or "Sparks" → LAS
      if (nm && (nm === seed || nm.endsWith(" " + seed) || seed.endsWith(nm))) {
        if (sa) out.add(sa);
        if (dk) out.add(dk);
        out.add(nm);
      }
    });
    TEAM_ALIAS_PAIRS.forEach(([a, b]) => {
      if (out.has(a)) out.add(b);
      if (out.has(b)) out.add(a);
    });
    return out;
  }

  function lookupMatchup(data, team) {
    const mus = data?.matchups || {};
    const aliases = teamAliasSet(data, team);
    for (const key of aliases) {
      if (mus[key]) return mus[key];
    }
    for (const [k, v] of Object.entries(mus)) {
      if (aliases.has(String(k).toUpperCase())) return v || {};
    }
    return {};
  }

  function teamDisplayName(data, abbr) {
    const want = teamAliasSet(data, abbr);
    for (const t of data?.teams || []) {
      const sa = String(t?.slate_abbr || "").trim().toUpperCase();
      const dk = String(t?.def_key || "").trim().toUpperCase();
      if (want.has(sa) || want.has(dk)) return t.name || sa || dk;
    }
    return nonEmptyAbbr(abbr);
  }

  function canonicalizeTeamAbbr(data, abbr) {
    const raw = nonEmptyAbbr(abbr);
    if (!raw) return "";
    const want = teamAliasSet(data, raw);
    for (const t of data?.teams || []) {
      const sa = String(t?.slate_abbr || "").trim().toUpperCase();
      if (want.has(sa)) return sa;
    }
    for (const t of data?.teams || []) {
      const dk = String(t?.def_key || "").trim().toUpperCase();
      if (want.has(dk)) return String(t?.slate_abbr || dk).trim().toUpperCase();
    }
    return raw.toUpperCase();
  }

  /** Resolve tonight's opponent from loaded Full Slate rows when matchup JSON lacks opp. */
  function opponentFromSlate(sport, team, data) {
    const rows = global.ALL_SLATE;
    if (!Array.isArray(rows) || !rows.length) return { opp: "", oppName: "" };
    const aliases = teamAliasSet(data, team);
    const sportKey = String(sport || "").toLowerCase();
    let oppRaw = "";
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (!r) continue;
      const rs = String(r.sport || "").trim().toLowerCase();
      // Accept blank sport (combined slate) or exact sport match.
      if (rs && rs !== sportKey && !(sportKey === "wnba" && (rs === "wnba1h" || rs === "wnba1q"))) {
        continue;
      }
      const t = String(r.team || "").trim().toUpperCase();
      const o = nonEmptyAbbr(r.opp || r.opp_team || r.opponent).toUpperCase();
      if (!t || !o || t.includes("/") || o.includes("/")) continue;
      const tAliases = teamAliasSet(data, t);
      const oAliases = teamAliasSet(data, o);
      const teamHit = [...aliases].some((a) => tAliases.has(a) || a === t);
      const oppHit = [...aliases].some((a) => oAliases.has(a) || a === o);
      if (teamHit) {
        oppRaw = o;
        break;
      }
      if (oppHit) {
        oppRaw = t;
        break;
      }
    }
    if (!oppRaw) return { opp: "", oppName: "" };
    const opp = canonicalizeTeamAbbr(data, oppRaw);
    return { opp, oppName: teamDisplayName(data, opp) || opp };
  }

  function opponentForTeam(sport, team) {
    const data = state[sport]?.data;
    if (!data || !team) return { opp: "", oppName: "" };
    const mu = lookupMatchup(data, team);
    let opp = nonEmptyAbbr(mu.opponent_slate);
    let oppName = nonEmptyAbbr(mu.opponent_name) || opp;
    if (!opp) {
      const aliases = teamAliasSet(data, team);
      const entry = Object.entries(data.players_by_team_cat || {}).find(([k]) => {
        const ab = String(k.split("|")[0] || "").toUpperCase();
        return aliases.has(ab);
      });
      const blockOpp = entry ? entry[1].opponent || {} : {};
      opp = nonEmptyAbbr(blockOpp.slate_abbr);
      oppName = nonEmptyAbbr(blockOpp.name) || opp;
    }
    if (!opp) {
      const fromSlate = opponentFromSlate(sport, team, data);
      opp = fromSlate.opp;
      oppName = fromSlate.oppName || opp;
    }
    if (opp) {
      opp = canonicalizeTeamAbbr(data, opp);
      if (!oppName || oppName === opp) oppName = teamDisplayName(data, opp) || opp;
    }
    return { opp, oppName, mu };
  }

  function onTeamChange(sport) {
    const data = state[sport]?.data;
    const team = document.getElementById(pid(sport, "team"))?.value;
    const catSel = document.getElementById(pid(sport, "cat"));
    const oppSel = document.getElementById(pid(sport, "opp"));
    if (!oppSel || !data || !team) return;
    if (catSel) {
      const aliases = teamAliasSet(data, team);
      const teamCats = Object.keys(data.players_by_team_cat || {})
        .filter((k) => aliases.has(String(k.split("|")[0] || "").toUpperCase()))
        .map((k) => k.split("|")[1]);
      if (teamCats.length && !teamCats.includes(catSel.value)) {
        catSel.value = teamCats[0];
      }
    }
    const { opp, oppName } = opponentForTeam(sport, team);
    oppSel.innerHTML = opp
      ? '<option value="' + esc(opp) + '" selected>' + esc(oppName || opp) + "</option>"
      : '<option value="">—</option>';
    render(sport);
  }

  function currentBlock(sport) {
    const data = state[sport]?.data;
    const team = document.getElementById(pid(sport, "team"))?.value;
    const cat = document.getElementById(pid(sport, "cat"))?.value;
    if (!team || !cat || !data) return null;
    const direct = (data.players_by_team_cat || {})[team + "|" + cat];
    if (direct) return direct;
    const aliases = teamAliasSet(data, team);
    const key = Object.keys(data.players_by_team_cat || {}).find((k) => {
      const [ab, c] = k.split("|");
      return c === cat && aliases.has(String(ab || "").toUpperCase());
    });
    return key ? data.players_by_team_cat[key] : null;
  }

  function render(sport) {
    const data = state[sport]?.data;
    const block = currentBlock(sport);
    const team = document.getElementById(pid(sport, "team"))?.value;
    const cat = document.getElementById(pid(sport, "cat"))?.value;
    const catLabel = (data?.categories || []).find((c) => c.id === cat)?.label || cat;
    const cards = document.getElementById(pid(sport, "cards"));
    const tbody = document.getElementById(pid(sport, "tbody"));
    const avgH = document.getElementById(pid(sport, "avg-h"));
    const legend = document.getElementById(pid(sport, "legend"));
    if (!block || !cards || !tbody || !data) return;

    const oppMeta = opponentForTeam(sport, team);
    const mu = oppMeta.mu || {};
    const opp = block.opponent || {};
    const oppRank = opp.def_rank != null ? opp.def_rank : mu.opponent_def_rank;
    const oppTier = opp.def_tier || mu.opponent_def_tier || "";
    const oppName = opp.name || oppMeta.oppName || mu.opponent_name || "—";
    const rankLbl = data.opp_metric_label || "Opp def rank";
    const view = leaderView(sport);
    const displayed = filteredPlayers(block.players || [], view);
    let top = 0,
      ok = 0,
      under = 0,
      fades = 0;
    displayed.forEach((p) => {
      if (p.edge === "TOP_EDGE") top++;
      else if (p.edge === "OK_EDGE") ok++;
      else if (isUnderEdge(p.edge)) under++;
      if (leaderSlice(p) === "bottom") fades++;
    });

    const fadeCard =
      view !== "top"
        ? '<div class="me-card"><div class="lbl">Fade rows</div><div class="val edge-fade">' +
          fades +
          "</div></div>"
        : "";

    cards.innerHTML =
      '<div class="me-card"><div class="lbl">' +
      esc(rankLbl) +
      '</div><div class="val ' +
      tierClass(oppTier) +
      '">#' +
      esc(oppRank != null ? oppRank : "—") +
      '</div></div><div class="me-card"><div class="lbl">Opp def tier</div><div class="val ' +
      tierClass(oppTier) +
      '">' +
      esc(oppTier || "—") +
      '</div></div><div class="me-card"><div class="lbl">Top over</div><div class="val edge-top">' +
      top +
      '</div></div><div class="me-card"><div class="lbl">OK over</div><div class="val edge-ok">' +
      ok +
      '</div></div><div class="me-card"><div class="lbl">Under edge</div><div class="val edge-under">' +
      under +
      '</div></div>' +
      fadeCard +
      '<div class="me-card"><div class="lbl">' +
      (data.matchup_mode === "player" ? "Your rank" : "Team def rank") +
      '</div><div class="val">#' +
      esc(mu.team_def_rank != null ? mu.team_def_rank : "—") +
      "</div></div>";

    if (avgH) avgH.textContent = (catLabel || "Stat").split(" ")[0] + " avg";

    updateSliceButtons(sport);

    tbody.innerHTML = displayed
      .map(
        (p) => {
          const rankBadge = playerRankBadge(p);
          const share =
            p.share_pct != null && p.share_pct !== ""
              ? esc(p.share_pct) + "%"
              : "—";
          const teamAvg = p.team_avg != null && p.team_avg !== "" ? esc(p.team_avg) : "—";
          let vsLine = "—";
          if (p.avg_vs_line != null && p.avg_vs_line !== "") {
            const lean = p.share_lean ? " " + esc(p.share_lean) : "";
            const sign = Number(p.avg_vs_line) > 0 ? "+" : "";
            vsLine = sign + esc(p.avg_vs_line) + lean;
          }
          return (
          "<tr><td><strong>" +
          esc(p.player) +
          "</strong>" +
          rankBadge +
          "</td><td>" +
          esc(p.pos || "—") +
          "</td><td>" +
          esc(p.season_avg) +
          "</td><td>" +
          share +
          "</td><td>" +
          teamAvg +
          "</td><td>" +
          vsLine +
          "</td><td>" +
          esc(p.game_score) +
          '</td><td><span class="me-edge ' +
          esc(p.edge) +
          '">' +
          edgeLabel(p.edge) +
          "</span></td><td>" +
          esc(p.notes) +
          "</td></tr>"
          );
        }
      )
      .join("");

    const overBtn = document.getElementById(pid(sport, "find-over"));
    const underBtn = document.getElementById(pid(sport, "find-under"));
    const hasOver = (block?.players || []).some((p) => isOverEdge(p.edge));
    const hasUnder = blockHasUnderSignals(block);
    if (overBtn) {
      overBtn.disabled = !hasOver;
      overBtn.title = hasOver ? "Jump to slate — OVER props for top-edge players" : "No OVER edges in this team/category";
    }
    if (underBtn) {
      underBtn.disabled = !hasUnder;
      underBtn.title = hasUnder
        ? "Jump to slate — UNDER on Standard lines (fade / bottom-5 edges)"
        : "No UNDER or fade edges in this team/category — try another stat (e.g. Rebounds, Assists)";
    }

    const panel = document.getElementById(panelId(sport));
    if (panel) {
      const sum = panel.querySelector("summary");
      if (sum) {
        const viewLbl =
          view === "bottom" ? " (bottom 5)" : view === "all" ? " (all leaders)" : "";
        sum.textContent =
          "Matchup Edge — " +
          (data.display_name || sport.toUpperCase()) +
          " | " +
          catLabel +
          " vs " +
          oppName +
          viewLbl;
      }
    }

    if (legend && data.edge_legend) {
      legend.innerHTML =
        "<strong>Edge logic:</strong> " +
        Object.entries(data.edge_legend)
          .map(([k, v]) => "<strong>" + k.replace(/_/g, " ") + ":</strong> " + esc(v))
          .join(" · ");
    }
  }

  function applySlatePickFilter(sport, pickType) {
    const gobBtn = document.getElementById("sfb-" + sport + "-goblin");
    const stdBtn = document.getElementById("sfb-" + sport + "-standard");
    if (!stdBtn || typeof global.togglePickFilter !== "function") return;
    if (gobBtn?.classList.contains("on")) global.togglePickFilter(sport, "Goblin", gobBtn);
    if (!stdBtn.classList.contains("on")) global.togglePickFilter(sport, "Standard", stdBtn);
    if (pickType === "Goblin" && gobBtn && !gobBtn.classList.contains("on")) {
      global.togglePickFilter(sport, "Goblin", gobBtn);
    }
  }

  function findProps(sport, direction) {
    const wantUnder = String(direction || "").toUpperCase() === "UNDER";
    if (wantUnder) {
      const blockPre = currentBlock(sport);
      if (blockPre && (blockPre.players || []).some((p) => leaderSlice(p) === "bottom" && isFadeCandidate(p))) {
        setLeaderView(sport, "bottom");
      }
    }
    const block = currentBlock(sport);
    const cat = document.getElementById(pid(sport, "cat"))?.value;
    const terms = PROP_SEARCH[cat] || [];
    const overPlayers = (block?.players || [])
      .filter((p) => isOverEdge(p.edge))
      .sort((a, b) => edgeRank(a.edge) - edgeRank(b.edge) || (a.rank_on_team || 99) - (b.rank_on_team || 99))
      .map((p) => p.player);
    // Unders: prefer visible bottom-5 fade/under edges — not an arbitrary roster fade
    // (that used to dump a leftover/random name into the slate filter).
    const underPlayers = underSearchPlayers(block, true).map((p) => p.player);
    const pool = wantUnder ? underPlayers : overPlayers;
    const dir = wantUnder ? "UNDER" : "OVER";
    const pick = wantUnder ? "Standard" : null;
    // Prefer category match, then any prop for that player/dir (naming can differ).
    let search = pickSearchName(sport, pool, { dir, pick, propTerms: terms });
    if (!search) search = pickSearchName(sport, pool, { dir, pick });
    if (!search && wantUnder) {
      // Relax Standard-only if fade names only have Goblin/Demon unders (rare).
      search = pickSearchName(sport, pool, { dir, pick: null });
    }
    if (!search && !wantUnder) {
      search = pickSearchName(sport, pool, { dir, pick: null });
    }
    // Slate not loaded yet — still jump to the preferred edge player (not a leftover name).
    if (!search && pool[0] && !slateRowsForSport(sport).length) {
      search = String(pool[0]).trim();
    }
    // Last resort for overs only: category keyword (e.g. "points") — never invent a player name.
    if (!search && !wantUnder && terms[0]) search = terms[0];

    const input = document.getElementById("sf-" + sport);
    if (!search) {
      if (input) {
        input.value = "";
        if (typeof global.filterSlate === "function") global.filterSlate(sport, "");
      }
      setFindStatus(
        sport,
        wantUnder
          ? "No matching UNDER props on the slate for these fade edges"
          : "No matching OVER props on the slate for these edges"
      );
      const dirBtnEmpty = document.getElementById("sfb-" + sport + (wantUnder ? "-under" : "-over"));
      const otherDirEmpty = document.getElementById("sfb-" + sport + (wantUnder ? "-over" : "-under"));
      if (otherDirEmpty?.classList.contains("on")) otherDirEmpty.click();
      if (dirBtnEmpty && !dirBtnEmpty.classList.contains("on")) dirBtnEmpty.click();
      if (wantUnder) applySlatePickFilter(sport, "Standard");
      document.getElementById("st-" + sport)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }

    setFindStatus(sport, "");
    if (input) {
      input.value = search;
      if (typeof global.filterSlate === "function") global.filterSlate(sport, search);
    }
    const dirBtn = document.getElementById("sfb-" + sport + (wantUnder ? "-under" : "-over"));
    const otherDir = document.getElementById("sfb-" + sport + (wantUnder ? "-over" : "-under"));
    if (otherDir?.classList.contains("on")) otherDir.click();
    if (dirBtn && !dirBtn.classList.contains("on")) dirBtn.click();
    if (wantUnder) applySlatePickFilter(sport, "Standard");
    document.getElementById("st-" + sport)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function init(sport) {
    if (SKIP.has(sport)) return;
    ensurePanel(sport);
    bindEvents(sport);
    const loading = document.getElementById(pid(sport, "loading"));
    const content = document.getElementById(pid(sport, "content"));
    try {
      await loadData(sport);
      if (loading) loading.style.display = "none";
      if (content) content.style.display = "block";
      populateSelectors(sport);
      // Race guard: if dropdown populated with 0 options, retry once after
      // a short delay (panel DOM may not have been ready on first paint)
      const teamSel = document.getElementById(pid(sport, "team"));
      if (teamSel && teamSel.options.length === 0) {
        await new Promise((r) => setTimeout(r, 250));
        populateSelectors(sport);
      }
      // Slate may load after matchup JSON — refresh opponent once ALL_SLATE arrives.
      scheduleSlateOppRefresh(sport);
      state[sport].ready = true;
    } catch (e) {
      if (loading)
        loading.textContent =
          "Matchup data unavailable — run: py -3 scripts/build_matchup_edge_json.py --sport " + sport;
      console.warn("Matchup edge", sport, e);
    }
  }

  function scheduleSlateOppRefresh(sport) {
    state[sport] = state[sport] || {};
    if (state[sport].slateOppTimer) return;
    let tries = 0;
    state[sport].slateOppTimer = setInterval(() => {
      tries += 1;
      const team = document.getElementById(pid(sport, "team"))?.value;
      const oppSel = document.getElementById(pid(sport, "opp"));
      if (!team || !oppSel) {
        if (tries >= 40) {
          clearInterval(state[sport].slateOppTimer);
          state[sport].slateOppTimer = null;
        }
        return;
      }
      const { opp } = opponentForTeam(sport, team);
      const cur = nonEmptyAbbr(oppSel.value);
      if (opp && opp !== cur) onTeamChange(sport);
      if ((opp && oppSel.value === opp) || tries >= 40) {
        clearInterval(state[sport].slateOppTimer);
        state[sport].slateOppTimer = null;
      }
    }, 250);
  }

  function onPanelOpen(sport) {
    if (SKIP.has(sport)) return;
    // If data already loaded (e.g. panel closed and reopened), skip fetch
    // but always re-populate in case DOM was rebuilt
    if (state[sport]?.ready) {
      populateSelectors(sport);
      scheduleSlateOppRefresh(sport);
    } else {
      init(sport);
    }
  }

  function installToggleHook() {
    const orig = global.toggleSlatePanel;
    if (typeof orig !== "function" || orig.__meWrapped) return Boolean(orig?.__meWrapped);
    global.toggleSlatePanel = function (sport) {
      orig(sport);
      if (ME_SPORTS.includes(sport)) onPanelOpen(sport);
    };
    global.toggleSlatePanel.__meWrapped = true;
    return true;
  }

  function boot() {
    ME_SPORTS.forEach((s) => {
      ensurePanel(s);
      bindEvents(s);
      const card = document.getElementById("sc-" + s);
      if (card && !card.dataset.meBound) {
        card.dataset.meBound = "1";
        card.addEventListener("click", () => {
          setTimeout(() => onPanelOpen(s), 0);
        });
      }
      const panel = document.getElementById("sp-" + s);
      if (panel?.classList.contains("open") || card?.classList.contains("active")) onPanelOpen(s);
    });
    if (typeof global.openSlatePanel === "string" && ME_SPORTS.includes(global.openSlatePanel)) {
      onPanelOpen(global.openSlatePanel);
    }
    if (!installToggleHook()) {
      let tries = 0;
      const hookTimer = setInterval(() => {
        if (installToggleHook() || ++tries > 120) clearInterval(hookTimer);
      }, 50);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  global.MatchupEdge = { init: init, render: render, sports: ME_SPORTS };
})(typeof window !== "undefined" ? window : globalThis);
