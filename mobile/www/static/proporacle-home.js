
// ── Real PLAYER_DATA (last 10 games) ──────────────────────
let ALL_SLATE = [];
const PLAYER_DATA = {};
let SLATE_DEBUG_META = { source: "", generated_at: "", date: "" };
/** True after Full Slate rows successfully mapped into ALL_SLATE (Excel or merged JSON). */
let SLATE_CARDS_POPULATED = false;

/** Fills optional #top-edges-debug. Never throw: loadSlateData calls this immediately before ticket→sheet merge. */
function renderTopEdgesDebugTag() {
  const el = document.getElementById("top-edges-debug");
  if (!el) return;
  const bid = document.documentElement.getAttribute("data-ui-build") || "";
  const sha = (document.documentElement.getAttribute("data-deploy-sha") || "").trim();
  const m = SLATE_DEBUG_META || {};
  const parts = [
    bid && `ui ${bid}`,
    sha && sha.slice(0, 7),
    m.source && `slate:${m.source}`,
  ].filter(Boolean);
  el.textContent = parts.length ? parts.join(" · ") : "—";
}

function fmtEdgeCell(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : "—";
}

/** Edge text for cards: match legacy OVER “+” prefix when non-negative. */
function fmtEdgePick(p) {
  const n = Number(p && p.edge);
  if (!Number.isFinite(n)) return "—";
  const over = String(p.dir || "").toUpperCase() === "OVER";
  if (over) return (n >= 0 ? "+" : "") + n.toFixed(2);
  return n.toFixed(2);
}

/** Model-projected stat: prefer API projection; never treat 0 as valid for normal stat totals. */
function projectedStatForPick(p) {
  if (!p) return null;
  const line = coercePropLine(p);
  const tryProj = (raw) => {
    const pj = Number(raw);
    if (!Number.isFinite(pj)) return null;
    if (pj === 0 && Number.isFinite(line) && line >= 2) return null;
    return pj;
  };
  let pj = tryProj(p.projection ?? p.proj ?? p.Projected);
  if (pj == null) pj = tryProj(p.standard_projection);
  if (pj != null) return pj;
  const edge = Number(p.edge);
  if (Number.isFinite(line) && Number.isFinite(edge)) return line + edge;
  return Number.isFinite(line) ? line : null;
}

/** Avoid crashes when pipeline rows omit sport (breaks .toLowerCase / tier CSS). */
function safeSportKey(p) {
  const s = String((p && p.sport != null) ? p.sport : "nba").trim().toLowerCase();
  return s || "nba";
}

/** Normalize Goblin/Demon boards using true Standard sibling (not synthetic line+1.5). */
function normalizeAltPickBoardRows(rows) {
  if (!Array.isArray(rows)) return rows;
  const groups = new Map();
  const keyOf = (r) =>
    [
      String(r?.sport || "").trim().toUpperCase(),
      String(r?.player || "").trim().toLowerCase(),
      String(r?.prop || r?.prop_type || "").trim().toLowerCase(),
    ].join("||");
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    const k = keyOf(r);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }
  const trueStd = new Map();
  for (const [k, grp] of groups.entries()) {
    const stdLines = grp
      .filter((r) => String(r.pick_type || r.pick || "").toLowerCase().includes("stan"))
      .map((r) => Number(r.line))
      .filter((n) => Number.isFinite(n));
    if (stdLines.length) {
      stdLines.sort((a, b) => a - b);
      trueStd.set(k, stdLines[Math.floor(stdLines.length / 2)]);
      continue;
    }
    const gobs = grp.filter((r) => String(r.pick_type || r.pick || "").toLowerCase().includes("gob"));
    const stdSet = new Set();
    let synthetic = gobs.length >= 2;
    for (const r of gobs) {
      const line = Number(r.line);
      const std = Number(r.standard_line);
      if (!Number.isFinite(line) || !Number.isFinite(std)) {
        synthetic = false;
        break;
      }
      const dir = String(r.dir || r.direction || "").trim().toUpperCase();
      const off = dir.startsWith("U") ? line - std : std - line;
      if (off < 0.4 || off > 2.6) synthetic = false;
      stdSet.add(Math.round(std * 100) / 100);
    }
    if (synthetic && stdSet.size >= 2) {
      trueStd.set(k, null);
    } else if (stdSet.size === 1) {
      trueStd.set(k, [...stdSet][0]);
    } else {
      trueStd.set(k, null);
    }
  }
  return rows.map((r) => {
    if (!r || typeof r !== "object") return r;
    return normalizeAltPickBoard({ ...r }, trueStd.get(keyOf(r)));
  });
}

function normalizeAltPickBoard(p, trueStandardLine) {
  if (!p || typeof p !== "object") return p;
  const raw = String(p.pick || p.pick_type || "Standard").trim();
  let pick = raw;
  const low = raw.toLowerCase();
  if (low.includes("gob")) pick = "Goblin";
  else if (low.includes("dem")) pick = "Demon";
  else if (low.includes("stan") || !raw) pick = "Standard";
  const line = Number(p.line);
  let std = Number.isFinite(Number(trueStandardLine)) ? Number(trueStandardLine) : Number(p.standard_line);
  const dir = String(p.dir || p.direction || "").trim().toUpperCase();
  const eps = 0.25;
  // Ignore synthetic std that makes Goblin look softer (OVER: std ≈ line+1.5).
  if (
    pick === "Goblin" &&
    Number.isFinite(line) &&
    Number.isFinite(std) &&
    !Number.isFinite(Number(trueStandardLine))
  ) {
    const fakeOff = dir.startsWith("U") ? line - std : std - line;
    if (fakeOff >= 0.4 && fakeOff <= 2.6) std = NaN;
  }
  if (Number.isFinite(std)) p.standard_line = std;
  const baseline = Math.max(
    ...[Number(p.season_avg), Number(p.projection), Number(p.standard_projection)].filter((n) =>
      Number.isFinite(n)
    ),
    0
  );
  let reclassified = null;
  if (pick === "Goblin" && Number.isFinite(line)) {
    if (Number.isFinite(std) && ((dir.startsWith("O") && line > std + eps) || (dir.startsWith("U") && line < std - eps))) {
      reclassified = "goblin_harder_than_standard";
      pick = "Demon";
    } else if (dir.startsWith("O") && baseline > 0 && line > baseline + 8) {
      reclassified = "goblin_harder_than_standard";
      pick = "Demon";
    }
  }
  p.pick = pick;
  p.pick_type = pick;
  if (reclassified) {
    p.pick_type_raw = raw;
    p.pick_reclassified = reclassified;
  }
  return p;
}

function mapApiPickToSlateRow(p) {
  if (!p || typeof p !== "object") return null;
  normalizeAltPickBoard(p);
  const hitRaw = p.hit;
  let hitNum = hitRaw;
  if (hitRaw != null && typeof hitRaw === "number" && hitRaw <= 1) {
    hitNum = Math.round(hitRaw * 100);
  }
  const rankScore = p.rank_score != null ? p.rank_score : p.rank;
  return {
    sport: p.sport,
    initials: p.initials || (p.player || "").split(" ").filter((w) => w).map((w) => w[0]).join("").slice(0, 2).toUpperCase(),
    player: p.player || "",
    team: p.team || "",
    opp: p.opp || "",
    prop: p.prop || p.prop_type || "",
    line: p.line,
    pick: p.pick || p.pick_type || "Standard",
    pick_type: p.pick_type || p.pick || "Standard",
    pick_reclassified: p.pick_reclassified || "",
    pick_type_raw: p.pick_type_raw || "",
    pick_platform: p.pick_platform || "prizepicks",
    standard_line: p.standard_line,
    book_line: p.book_line != null ? p.book_line : p.prop_line,
    prop_line: p.prop_line,
    dir: p.dir || p.direction || "",
    hit: hitNum,
    hit_rate: p.hit_rate != null ? p.hit_rate : (typeof hitNum === "number" && hitNum > 1 ? hitNum / 100 : hitRaw),
    edge: p.edge,
    abs_edge: p.abs_edge,
    projection: p.projection,
    tier: p.tier,
    rank_score: rankScore,
    rank_tier: p.rank_tier ?? p.tier,
    ml_prob: p.ml_prob,
    def_tier: p.def_tier,
    opponent_def_rank: p.opponent_def_rank,
    stat_def_tier: p.stat_def_tier,
    stat_def_rank: p.stat_def_rank,
    stat_def_category: p.stat_def_category,
    game_time: p.game_time || "",
    l5_over: p.l5_over,
    l5_under: p.l5_under != null ? p.l5_under : resolvedUnderHits(p, 5),
    l10_over: p.l10_over,
    l10_under: p.l10_under != null ? p.l10_under : resolvedUnderHits(p, 10),
    l10_streak: p.l10_streak,
    l10_over_pct: p.l10_over_pct,
    l5_avg: p.l5_avg,
    season_avg: p.season_avg,
    actual_series: p.actual_series,
    line_series: p.line_series,
    ...(function () {
      const hist = {};
      for (let gi = 1; gi <= 10; gi++) {
        const gk = `g${gi}`;
        const sk = `stat_g${gi}`;
        const lk = `line_g${gi}`;
        if (p[gk] != null && p[gk] !== "") hist[gk] = p[gk];
        if (p[sk] != null && p[sk] !== "") hist[sk] = p[sk];
        if (p[lk] != null && p[lk] !== "") hist[lk] = p[lk];
      }
      return hist;
    })(),
    standard_projection: p.standard_projection,
    image_url: p.image_url,
    confidence_tier: p.confidence_tier,
    confidence_slice_hr: p.confidence_slice_hr,
  };
}

function playerSeriesKey(name, line, prop="", sport="") {
  const n = String(name || "").trim().toLowerCase();
  const p = String(prop || "").trim().toLowerCase();
  const s = String(sport || "").trim().toLowerCase();
  const l = Number(line);
  const lv = Number.isFinite(l) ? l.toFixed(3) : String(line || "");
  return `${s}|${n}|${p}|${lv}`;
}

function getPD(name, line, prop="", sport="") {
  const k = playerSeriesKey(name, line, prop, sport);
  if (PLAYER_DATA[k]) return PLAYER_DATA[k];
  let s = 0;
  for (let c of name) s = (s * 31 + c.charCodeAt(0)) % 1000;
  const built = Array.from({length: 10}, (_, i) => {
    s = (s * 9301 + 49297) % 233280;
    return Math.max(0, Math.round((line + ((s / 233280) - 0.5) * line * 1.2) * 4) / 4);
  });
  PLAYER_DATA[k] = built;
  return built;
}

function normalizeSeries(vals) {
  if (!Array.isArray(vals)) return [];
  const out = [];
  for (const v of vals) {
    const n = Number(v);
    if (Number.isFinite(n)) out.push(streakQuantize(n));
  }
  return out;
}

/** Parse floats from pipeline / JSON (mirrors ui_runner app _extract_history_series). */
function parseFiniteNumber(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  if (!Number.isFinite(n) || Number.isNaN(n)) return null;
  return n;
}

/**
 * Build per-game stat arrays in pipeline order: g1 = most recent, …, gN.
 * Mirrors Python _extract_history_series (stat_g / actual_g / g, plus line_g / prop_line_g).
 */
function extractPerGameSeriesFromObject(obj, maxN = 10) {
  const actualVals = [];
  const lineVals = [];
  if (!obj || typeof obj !== "object") return { actualVals, lineVals };
  for (let i = 1; i <= maxN; i++) {
    let aval = null;
    for (const key of [
      `stat_g${i}`, `Stat_G${i}`, `STAT_G${i}`, `Actual_G${i}`, `actual_g${i}`, `g${i}`, `G${i}`,
    ]) {
      if (!Object.prototype.hasOwnProperty.call(obj, key)) continue;
      aval = parseFiniteNumber(obj[key]);
      if (aval !== null) break;
    }
    if (aval === null) continue;
    actualVals.push(aval);

    let lval = null;
    for (const key of [
      `line_g${i}`, `Line_G${i}`, `PROP_LINE_G${i}`, `prop_line_g${i}`, `Prop_Line_G${i}`,
    ]) {
      if (!Object.prototype.hasOwnProperty.call(obj, key)) continue;
      lval = parseFiniteNumber(obj[key]);
      if (lval !== null) break;
    }
    lineVals.push(lval !== null ? lval : null);
  }
  return { actualVals, lineVals };
}

/** Excel / combined row: parallel column names → object for extractPerGameSeriesFromObject. */
function extractPerGameFromColumnsRow(columns, row) {
  const o = {};
  if (!Array.isArray(columns) || !Array.isArray(row)) {
    return extractPerGameSeriesFromObject({}, 10);
  }
  for (let i = 0; i < columns.length; i++) {
    const nm = String(columns[i] ?? "").trim();
    if (!nm || row[i] === undefined || row[i] === null || row[i] === "") continue;
    o[nm] = row[i];
  }
  return extractPerGameSeriesFromObject(o, 10);
}

/** Prefer first-n games when series is longest-first recent (pipeline g1..gn); fallback to tail when short. */
function takeFirstNGames(series, n) {
  if (!Array.isArray(series) || !n) return [];
  if (series.length >= n) return series.slice(0, n);
  return series.slice();
}

/** l5_avg is sometimes a hit-rate fraction (≤1); never use it as stat level vs a real book line. */
function plausibleStatBaseline(l5Avg, seasonAvg, bookLine) {
  const L = Number(bookLine);
  const tryOne = (raw) => {
    const avn = Number(raw);
    if (!Number.isFinite(avn)) return null;
    if (Number.isFinite(L) && L >= 3 && avn > 0 && avn <= 1) return null;
    return avn;
  };
  const a = tryOne(l5Avg);
  if (a !== null) return a;
  const b = tryOne(seasonAvg);
  if (b !== null) return b;
  return Number.isFinite(L) ? L : 0;
}

function normalizePlayerForMerge(s) {
  return String(s ?? "").trim().toLowerCase().replace(/\s+/g, " ");
}

/** OVER / UNDER tokens: some Excel feeds use O/U. */
function normalizeDirForMerge(d) {
  const s = String(d ?? "").trim().toUpperCase();
  if (s === "O" || s === "OV" || s === "OVR") return "OVER";
  if (s === "U" || s === "UN" || s === "UND") return "UNDER";
  return s;
}

function pickDirNorm(rec) {
  if (!rec) return "";
  const raw = rec.dir != null && rec.dir !== "" ? rec.dir : rec.direction;
  return normalizeDirForMerge(raw);
}

/** Prop tokens: combined sheet uses shortcodes (pra, pr, pts) while tickets use long PrizePicks names. */
const PROP_MERGE_CANON = {
  pra: "pts+rebs+asts",
  pr: "pts+rebs",
  pa: "pts+asts",
  pts: "points",
  ast: "assists",
  reb: "rebounds",
  points: "points",
  rebounds: "rebounds",
  assists: "assists",
  "pts+rebs": "pts+rebs",
  "pts+asts": "pts+asts",
  "pts+rebs+asts": "pts+rebs+asts",
  "points+rebounds": "pts+rebs",
  "points+assists": "pts+asts",
  "points+rebounds+assists": "pts+rebs+asts",
};

function normalizePropForMerge(s) {
  let t = String(s ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "");
  t = t.replace(/\u2013/g, "-").replace(/\u2014/g, "-");
  if (Object.prototype.hasOwnProperty.call(PROP_MERGE_CANON, t)) return PROP_MERGE_CANON[t];
  return t;
}

function propForMergeKey(rec) {
  if (!rec) return "";
  const raw = rec.prop != null && String(rec.prop).trim() ? rec.prop : rec.prop_type;
  return normalizePropForMerge(raw);
}

/** Promo vs standard lines: register every numeric variant so ticket ↔ sheet rows merge. */
function mergeLineTokens(rec) {
  if (!rec) return [""];
  const toks = new Set();
  for (const c of [rec.line, rec.standard_line, rec.book_line, rec.prop_line]) {
    if (c == null || c === "") continue;
    const x = Number(c);
    if (Number.isFinite(x)) {
      toks.add(x.toFixed(3));
      continue;
    }
    const cleaned = String(c)
      .trim()
      .replace(/[^0-9.+-]/g, "");
    const n = Number(cleaned);
    if (Number.isFinite(n)) toks.add(n.toFixed(3));
  }
  return toks.size ? [...toks] : [""];
}

function slatePickBaseParts(rec, includeSport) {
  const prop = propForMergeKey(rec);
  if (includeSport) {
    return [
      String(rec.sport || "").trim().toUpperCase(),
      normalizePlayerForMerge(rec.player),
      prop,
      pickDirNorm(rec),
    ].join("||");
  }
  return [normalizePlayerForMerge(rec.player), prop, pickDirNorm(rec)].join("||");
}

function buildSlatePickMaps(picks) {
  const fullMap = Object.create(null);
  const looseMap = Object.create(null);
  for (const p of picks || []) {
    const fb = slatePickBaseParts(p, true);
    const lb = slatePickBaseParts(p, false);
    for (const lt of mergeLineTokens(p)) {
      fullMap[`${fb}||${lt}`] = p;
      looseMap[`${lb}||${lt}`] = p;
    }
  }
  return { fullMap, looseMap };
}

function resolveSlatePickForRow(row, maps) {
  for (const lt of mergeLineTokens(row)) {
    const hit = maps.fullMap[`${slatePickBaseParts(row, true)}||${lt}`];
    if (hit) return hit;
  }
  for (const lt of mergeLineTokens(row)) {
    const hit = maps.looseMap[`${slatePickBaseParts(row, false)}||${lt}`];
    if (hit) return hit;
  }
  return null;
}

/** Numeric book line for charts (handles string "15.5" etc.). */
function coercePropLine(p) {
  if (!p) return NaN;
  const cands = [p.line, p.standard_line, p.book_line, p.prop_line];
  for (const c of cands) {
    const n0 = Number(c);
    if (Number.isFinite(n0) && n0 >= 0) return n0;
    const s = String(c ?? "")
      .trim()
      .replace(/[^0-9.+-]/g, "");
    const n1 = Number(s);
    if (Number.isFinite(n1) && n1 >= 0) return n1;
  }
  return NaN;
}

/** Book line for synthetic series / getPD: tickets often put the number in standard_line only. */
function bookLineNumForPick(p) {
  const c = coercePropLine(p);
  if (Number.isFinite(c) && c >= 0) return c;
  return 0;
}

/**
 * Some feeds mislabel hit/miss (0/1) columns as actual_series. Skip when scale is clearly stat-total.
 */
function storedSeriesLooksLikeHitFlags(storedArr, book) {
  if (!Array.isArray(storedArr) || !storedArr.length) return false;
  const nums = storedArr.map((x) => Number(x)).filter((x) => Number.isFinite(x));
  if (!nums.length) return false;
  const mx = Math.max(...nums);
  const mn = Math.min(...nums);
  if (mx > 1.25 || mn < 0) return false;
  const b = Number(book);
  if (Number.isFinite(b) && b >= 2) return mx < b * 0.25;
  // No reliable book line: still reject obvious 0/1-ish "actuals" from mis-labeled Excel columns.
  return true;
}

/**
 * Per-game columns (extract / g1–g5): reject 0/1-ish junk vs real book line (same as actual_series).
 * Use full coercePropLine(pick) so line/standard_line/book_line all count.
 */
function perGameSeriesLooksLikeNoise(series, _book, pick) {
  const b = coercePropLine(pick);
  if (!Number.isFinite(b) || b < 2) return false;
  return storedSeriesLooksLikeHitFlags(series, b);
}

function historySeriesForPick(p, n) {
  const book = coercePropLine(p);
  const minNeed = Math.min(3, n);
  const ex = extractPerGameSeriesFromObject(p, 10);

  const stored = normalizeSeries(Array.isArray(p.actual_series) ? p.actual_series : []);
  let actual = [];

  /** Recent-first: slice first n stats (pipeline g1 = last game). */
  const storedN = takeFirstNGames(stored, n);
  const extractedN = normalizeSeries(takeFirstNGames(ex.actualVals.slice(), Math.min(ex.actualVals.length, n)));

  const fromGC = [];
  for (let gi = 1; gi <= 10 && fromGC.length < n; gi++) {
    let v = parseFiniteNumber(p[`g${gi}`]);
    if (v === null) v = parseFiniteNumber(p[`stat_g${gi}`]);
    if (v === null) break;
    fromGC.push(v);
  }
  let fromGn = normalizeSeries(fromGC);

  let source = "";
  const canUseStored =
    storedN.length >= minNeed && !storedSeriesLooksLikeHitFlags(storedN, book);
  if (canUseStored) {
    actual = takeFirstNGames(storedN, n);
    source = "stored";
  } else if (extractedN.length >= minNeed && !perGameSeriesLooksLikeNoise(extractedN, book, p)) {
    actual = takeFirstNGames(extractedN, n);
    source = "extract";
  } else if (fromGn.length >= minNeed && !perGameSeriesLooksLikeNoise(fromGn, book, p)) {
    actual = takeFirstNGames(fromGn, n);
    source = "gcols";
  } else {
    return null;
  }

  let lineNums = [];

  if (source === "stored") {
    const ls = normalizeSeries(Array.isArray(p.line_series) ? p.line_series : []);
    const lsN = takeFirstNGames(ls, n);
    for (let i = 0; i < actual.length; i++) {
      const lv = Number.isFinite(lsN[i])
        ? lsN[i]
        : Number.isFinite(book)
          ? book
          : actual[i];
      lineNums.push(streakQuantize(lv));
    }
  } else if (source === "extract") {
    for (let i = 0; i < actual.length; i++) {
      const lv = ex.lineVals[i];
      lineNums.push(
        lv !== null && Number.isFinite(Number(lv))
          ? streakQuantize(Number(lv))
          : Number.isFinite(book)
            ? book
            : actual[i],
      );
    }
  } else {
    for (let i = 0; i < actual.length; i++)
      lineNums.push(Number.isFinite(book) ? book : actual[i]);
  }

  return { actual, lineSeries: lineNums };
}

function empiricalHitPctForPick(p, n = 5) {
  const hist = historySeriesForPick(p, n);
  if (!hist || !Array.isArray(hist.actual) || !hist.actual.length) return null;
  const dir = String(p?.dir || "").trim().toUpperCase();
  const lineVal = coercePropLine(p);
  if (!Number.isFinite(lineVal)) return null;
  let hits = 0;
  // Match MLB/NHL pipeline: strict > / < vs line; pushes (== line) are not over or under hits.
  for (let i = 0; i < hist.actual.length; i++) {
    const cap =
      hist.lineSeries && Number.isFinite(hist.lineSeries[i])
        ? hist.lineSeries[i]
        : lineVal;
    if (!Number.isFinite(cap)) continue;
    if (dir === "OVER") {
      if (hist.actual[i] > cap) hits += 1;
    } else {
      if (hist.actual[i] < cap) hits += 1;
    }
  }
  return Math.round((hits / hist.actual.length) * 100);
}

function pctFromValue(raw) {
  const x = Number(raw);
  if (!Number.isFinite(x)) return null;
  return x <= 1 ? Math.round(x * 100) : Math.round(x);
}

function topEdgeL5HitPct(p, dirOverride = "") {
  const d = String(dirOverride || p?.dir || "").trim().toUpperCase();
  // Game-log L5 (chart) wins over pipeline l5_over/l5_under — avoids UNDER cards showing
  // 80% when actuals vs today's line are mostly overs (or vice versa).
  const empirical = empiricalHitPctForPick({ ...p, dir: d }, 5);
  if (Number.isFinite(empirical)) return empirical;
  const hits = d === "UNDER" ? resolvedUnderHits(p, 5) : resolvedOverHits(p, 5);
  if (hits !== null) return Math.round((hits / 5) * 100);
  return pctFromValue(p?.hit);
}

/** If pipeline L5 is 80%+ but chart/game-log data are flat near zero vs line, omit the card. */
function passesTopEdgeEmpiricalSanity(p, dir) {
  const d = String(dir || "OVER").trim().toUpperCase();
  const emp = empiricalHitPctForPick({ ...p, dir: d }, 5);
  const gate = topEdgeL5HitPct({ ...p, dir: d }, d);
  if (!Number.isFinite(gate) || gate < 80) return true;
  // When we have real game logs, hit% must match the chart direction at this line.
  if (Number.isFinite(emp) && emp < 80) return false;
  const lineVal = coercePropLine(p);
  if (!Number.isFinite(lineVal) || lineVal < 2) return true;
  if (Number.isFinite(emp) && emp <= 0 && gate >= 80) return false;
  const plot = expandHistForEdgeChart(p, 5);
  if (plot && Array.isArray(plot.actual) && plot.actual.length >= 3 && gate >= 80) {
    const nums = plot.actual.map((x) => Number(x)).filter((x) => Number.isFinite(x));
    if (nums.length >= 3) {
      const avg = nums.reduce((a, x) => a + x, 0) / nums.length;
      const mx = Math.max(...nums);
      if (avg < lineVal * 0.15 && mx < lineVal * 0.35) return false;
    }
  }
  return true;
}

/** L5/L10 over/under: integer hit counts (0..n) or rates in (0,1] / percent. */
function streakHits(raw, n) {
  if (raw === null || raw === undefined) return null;
  const x = Number(raw);
  if (!Number.isFinite(x)) return null;
  const xi = Math.round(x);
  if (Math.abs(x - xi) < 1e-6 && xi >= 0 && xi <= n) return xi;
  if (x > 0 && x <= 1) return Math.max(0, Math.min(n, Math.round(x * n)));
  if (x > n && x <= 100) return Math.max(0, Math.min(n, Math.round((x / 100) * n)));
  return Math.max(0, Math.min(n, Math.round(x)));
}

/** Season line-class consistency leaders (GOB / STD / UND). */
window.__CONS_LEADERS = window.__CONS_LEADERS || { ready: false, byKey: new Map(), band: 0.5 };
function _consNormName(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9\s]/g, "").replace(/\s+/g, " ").trim();
}
function _consNormProp(s) {
  let t = String(s || "").toLowerCase().replace(/_/g, " ").replace(/\+/g, " + ").replace(/\s+/g, " ").trim();
  const aliases = {
    pts: "points", reb: "rebounds", rebs: "rebounds", ast: "assists", asts: "assists",
    pra: "pts+rebs+asts", pr: "pts+rebs", pa: "pts+asts", ra: "rebs+asts",
    "pts + rebs + asts": "pts+rebs+asts", "pts + rebs": "pts+rebs", "pts + asts": "pts+asts",
    "rebs + asts": "rebs+asts", "3pm": "3-pt made", blocks: "blocked shots",
    "g+a": "goals+assists", "goals + assists": "goals+assists",
  };
  return aliases[t] || t;
}
function _consNormPick(pt) {
  const s = String(pt || "").toLowerCase();
  if (s.includes("goblin")) return "Goblin";
  if (s.includes("demon")) return "Demon";
  if (s.includes("standard")) return "Standard";
  return "Other";
}
function _consPickClass(pickType, dir) {
  const pick = _consNormPick(pickType);
  let d = String(dir || "").toUpperCase();
  if (d === "O" || d === "MORE") d = "OVER";
  if (d === "U" || d === "LESS" || d === "LOWER") d = "UNDER";
  if (pick === "Goblin" && d === "OVER") return "goblin_over";
  if (pick === "Standard" && d === "OVER") return "standard_over";
  if (pick === "Standard" && d === "UNDER") return "standard_under";
  if (pick === "Goblin" && d === "UNDER") return "goblin_under";
  return null;
}
function _consBadgePrefix(pc) {
  return ({ goblin_over: "GOB", standard_over: "STD", standard_under: "UND", goblin_under: "UND" })[pc] || "CONS";
}
function _consKey(sport, player, prop, pickClass) {
  return [String(sport || "").toUpperCase(), _consNormName(player), _consNormProp(prop), String(pickClass || "")].join("|");
}
async function ensureConsistencyLeaders() {
  const store = window.__CONS_LEADERS;
  if (store.ready) return true;
  if (store._loadingPromise) return store._loadingPromise;
  store.loading = true;
  store._loadingPromise = (async () => {
    const urls = ["/api/consistency-leaders", "consistency_leaders_latest.json", "/data/consistency_leaders_latest.json"];
    for (const url of urls) {
      try {
        const resp = await fetch(url, { cache: "no-store" });
        if (!resp.ok) continue;
        const data = await resp.json();
        const band = Number(data.line_band);
        // Floor at 1.0 so ordinary line moves still badge season leaders.
        store.band = Math.max(Number.isFinite(band) ? band : 0.5, 1.0);
        const rows = data.match_index || data.leaders || [];
        for (const r of rows) {
          if (!r || !r.player) continue;
          const pc = r.pick_class || _consPickClass(r.pick_type, r.direction);
          if (!pc) continue;
          const k = _consKey(r.sport, r.player_norm || r.player, r.prop_key || r.prop, pc);
          const prev = store.byKey.get(k);
          if (!prev || Number(r.score || 0) > Number(prev.score || 0)) store.byKey.set(k, r);
        }
        store.ready = true;
        store.loading = false;
        return true;
      } catch (_) { /* try next */ }
    }
    store.loading = false;
    store._loadingPromise = null;
    return false;
  })();
  return store._loadingPromise;
}
function matchConsistencyLeader(p) {
  const store = window.__CONS_LEADERS;
  if (!store.ready || !p) return null;
  let dir = String(p.direction || p.dir || "").toUpperCase();
  if (dir === "O" || dir === "MORE") dir = "OVER";
  if (dir === "U" || dir === "LESS" || dir === "LOWER") dir = "UNDER";
  // Home Top Edges / ALL_SLATE use `pick`; slate tables use `pick_type`.
  const pc = _consPickClass(p.pick_type || p.pick, dir);
  if (!pc) return null;
  const k = _consKey(p.sport, p.player, p.prop || p.prop_type, pc);
  const row = store.byKey.get(k);
  if (!row) return null;
  const slateLine = Number(p.line);
  const leaderLine = Number(row.reference_line != null ? row.reference_line : row.line);
  if (Number.isFinite(slateLine) && Number.isFinite(leaderLine)) {
    if (Math.abs(slateLine - leaderLine) > (store.band + 1e-9)) return null;
  }
  return row;
}
function consLineBadgeHtml(p) {
  const row = matchConsistencyLeader(p);
  if (!row) return "";
  const hr = row.hit_rate != null ? Math.round(Number(row.hit_rate) * 100) + "%" : "?";
  const n = row.sample_n != null ? row.sample_n : "?";
  const lineVal = row.reference_line != null ? row.reference_line : row.line;
  const line = lineVal != null ? Number(lineVal).toFixed(1) : "?";
  const prefix = row.badge_prefix || _consBadgePrefix(row.pick_class);
  const tip = `Season ${row.pick_class || row.pick_type || ""} ${row.direction} ${row.prop} @${line} · ${hr} (n=${n})`;
  return `<span class="cons-line-badge cons-${String(prefix).toLowerCase()}" title="${tip.replace(/"/g, "&quot;")}">📌 ${prefix} ${hr}</span>`;
}
ensureConsistencyLeaders().then((ok) => {
  if (!ok) return;
  try {
    if (typeof scheduleRenderSlateTable === "function") {
      Object.keys(window.SLATE_DATA || {}).forEach((sp) => scheduleRenderSlateTable(sp));
    }
  } catch (_) { /* ignore */ }
  // Top Edges / Best to Run often paint before leaders finish loading — refresh badges.
  try {
    if (typeof ALL_SLATE !== "undefined" && ALL_SLATE.length) {
      if (typeof renderEdges === "function") renderEdges();
      if (typeof renderBestToRun === "function") renderBestToRun();
    }
  } catch (_) { /* ignore */ }
});

/** Prefer season consistency matches so GOB/STD/UND badges survive card limits. */
function prioritizeConsLeaderRows(rows, keyFn) {
  const keyOf = keyFn || ((p) => btrPropKey(p));
  const pinned = [];
  const rest = [];
  const seen = new Set();
  for (const p of rows || []) {
    if (!p) continue;
    const k = keyOf(p);
    if (seen.has(k)) continue;
    seen.add(k);
    if (typeof matchConsistencyLeader === "function" && matchConsistencyLeader(p)) pinned.push(p);
    else rest.push(p);
  }
  return [...pinned, ...rest];
}
/** HOT/COLD L10 badge for edge cards and slate rows (NEUTRAL → nothing). */
function l10StreakBadgeHtml(p) {
  const streak = String(p?.l10_streak || "").trim().toUpperCase();
  if (streak !== "HOT" && streak !== "COLD") return "";
  const dir = String(p?.direction || p?.dir || "OVER").trim().toUpperCase();
  const over = streakHits(p?.l10_over, 10);
  const under = streakHits(p?.l10_under, 10);
  const sideHits = dir === "UNDER" ? under : over;
  const oppHits = dir === "UNDER" ? over : under;
  if (streak === "HOT" && sideHits != null) {
    const side = dir === "UNDER" ? "under" : "over";
    return `<span class="l10-streak-badge l10-hot" title="Last 10 games ${side} today's line">🔥 ${sideHits}/10</span>`;
  }
  if (streak === "COLD" && oppHits != null) {
    const side = dir === "UNDER" ? "over" : "under";
    return `<span class="l10-streak-badge l10-cold" title="Last 10 games ${side} today's line (against pick)">❄️ ${oppHits}/10</span>`;
  }
  return "";
}

function confDotHtml(p) {
  const t = String(p?.confidence_tier || 'TRACKING').trim().toUpperCase();
  const cls = { HIGH: 'conf-high', MEDIUM: 'conf-medium', LOW: 'conf-low' }[t] || 'conf-tracking';
  let tip = 'Collecting data';
  if (t === 'LOW') {
    const hr = p?.confidence_slice_hr;
    tip = (hr != null && hr !== '') ? `Model HR: ${hr}%` : 'Model HR: low';
  } else if (t === 'TRACKING') {
    tip = 'Collecting data';
  }
  return `<span class="conf-dot ${cls}" title="${tip.replace(/"/g, '&quot;')}" aria-hidden="true"></span>`;
}

/** Detail panel L10 over/under bar (skipped when counts missing). */
function l10BarHtml(p) {
  const over = streakHits(p?.l10_over, 10);
  const under = streakHits(p?.l10_under, 10);
  if (over == null && under == null) return "";
  const ov = over != null ? over : 0;
  const un = under != null ? under : 0;
  const filled = Math.max(0, Math.min(10, ov));
  const empty = Math.max(0, 10 - filled);
  const bar = "█".repeat(filled) + "░".repeat(empty);
  return `<div class="l10-bar-wrap">
    <div class="l10-bar l10-bar-over">${bar}</div>
    <div class="l10-bar-label">${ov}/10 OVERs · ${un}/10 UNDERs</div>
  </div>`;
}

/**
 * Resolved under-side hit count in last n games.
 * Uses l5_under / l10_under when present; otherwise derives n − over_hits from l5_over / l10_over
 * (pipeline often omits the under column when only the over side is filled).
 */
function resolvedUnderHits(p, n) {
  const keyU = n === 5 ? "l5_under" : "l10_under";
  const keyO = n === 5 ? "l5_over" : "l10_over";
  const u = p[keyU];
  if (u !== null && u !== undefined && u !== "") return streakHits(u, n);
  const o = p[keyO];
  if (o === null || o === undefined || o === "") return null;
  const ho = streakHits(o, n);
  if (ho === null) return null;
  return Math.max(0, Math.min(n, n - ho));
}

/** Resolved over-side hit count in last n games (supports over-only or under-only payloads). */
function resolvedOverHits(p, n) {
  const keyO = n === 5 ? "l5_over" : "l10_over";
  const keyU = n === 5 ? "l5_under" : "l10_under";
  const o = p[keyO];
  if (o !== null && o !== undefined && o !== "") return streakHits(o, n);
  const u = p[keyU];
  if (u === null || u === undefined || u === "") return null;
  const hu = streakHits(u, n);
  if (hu === null) return null;
  return Math.max(0, Math.min(n, n - hu));
}

/** Show L5/L10 hit counts with sample size when early season (< n games). */
function formatL5Cell(overVal, underVal, gamesPlayed, window) {
  const n = window === 10 ? 10 : 5;
  const gp = gamesPlayed != null && gamesPlayed !== "" ? Number(gamesPlayed) : null;
  const sample = gp != null && Number.isFinite(gp) && gp > 0 ? Math.min(n, Math.round(gp)) : n;
  const suffix = sample < n ? `/${sample}` : "";
  const fmt = (v) => (v != null && v !== "" ? `${v}${suffix}` : "—");
  return { over: fmt(overVal), under: fmt(underVal) };
}

/** Goblin is OVER-only in this product — exclude from under-edge and under-streak surfaces. */
function isGoblinPick(p) {
  const t = String(p?.pick ?? p?.pick_type ?? "").trim().toLowerCase();
  return t === "goblin";
}

/**
 * Top Edges cards/charts: omit Fantasy Score (still in combined slate / tickets for other uses).
 * Checks several prop fields — feeds differ (display name, PP code, extra spaces).
 */
function isFantasyScoreEdgePick(p) {
  if (!p) return false;
  const fields = [
    p.prop,
    p.prop_type,
    p.market,
    p.stat,
    p.Stat,
    p.pick_stat,
    p.selection,
  ].filter((x) => x != null && String(x).trim() !== "");
  for (const f of fields) {
    const raw = String(f)
      .replace(/\u00a0/g, " ")
      .trim()
      .toLowerCase();
    const compact = raw.replace(/\s+/g, "");
    if (
      raw.includes("fantasy score") ||
      raw.includes("fantasy_score") ||
      raw.includes("fantasy pts") ||
      raw.includes("fantasy points") ||
      compact === "fantasyscore" ||
      compact === "fantasy" ||
      compact === "fs" ||
      compact === "fpts" ||
      compact.includes("fantasypts") ||
      (compact.includes("fantasy") && compact.includes("score"))
    ) {
      return true;
    }
  }
  return false;
}

/** Deterministic [0,1) — stable per player index (not Math.random). */
function streakDet01(seed, salt) {
  const x = Math.sin(seed * 12.9898 + salt * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

function streakQuantize(x) {
  return Math.max(0, Math.round(Number(x) * 4) / 4);
}

function countHitsVsPickLine(values, line, isOver) {
  if (!Array.isArray(values) || !Number.isFinite(line)) return null;
  let hits = 0;
  for (const v of values) {
    const n = Number(v);
    if (!Number.isFinite(n)) continue;
    if (isOver ? n > line : n < line) hits += 1;
  }
  return hits;
}

/** Keep quantized points strictly over/under the pick line (pushes must not sit on it). */
function forceVsPickLine(v, L, wantOver) {
  const qStep = 0.25;
  if (wantOver) {
    let q = streakQuantize(Math.max(Number(v), L + qStep));
    if (!(q > L)) q = streakQuantize(L + qStep);
    if (!(q > L)) q = L + qStep;
    return q;
  }
  let q = streakQuantize(Math.min(Number(v), Math.max(0, L - qStep)));
  if (!(q < L)) q = streakQuantize(Math.max(0, L - qStep));
  if (!(q < L)) q = Math.max(0, L - qStep);
  return q;
}

/** OVER streak slice: re-center synthetic series on pipeline L5 avg so Y scale matches the line. */
function getOverStreakSlice(p, n) {
  const L = bookLineNumForPick(p);
  const avg = plausibleStatBaseline(p.l5_avg, p.season_avg, L);
  return getPD(p.player, L, p.prop, p.sport).slice(-n).map((b) => streakQuantize(avg + (b - L) * 0.62));
}

/**
 * Spark points vs today's pick line. Real logs only if they grade to the same
 * L5/L10 count; otherwise pin hits to the correct side of the pick line.
 */
function streakSparkData(p, n, isOver, hits) {
  const L = bookLineNumForPick(p);
  const hist = historySeriesForPick(p, n);
  if (hist && Array.isArray(hist.actual) && hist.actual.length >= Math.min(n, 5)) {
    const emp = countHitsVsPickLine(hist.actual, L, isOver);
    if (emp === hits) return hist.actual;
  }
  return alignStreakSeriesToHits(p, n, isOver, hits);
}

/**
 * Last-n values for UNDER streak cards: uses pipeline l5_avg (when present) so scale matches the prop,
 * preserves game-to-game variance, and places the last `hits` games below the line (misses above).
 */
function getUnderStreakSeries(p, n, hits) {
  return alignStreakSeriesToHits(p, n, false, hits);
}

/** Pin the last `hits` games to the claimed side of the pick line (OVER above, UNDER below). */
function alignStreakSeriesToHits(p, n, isOver, hits) {
  const L = bookLineNumForPick(p);
  const avg = plausibleStatBaseline(p.l5_avg, p.season_avg, L);
  let seed = 0;
  for (const c of String(p.player || "")) seed = (seed * 31 + c.charCodeAt(0)) % 999983;
  const base = getPD(p.player, L, p.prop, p.sport).slice(-n);
  if (!Number.isFinite(hits) || hits < 0) {
    return base.map((b) => forceVsPickLine(avg + (b - L) * 0.62, L, isOver));
  }
  const h = Math.min(n, Math.max(0, Math.round(hits)));
  const jitterAmp = Math.max(0.12, Math.abs(L) * 0.04);
  return base.map((b, i) => {
    const centered = avg + (b - L) * 0.62;
    const idxFromEnd = n - 1 - i;
    const isHit = idxFromEnd < h;
    const wantOver = isOver ? isHit : !isHit;
    const jitter = (streakDet01(seed, i * 19) - 0.5) * jitterAmp;
    return forceVsPickLine(centered + jitter, L, wantOver);
  });
}

/** Game-log series for Top Edge charts: real logs when JSON has them; else streak-style synthetic (same path as L5 streak cards). */
function expandHistForEdgeChart(p, n) {
  const isOver = String(p.dir || "").toUpperCase() === "OVER";
  const hist = historySeriesForPick(p, n);
  if (hist && Array.isArray(hist.actual) && hist.actual.length >= Math.min(3, n)) {
    return hist;
  }
  let hits = isOver ? resolvedOverHits(p, n) : resolvedUnderHits(p, n);
  if (hits === null) {
    const emp = empiricalHitPctForPick({ ...p, dir: isOver ? "OVER" : "UNDER" }, n);
    if (Number.isFinite(emp)) hits = Math.round((emp / 100) * n);
  }
  if (hits === null && p.h !== undefined && p.h !== null) {
    const hh = streakHits(p.h, n);
    if (hh !== null) hits = hh;
  }
  if (hits === null) {
    const pct = topEdgeL5HitPct(p, isOver ? "OVER" : "UNDER");
    if (Number.isFinite(pct)) hits = Math.round((pct / 100) * n);
  }
  if (hits === null) hits = Math.max(1, Math.min(Math.max(1, n - 1), Math.round(0.65 * n)));
  const synth = streakSparkData(p, n, isOver, hits);
  if (!Array.isArray(synth) || !synth.length) return null;
  const actual = takeFirstNGames(normalizeSeries(synth), n);
  if (actual.length < Math.min(3, n)) return null;
  const rawLine = normalizeSeries(p.line_series || []);
  let lineSeries =
    rawLine.length >= actual.length ? takeFirstNGames(rawLine, actual.length) : [];
  if (!lineSeries.length) {
    const L = coercePropLine(p);
    lineSeries = Array.from({ length: actual.length }, () =>
      Number.isFinite(L) ? L : Number(actual[actual.length - 1]) || 0
    );
  }
  return { actual, lineSeries };
}

function seedPlayerDataFromCardPicks(picks) {
  for (const p of picks || []) {
    if (!p || !p.player) continue;
    const lineNum = bookLineNumForPick(p);
    const spread = lineNum * 0.35;
    const avg = plausibleStatBaseline(p.l5_avg, p.season_avg, lineNum);
    const pk = playerSeriesKey(p.player, lineNum, p.prop, p.sport);
    if (PLAYER_DATA[pk]) continue;
    let s = 0;
    for (const c of p.player) s = (s * 31 + c.charCodeAt(0)) % 1000;
    PLAYER_DATA[pk] = Array.from({length: 10}, (_, i) => {
      s = (s * 9301 + 49297) % 233280;
      return Math.max(0, Math.round((avg + ((s / 233280) - 0.5) * spread * 2) * 4) / 4);
    });
  }
}

function mergePlayerDataFromTicketLegs(picks) {
  for (const p of picks || []) {
    if (!p || !p.player) continue;
    const prop = p.prop || p.prop_type || "";
    const lineNum = bookLineNumForPick(p);
    const pk = playerSeriesKey(p.player, lineNum, prop, p.sport);
    if (PLAYER_DATA[pk]) continue;
    const spread = lineNum * 0.35;
    const avg = plausibleStatBaseline(p.l5_avg, p.season_avg, lineNum);
    let s = 0;
    for (const c of p.player) s = (s * 31 + c.charCodeAt(0)) % 1000;
    PLAYER_DATA[pk] = Array.from({length: 10}, (_, i) => {
      s = (s * 9301 + 49297) % 233280;
      return Math.max(0, Math.round((avg + ((s / 233280) - 0.5) * spread * 2) * 4) / 4);
    });
  }
}

function picksFromSlateLatestJson(data) {
  if (!data || typeof data !== "object") {
    return { picks: [], date: "", generated_at: "", source: "slate_latest" };
  }
  const sports = data.sports || {};
  const picks = [];
  const seen = new Set();
  for (const rawKey of Object.keys(sports)) {
    const rows = sports[rawKey];
    if (!Array.isArray(rows)) continue;
    const sportLabel = String(rawKey).trim().toUpperCase();
    for (const row of rows) {
      if (!row || typeof row !== "object") continue;
      const player = row.player || "";
      const prop = row.prop || row.prop_type || "";
      const dirv = String(row.dir || row.direction || "OVER").trim().toUpperCase() || "OVER";
      const line = row.line;
      const key = `${player}|${prop}|${dirv}|${line}`;
      if (seen.has(key)) continue;
      seen.add(key);
      let l5_under = row.l5_under;
      if (l5_under == null && row.l5_over != null) {
        const ho = streakHits(row.l5_over, 5);
        if (ho != null) l5_under = 5 - ho;
      }
      let l10_under = row.l10_under;
      if (l10_under == null && row.l10_over != null) {
        const ho = streakHits(row.l10_over, 10);
        if (ho != null) l10_under = 10 - ho;
      }
      let hr = Number(row.hit_rate != null ? row.hit_rate : 0);
      if (!Number.isFinite(hr)) hr = 0;
      let edge = Number(row.edge != null ? row.edge : 0);
      if (!Number.isFinite(edge)) edge = 0;
      const hitPct = hr <= 1 ? Math.round(hr * 100) : Math.round(hr);
      const rawExGames = extractPerGameSeriesFromObject(row, 10);
      let actualSeriesRow = Array.isArray(row.actual_series) ? row.actual_series : [];
      let lineSeriesRow = Array.isArray(row.line_series) ? row.line_series : [];
      if (!normalizeSeries(actualSeriesRow).length && rawExGames.actualVals.length) {
        actualSeriesRow = rawExGames.actualVals;
      }
      if (!normalizeSeries(lineSeriesRow).length && rawExGames.lineVals.some((v) => v != null && Number.isFinite(Number(v)))) {
        lineSeriesRow = rawExGames.lineVals.map((v) =>
          v != null && Number.isFinite(Number(v)) ? Number(v) : row.line,
        );
      }
      picks.push({
        sport: sportLabel,
        tier: row.tier || row.rank_tier || "",
        initials: row.initials || (row.player||"").split(" ").filter(w=>w).map(w=>w[0]).join("").slice(0,2).toUpperCase(),
        player,
        prop,
        line,
        pick: row.pick_type || "Standard",
        dir: dirv,
        hit: hitPct,
        edge,
        projection: row.projection,
        rank_tier: row.rank_tier ?? row.tier ?? "",
        l5_over: row.l5_over,
        l5_under,
        l10_over: row.l10_over,
        l10_under,
        l5_avg: row.l5_avg,
        season_avg: row.season_avg || row.szn_avg,
        actual_series: actualSeriesRow,
        line_series: lineSeriesRow,
      });
    }
  }
  picks.sort((a, b) => Math.abs(Number(b.edge) || 0) - Math.abs(Number(a.edge) || 0));
  const cap = 2500;
  const capped = picks.length > cap ? picks.slice(0, cap) : picks;
  return {
    picks: capped,
    date: String(data.date || ""),
    generated_at: String(data.generated_at || ""),
    source: "slate_latest",
  };
}

function slateFetchOpts(timeoutMs) {
  const fetchOpts = { cache: "default" };
  if (typeof AbortSignal !== "undefined" && AbortSignal.timeout) {
    fetchOpts.signal = AbortSignal.timeout(timeoutMs || 60000);
  }
  return fetchOpts;
}

async function loadHomeCardsFromFullSlate() {
  try {
    const fetchOpts = slateFetchOpts(60000);
    // Prefer compact card payload (history included, capped) over full combined slate.
    const rCards = await fetch("/api/slate-cards?max=400", fetchOpts);
    if (rCards.ok) {
      const dCards = await rCards.json();
      const rows = Array.isArray(dCards.rows) ? dCards.rows : [];
      if (rows.length) {
        SLATE_DEBUG_META = {
          source: "slate_cards_api",
          generated_at: String(dCards.generated_at || ""),
          date: String(dCards.date || ""),
        };
        if (syncCardsFromCombinedRows(rows)) return;
      }
    }
    const rBundle = await fetch("slate_cards.json", fetchOpts);
    if (rBundle.ok) {
      const dBundle = await rBundle.json();
      const rows = Array.isArray(dBundle.rows) ? dBundle.rows : [];
      if (rows.length) {
        SLATE_DEBUG_META = {
          source: "slate_cards_bundle",
          generated_at: String(dBundle.generated_at || ""),
          date: String(dBundle.date || ""),
        };
        if (syncCardsFromCombinedRows(rows)) return;
      }
    }
    // Fallbacks for older deploys / offline bundles without slate_cards.json
    const r2 = await fetch("/api/slate-sport/combined", fetchOpts);
    if (r2.ok) {
      const d2 = await r2.json();
      const rows = Array.isArray(d2.rows) ? d2.rows : [];
      if (rows.length) {
        SLATE_DEBUG_META = {
          source: "slate_latest_combined",
          generated_at: String(d2.generated_at || ""),
          date: String(d2.date || ""),
        };
        if (syncCardsFromCombinedRows(rows)) return;
      }
    }
    const r3 = await fetch("slate_sport_combined.json", fetchOpts);
    if (r3.ok) {
      const d3 = await r3.json();
      const rows = Array.isArray(d3.rows) ? d3.rows : [];
      if (rows.length) {
        SLATE_DEBUG_META = {
          source: "slate_sport_combined_bundle",
          generated_at: String(d3.generated_at || ""),
          date: String(d3.date || ""),
        };
        if (syncCardsFromCombinedRows(rows)) return;
      }
    }
    const r = await fetch("/api/slate-excel", fetchOpts);
    if (r.ok) {
      const d = await r.json();
      const sh = d.sheets && d.sheets.combined;
      if (sh && sh.columns && sh.rows && sh.rows.length) {
        SLATE_DEBUG_META = {
          source: "combined_excel",
          generated_at: "",
          date: String(d.date || ""),
        };
        if (syncCardsFromCombinedSheet(sh.columns, sh.rows)) return;
      }
    }
  } catch (e) {
    console.warn("loadHomeCardsFromFullSlate:", e);
  }
}

async function loadSlateData() {
  if (slateDataPromise) return slateDataPromise;
  slateDataPromise = (async () => {
    await loadHomeCardsFromFullSlate();
    const applySlatePayload = (d) => {
      const ticketMeta = {
        source: String(d?.source || ""),
        generated_at: String(d?.generated_at || ""),
        date: String(d?.date || ""),
      };
      if (!SLATE_CARDS_POPULATED) {
        SLATE_DEBUG_META = ticketMeta;
        ALL_SLATE = (d.picks || []).map(mapApiPickToSlateRow).filter(Boolean);
        for (const p of (d.picks || [])) {
          if (p.player) {
            const lineNum = bookLineNumForPick(p);
            const avg = plausibleStatBaseline(p.l5_avg, p.season_avg, lineNum);
            const spread = lineNum * 0.35;
            const pk = playerSeriesKey(p.player, lineNum, p.prop, p.sport);
            if (PLAYER_DATA[pk]) continue;
            let s = 0;
            for (let c of p.player) s = (s * 31 + c.charCodeAt(0)) % 1000;
            PLAYER_DATA[pk] = Array.from({length: 10}, (_, i) => {
              s = (s * 9301 + 49297) % 233280;
              return Math.max(0, Math.round((avg + ((s / 233280) - 0.5) * spread * 2) * 4) / 4);
            });
          }
        }
      } else {
        if (!SLATE_DEBUG_META.date && ticketMeta.date) SLATE_DEBUG_META.date = ticketMeta.date;
        mergePlayerDataFromTicketLegs(d.picks || []);
      }
    };
    let slatePayload = null;
    try {
      const fetchOpts = slateFetchOpts(120000);
      if (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) {
        fetchOpts.signal = AbortSignal.timeout(120000);
      }
      const sportQ = new URLSearchParams(window.location.search).get("sport");
      const slateUrl = sportQ
        ? `/api/slate?sport=${encodeURIComponent(String(sportQ).trim().toUpperCase())}`
        : "/api/slate";
      const res = await fetch(slateUrl, fetchOpts);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const d = await res.json();
      slatePayload = d;
      applySlatePayload(d);
    } catch (err) {
      console.warn("loadSlateData failed:", err);
      if (!SLATE_CARDS_POPULATED) {
        try {
          const fb = await fetch("slate_latest.json", slateFetchOpts(60000));
          if (fb.ok) {
            const raw = await fb.json();
            const d = Array.isArray(raw.picks) ? raw : picksFromSlateLatestJson(raw);
            slatePayload = d;
            applySlatePayload(d);
          }
        } catch (fbErr) {
          console.warn("loadSlateData fallback failed:", fbErr);
        }
      }
    }
    if (typeof window.applyHeroSlateDate === "function") {
      await window.applyHeroSlateDate();
    }
    renderTopEdgesDebugTag();
    // Merge actual_series/line_series from /api/slate into ALL_SLATE entries
    if (slatePayload && Array.isArray(slatePayload.picks)) {
      const maps = buildSlatePickMaps(slatePayload.picks);
      for (const row of ALL_SLATE) {
        const _m = resolveSlatePickForRow(row, maps);
        if (_m) {
          const apiAct = _m.actual_series;
          if (Array.isArray(apiAct) && apiAct.length >= 3) {
            row.actual_series = apiAct;
          }
          const apiLS = _m.line_series;
          if (Array.isArray(apiLS) && apiLS.length > 0) {
            row.line_series = apiLS;
          }
          if (_m.line != null && _m.line !== "") {
            row.line = _m.line;
          }
          if (_m.standard_line != null && _m.standard_line !== "") {
            row.standard_line = _m.standard_line;
          }
          if (_m.book_line != null && _m.book_line !== "") {
            row.book_line = _m.book_line;
          }
          if (_m.prop_line != null && _m.prop_line !== "") {
            row.prop_line = _m.prop_line;
          }
          const apiProj = Number(_m.projection);
          if (Number.isFinite(apiProj) && apiProj > 0) {
            row.projection = _m.projection;
          } else if (row.projection == null || row.projection === "" || Number(row.projection) === 0) {
            row.projection = _m.projection;
          }
          if (_m.standard_projection != null && _m.standard_projection !== "") {
            row.standard_projection = _m.standard_projection;
          }
          if (row.l5_avg == null) row.l5_avg = _m.l5_avg;
          if (row.season_avg == null) row.season_avg = _m.season_avg;
          if (row.team == null || row.team === "") row.team = _m.team;
          if (row.opp == null || row.opp === "") row.opp = _m.opp;
          if (row.tier == null) row.tier = _m.tier;
          if (row.rank_score == null) row.rank_score = _m.rank_score ?? _m.rank;
          if (row.ml_prob == null) row.ml_prob = _m.ml_prob;
          if (row.def_tier == null) row.def_tier = _m.def_tier;
          if (row.game_time == null || row.game_time === "") row.game_time = _m.game_time;
          if (row.book_line == null) row.book_line = _m.book_line ?? _m.prop_line;
          if (row.abs_edge == null) row.abs_edge = _m.abs_edge;
          for (let gi = 1; gi <= 10; gi++) {
            const gk = `g${gi}`;
            const sk = `stat_g${gi}`;
            if (_m[gk] != null && _m[gk] !== "") row[gk] = _m[gk];
            if (_m[sk] != null && _m[sk] !== "") row[sk] = _m[sk];
          }
        }
      }
    }
    renderEdges();
    renderBestToRun();
    renderStreaks();
    // Slate panel rows are fetched lazily per sport via /api/slate-sport/<sport>.
  })();
  return slateDataPromise;
}

/** Pipeline modified string: date only on Slate Explorer cards (no time). */
function formatSlateModifiedDisplay(raw) {
  if (!raw || typeof raw !== "string") return "—";
  const s = raw.trim();
  const m = s.match(/^(\d{4}-\d{2}-\d{2})(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?/);
  if (m) return m[1];
  return s;
}

/** Normalize mixed game-time strings to "MM/DD h:mm AM/PM" for mobile tables. */
function formatGameTimeDisplay(raw) {
  if (raw == null) return '—';
  const s = String(raw).trim();
  if (!s) return '—';

  // Already like "04/25 8:30 PM" -> normalize spacing/casing.
  const mdAmpm = s.match(/^(\d{1,2})\/(\d{1,2})(?:\/\d{2,4})?\s+(\d{1,2}):(\d{2})\s*([AP]M)$/i);
  if (mdAmpm) {
    const mm = mdAmpm[1].padStart(2, '0');
    const dd = mdAmpm[2].padStart(2, '0');
    const hh = String(parseInt(mdAmpm[3], 10));
    const mi = mdAmpm[4];
    const ap = mdAmpm[5].toUpperCase();
    return `${mm}/${dd} ${hh}:${mi} ${ap}`;
  }

  // ISO-like: 2026-04-25 18:05:00-04:00 or 2026-04-25T18:05:00Z
  const isoLike = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/);
  if (isoLike) {
    const mm = isoLike[2];
    const dd = isoLike[3];
    let h = parseInt(isoLike[4], 10);
    const mi = isoLike[5];
    const ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12;
    if (h === 0) h = 12;
    return `${mm}/${dd} ${h}:${mi} ${ap}`;
  }

  // Fallback: try Date parsing, then format.
  const d = new Date(s);
  if (!Number.isNaN(d.getTime())) {
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    let h = d.getHours();
    const mi = String(d.getMinutes()).padStart(2, '0');
    const ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12;
    if (h === 0) h = 12;
    return `${mm}/${dd} ${h}:${mi} ${ap}`;
  }

  return s;
}

/** Pipeline / API timestamps are UTC wall clock (YYYY-MM-DD HH:MM:SS). Fresh = same US Eastern calendar day as "now". */
const PROPORACLE_SLATE_FRESHNESS_TZ = "America/New_York";
function ymdInEastern(d) {
  if (!d || Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: PROPORACLE_SLATE_FRESHNESS_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

/** Match run_pipeline.ps1 / combined_slate_tickets season resume dates (ET). */
const SPORT_SEASON_RESUME = {
  nba: "2026-10-01",
  nba1h: "2026-10-01",
  nba1q: "2026-10-01",
  nhl: "2026-09-01",
};
function isSportDateOffSeason(sportId) {
  const resume = SPORT_SEASON_RESUME[String(sportId || "").toLowerCase()];
  if (!resume) return false;
  const today = ymdInEastern(new Date());
  return Boolean(today && today < resume);
}
function isNbaFamilyOffSeason() {
  return isSportDateOffSeason("nba");
}
function getOffseasonSportIds() {
  const ids = ["cbb", "cfb", "nfl", "wcbb"];
  for (const sport of ["nba", "nba1h", "nba1q", "nhl"]) {
    if (isSportDateOffSeason(sport)) ids.push(sport);
  }
  return ids;
}
function getDefaultBootSlateSport() {
  if (!isSportDateOffSeason("nba")) return "nba";
  const off = new Set(getOffseasonSportIds());
  for (const sport of ["wnba", "soccer", "mlb", "tennis"]) {
    if (!off.has(sport)) return sport;
  }
  return "wnba";
}

/** Open the default in-season sport panel so fetched props are visible without an extra click. */
function autoOpenBootSlatePanel() {
  const sport = getDefaultBootSlateSport();
  const panel = document.getElementById(`sp-${sport}`);
  if (!panel || panel.classList.contains("open")) return;
  try {
    toggleSlatePanel(sport);
  } catch (e) {
    console.warn("autoOpenBootSlatePanel:", e);
  }
}
function applyOffseasonSportCards() {
  const today = ymdInEastern(new Date());
  ["cbb", "cfb", "nfl", "wcbb"].forEach((id) => {
    document.getElementById(`sc-${id}`)?.classList.add("inactive-sport");
  });
  if (!today) return;
  document.querySelectorAll("#slate-panel-header-row [data-offseason-resume]").forEach((el) => {
    const resume = String(el.getAttribute("data-offseason-resume") || "").trim();
    if (resume && today < resume) el.classList.add("inactive-sport");
    else el.classList.remove("inactive-sport");
  });
}

/** Tennis always targets the next ET calendar day (tomorrow's board). */
function ymdTomorrowEt() {
  const today = ymdInEastern(new Date());
  if (!today) return null;
  const parts = today.split("-").map((x) => parseInt(x, 10));
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return null;
  const dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + 1, 12, 0, 0));
  return ymdInEastern(dt);
}
function tennisMatchDayEt() {
  return ymdTomorrowEt();
}
function parsePipelineModifiedAsUtc(s) {
  const m = (s || "").trim().match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (!m) return null;
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]));
}

/** Sports where FRESH requires at least one prop on today's ET calendar day (not tomorrow's board). */
const SLATE_STRICT_GAME_DAY_SPORTS = new Set(["nhl", "nfl", "mlb", "nba1h", "nba1q", "soccer", "wnba"]);

function slateRowsFromPayload(data) {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if (Array.isArray(data.rows)) return data.rows;
  if (Array.isArray(data.props)) return data.props;
  return [];
}

function rowGameDateEt(row) {
  const gd = String(row?.game_date || "").trim().slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(gd)) return gd;
  const gt = String(row?.game_time || "").trim();
  const mIso = gt.match(/^(\d{4}-\d{2}-\d{2})/);
  if (mIso) return mIso[1];
  const mMd = gt.match(/^(\d{1,2})\/(\d{1,2})(?:\b|[\sT])/);
  if (mMd) {
    const y = ymdInEastern(new Date()).slice(0, 4);
    return `${y}-${String(mMd[1]).padStart(2, "0")}-${String(mMd[2]).padStart(2, "0")}`;
  }
  return null;
}

async function sportSlateHasGamesOnDay(sportId, targetYmd) {
  if (!targetYmd) return null;
  try {
    let res = await fetch(`/api/slate-sport/${encodeURIComponent(sportId)}`, slateFetchOpts(60000));
    if (!res.ok) res = await fetch(`slate_sport_${sportId}.json`, slateFetchOpts(60000));
    if (!res.ok) return null;
    const data = await res.json();
    const rows = slateRowsFromPayload(data);
    if (!rows.length) return false;
    return rows.some((r) => rowGameDateEt(r) === targetYmd);
  } catch {
    return null;
  }
}

async function sportSlateHasTodayGames(sportId) {
  if (!SLATE_STRICT_GAME_DAY_SPORTS.has(sportId)) return null;
  return sportSlateHasGamesOnDay(sportId, ymdInEastern(new Date()));
}

function applyStatusCard(id, info, _label, opts) {
  const card = document.getElementById(`sc-${id}`),
        val = document.getElementById(`sc-${id}-val`),
        badge = document.getElementById(`sc-${id}-badge`);
  if (!card || !val || !badge) return;
  card.classList.remove("fresh","stale","missing","loading");
  badge.classList.remove("fresh","stale","missing","loading");
  // Missing endpoint field or no artifact yet → neutral pending (not "stale").
  if (!info || !info.exists) {
    card.classList.add("loading"); badge.classList.add("loading");
    val.textContent = "Not Yet Run";
    badge.textContent = "PENDING";
    return;
  }
  const modUtc = parsePipelineModifiedAsUtc(info.modified || "");
  const modEt = modUtc ? ymdInEastern(modUtc) : null;
  const todayEt = ymdInEastern(new Date());
  let fresh = Boolean(modEt && todayEt && modEt === todayEt);
  if (fresh && opts?.requireTodayGames && opts.hasTodayGames === false) fresh = false;
  const cls = fresh ? "fresh" : "stale";
  card.classList.add(cls); badge.classList.add(cls);
  val.textContent = formatSlateModifiedDisplay(info.modified || "—");
  badge.textContent = fresh ? "FRESH" : "STALE";
}

function sportDisplayLabel(rawSport) {
  const key = String(rawSport || '').trim().toUpperCase();
  const labels = {
    NBA: 'NBA (Full Game)',
    NBA1H: 'NBA (1H)',
    NBA1Q: 'NBA (1Q)',
    CBB: 'CBB',
    CFB: 'College Football',
    WCBB: 'WCBB',
    NHL: 'NHL',
    SOCCER: 'Soccer',
    MLB: 'MLB',
    NFL: 'NFL',
    TENNIS: 'Tennis',
    WNBA: 'WNBA',
  };
  return labels[key] || rawSport || '';
}

async function refreshStatus() {
  let d = null;
  try {
    const res = await fetch("/api/pipeline/status", slateFetchOpts(60000));
    if (res.ok) d = await res.json();
  } catch (e) {}
  // Bundled / Capacitor WebView: no API — use static file from mobile/www (see generate_mobile_bundle.py).
  if (!d) {
    try {
      const r2 = await fetch("pipeline_status.json", slateFetchOpts(60000));
      if (r2.ok) d = await r2.json();
    } catch (e2) {}
  }
  const statusIds = ["nba", "nba1h", "nba1q", "cbb", "cfb", "nhl", "soccer", "mlb", "nfl", "tennis", "wnba", "combined"];
  if (!d) {
    for (const id of statusIds) applyStatusCard(id, { exists: false, modified: "" }, "");
    applyOffseasonSportCards();
    return;
  }
  // Prefer server-side game_day flags (avoids N× /api/slate-sport fan-out every minute).
  const gameDay = (d.game_day && typeof d.game_day === "object") ? d.game_day : {};
  const statusOpts = (sid) => {
    if (sid === "tennis") {
      return { requireTodayGames: true, hasTodayGames: gameDay.tennis };
    }
    if (SLATE_STRICT_GAME_DAY_SPORTS.has(sid)) {
      return { requireTodayGames: true, hasTodayGames: gameDay[sid] };
    }
    return null;
  };
  applyStatusCard("nba",      d.nba?.slate,      "NBA Slate");
  applyStatusCard("nba1h",    d.nba1h?.slate,    "NBA 1H Slate", statusOpts("nba1h"));
  applyStatusCard("nba1q",    d.nba1q?.slate,    "NBA 1Q Slate", statusOpts("nba1q"));
  applyStatusCard("cbb",      d.cbb?.slate,      "CBB Slate");
  applyStatusCard("cfb",      d.cfb?.slate,      "CFB Slate");
  applyStatusCard("nhl",      d.nhl?.slate,      "NHL Slate", statusOpts("nhl"));
  applyStatusCard("soccer",   d.soccer?.slate,   "Soccer Slate", statusOpts("soccer"));
  const soccerVal = document.getElementById("sc-soccer-val");
  const soccerMd = d.soccer_match_day;
  if (soccerVal && soccerMd && d.soccer?.slate?.exists) soccerVal.textContent = soccerMd;
  applyStatusCard("mlb",      d.mlb?.slate,      "MLB Slate", statusOpts("mlb"));
  applyStatusCard("nfl",      d.nfl?.slate,      "NFL Slate", statusOpts("nfl"));
  applyStatusCard("tennis",   d.tennis?.slate,   "Tennis Slate", statusOpts("tennis"));
  const tennisVal = document.getElementById("sc-tennis-val");
  const tennisMd = d.tennis_match_day || tennisMatchDayEt();
  if (tennisVal && tennisMd) tennisVal.textContent = tennisMd;
  applyStatusCard("wnba",     d.wnba?.slate,     "WNBA Slate", statusOpts("wnba"));
  applyStatusCard("combined", d.combined?.slate, "Combined Tickets");
  applyOffseasonSportCards();
  if (typeof window.applyHomeSkewBanner === "function") {
    window.applyHomeSkewBanner(d);
  }
}
setInterval(refreshStatus, 60000);
refreshStatus();

(function initHomeSkewBanner() {
  function fmtChip(ymd) {
    if (!ymd || String(ymd).length < 10) return "";
    const parts = String(ymd).slice(0, 10).split("-").map(Number);
    const dt = new Date(parts[0], parts[1] - 1, parts[2]);
    return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  function applyHomeSkewBanner(meta) {
    const el = document.getElementById("home-skew-banner");
    if (!el || !meta) return;
    const ticketsEmpty = Boolean(meta.tickets_empty);
    const skew = Boolean(meta.skew) || (
      meta.tickets_date && meta.slate_date && meta.tickets_date !== meta.slate_date
    );
    if (!ticketsEmpty && !skew) {
      el.removeAttribute("data-show");
      el.textContent = "";
      return;
    }
    const slateChip = fmtChip(meta.slate_date || meta.date || meta.tickets_date);
    const populated = Array.isArray(meta.populated_sports) ? meta.populated_sports : [];
    let detail = "showing pipeline props";
    if (ticketsEmpty && populated.length) {
      detail = "tickets empty · " + populated.join("/") + " on slate";
    } else if (ticketsEmpty) {
      detail = "tickets empty · showing pipeline props";
    } else if (skew) {
      detail = "tickets " + fmtChip(meta.tickets_date) + " · slate " + fmtChip(meta.slate_date);
    }
    el.innerHTML = "<strong>BOARD</strong>" +
      (slateChip ? ("Slate " + slateChip + " · ") : "") + detail;
    el.setAttribute("data-show", "1");
  }
  window.applyHomeSkewBanner = applyHomeSkewBanner;
  (async function bootBanner() {
    try {
      const res = await fetch("/api/slate-display-date", slateFetchOpts(60000));
      if (res.ok) applyHomeSkewBanner(await res.json());
    } catch (e) {}
  })();
})();

// ── SVG chart (full) — premium area chart ──────────────────
function makeSVG(data, bookLine, isOver, W=260, H=100, bookLineSeries=null, extraScale=null) {
  if (!data || data.length === 0) {
    return `<div style="height:100px;display:flex;align-items:center;justify-content:center;color:var(--muted2);font-size:11px;border:1px dashed rgba(255,255,255,.12);border-radius:10px;">No chart data</div>`;
  }
  const pL=32,pR=10,pT=14,pB=22, cW=W-pL-pR, cH=H-pT-pB;
  const lineVals = Array.isArray(bookLineSeries) && bookLineSeries.length === data.length ? bookLineSeries : Array.from({length:data.length},()=>bookLine);
  const scaleExtras = [];
  const blN = Number(bookLine);
  if (Number.isFinite(blN)) scaleExtras.push(blN);
  if (Array.isArray(extraScale)) {
    for (const x of extraScale) {
      if (Number.isFinite(Number(x))) scaleExtras.push(Number(x));
    }
  }
  const allVals = [...data, ...lineVals, ...scaleExtras].filter((x) =>
    Number.isFinite(Number(x)),
  );
  const pad=Math.max((Math.max(...allVals)-Math.min(...allVals))*0.18, Number(bookLine||0)*0.08);
  const mn=Math.min(...allVals)-pad, mx=Math.max(...allVals)+pad, R=mx-mn||1;
  const xDenom = Math.max(1, data.length - 1);
  const px=(v,i)=>pL+(i/xDenom)*cW;
  const py=v=>pT+cH-((v-mn)/R)*cH;
  const actualColor='#22d3ee', lineColor='#f39c12';
  const uid='ch'+Math.random().toString(36).slice(2,7);
  const pts=data.map((v,i)=>({x:px(v,i),y:py(v)}));
  const lpts=lineVals.map((v,i)=>({x:px(v,i),y:py(v)}));
  // bezier control points
  function cpx(p1,p2,t){return p1.x+(p2.x-p1.x)*t;}
  function cpy(p1,p2,t){return p1.y+(p2.y-p1.y)*t;}
  let pathD='M'+pts[0].x+','+pts[0].y;
  let lineD='M'+lpts[0].x+','+lpts[0].y;
  for(let i=1;i<pts.length;i++){
    const prev=pts[i-1],curr=pts[i];
    const lprev=lpts[i-1], lcurr=lpts[i];
    const cp1x=prev.x+(curr.x-prev.x)*0.5, cp1y=prev.y;
    const cp2x=prev.x+(curr.x-prev.x)*0.5, cp2y=curr.y;
    pathD+=` C${cp1x},${cp1y} ${cp2x},${cp2y} ${curr.x},${curr.y}`;
    const lcp1x=lprev.x+(lcurr.x-lprev.x)*0.5, lcp1y=lprev.y;
    const lcp2x=lprev.x+(lcurr.x-lprev.x)*0.5, lcp2y=lcurr.y;
    lineD+=` C${lcp1x},${lcp1y} ${lcp2x},${lcp2y} ${lcurr.x},${lcurr.y}`;
  }
  const areaD=pathD+` L${pts[pts.length-1].x},${pT+cH} L${pts[0].x},${pT+cH} Z`;
  let s=`<svg viewBox="0 0 ${W} ${H}" style="overflow:visible;width:100%;height:auto">`;
  s+=`<defs>
    <linearGradient id="ag${uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${actualColor}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="${actualColor}" stop-opacity="0.01"/>
    </linearGradient>
    <clipPath id="clip${uid}"><rect x="${pL}" y="${pT}" width="${cW}" height="${cH}"/></clipPath>
  </defs>`;
  // subtle horizontal grid lines
  [0,0.25,0.5,0.75,1].forEach(t=>{
    const y=pT+cH*t;
    s+=`<line x1="${pL}" y1="${y}" x2="${W-pR}" y2="${y}" stroke="rgba(255,255,255,.04)" stroke-width="1"/>`;
  });
  // axis labels
  [mn,(mn+mx)/2,mx].forEach(v=>{
    const y=py(v);
    s+=`<text x="${pL-4}" y="${y+3.5}" text-anchor="end" font-size="8" fill="#555575" font-family="Inter,sans-serif" font-weight="500">${Math.round(v*10)/10}</text>`;
  });
  // area fill
  s+=`<path d="${areaD}" fill="url(#ag${uid})" clip-path="url(#clip${uid})"/>`;
  s+=`<path d="${lineD}" fill="none" stroke="${lineColor}" stroke-width="1.25" stroke-dasharray="4,3" opacity="0.9" clip-path="url(#clip${uid})"/>`;
  s+=`<path d="${pathD}" fill="none" stroke="${actualColor}" stroke-width="1.8" stroke-linecap="round" clip-path="url(#clip${uid})"/>`;
  // dots + labels
  data.forEach((v,i)=>{
    const cx=px(v,i), cy=py(v);
    const ly=py(lineVals[i]);
    s+=`<circle cx="${cx}" cy="${cy}" r="3.5" fill="${actualColor}" stroke="rgba(0,0,0,.5)" stroke-width="1"/>`;
    s+=`<circle cx="${cx}" cy="${ly}" r="2.5" fill="${lineColor}" stroke="rgba(0,0,0,.45)" stroke-width="0.8"/>`;
    s+=`<text x="${cx}" y="${cy-9}" text-anchor="middle" font-size="8.5" fill="${actualColor}" font-weight="700" font-family="Inter,sans-serif">${v}</text>`;
    s+=`<text x="${cx}" y="${H-5}" text-anchor="middle" font-size="7" fill="#44446a" font-family="Inter,sans-serif">G${i+1}</text>`;
  });
  s+=`<text x="${pL}" y="${pT-2}" font-size="8" fill="${actualColor}" font-family="Inter,sans-serif">Actual</text>`;
  s+=`<text x="${pL+36}" y="${pT-2}" font-size="8" fill="${lineColor}" font-family="Inter,sans-serif">Line</text>`;
  s+='</svg>'; return s;
}

// ── SVG sparkline (streak cards) — premium ────────────────
/** Orange dashed line = pick/book line the 5/5 is claimed against (not model projection). */
function makeSparkSVG(data, line, isOver, W=150, H=48, projRef=null) {
  if (!data || data.length === 0) {
    return `<svg viewBox="0 0 ${W} ${H}" style="overflow:visible;width:100%;height:auto;opacity:.35"><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="var(--muted2)" font-size="10">—</text></svg>`;
  }
  const bookLine = Number(line);
  const refLine = bookLine;
  const dMin = Math.min(...data), dMax = Math.max(...data);
  const span = dMax - dMin;
  const linePad = Math.max(Math.abs(Number(line) || 0) * 0.1, 0.14);
  let pad = span * 0.24;
  if (!Number.isFinite(pad) || pad < linePad * 0.45) pad = linePad * 0.45;
  if (span === 0) pad = linePad;
  const mn = Math.min(dMin, bookLine, refLine) - pad, mx = Math.max(dMax, bookLine, refLine) + pad, R = mx - mn || 1;
  const denom = Math.max(1, data.length - 1);
  const px=(v,i)=>4+(i/denom)*(W-8);
  const py=v=>H-4-((v-mn)/R)*(H-10);
  const hc=isOver?'#2ecc71':'#f39c12', mc='#e74c3c';
  const uid='sp'+Math.random().toString(36).slice(2,7);
  const pts=data.map((v,i)=>({x:px(v,i),y:py(v)}));
  let pathD='M'+pts[0].x+','+pts[0].y;
  for(let i=1;i<pts.length;i++){
    const p=pts[i-1],c=pts[i];
    pathD+=` C${p.x+(c.x-p.x)*.5},${p.y} ${p.x+(c.x-p.x)*.5},${c.y} ${c.x},${c.y}`;
  }
  const areaD=pathD+` L${pts[pts.length-1].x},${H} L${pts[0].x},${H} Z`;
  const lY=py(refLine);
  let s=`<svg viewBox="0 0 ${W} ${H}" style="overflow:visible;width:100%;height:auto">`;
  s+=`<defs>
    <linearGradient id="sg${uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${hc}" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="${hc}" stop-opacity="0"/>
    </linearGradient>
  </defs>`;
  s+=`<path d="${areaD}" fill="url(#sg${uid})"/>`;
  s+=`<line x1="0" y1="${lY}" x2="${W}" y2="${lY}" stroke="#f39c12" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>`;
  s+=`<path d="${pathD}" fill="none" stroke="${hc}55" stroke-width="2.5" stroke-linecap="round"/>`;
  s+=`<path d="${pathD}" fill="none" stroke="${hc}" stroke-width="1.5" stroke-linecap="round"/>`;
  data.forEach((v,i)=>{
    const hit = isOver ? v > bookLine : v < bookLine;
    const dc = hit ? hc : mc;
    const cx=px(v,i), cy=py(v);
    s+=`<circle cx="${cx}" cy="${cy}" r="4.5" fill="${hc}18" stroke="none"/>`;
    s+=`<circle cx="${cx}" cy="${cy}" r="2.5" fill="${dc}" stroke="rgba(0,0,0,.6)" stroke-width="0.8"/>`;
  });
  s+='</svg>'; return s;
}

// ── Top Edges — expandable cards ──────────────────────────
/** Legacy: charts are always rendered; accordion state removed */
let EDGE_DISPLAY_PICK = {};

function buildEdgeCard(p, idx) {
  const isOver=p.dir==="OVER", dc=isOver?"over":"under";
  const sc=`sp-${safeSportKey(p)}`, pc=p.pick==="Goblin"?"pick-goblin":"pick-standard";
  const sportLabel = sportDisplayLabel(p.sport);
  const edgeDisp = fmtEdgePick(p);
  const hitDisplay = topEdgeL5HitPct(p);
  const hitPct = Number.isFinite(hitDisplay) ? hitDisplay : 0;
  const hc=hitPct>=90?"var(--green)":hitPct>=75?"var(--amber)":"var(--red)";
  const lineDisp = (() => {
    const v = coercePropLine(p);
    return Number.isFinite(v) ? v : p.line ?? "—";
  })();
  const div=document.createElement("div");
  div.className=`edge-card insight-card ${dc}`;
  const hitBar=Math.min(100,hitPct);
  const hitColor=hitPct>=90?'var(--green)':hitPct>=75?'var(--amber)':'var(--red)';
  div.innerHTML=`
    <div class="edge-card-top">
      <div class="edge-row edge-row-top">
        <div class="edge-avatar ${dc}">${p.initials || (p.player||"").split(" ").filter(w=>w).map(w=>w[0]).join("").slice(0,2).toUpperCase()}</div>
        <div class="edge-val">
          <div class="edge-num edge-badge ${dc}">${edgeDisp}</div>
          <div class="edge-mini">${hitPct}% · L${lineDisp}</div>
        </div>
      </div>
      <div class="edge-row edge-row-main">
        <div class="edge-name-wrap"><div class="edge-name">${p.player}${l10StreakBadgeHtml(p)}</div>${consLineBadgeHtml(p)}</div>
        <div class="edge-prop">${p.dir} ${lineDisp} · ${p.prop}</div>
      </div>
      <div class="edge-row edge-row-tags">
        <div class="edge-tags">
          <span class="edge-sport ${sc}">${sportLabel}</span>
          <span class="edge-pick ${pc}">${p.pick}</span>
          ${p.tier ? `<span class="tier-badge tier-${p.tier}">${p.tier}</span>` : ''}${confDotHtml(p)}
        </div>
        <div class="edge-line-badge">${hitPct}% hit</div>
      </div>
    </div>
    <div style="padding:0 12px 10px;display:flex;align-items:center;gap:8px;">
      <div style="flex:1;height:3px;background:rgba(255,255,255,.07);border-radius:3px;overflow:hidden;">
        <div style="width:${hitBar}%;height:100%;background:${hitColor};border-radius:3px;transition:width .6s ease;"></div>
      </div>
      <span style="font-size:10px;font-weight:700;color:${hitColor};font-family:'Inter',sans-serif;min-width:32px;text-align:right;">${hitPct}%</span>
    </div>
    <div class="edge-expand" id="expand-${idx}">
      <div class="expand-tabs">
        <button class="expand-tab active" onclick="switchExpandTab(${idx},'l5',this)">L5</button>
        <button class="expand-tab" onclick="switchExpandTab(${idx},'l10',this)">L10</button>
        <button class="expand-tab" onclick="switchExpandTab(${idx},'h2h',this)">H2H</button>
      </div>
      <div class="expand-chart" id="chart-${idx}"></div>
      <div class="expand-proj">
        <div class="expand-proj-lbl"><span>PROJECTION VS LINE</span><span id="plbl-${idx}"></span></div>
        <div class="expand-proj-bar">
          <div class="expand-proj-fill" id="pfill-${idx}" style="width:0%"></div>
          <div class="expand-proj-marker" id="pmkr-${idx}"></div>
        </div>
      </div>
      <div class="expand-stats">
        <div class="expand-stat"><div class="expand-stat-lbl">HIT RATE</div><div class="expand-stat-val" style="color:${hitColor}">${hitPct}%</div></div>
        <div class="expand-stat"><div class="expand-stat-lbl">EDGE</div><div class="expand-stat-val" style="color:var(--accent)">${edgeDisp}</div></div>
        <div class="expand-stat"><div class="expand-stat-lbl">PICK TYPE</div><div class="expand-stat-val" style="color:var(--cyan);font-size:clamp(11px,1.3vw,15px);">${p.pick}</div></div>
      </div>
    </div>`;
  return div;
}

function renderExpandChart(idx, p, tab) {
  const chartEl = document.getElementById(`chart-${idx}`);
  const pfillEl = document.getElementById(`pfill-${idx}`);
  const pmkrEl = document.getElementById(`pmkr-${idx}`);
  const plblEl = document.getElementById(`plbl-${idx}`);
  if (!chartEl || !pfillEl || !pmkrEl || !plblEl) return;
  const isOver = p.dir === "OVER";
  const n = tab === "l5" || tab === "h2h" ? 5 : 10;
  const hist = expandHistForEdgeChart(p, n);
  if (!hist || !hist.actual.length) {
    chartEl.innerHTML =
      `<div style="height:100px;display:flex;align-items:center;justify-content:center;color:var(--muted2);font-size:11px;border:1px dashed rgba(255,255,255,.12);border-radius:10px;">No chart series for this leg.</div>`;
    pfillEl.style.width = "0%";
    pmkrEl.style.left = "0%";
    plblEl.textContent = "No data";
    return;
  }
  const show = hist.actual;
  const coercedBook = coercePropLine(p);
  const displayBook = Number.isFinite(coercedBook)
    ? coercedBook
    : Number.isFinite(Number(p?.line))
      ? Number(p.line)
      : NaN;
  const bookLineVals = Array.from({ length: show.length }, () =>
    Number.isFinite(displayBook)
      ? displayBook
      : show.reduce((a, b) => a + b, 0) / show.length,
  );
  const proj = projectedStatForPick(p);
  const scaleExtras = [];
  if (Number.isFinite(proj)) scaleExtras.push(proj);
  chartEl.innerHTML = makeSVG(
    show,
    displayBook,
    isOver,
    260,
    100,
    bookLineVals,
    scaleExtras,
  );
  const avg = show.reduce((a, b) => a + b, 0) / show.length;
  const refN = Number.isFinite(proj)
    ? proj
    : Number.isFinite(displayBook)
      ? displayBook
      : avg;
  const maxV = Math.max(
    refN * 1.5,
    (Number.isFinite(displayBook) ? displayBook : 0) * 1.5,
    avg * 1.3,
    1
  );
  pfillEl.style.width =
    Math.min(100, Math.round((avg / maxV) * 100)) + "%";
  pmkrEl.style.left =
    Math.min(100, Math.round((refN / maxV) * 100)) + "%";
  plblEl.textContent = `${avg.toFixed(1)} L5 · Line ${Number.isFinite(displayBook) ? displayBook.toFixed(1) : "—"} · Proj ${Number.isFinite(proj) ? proj.toFixed(1) : "—"}`;
}

function switchExpandTab(idx, tab, btn) {
  document.getElementById(`expand-${idx}`).querySelectorAll(".expand-tab").forEach(t=>t.classList.remove("active"));
  btn.classList.add("active");
  const p = EDGE_DISPLAY_PICK[idx] ?? ALL_SLATE[idx];
  renderExpandChart(idx, p, tab);
}

/** UNDER edge display: Standard picks only (Goblin/Demon have no under side here). Real UNDER legs as-is; OVER legs → synthetic under card. */
function underEdgeDisplayPick(basePick) {
  if (isGoblinPick(basePick) || isDemonPick(basePick)) return null;
  if (!isStandardPick(basePick)) return null;

  const dir = String(basePick.dir || "").trim().toUpperCase();
  if (dir === "UNDER") {
    const eu = Number(basePick.edge);
    if (!Number.isFinite(eu) || eu >= 0) return null; // native UNDER must have negative edge (real abs_edge > 0)
    return basePick;
  }
  if (dir !== "OVER") return null;

  const eo = Number(basePick.edge);
  // Tune UP for stricter parity with visible OVER cards (e.g. 0.5); 0.1 drops tiny projection noise (+0.06 synth).
  const UNDER_SYNTH_EDGE_MIN = 0.1;
  if (!Number.isFinite(eo) || Math.abs(eo) < UNDER_SYNTH_EDGE_MIN) return null;
  const edgeUnder = -eo;
  const disp = { ...basePick, dir: "UNDER", edge: edgeUnder };
  const emp5 = empiricalHitPctForPick(disp, 5);
  if (Number.isFinite(emp5)) {
    if (emp5 < 80) return null;
    return { ...disp, hit: emp5 };
  }
  const h5 = resolvedUnderHits(basePick, 5);
  if (h5 !== null) {
    if (h5 < 4) return null;
    return { ...disp, hit: Math.max(0, Math.min(100, Math.round((h5 / 5) * 100))) };
  }
  const h10 = resolvedUnderHits(basePick, 10);
  if (h10 !== null) {
    if (h10 < 8) return null;
    return { ...disp, hit: Math.max(0, Math.min(100, Math.round((h10 / 10) * 100))) };
  }
  return null;
}

function collectUnderEdgeRows() {
  const rows = [];
  for (let i = 0; i < ALL_SLATE.length; i++) {
    if (isFantasyScoreEdgePick(ALL_SLATE[i])) continue;
    const disp = underEdgeDisplayPick(ALL_SLATE[i]);
    if (!disp) continue;
    if (isFantasyScoreEdgePick(disp)) continue;
    rows.push({ baseIdx: i, disp });
  }
  return rows;
}

function pickPrimaryLineRows(rows) {
  const out = new Map();
  const lineKey = (p) => {
    const v = coercePropLine(p);
    return Number.isFinite(v) ? v.toFixed(3) : String(p?.line ?? "").trim();
  };
  const keyFor = (p) => [
    String(p.sport || "").trim().toUpperCase(),
    String(p.player || "").trim().toLowerCase(),
    String(p.prop || "").trim().toLowerCase(),
    String(p.pick || "").trim().toLowerCase(),
    String(p.dir || "").trim().toUpperCase(),
    lineKey(p),
  ].join("|");
  const lineNum = (p) => {
    const v = Number(p?.line);
    return Number.isFinite(v) ? v : NaN;
  };
  const edgeNum = (p) => {
    const v = Number(p?.edge);
    return Number.isFinite(v) ? v : -Infinity;
  };
  const isBetter = (cand, cur) => {
    // Canonical card row = strongest model edge for that card key.
    return edgeNum(cand) > edgeNum(cur);
  };

  for (const p of rows) {
    const k = keyFor(p);
    const cur = out.get(k);
    if (!cur || isBetter(p, cur)) out.set(k, p);
  }
  return Array.from(out.values());
}

function renderEdges() {
  const os=document.getElementById("over-edges-standard");
  const og=document.getElementById("over-edges-goblin");
  const us=document.getElementById("under-edges-standard");
  if (!os || !og) return;
  os.innerHTML=""; og.innerHTML="";
  if (us) us.innerHTML="";
  EDGE_DISPLAY_PICK = {};
  const num = (x) => {
    const v = Number(x);
    return Number.isFinite(v) ? v : 0;
  };
  const overRows = [];
  for (const p of ALL_SLATE) {
    const dir = String(p.dir || "").trim().toUpperCase();
    if (dir === "OVER" && !isFantasyScoreEdgePick(p)) overRows.push(p);
  }
  // Top Edges quality gate: prefer strong L5 (>=4/5). If nothing clears it,
  // fall back to best available slate rows so homepage still shows fetched props.
  const passesEdgeL5Gate = (p, dir) => {
    const pct = topEdgeL5HitPct(p, dir);
    return Number.isFinite(pct) && pct >= 80;
  };
  let overPrimary = pickPrimaryLineRows(overRows)
    .filter((p) => passesEdgeL5Gate(p, "OVER"))
    .filter((p) => passesTopEdgeEmpiricalSanity(p, "OVER"));
  if (!overPrimary.length) {
    overPrimary = pickPrimaryLineRows(overRows)
      .slice()
      .sort((a, b) => {
        const ha = topEdgeL5HitPct(a, "OVER") || 0;
        const hb = topEdgeL5HitPct(b, "OVER") || 0;
        if (hb !== ha) return hb - ha;
        return num(b.edge) - num(a.edge);
      });
  }
  const stdO = overPrimary.filter((p) => !isGoblinPick(p));
  const gobO = overPrimary.filter((p) => isGoblinPick(p));
  // Prefer stronger L5 among similar edges so Best-to-Run 5/5s stay visible.
  const byEdgeThenL5 = (a, b) => {
    const ed = num(b.edge) - num(a.edge);
    if (Math.abs(ed) > 0.05) return ed;
    return (topEdgeL5HitPct(b, "OVER") || 0) - (topEdgeL5HitPct(a, "OVER") || 0);
  };
  stdO.sort(byEdgeThenL5);
  gobO.sort(byEdgeThenL5);
  // Pin Best-to-Run Std/Gob OVER legs into Top Edges when they clear the L5 gate.
  const pinBtrIntoEdges = (bucket, gobOnly) => {
    const seen = new Set(bucket.map((p) => btrPropKey(p)));
    for (const p of ALL_SLATE) {
      if (!p || isFantasyScoreEdgePick(p) || isDemonPick(p)) continue;
      if (String(p.tier || "").trim().toUpperCase() === "D") continue;
      if (String(p.dir || "").trim().toUpperCase() !== "OVER") continue;
      if (!(num(p.edge) > 0) || !btrPassesL5Perfect(p)) continue;
      const gob = isGoblinPick(p);
      const std = isStandardPick(p);
      if (gobOnly ? !gob : !std) continue;
      if (!passesEdgeL5Gate(p, "OVER")) continue;
      if (!passesTopEdgeEmpiricalSanity(p, "OVER")) continue;
      const k = btrPropKey(p);
      if (seen.has(k)) continue;
      seen.add(k);
      bucket.push(p);
    }
    bucket.sort(byEdgeThenL5);
  };
  pinBtrIntoEdges(stdO, false);
  pinBtrIntoEdges(gobO, true);
  // Pin season consistency leaders onto Top Edges even when their raw edge
  // ranks below EDGE_CARD_LIMIT (otherwise GOB/STD badges never appear).
  const pinConsIntoOverBucket = (bucket, gobOnly) => {
    if (!window.__CONS_LEADERS?.ready) return;
    const seen = new Set(bucket.map((p) => btrPropKey(p)));
    for (const p of ALL_SLATE) {
      if (!p || isFantasyScoreEdgePick(p) || isDemonPick(p)) continue;
      if (String(p.dir || "").trim().toUpperCase() !== "OVER") continue;
      const gob = isGoblinPick(p);
      const std = isStandardPick(p);
      if (gobOnly ? !gob : !std) continue;
      if (!matchConsistencyLeader(p)) continue;
      const k = btrPropKey(p);
      if (seen.has(k)) continue;
      seen.add(k);
      bucket.push(p);
    }
  };
  pinConsIntoOverBucket(stdO, false);
  pinConsIntoOverBucket(gobO, true);

  const underSourceRows = collectUnderEdgeRows();
  const underByKey = new Map();
  for (const row of underSourceRows) {
    const d = row.disp || {};
    const k = [
      String(d.sport || "").trim().toUpperCase(),
      String(d.player || "").trim().toLowerCase(),
      String(d.prop || "").trim().toLowerCase(),
      String(d.pick || "").trim().toLowerCase(),
      String(d.dir || "").trim().toUpperCase(),
    ].join("|");
    if (!underByKey.has(k)) underByKey.set(k, row);
  }
  let underRows = pickPrimaryLineRows(underSourceRows.map((x) => x.disp))
    .filter((disp) => passesEdgeL5Gate(disp, "UNDER"))
    .filter((disp) => passesTopEdgeEmpiricalSanity(disp, "UNDER"))
    .map((disp) => {
      const k = [
        String(disp.sport || "").trim().toUpperCase(),
        String(disp.player || "").trim().toLowerCase(),
        String(disp.prop || "").trim().toLowerCase(),
        String(disp.pick || "").trim().toLowerCase(),
        String(disp.dir || "").trim().toUpperCase(),
      ].join("|");
      return underByKey.get(k) || { baseIdx: 0, disp };
    })
    .sort((a, b) => num(b.disp.edge) - num(a.disp.edge));
  if (!underRows.length) {
    underRows = pickPrimaryLineRows(underSourceRows.map((x) => x.disp))
      .map((disp) => {
        const k = [
          String(disp.sport || "").trim().toUpperCase(),
          String(disp.player || "").trim().toLowerCase(),
          String(disp.prop || "").trim().toLowerCase(),
          String(disp.pick || "").trim().toLowerCase(),
          String(disp.dir || "").trim().toUpperCase(),
        ].join("|");
        return underByKey.get(k) || { baseIdx: 0, disp };
      })
      .sort((a, b) => {
        const ha = topEdgeL5HitPct(a.disp, "UNDER") || 0;
        const hb = topEdgeL5HitPct(b.disp, "UNDER") || 0;
        if (hb !== ha) return hb - ha;
        return num(b.disp.edge) - num(a.disp.edge);
      });
  }
  const EDGE_CARD_LIMIT = 10;

  // Also pin consistency UNDER leaders that missed the high-abs-edge cut.
  if (window.__CONS_LEADERS?.ready) {
    const seenU = new Set(
      underRows.map(({ disp }) =>
        [
          String(disp?.sport || "").trim().toUpperCase(),
          String(disp?.player || "").trim().toLowerCase(),
          String(disp?.prop || "").trim().toLowerCase(),
          String(disp?.pick || "").trim().toLowerCase(),
          String(disp?.dir || "").trim().toUpperCase(),
        ].join("|")
      )
    );
    for (let i = 0; i < ALL_SLATE.length; i++) {
      const p = ALL_SLATE[i];
      if (!p || isFantasyScoreEdgePick(p) || isDemonPick(p)) continue;
      if (String(p.dir || "").trim().toUpperCase() !== "UNDER") continue;
      if (!isStandardPick(p) && !isGoblinPick(p)) continue;
      if (!matchConsistencyLeader(p)) continue;
      const k = [
        String(p.sport || "").trim().toUpperCase(),
        String(p.player || "").trim().toLowerCase(),
        String(p.prop || "").trim().toLowerCase(),
        String(p.pick || "").trim().toLowerCase(),
        String(p.dir || "").trim().toUpperCase(),
      ].join("|");
      if (seenU.has(k)) continue;
      seenU.add(k);
      underRows.push({ baseIdx: i, disp: p });
    }
  }

  const appendAll = (arr, el) => {
    for (const p of prioritizeConsLeaderRows(arr).slice(0, EDGE_CARD_LIMIT)) {
      const idx = Math.max(0, ALL_SLATE.indexOf(p));
      el.appendChild(buildEdgeCard(p, idx));
      queueMicrotask(() =>
        renderExpandChart(idx, EDGE_DISPLAY_PICK[idx] ?? p, "l5")
      );
    }
  };
  const appendUnderRows = (rows, el) => {
    const ranked = prioritizeConsLeaderRows(
      rows.map((r) => r.disp),
      (disp) =>
        [
          String(disp?.sport || "").trim().toUpperCase(),
          String(disp?.player || "").trim().toLowerCase(),
          String(disp?.prop || "").trim().toLowerCase(),
          String(disp?.pick || "").trim().toLowerCase(),
          String(disp?.dir || "").trim().toUpperCase(),
        ].join("|")
    );
    const byDispKey = new Map(
      rows.map((r) => [
        [
          String(r.disp?.sport || "").trim().toUpperCase(),
          String(r.disp?.player || "").trim().toLowerCase(),
          String(r.disp?.prop || "").trim().toLowerCase(),
          String(r.disp?.pick || "").trim().toLowerCase(),
          String(r.disp?.dir || "").trim().toUpperCase(),
        ].join("|"),
        r,
      ])
    );
    for (const disp of ranked.slice(0, EDGE_CARD_LIMIT)) {
      const k = [
        String(disp?.sport || "").trim().toUpperCase(),
        String(disp?.player || "").trim().toLowerCase(),
        String(disp?.prop || "").trim().toLowerCase(),
        String(disp?.pick || "").trim().toLowerCase(),
        String(disp?.dir || "").trim().toUpperCase(),
      ].join("|");
      const row = byDispKey.get(k) || { baseIdx: Math.max(0, ALL_SLATE.indexOf(disp)), disp };
      const { baseIdx } = row;
      if (disp !== ALL_SLATE[baseIdx]) EDGE_DISPLAY_PICK[baseIdx] = disp;
      el.appendChild(buildEdgeCard(disp, baseIdx));
      queueMicrotask(() =>
        renderExpandChart(
          baseIdx,
          EDGE_DISPLAY_PICK[baseIdx] ?? ALL_SLATE[baseIdx],
          "l5"
        )
      );
    }
  };
  appendAll(stdO, os);
  appendAll(gobO, og);
  if (us) appendUnderRows(underRows, us);
  wireEdgeCardExpandHandlers();
  /* Hide empty bucket chrome so Top Edges doesn't look blank under full grids. */
  const toggleBucket = (gridEl, hasCards) => {
    if (!gridEl) return;
    gridEl.hidden = !hasCards;
    let label = gridEl.previousElementSibling;
    while (label && label.classList && !label.classList.contains("edge-bucket-label") && !label.classList.contains("sub-header")) {
      label = label.previousElementSibling;
    }
    if (label && label.classList.contains("edge-bucket-label")) label.hidden = !hasCards;
  };
  toggleBucket(os, stdO.length > 0);
  toggleBucket(og, gobO.length > 0);
  if (us) {
    toggleBucket(us, underRows.length > 0);
    const underHeader = us.parentElement && [...us.parentElement.querySelectorAll(".sub-header")].find((h) => /UNDER/i.test(h.textContent || ""));
    if (underHeader) underHeader.hidden = underRows.length === 0;
  }
  const emptyHost = document.getElementById("top-edges-empty");
  const anyCards = (stdO.length + gobO.length + underRows.length) > 0;
  if (!anyCards) {
    let el = emptyHost;
    if (!el) {
      const body = document.querySelector("#top-edges .home-cat-body .home-cat-flat") ||
        document.querySelector("#top-edges .home-cat-body");
      if (body) {
        el = document.createElement("div");
        el.id = "top-edges-empty";
        el.className = "home-cat-empty-state";
        body.appendChild(el);
      }
    }
    if (el) {
      el.hidden = false;
      el.innerHTML = '<div class="hec-title">No Top Edges yet</div>' +
        (ALL_SLATE.length
          ? '<div>No legs cleared the L5 quality gate on this slate</div>'
          : '<div>Waiting for pipeline props — open Prop Explorer or check back after the daily run</div>');
    }
  } else if (emptyHost) {
    emptyHost.hidden = true;
    emptyHost.innerHTML = "";
  }
}

/** Best to Run — stricter daily board (L5 5/5, edge>0; Standards also L10≥80%). */
function isStandardPick(p) {
  const t = String(p?.pick ?? p?.pick_type ?? "").trim().toLowerCase();
  return t === "standard" || t === "std";
}

function isDemonPick(p) {
  const t = String(p?.pick ?? p?.pick_type ?? "").trim().toLowerCase();
  return t === "demon";
}

function btrBetSideHits(p, n) {
  const d = String(p?.dir || "").trim().toUpperCase();
  if (d === "UNDER") return resolvedUnderHits(p, n);
  if (d === "OVER") return resolvedOverHits(p, n);
  return null;
}

function btrPassesL5Perfect(p) {
  const hits = btrBetSideHits(p, 5);
  if (hits != null && hits >= 5) return true;
  const sideHr = Number(p?.l5_side_hit_rate);
  if (Number.isFinite(sideHr) && sideHr >= 0.999) return true;
  const pct = topEdgeL5HitPct(p);
  return Number.isFinite(pct) && pct >= 100;
}

function btrL10Rate(p) {
  const hits = btrBetSideHits(p, 10);
  if (hits == null) return 0;
  return hits / 10;
}

function btrPropKey(p) {
  return [
    String(p?.sport || "").trim().toUpperCase(),
    String(p?.player || "").trim().toLowerCase(),
    String(p?.prop || "").trim().toLowerCase(),
    String(p?.dir || "").trim().toUpperCase(),
    String(p?.line ?? ""),
  ].join("|");
}

function btrPlayerPropKey(p) {
  return [
    String(p?.sport || "").trim().toUpperCase(),
    String(p?.player || "").trim().toLowerCase(),
    String(p?.prop || "").trim().toLowerCase(),
  ].join("|");
}

function btrFormatLeg(p) {
  const side = String(p.dir || "").toUpperCase() === "UNDER" ? "U" : "O";
  const line = (() => {
    const v = coercePropLine(p);
    return Number.isFinite(v) ? v : (p.line ?? "");
  })();
  const sport = sportDisplayLabel(p.sport) || String(p.sport || "").toUpperCase();
  return `${p.player} ${side}${line} ${p.prop} (${sport})`;
}

function renderBestToRun() {
  const stdEl = document.getElementById("btr-standards");
  const gobHost = document.getElementById("btr-goblins-host");
  const mixEl = document.getElementById("btr-mix");
  const emptyEl = document.getElementById("btr-empty");
  if (!stdEl || !gobHost) return;

  stdEl.innerHTML = "";
  gobHost.innerHTML = "";
  if (mixEl) {
    mixEl.hidden = true;
    mixEl.innerHTML = "";
  }
  if (emptyEl) emptyEl.hidden = true;

  const num = (x) => {
    const v = Number(x);
    return Number.isFinite(v) ? v : 0;
  };
  const tier = (p) => String(p?.tier || "").trim().toUpperCase();

  const candidates = [];
  for (const p of ALL_SLATE) {
    if (!p || isDemonPick(p) || isFantasyScoreEdgePick(p)) continue;
    if (tier(p) === "D") continue;
    const dir = String(p.dir || "").trim().toUpperCase();
    if (dir !== "OVER" && dir !== "UNDER") continue;
    const edge = num(p.edge);
    if (!(edge > 0)) continue;
    if (!btrPassesL5Perfect(p)) continue;
    const gob = isGoblinPick(p);
    const std = isStandardPick(p);
    if (!gob && !std) continue;
    if (gob && dir !== "OVER") continue;
    candidates.push(p);
  }

  const seen = new Set();
  const uniq = [];
  for (const p of candidates) {
    const k = btrPropKey(p);
    if (seen.has(k)) continue;
    seen.add(k);
    uniq.push(p);
  }

  let eliteStd = uniq
    .filter((p) => isStandardPick(p) && btrL10Rate(p) >= 0.8)
    .sort((a, b) => {
      const ed = num(b.edge) - num(a.edge);
      if (ed) return ed;
      const l10 = btrL10Rate(b) - btrL10Rate(a);
      if (l10) return l10;
      return num(b.hit) - num(a.hit);
    });
  eliteStd = prioritizeConsLeaderRows(pickPrimaryLineRows(eliteStd)).slice(0, 6);

  const goblins = uniq
    .filter((p) => isGoblinPick(p))
    .sort((a, b) => num(b.edge) - num(a.edge));
  const bySport = new Map();
  for (const p of goblins) {
    const sk = String(p.sport || "").trim().toUpperCase() || "OTHER";
    if (!bySport.has(sk)) bySport.set(sk, []);
    bySport.get(sk).push(p);
  }
  // Prefer WNBA / MLB first in display order when present
  const sportOrder = ["WNBA", "MLB", "SOCCER", "TENNIS", "NBA", "NHL", "NFL"];
  const sportKeys = [
    ...sportOrder.filter((s) => bySport.has(s)),
    ...[...bySport.keys()].filter((s) => !sportOrder.includes(s)).sort(),
  ];

  const appendCards = (arr, el) => {
    for (const p of arr) {
      const idx = Math.max(0, ALL_SLATE.indexOf(p));
      el.appendChild(buildEdgeCard(p, idx));
      queueMicrotask(() => renderExpandChart(idx, EDGE_DISPLAY_PICK[idx] ?? p, "l5"));
    }
  };

  appendCards(eliteStd, stdEl);
  const stdLabel = stdEl.previousElementSibling;
  if (stdLabel && stdLabel.classList.contains("edge-bucket-label")) {
    stdLabel.hidden = eliteStd.length === 0;
  }
  const stdHeader = stdLabel && stdLabel.previousElementSibling;
  if (stdHeader && stdHeader.classList && stdHeader.classList.contains("sub-header")) {
    stdHeader.hidden = eliteStd.length === 0;
  }
  stdEl.hidden = eliteStd.length === 0;

  let gobCount = 0;
  for (const sk of sportKeys) {
    // Keep GOB consistency matches visible even when lower-edge than the top 6.
    const rows = prioritizeConsLeaderRows(pickPrimaryLineRows(bySport.get(sk) || [])).slice(0, 8);
    if (!rows.length) continue;
    gobCount += rows.length;
    const label = document.createElement("div");
    label.className = "edge-bucket-label";
    label.style.color = "var(--purple)";
    label.textContent = `${sportDisplayLabel(sk) || sk} · L5 5/5 OVER`;
    const grid = document.createElement("div");
    grid.className = "edge-grid";
    grid.dataset.btrSport = sk.toLowerCase();
    grid.style.marginBottom = "18px";
    gobHost.appendChild(label);
    gobHost.appendChild(grid);
    appendCards(rows, grid);
  }
  const gobHeader = gobHost.previousElementSibling;
  if (gobHeader && gobHeader.classList && gobHeader.classList.contains("sub-header")) {
    gobHeader.hidden = gobCount === 0;
  }

  // Suggested 6-leg: 3 Standards + 3 Goblins (cross-sport when possible)
  const mixStd = [];
  const seenPp = new Set();
  for (const p of eliteStd) {
    const k = btrPlayerPropKey(p);
    if (seenPp.has(k)) continue;
    seenPp.add(k);
    mixStd.push(p);
    if (mixStd.length >= 3) break;
  }
  const mixGob = [];
  const preferSports = sportKeys.length ? sportKeys : ["WNBA", "MLB"];
  for (const sk of preferSports) {
    for (const p of bySport.get(sk) || []) {
      const k = btrPlayerPropKey(p);
      if (seenPp.has(k)) continue;
      seenPp.add(k);
      mixGob.push(p);
      break;
    }
    if (mixGob.length >= 3) break;
  }
  if (mixGob.length < 3) {
    for (const sk of sportKeys) {
      for (const p of bySport.get(sk) || []) {
        const k = btrPlayerPropKey(p);
        if (seenPp.has(k)) continue;
        seenPp.add(k);
        mixGob.push(p);
        if (mixGob.length >= 3) break;
      }
      if (mixGob.length >= 3) break;
    }
  }
  const mixLegs = [...mixStd, ...mixGob].slice(0, 6);
  if (mixEl && mixLegs.length >= 2) {
    mixEl.hidden = false;
    mixEl.innerHTML =
      "<strong>Suggested mix</strong>" +
      `<div class="btr-mix-legs">${mixLegs.map(btrFormatLeg).join(" · ")}</div>`;
  }

  const any = eliteStd.length + gobCount > 0;
  if (emptyEl) emptyEl.hidden = any;
  const cat = document.getElementById("best-to-run-cat");
  if (cat && any) cat.setAttribute("open", "");
  const btrVal = document.getElementById("sc-best-to-run-val");
  const btrBadge = document.getElementById("sc-best-to-run-badge");
  if (btrVal) {
    btrVal.textContent = any
      ? `${eliteStd.length} Std · ${gobCount} Gob`
      : "Waiting for slate…";
  }
  if (btrBadge) {
    btrBadge.textContent = any ? "LIVE" : "…";
    btrBadge.className = any ? "sbadge fresh" : "sbadge loading";
  }
  wireBestToRunExpandHandlers();
}

/** Sport-row tab: jump to Best to Run and ensure cards are warmed on mobile. */
async function jumpToBestToRun() {
  const cat = document.getElementById("best-to-run-cat");
  if (!cat) return;
  cat.setAttribute("open", "");
  try {
    document.querySelectorAll("#slate-panel-header-row .scard.active").forEach((el) => {
      el.classList.remove("active");
    });
    document.querySelectorAll(".slate-expand.open, .slate-expand.active").forEach((el) => {
      el.classList.remove("open", "active");
    });
    document.getElementById("sc-best-to-run")?.classList.add("active");
  } catch (e) {}
  if (!ALL_SLATE.length) {
    try {
      await loadHomeCardsFromFullSlate();
    } catch (e) {
      console.warn("jumpToBestToRun warm:", e);
    }
  }
  renderBestToRun();
  cat.scrollIntoView({ behavior: "smooth", block: "start" });
}

function wireBestToRunExpandHandlers() {
  const ids = ["btr-standards"];
  document.querySelectorAll("#btr-goblins-host .edge-grid").forEach((el, i) => {
    if (!el.id) el.id = `btr-goblin-grid-${i}`;
    ids.push(el.id);
  });
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.expandWired === "1") return;
    el.dataset.expandWired = "1";
    el.addEventListener("click", (e) => {
      if (e.target.closest(".expand-tab")) return;
      const card = e.target.closest(".edge-card");
      if (!card) return;
      const wasOpen = card.classList.contains("expanded");
      el.querySelectorAll(".edge-card.expanded").forEach((c) => c.classList.remove("expanded"));
      if (!wasOpen) card.classList.add("expanded");
    });
  });
}

function wireEdgeCardExpandHandlers() {
  ["over-edges-standard", "over-edges-goblin", "under-edges-standard"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.expandWired === "1") return;
    el.dataset.expandWired = "1";
    el.addEventListener("click", (e) => {
      if (e.target.closest(".expand-tab")) return;
      const card = e.target.closest(".edge-card");
      if (!card) return;
      const wasOpen = card.classList.contains("expanded");
      el.querySelectorAll(".edge-card.expanded").forEach((c) => c.classList.remove("expanded"));
      if (!wasOpen) card.classList.add("expanded");
    });
  });
}

function formatOppDef(p) {
  if (!p) return "—";
  // Prefer prop-category defense when present (Matchup Edge / ticket overlay).
  const statTier = p.stat_def_tier != null && String(p.stat_def_tier).trim() !== ""
    ? String(p.stat_def_tier).trim()
    : "";
  const statRankRaw = p.stat_def_rank;
  const statRankNum = statRankRaw != null && statRankRaw !== "" ? Number(statRankRaw) : NaN;
  if (statTier || Number.isFinite(statRankNum)) {
    const tier = formatStatDefTier(statTier);
    const rank = Number.isFinite(statRankNum) ? `#${Math.round(statRankNum)}` : "";
    if (tier && rank) return `${tier} · ${rank}`;
    if (tier) return tier;
    if (rank) return rank;
  }
  const tier = p.def_tier != null && String(p.def_tier).trim() !== "" ? String(p.def_tier).trim() : "";
  const rankRaw = p.opponent_def_rank;
  const rankNum = rankRaw != null && rankRaw !== "" ? Number(rankRaw) : NaN;
  const rank = Number.isFinite(rankNum) ? `#${Math.round(rankNum)}` : "";
  if (tier && rank) return `${tier} · ${rank}`;
  if (tier) return tier;
  if (rank) return rank;
  return "—";
}

function formatCategoryRank(p) {
  if (!p) return "—";
  if (p.category_rank_label) return String(p.category_rank_label);
  const parts = [];
  if (p.league_rank != null && p.league_rank !== "") parts.push(`L#${p.league_rank}`);
  if (p.rank_on_team != null && p.rank_on_team !== "") parts.push(`T${p.rank_on_team}`);
  return parts.length ? parts.join(" · ") : "—";
}

function formatStatDefTier(tier) {
  const t = String(tier || "").trim().toUpperCase().replace(/\s+/g, "_");
  if (t === "HARD" || t === "HARD_MID") return t === "HARD" ? "Elite" : "Above Avg";
  if (t === "EASY" || t === "EASY_MID") return t === "EASY" ? "Weak" : "Below Avg";
  if (t === "MID") return "Avg";
  return String(tier || "").trim();
}

function formatMatchupSignal(p) {
  if (!p || p.def_matchup_signal == null || p.def_matchup_signal === "") return "—";
  const n = Number(p.def_matchup_signal);
  if (!Number.isFinite(n)) return "—";
  return (n >= 0 ? "+" : "") + n.toFixed(1);
}

async function ensurePropHistory(p) {
  if (!p) return p;
  const hasSeries = Array.isArray(p.actual_series) && p.actual_series.length > 0;
  const hasG = p.g1 != null || p.stat_g1 != null;
  if (hasSeries || hasG) return p;
  const sport = String(p.sport || "").trim().toLowerCase();
  const player = String(p.player || "").trim();
  const prop = String(p.prop || "").trim();
  const line = p.line != null ? String(p.line) : "";
  if (!player || !prop) return p;
  const qs = new URLSearchParams({ sport, player, prop, line });
  try {
    let res = await fetch(`/api/slate-history?${qs}`, slateFetchOpts(20000));
    if (!res.ok) {
      // Offline / older bundle: no history endpoint — keep synthetic charts.
      return p;
    }
    const d = await res.json();
    const hist = d && d.history && typeof d.history === "object" ? d.history : null;
    if (!hist) return p;
    Object.assign(p, hist);
  } catch (e) {
    console.warn("ensurePropHistory:", e);
  }
  return p;
}

async function openPropDetailPanel(p) {
  if (!p) return;
  const overlay = document.getElementById("prop-detail-overlay");
  if (!overlay) return;
  const title = document.getElementById("prop-detail-title");
  const sub = document.getElementById("prop-detail-sub");
  const chart = document.getElementById("prop-detail-chart");
  const meta = document.getElementById("prop-detail-meta");
  if (title) title.textContent = p.player || "—";
  const lineDisp = coercePropLine(p);
  const sportLabel = sportDisplayLabel(p.sport);
  if (sub) {
    let board = p.pick || p.pick_type || "Standard";
    if (p.pick_reclassified) board = `${board} (was ${p.pick_type_raw || "Goblin"})`;
    sub.textContent = `${sportLabel} · ${p.dir || ""} ${lineDisp != null ? lineDisp : p.line ?? "—"} · ${p.prop || ""} · ${board}`;
  }
  // Paint shell immediately; hydrate series for chart when list payload omitted history.
  if (meta) {
    const pct = (v) => (v != null && v !== "" ? String(v) : "—");
    const edgeStr = p.edge != null ? ((p.edge >= 0 ? "+" : "") + Number(p.edge).toFixed(2)) : "—";
    const mlStr = p.ml_prob != null ? (Number(p.ml_prob) * 100).toFixed(1) + "%" : "—";
    const rows = [
      ["TEAM", pct(p.team)], ["OPP", pct(p.opp)], ["TIER", pct(p.tier)],
      ["RANK", pct(p.rank_score)], ["CAT RANK", formatCategoryRank(p)], ["OPP DEF", formatOppDef(p)], ["MATCHUP", formatMatchupSignal(p)],
      ["ML PROB", mlStr], ["EDGE", edgeStr], ["BOOK LINE", pct(p.book_line ?? p.prop_line ?? p.line)],
      ["STD LINE", pct(p.standard_line)], ["SEASON AVG", pct(p.season_avg)], ["PROJECTION", pct(p.projection)],
      ["GAME TIME", formatGameTimeDisplay(p.game_time)],
    ];
    meta.innerHTML = rows.map(([lbl, val]) =>
      `<div class="expand-stat"><div class="expand-stat-lbl">${lbl}</div><div class="expand-stat-val">${val}</div></div>`
    ).join("");
  }
  if (chart) {
    chart.innerHTML = '<div style="padding:18px;text-align:center;color:var(--muted2);font-size:12px;">Loading game log…</div>';
  }
  overlay.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  await ensurePropHistory(p);
  if (chart) {
    const hist = expandHistForEdgeChart(p, 5);
    let chartHtml = "";
    if (hist && hist.actual.length) {
      const isOver = String(p.dir || "").toUpperCase() === "OVER";
      const book = Number.isFinite(coercePropLine(p)) ? coercePropLine(p) : Number(p.line);
      chartHtml = makeSVG(hist.actual, book, isOver, 280, 110, null, [projectedStatForPick(p)]);
    } else {
      chartHtml = '<div style="padding:24px;text-align:center;color:var(--muted2);font-size:12px;">No game log series for this prop.</div>';
    }
    chart.innerHTML = chartHtml + l10BarHtml(p);
  }
}

function closePropDetailPanel() {
  const overlay = document.getElementById("prop-detail-overlay");
  if (!overlay) return;
  overlay.classList.add("hidden");
  document.body.style.overflow = "";
}
window.openPropDetailPanel = openPropDetailPanel;
window.closePropDetailPanel = closePropDetailPanel;

function openPropDetailByKey(encodedKey) {
  const key = decodeURIComponent(String(encodedKey || ""));
  const pick = ALL_SLATE.find(
    (x) => playerSeriesKey(x.player, x.line, x.prop, x.sport) === key
  );
  if (pick) openPropDetailPanel(pick);
}
window.openPropDetailByKey = openPropDetailByKey;

function wireStreakGridClicks(rootId) {
  const root = document.getElementById(rootId);
  if (!root || root.dataset.pickWired === "1") return;
  root.dataset.pickWired = "1";
  root.addEventListener("click", (e) => {
    const card = e.target.closest(".streak-card[data-pick-key]");
    if (!card) return;
    openPropDetailByKey(card.dataset.pickKey);
  });
}

// ── Streak card (shared for L5 and L10) ───────────────────
function streakCard(p, n) {
  const isOver=p.dir==="OVER";
  const hits = (p.h !== undefined && p.h !== null) ? Math.min(n, Math.max(0, Math.round(p.h))) : n;
  const pct=Math.round((hits/n)*100);
  const data = streakSparkData(p, n, isOver, hits);
  const bookSpark = coercePropLine(p);
  const spark=makeSparkSVG(data, Number.isFinite(bookSpark) ? bookSpark : Number(p.line), isOver,150,48);
  const sc=`sp-${safeSportKey(p)}`, pc=p.pick==="Goblin"?"pick-goblin":"pick-standard";
  const sportLabel = sportDisplayLabel(p.sport);
  const lineDisp = Number.isFinite(bookSpark) ? bookSpark : p.line ?? "—";
  const hc=isOver?"var(--green)":"var(--amber)";
  const bc=isOver?"rgba(125,255,203,.3)":"rgba(255,192,107,.3)";
  const pctCol=pct===100?"var(--green)":pct>=80?"var(--amber)":"var(--red)";
  // fire/ice emoji based on streak quality
  const badge=hits===n?(isOver?"🔥 PERFECT":"❄️ PERFECT"):hits>=(n*0.8)?(isOver?"🔥 HOT":"❄️ COLD"):"";
  return `
  <div class="streak-card" data-pick-key="${encodeURIComponent(playerSeriesKey(p.player, p.line, p.prop, p.sport))}" style="border-color:${bc};" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 24px rgba(0,0,0,.35)'" onmouseout="this.style.transform='';this.style.boxShadow=''">
    <div style="position:absolute;left:0;top:0;bottom:0;width:3px;background:${hc};border-radius:3px 0 0 3px;"></div>
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:10px;">
      <div style="min-width:0;flex:1;">
        <div style="font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px;">${p.player}</div>
        <div style="font-size:10px;color:var(--muted);">${p.dir} ${lineDisp} · ${p.prop}</div>
        <div style="margin-top:5px;display:flex;gap:5px;flex-wrap:wrap;align-items:center;">
          <span class="edge-sport ${sc}">${sportLabel}</span>
          <span class="edge-pick ${pc}">${p.pick}</span>
          ${badge?`<span style="font-size:9px;color:${hc};letter-spacing:.5px;">${badge}</span>`:''}
        </div>
      </div>
      <div style="text-align:right;flex-shrink:0;">
        <div style="font-family:'Bebas Neue',sans-serif;font-size:32px;color:${hc};line-height:1;">${hits}/${n}</div>
        <div style="font-size:9px;color:var(--muted);letter-spacing:1px;margin-top:1px;">L${n} ${p.dir}</div>
        <div style="font-size:10px;color:var(--accent);margin-top:2px;">${fmtEdgePick(p)} edge</div>
      </div>
    </div>
    <div style="margin:8px 0 10px;">${spark}</div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
      <span style="font-size:9px;color:var(--muted);letter-spacing:1px;">HIT RATE L${n}</span>
      <span style="font-family:'Bebas Neue',sans-serif;font-size:16px;color:${pctCol};">${pct}%</span>
    </div>
    <div style="height:4px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden;">
      <div style="width:${pct}%;height:100%;background:${hc};border-radius:3px;"></div>
    </div>
  </div>`;
}

function renderStreaks() {
  // Cap keeps the homepage readable; pin + edge sort keeps Best-to-Run L5s visible.
  const STREAK_CARD_LIMIT = 18;
  const edgeNum = (p) => {
    const v = Number(p?.edge);
    return Number.isFinite(v) ? v : -Infinity;
  };
  const streakKey = (p) =>
    [
      String(p?.sport || "").trim().toUpperCase(),
      String(p?.player || "").trim().toLowerCase(),
      String(p?.prop || "").trim().toLowerCase(),
      String(p?.pick || p?.pick_type || "").trim().toLowerCase(),
      String(p?.dir || "").trim().toUpperCase(),
      String(coercePropLine(p) ?? p?.line ?? ""),
    ].join("|");

  /** Same hit resolution as Best to Run / Top Edges (not raw l5_over alone). */
  function sideHits(p, n, dirForce) {
    const dir = String(dirForce || p?.dir || "").trim().toUpperCase();
    if (dir === "UNDER") return resolvedUnderHits(p, n);
    if (dir === "OVER") return resolvedOverHits(p, n);
    return null;
  }

  function sortStreakRows(rows) {
    return rows.slice().sort((a, b) => {
      if (b.h !== a.h) return b.h - a.h;
      const ed = edgeNum(b) - edgeNum(a);
      if (ed) return ed;
      return String(a.player || "").localeCompare(String(b.player || ""));
    });
  }

  /** Prefer primary book lines so alt-lines don't crowd out elite L5s. */
  function dedupeStreakRows(rows) {
    return pickPrimaryLineRows(rows);
  }

  /**
   * Pin Best-to-Run-quality legs (L5 5/5 + edge>0 Std/Gob) into the streak list
   * so homepage sections stay consistent when hundreds of props share 5/5.
   */
  function pinBestToRunIntoStreaks(ranked, n, dir) {
    const wantDir = String(dir || "OVER").trim().toUpperCase();
    const pinned = [];
    for (const p of ALL_SLATE) {
      if (!p || isFantasyScoreEdgePick(p) || isDemonPick(p)) continue;
      if (String(p.tier || "").trim().toUpperCase() === "D") continue;
      const d = String(p.dir || "").trim().toUpperCase();
      if (d !== wantDir) continue;
      if (!(edgeNum(p) > 0)) continue;
      if (!btrPassesL5Perfect(p)) continue;
      const gob = isGoblinPick(p);
      const std = isStandardPick(p);
      if (!gob && !std) continue;
      if (gob && wantDir !== "OVER") continue;
      if (wantDir === "OVER" && n === 10 && btrL10Rate(p) < 0.8) continue;
      const h = sideHits(p, n, wantDir);
      if (h == null) continue;
      if (n === 5 && h < 4) continue;
      if (n === 10 && h < 8) continue;
      pinned.push({ ...p, dir: wantDir, h });
    }
    const byKey = new Map();
    for (const p of [...sortStreakRows(pinned), ...ranked]) {
      const k = streakKey(p);
      if (!byKey.has(k)) byKey.set(k, p);
    }
    return sortStreakRows([...byKey.values()]);
  }

  /** Under-side streaks: Standard legs only (no Goblin/Demon). */
  function underStreakRows(n, minHits) {
    const out = [];
    for (const p of ALL_SLATE) {
      if (!isStandardPick(p) || isGoblinPick(p) || isDemonPick(p)) continue;
      if (isFantasyScoreEdgePick(p)) continue;
      const h = resolvedUnderHits(p, n);
      if (h === null || h < 1) continue;
      if (minHits != null && h < minHits) continue;
      out.push({ ...p, dir: "UNDER", h });
    }
    return sortStreakRows(dedupeStreakRows(out));
  }

  function overStreakRows(n, minHits) {
    const out = [];
    for (const p of ALL_SLATE) {
      if (isFantasyScoreEdgePick(p)) continue;
      if (String(p.dir || "").trim().toUpperCase() !== "OVER") continue;
      const h = sideHits(p, n, "OVER");
      if (h === null || h < 1) continue;
      if (minHits != null && h < minHits) continue;
      out.push({ ...p, dir: "OVER", h });
    }
    return sortStreakRows(dedupeStreakRows(out));
  }

  let l5O = pinBestToRunIntoStreaks(overStreakRows(5, 4), 5, "OVER");
  let l5U = underStreakRows(5, 4);
  if (!l5O.length && !l5U.length) {
    l5O = pinBestToRunIntoStreaks(overStreakRows(5, 1), 5, "OVER");
    l5U = underStreakRows(5, 1);
  }

  let l10O = pinBestToRunIntoStreaks(overStreakRows(10, 8), 10, "OVER");
  let l10U = underStreakRows(10, 8);
  if (!l10O.length && !l10U.length) {
    l10O = pinBestToRunIntoStreaks(overStreakRows(10, 1), 10, "OVER");
    l10U = underStreakRows(10, 1);
  }

  const none = msg => `<div class="home-cat-empty-state" style="padding:14px 0;"><div class="hec-title" style="font-size:18px;margin-bottom:4px;">${msg}</div></div>`;

  document.getElementById("l5-over-grid").innerHTML   = l5O.length  ? l5O.slice(0, STREAK_CARD_LIMIT).map(p=>streakCard(p,5)).join("")   : none("No L5 over streaks");
  document.getElementById("l5-under-grid").innerHTML  = l5U.length  ? l5U.slice(0, STREAK_CARD_LIMIT).map(p=>streakCard(p,5)).join("")   : none("No L5 under streaks");
  document.getElementById("l10-over-grid").innerHTML  = l10O.length ? l10O.slice(0, STREAK_CARD_LIMIT).map(p=>streakCard(p,10)).join("") : none("No L10 over streaks");
  document.getElementById("l10-under-grid").innerHTML = l10U.length ? l10U.slice(0, STREAK_CARD_LIMIT).map(p=>streakCard(p,10)).join("") : none("No L10 under streaks");
  ["l5-over-grid", "l5-under-grid", "l10-over-grid", "l10-under-grid"].forEach(wireStreakGridClicks);
}

// ── Add streak-card CSS ───────────────────────────────────
document.head.insertAdjacentHTML("beforeend",`<style>
.streak-card{background:rgba(255,255,255,0.03);backdrop-filter:blur(18px) saturate(160%);-webkit-backdrop-filter:blur(18px) saturate(160%);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:14px 14px 14px 18px;position:relative;overflow:hidden;transition:transform .2s,box-shadow .2s;}
@keyframes slateSpin{to{transform:rotate(360deg);}}
</style>`);

// ── Slate Panel expand / sort / filter ───────────────────
const SLATE_DATA  = {};   // raw rows per sport
const SLATE_STATE = {};   // sort + filter state per sport
const RENDER_SCHEDULED = {};
const RENDER_TOKEN = {};
const MOBILE_TABLE_QUERY = window.matchMedia('(max-width: 900px)');
const L5_FILTER_MIN_HITS = 4;

const SPORTS = ['nba','nba1h','nba1q','cbb','cfb','nhl','soccer','mlb','nfl','tennis','wnba'];
SPORTS.forEach(s => {
  SLATE_STATE[s] = { sortKey: 'abs_edge', sortDir: -1, search: '', dir: null, pick: null, tier: null, l5: null, platform: null };
});
SLATE_STATE['combined'] = { sortKey: 'Rank Score', sortDir: -1, search: '', dir: null, pick: null, tier: null, l5: null, platform: null };

function _l5HitCount(val) {
  if (val == null) return null;
  if (typeof val === 'number' && Number.isFinite(val)) {
    return streakHits(val, 5);
  }
  const s = String(val).trim();
  if (!s) return null;
  const frac = s.match(/^(\d+(?:\.\d+)?)\s*\/\s*5$/);
  if (frac) {
    const n = Number(frac[1]);
    return Number.isFinite(n) ? Math.max(0, Math.min(5, Math.round(n))) : null;
  }
  const n = Number(s);
  if (!Number.isFinite(n)) return null;
  return streakHits(n, 5);
}

function _passesL5FilterForObjectRow(row, l5Mode) {
  if (!l5Mode) return true;
  const dir = String(row?.dir || row?.direction || '').trim().toUpperCase();
  const pick = String(row?.pick_type || row?.pick || '').trim().toLowerCase();
  // Goblin/Demon soft OVERs do not belong in L5 UNDER.
  if (l5Mode === 'UNDER' && (pick === 'goblin' || pick === 'demon')) return false;
  if (l5Mode === 'OVER') {
    if (dir !== 'OVER') return false;
    return (_l5HitCount(row?.l5_over) ?? -1) >= L5_FILTER_MIN_HITS;
  }
  if (l5Mode === 'UNDER') {
    if (dir !== 'UNDER') return false;
    return (_l5HitCount(row?.l5_under) ?? -1) >= L5_FILTER_MIN_HITS;
  }
  return true;
}

/** Magnitude of edge for default Slate Explorer sort (UNDER −2.6 ranks with OVER +2.6). */
function _slateAbsEdge(row) {
  const ae = row?.abs_edge;
  const n = ae != null ? Number(ae) : NaN;
  if (Number.isFinite(n)) return n;
  const e = row?.edge;
  const m = e != null ? Number(e) : NaN;
  if (Number.isFinite(m)) return Math.abs(m);
  return null;
}

function _rowPickPlatformNorm(row) {
  const raw = row && (row.pick_platform != null ? row.pick_platform : row.PickPlatform);
  let s = String(raw == null || raw === '' ? 'prizepicks' : raw).trim().toLowerCase().replace(/\s+/g, '');
  if (s === 'pp') s = 'prizepicks';
  if (s === 'ud') s = 'underdog';
  if (s === 'dk') s = 'draftkings';
  return s;
}

function _slateLineNum(v) {
  if (v == null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** True when the row carries an Underdog book line (matched or UD-only pick). */
function _rowHasUnderdogLine(row) {
  if (!row || typeof row !== 'object') return false;
  return _slateLineNum(row.line_underdog ?? row['Line (UD)']) != null;
}

/** PrizePicks = default PP rows; Underdog = UD-only rows OR any row with line_underdog set. */
function _rowMatchesPlatformFilter(row, platformKey) {
  const plat = _rowPickPlatformNorm(row);
  if (platformKey === 'prizepicks') {
    return plat !== 'underdog' && plat !== 'draftkings';
  }
  if (platformKey === 'underdog') {
    return plat === 'underdog' || _rowHasUnderdogLine(row);
  }
  return plat === platformKey;
}

function injectSlateL5Buttons() {
  document.querySelectorAll('.slate-toolbar').forEach((bar) => {
    const input = bar.querySelector('.slate-filter-input[id^="sf-"]');
    if (!input) return;
    const sport = String(input.id || '').replace(/^sf-/, '');
    if (!sport) return;
    if (bar.querySelector(`#sfb-${sport}-l5over`)) return;

    const overBtn = document.createElement('button');
    overBtn.className = 'slate-filter-btn';
    overBtn.id = `sfb-${sport}-l5over`;
    overBtn.type = 'button';
    overBtn.textContent = 'L5 OVER';
    overBtn.title = 'OVER picks with ≥4/5 L5 overs vs the line';
    overBtn.onclick = () => toggleL5Filter(sport, 'OVER', overBtn);

    const underBtn = document.createElement('button');
    underBtn.className = 'slate-filter-btn';
    underBtn.id = `sfb-${sport}-l5under`;
    underBtn.type = 'button';
    underBtn.textContent = 'L5 UNDER';
    underBtn.title = 'Standard UNDER picks with ≥4/5 L5 unders (no Goblin/Demon)';
    underBtn.onclick = () => toggleL5Filter(sport, 'UNDER', underBtn);

    const tierGroup = bar.querySelector('.slate-tier-group');
    if (tierGroup && tierGroup.parentNode === bar) {
      bar.insertBefore(overBtn, tierGroup);
      bar.insertBefore(underBtn, tierGroup);
    } else {
      bar.appendChild(overBtn);
      bar.appendChild(underBtn);
    }
  });
}

function injectSlatePlatformButtons() {
  document.querySelectorAll('.slate-toolbar').forEach((bar) => {
    const input = bar.querySelector('.slate-filter-input[id^="sf-"]');
    if (!input) return;
    const sport = String(input.id || '').replace(/^sf-/, '');
    if (!sport) return;
    if (bar.querySelector(`#sfb-${sport}-pp`)) return;

    const stdBtn = bar.querySelector(`#sfb-${sport}-standard`);
    const pp = document.createElement('button');
    pp.className = 'slate-filter-btn';
    pp.id = `sfb-${sport}-pp`;
    pp.type = 'button';
    pp.textContent = 'PrizePicks';
    pp.title = 'PrizePicks lines only';
    pp.onclick = () => togglePlatformFilter(sport, 'prizepicks', pp);

    const ud = document.createElement('button');
    ud.className = 'slate-filter-btn';
    ud.id = `sfb-${sport}-ud`;
    ud.type = 'button';
    ud.textContent = 'Underdog';
    ud.title = 'Underdog lines only';
    ud.onclick = () => togglePlatformFilter(sport, 'underdog', ud);

    if (stdBtn && stdBtn.parentNode === bar) {
      stdBtn.insertAdjacentElement('afterend', pp);
      pp.insertAdjacentElement('afterend', ud);
    } else {
      const tierGroup = bar.querySelector('.slate-tier-group');
      if (tierGroup && tierGroup.parentNode === bar) {
        bar.insertBefore(pp, tierGroup);
        bar.insertBefore(ud, tierGroup);
      } else {
        bar.appendChild(pp);
        bar.appendChild(ud);
      }
    }
  });
}

const SLATE_COLS = {};  // sport -> array of column names from Excel
let openSlatePanel = null;
let slateDataPromise = null;
let _slateExcelPromise = null; // lazy: only fetches /api/slate-excel when combined panel is first opened
const SLATE_SPORT_CACHE = {};           // sport -> true once fetched from /api/slate-sport/<sport>
const SLATE_SPORT_FETCH_PROMISES = {};  // sport -> in-flight promise

/** Capacitor / file:// bundle: no Flask — use JSON siblings from generate_mobile_bundle.py */
async function fetchBundledSlateSportPayload(sportRaw) {
  const key = String(sportRaw || "").trim().toLowerCase();
  if (!key || key === "combined") return null;
  try {
    const r = await fetch(`slate_sport_${key}.json`, slateFetchOpts(60000));
    if (r.ok) return await r.json();
  } catch (e) {}
  return null;
}
async function fetchBundledSlateSportCombinedPayload() {
  try {
    const r = await fetch("slate_sport_combined.json", slateFetchOpts(60000));
    if (r.ok) return await r.json();
  } catch (e) {}
  return null;
}

function scheduleRenderSlateTable(sport) {
  if (RENDER_SCHEDULED[sport]) return;
  RENDER_SCHEDULED[sport] = true;
  requestAnimationFrame(() => {
    RENDER_SCHEDULED[sport] = false;
    renderSlateTable(sport);
  });
}

function toggleSlatePanel(sport) {
  const panel = document.getElementById(`sp-${sport}`);
  const card  = document.getElementById(`sc-${sport}`);
  if (!panel) return;
  const isOpen = panel.classList.contains('open');

  // close any open panel
  if (openSlatePanel && openSlatePanel !== sport) {
    document.getElementById(`sp-${openSlatePanel}`)?.classList.remove('open');
    document.getElementById(`sc-${openSlatePanel}`)?.classList.remove('active');
  }

  if (isOpen) {
    panel.classList.remove('open');
    card.classList.remove('active');
    openSlatePanel = null;
  } else {
    panel.classList.add('open');
    card.classList.add('active');
    openSlatePanel = sport;
    if (!SLATE_DATA[sport]) loadSlateSport(sport);
    else scheduleRenderSlateTable(sport);
    if (typeof MatchupEdge !== 'undefined' && MatchupEdge.sports?.includes(sport)) {
      MatchupEdge.init(sport);
    }
  }
}

function showSlateSportLoading(sport, msg = 'Loading...') {
  const tbody = document.getElementById(`stb-${sport}`);
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="14" style="text-align:center;padding:20px;color:var(--muted2);font-size:11px;letter-spacing:.06em;">
    <span style="display:inline-flex;align-items:center;gap:8px;">
      <span style="width:12px;height:12px;border:2px solid rgba(255,255,255,.25);border-top-color:var(--accent);border-radius:50%;display:inline-block;animation:slateSpin .7s linear infinite;"></span>
      ${msg}
    </span>
  </td></tr>`;
}

// ── Populate SLATE_DATA — per-sport lazy endpoint, ticket fallback ────────────
/** Ticket legs use uppercase sport labels (e.g. NFL, NBA); Slate Explorer uses lowercase keys (nfl, nba). */
function _sportKeyNorm(sp) {
  const x = String(sp || '').trim().toLowerCase().replace(/\s+/g, '');
  if (x === 'nba1h' || x === 'nba_1h') return 'nba1h';
  if (x === 'nba1q' || x === 'nba_1q') return 'nba1q';
  return x;
}

/** Per-game history columns for slate table + detail modal charts. */
function _slateHistoryFieldsFromPick(p) {
  const out = {};
  if (!p || typeof p !== "object") return out;
  if (Array.isArray(p.actual_series) && p.actual_series.length) out.actual_series = p.actual_series;
  if (Array.isArray(p.line_series) && p.line_series.length) out.line_series = p.line_series;
  for (let gi = 1; gi <= 10; gi++) {
    const gk = `g${gi}`;
    const sk = `stat_g${gi}`;
    const lk = `line_g${gi}`;
    if (p[gk] != null && p[gk] !== "") out[gk] = p[gk];
    if (p[sk] != null && p[sk] !== "") out[sk] = p[sk];
    if (p[lk] != null && p[lk] !== "") out[lk] = p[lk];
  }
  return out;
}

function _fallbackSlateRowsFromTickets(sport) {
  return ALL_SLATE
    .filter(p => {
      const sp = _sportKeyNorm(p.sport);
      if (sport === 'cbb') return sp === 'cbb' || sp === 'wcbb';
      return sp === sport;
    })
    .map(p => ({
      tier:      p.tier ?? null,
      rank_score: p.rank_score != null ? p.rank_score : (p.edge != null ? Math.abs(p.edge) : null),
      player:    p.player || '',
      team:      p.team   || '',
      opp:       p.opp    || '',
      prop:      p.prop   || '',
      pick_type: p.pick   || '',
      pick_platform: p.pick_platform || 'prizepicks',
      line:      p.line,
      dir:       p.dir    || '',
      edge:      p.edge,
      hit_rate:  p.hit_rate != null ? p.hit_rate : (p.hit != null ? p.hit / 100 : null),
      l5_avg:    p.l5_avg,
      l5_over:   p.l5_over,
      l5_under:  p.l5_under,
      l5_games_played: p.l5_games_played,
      l10_over:  p.l10_over,
      l10_under: p.l10_under,
      l10_games_played: p.l10_games_played,
      season_avg: p.season_avg,
      projection: p.projection,
      game_time: p.game_time || '',
      sport:     p.sport || sport.toUpperCase(),
      ..._slateHistoryFieldsFromPick(p),
    }));
}

function _slateRowIsFantasyProp(row, sport) {
  if (!row) return false;
  if (typeof row === 'object' && !Array.isArray(row)) {
    return isFantasyScoreEdgePick({
      prop: row.prop,
      prop_type: row.prop_type || row.prop,
      market: row.market,
      stat: row.stat,
    });
  }
  if (Array.isArray(row)) {
    const cols = SLATE_COLS[sport] || SLATE_COLS.combined || [];
    const pi = cols.indexOf('Prop') >= 0 ? cols.indexOf('Prop') : cols.indexOf('Stat');
    if (pi >= 0) return isFantasyScoreEdgePick({ prop: row[pi] });
  }
  return false;
}

function _setSlateSportRows(sport, rows) {
  delete SLATE_COLS[sport];
  let raw = Array.isArray(rows) ? rows : [];
  if (sport === "tennis") {
    const md = tennisMatchDayEt();
    if (md) {
      const onDay = raw.filter((r) => {
        const gd = rowGameDateEt(r);
        return !gd || gd === md;
      });
      if (onDay.length) raw = onDay;
    }
  }
  SLATE_DATA[sport] = normalizeAltPickBoardRows(raw)
    .filter((r) => !_slateRowIsFantasyProp(r, sport))
    .filter((r) => {
      // Mirror server: Demon must be OVER with positive edge (drops hard mislabeled Goblins).
      const pt = String(r?.pick_type || r?.pick || "").trim().toLowerCase();
      if (pt !== "demon") return true;
      const dir = String(r?.dir || r?.direction || "").trim().toUpperCase();
      const edge = Number(r?.edge);
      return dir === "OVER" && Number.isFinite(edge) && edge > 0;
    });
  SLATE_DATA[sport].sort((a,b) => Math.abs(b?.edge||0) - Math.abs(a?.edge||0));
}

function _v(row, keys) {
  for (const k of keys) {
    if (row && row[k] !== undefined && row[k] !== null) return row[k];
  }
  return null;
}

function syncCardsFromCombinedRows(rows) {
  if (!Array.isArray(rows) || !rows.length) return false;
  const mapped = rows.map((r) => {
    const ex = extractPerGameSeriesFromObject(r, 10);
    let actual_series = _v(r, ["actual_series", "Actual Series"]);
    let line_series = _v(r, ["line_series", "Line Series"]);
    actual_series = Array.isArray(actual_series) ? actual_series : [];
    line_series = Array.isArray(line_series) ? line_series : [];
    if (!normalizeSeries(actual_series).length && ex.actualVals.length) {
      actual_series = ex.actualVals;
    }
    const lineNum = Number(_v(r, ["line", "Line"]));
    if (!normalizeSeries(line_series).length && ex.lineVals.some((v) => v != null && Number.isFinite(Number(v)))) {
      line_series = ex.lineVals.map((v) =>
        v != null && Number.isFinite(Number(v)) ? Number(v) : lineNum,
      );
    }
    return mapApiPickToSlateRow({
      sport: _v(r, ["sport", "Sport"]),
      initials: _v(r, ["initials", "Initials"]),
      player: _v(r, ["player", "Player"]),
      team: _v(r, ["team", "Team"]),
      opp: _v(r, ["opp", "Opp", "opp_team"]),
      prop: _v(r, ["prop", "Prop"]),
      line: lineNum,
      pick: _v(r, ["pick_type", "pick", "Pick Type", "Pick"]),
      pick_platform: _v(r, ["pick_platform", "Platform"]) || "prizepicks",
      dir: _v(r, ["dir", "direction", "Dir", "Direction"]),
      hit: _v(r, ["hit", "hit_rate", "Hit", "Hit Rate"]),
      edge: Number(_v(r, ["edge", "Edge"])),
      abs_edge: _v(r, ["abs_edge", "Abs Edge"]),
      projection: Number(_v(r, ["projection", "Projection", "Proj"])),
      ml_prob: _v(r, ["ml_prob", "ML Prob"]),
      def_tier: _v(r, ["def_tier", "Def Tier"]),
      rank_score: _v(r, ["rank_score", "Rank Score", "rank"]),
      game_time: _v(r, ["game_time", "Game Time"]),
      book_line: _v(r, ["book_line", "Book Line", "prop_line"]),
      l5_over: _v(r, ["l5_over", "L5 Over", "L5 O"]),
      l5_under: _v(r, ["l5_under", "L5 Under", "L5 U"]),
      l10_over: _v(r, ["l10_over", "L10 Over", "L10 O"]),
      l10_under: _v(r, ["l10_under", "L10 Under", "L10 U"]),
      tier: _v(r, ["tier", "Tier"]),
      rank_tier: _v(r, ["rank_tier", "Rank Tier"]) || _v(r, ["tier", "Tier"]),
      l5_avg: _v(r, ["l5_avg", "L5 Avg"]),
      season_avg: _v(r, ["season_avg", "Season Avg"]),
      actual_series,
      line_series,
    });
  }).filter((p) => p && p.player && p.prop && Number.isFinite(p.edge));
  if (!mapped.length) return false;
  ALL_SLATE = mapped;
  SLATE_CARDS_POPULATED = true;
  seedPlayerDataFromCardPicks(mapped);
  renderEdges();
  renderBestToRun();
  renderStreaks();
  return true;
}

function syncCardsFromCombinedSheet(columns, rows) {
  if (!Array.isArray(columns) || !Array.isArray(rows) || !rows.length) return false;
  const ci = (name) => columns.indexOf(name);
  const idx = {
    sport: ci("Sport"),
    initials: ci("Initials"),
    player: ci("Player"),
    prop: ci("Prop"),
    line: ci("Line"),
    pick: ci("Pick Type") >= 0 ? ci("Pick Type") : ci("Pick"),
    dir: ci("Dir") >= 0 ? ci("Dir") : ci("Direction"),
    hit: ci("Hit %") >= 0 ? ci("Hit %") : (ci("Hit") >= 0 ? ci("Hit") : ci("Hit Rate")),
    edge: ci("Edge"),
    projection: ci("Projection") >= 0 ? ci("Projection") : ci("Proj"),
    l5_over: ci("L5 Over") >= 0 ? ci("L5 Over") : ci("L5 O"),
    l5_under: ci("L5 Under") >= 0 ? ci("L5 Under") : ci("L5 U"),
    l10_over: ci("L10 Over") >= 0 ? ci("L10 Over") : ci("L10 O"),
    l10_under: ci("L10 Under") >= 0 ? ci("L10 Under") : ci("L10 U"),
    l5_avg: ci("L5 Avg"),
    season_avg: ci("Season Avg"),
    tier: ci("Tier"),
    rank_tier: ci("Rank Tier") >= 0 ? ci("Rank Tier") : ci("Tier"),
    actual_series: ci("Actual Series"),
    line_series: ci("Line Series"),
    pick_platform: ci("Platform") >= 0 ? ci("Platform") : ci("pick_platform"),
  };
  const get = (row, i) => (i >= 0 ? row[i] : null);
  const mapped = rows.map((r) => {
    const ex = extractPerGameFromColumnsRow(columns, r);
    let actual_series = get(r, idx.actual_series);
    let line_series = get(r, idx.line_series);
    actual_series = Array.isArray(actual_series) ? actual_series : [];
    line_series = Array.isArray(line_series) ? line_series : [];
    if (!normalizeSeries(actual_series).length && ex.actualVals.length) {
      actual_series = ex.actualVals;
    }
    const lineNum = Number(get(r, idx.line));
    if (!normalizeSeries(line_series).length && ex.lineVals.some((v) => v != null && Number.isFinite(Number(v)))) {
      line_series = ex.lineVals.map((v) =>
        v != null && Number.isFinite(Number(v)) ? Number(v) : lineNum,
      );
    }
    return {
      sport: get(r, idx.sport),
      initials: get(r, idx.initials),
      player: get(r, idx.player),
      prop: get(r, idx.prop),
      line: lineNum,
      pick: get(r, idx.pick),
      dir: get(r, idx.dir),
      hit: get(r, idx.hit),
      edge: Number(get(r, idx.edge)),
      projection: Number(get(r, idx.projection)),
      l5_over: get(r, idx.l5_over),
      l5_under: get(r, idx.l5_under),
      l10_over: get(r, idx.l10_over),
      l10_under: get(r, idx.l10_under),
      l5_avg: get(r, idx.l5_avg),
      season_avg: get(r, idx.season_avg),
      tier: get(r, idx.tier),
      rank_tier: get(r, idx.rank_tier),
      pick_platform: get(r, idx.pick_platform) || 'prizepicks',
      actual_series,
      line_series,
    };
  }).filter((p) => p.player && p.prop && Number.isFinite(p.edge));
  if (!mapped.length) return false;
  ALL_SLATE = mapped;
  SLATE_CARDS_POPULATED = true;
  seedPlayerDataFromCardPicks(mapped);
  renderEdges();
  renderBestToRun();
  renderStreaks();
  return true;
}

async function fetchSlateSport(sport, opts = {}) {
  if (sport === 'combined') return;
  if (SLATE_SPORT_CACHE[sport] && Array.isArray(SLATE_DATA[sport])) return;
  if (SLATE_SPORT_FETCH_PROMISES[sport]) return SLATE_SPORT_FETCH_PROMISES[sport];
  const prefetch = !!opts.prefetch;
  if (!prefetch || openSlatePanel === sport) showSlateSportLoading(sport, 'Loading slate...');

  SLATE_SPORT_FETCH_PROMISES[sport] = (async () => {
    // Do not kick multi-MB /api/slate on every sport open — edges warm via idle boot.
    let rows = [];
    let source = "";
    try {
      const res = await fetch(`/api/slate-sport/${encodeURIComponent(sport)}`, slateFetchOpts(60000));
      if (res.ok) {
        const d = await res.json();
        rows = Array.isArray(d.rows) ? d.rows : [];
        if (rows.length) source = "api_slate_sport";
      } else {
        console.warn(`slate-sport/${sport} HTTP ${res.status}`);
      }
    } catch (e) {
      console.warn(`slate-sport/${sport} fetch failed, trying bundled JSON:`, e);
    }
    if (!rows.length) {
      const d0 = await fetchBundledSlateSportPayload(sport);
      if (d0 && Array.isArray(d0.rows)) {
        rows = d0.rows;
        if (rows.length) source = "bundled_json";
      }
    }
    if (!rows.length) {
      // Ticket fallback needs ALL_SLATE from /api/slate — load only when sport JSON is empty.
      try {
        await loadSlateData();
      } catch (eWarm) {
        console.warn("loadSlateData (ticket fallback):", eWarm);
      }
      rows = _fallbackSlateRowsFromTickets(sport);
      if (rows.length) source = "ticket_fallback";
    }
    if (source === "ticket_fallback") {
      console.warn(
        `[slate] ${sport}: ticket fallback (${rows.length} rows) — detail charts need actual_series/stat_g on ALL_SLATE picks`,
      );
    } else if (source) {
      console.debug(`[slate] ${sport}: ${rows.length} rows from ${source}`);
    }
    _setSlateSportRows(sport, rows);
    SLATE_SPORT_CACHE[sport] = true;
    if (openSlatePanel === sport) scheduleRenderSlateTable(sport);
  })().finally(() => {
    delete SLATE_SPORT_FETCH_PROMISES[sport];
  });

  return SLATE_SPORT_FETCH_PROMISES[sport];
}

async function loadSlatePicks() {
  // No-op: panel rows are now fetched lazily per sport.
  if (openSlatePanel && SLATE_DATA[openSlatePanel]) scheduleRenderSlateTable(openSlatePanel);
}

function loadSlateSport(sport) {
  if (sport === 'combined') { loadSlateExcel(); return; }
  if (SLATE_SPORT_CACHE[sport] && SLATE_DATA[sport]) { scheduleRenderSlateTable(sport); return; }
  fetchSlateSport(sport).then(() => scheduleRenderSlateTable(sport));
}

function renderSlateTable(sport) {
  const rowsPre = SLATE_DATA[sport] || [];
  // Excel "combined" path uses array rows + SLATE_COLS; JSON slate uses plain objects
  if (SLATE_COLS[sport] && rowsPre.length && typeof rowsPre[0] === 'object' && !Array.isArray(rowsPre[0])) {
    delete SLATE_COLS[sport];
  }
  if (SLATE_COLS[sport]) { renderSlateTableDynamic(sport); return; }
  const rows  = SLATE_DATA[sport] || [];
  const state = SLATE_STATE[sport];
  const tbody = document.getElementById(`stb-${sport}`);
  const countEl = document.getElementById(`src-${sport}`);
  const token = (RENDER_TOKEN[sport] || 0) + 1;
  RENDER_TOKEN[sport] = token;
  if (!tbody) return;

  let filtered = rows.filter(r => {
    if (state.search) {
      const q = state.search.toLowerCase();
      if (!((r.player||'').toLowerCase().includes(q) || (r.prop||'').toLowerCase().includes(q) || (r.team||'').toLowerCase().includes(q) || (r.sport||'').toLowerCase().includes(q))) return false;
    }
    if (state.dir  && r.dir       !== state.dir)  return false;
    if (state.pick && r.pick_type !== state.pick) return false;
    if (state.platform && !_rowMatchesPlatformFilter(r, state.platform)) return false;
    if (state.tier) {
      const tv = String(r.tier == null ? '' : r.tier).trim().toUpperCase();
      if (tv !== String(state.tier).toUpperCase()) return false;
    }
    if (!_passesL5FilterForObjectRow(r, state.l5)) return false;
    return true;
  });

  filtered.sort((a, b) => {
    if (state.sortKey === 'abs_edge') {
      let av = _slateAbsEdge(a), bv = _slateAbsEdge(b);
      if (av == null) av = state.sortDir < 0 ? -Infinity : Infinity;
      if (bv == null) bv = state.sortDir < 0 ? -Infinity : Infinity;
      return state.sortDir * (av - bv);
    }
    let av = a[state.sortKey], bv = b[state.sortKey];
    if (av == null) av = state.sortDir < 0 ? -Infinity : Infinity;
    if (bv == null) bv = state.sortDir < 0 ? -Infinity : Infinity;
    if (typeof av === 'string') return state.sortDir * av.localeCompare(bv);
    return state.sortDir * (av - bv);
  });

  // update sort header classes
  const table = document.getElementById(`st-${sport}`);
  table?.querySelectorAll('th').forEach(th => { th.classList.remove('sort-asc','sort-desc'); });
  const ths = table?.querySelectorAll('th');
  const keyMap = ['tier','rank_score','player','team','opp','prop','pick_type','line','dir','edge','hit_rate','l5_over','l5_under','game_time'];
  if (ths) {
    const sortKeyForTh = state.sortKey === 'abs_edge' ? 'edge' : state.sortKey;
    const ci = keyMap.indexOf(sortKeyForTh);
    if (ci >= 0) ths[ci].classList.add(state.sortDir > 0 ? 'sort-asc' : 'sort-desc');
    const edgeIdx = keyMap.indexOf('edge');
    const thEdge = edgeIdx >= 0 ? ths[edgeIdx] : null;
    if (thEdge) {
      if (state.sortKey === 'abs_edge') {
        thEdge.textContent = '|EDGE|';
        thEdge.title = 'Sorted by absolute edge (OVER +11 and UNDER −11 rank together). Click for signed edge.';
      } else if (state.sortKey === 'edge') {
        thEdge.textContent = 'EDGE';
        thEdge.title = 'Sorted by signed edge (positive favors OVER, negative favors UNDER). Click again to reverse.';
      } else {
        thEdge.textContent = 'EDGE';
        thEdge.removeAttribute('title');
      }
    }
  }

  if (countEl) countEl.textContent = `${filtered.length} / ${rows.length} PROPS`;

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="14" style="text-align:center;padding:20px;color:var(--muted2);font-size:10px;letter-spacing:1px;">NO MATCHING PROPS</td></tr>`;
    return;
  }

  const rowHtml = (r, rowIdx) => {
    const isOver = r.dir === 'OVER';
    const dirCls = isOver ? 'dir-over' : 'dir-under';
    const dirSym = isOver ? '▲' : '▼';
    const edgeCls = (r.edge || 0) >= 0 ? 'edge-pos' : 'edge-neg';
    const edgeStr = r.edge != null ? (r.edge >= 0 ? '+' : '') + r.edge.toFixed(2) : '—';
    const hitStr  = r.hit_rate != null ? Math.round(r.hit_rate * 100) + '%' : '—';
    const tierCls = `tier-${r.tier || 'D'}`;
    const pickNorm = String(r.pick_type || '').trim().toLowerCase();
    const pickCls = pickNorm === 'goblin' ? 'pick-goblin-cell' : pickNorm === 'demon' ? 'pick-demon-cell' : 'pick-standard-cell';
    const l5fmt = formatL5Cell(r.l5_over, r.l5_under, r.l5_games_played, 5);
    const l5o = l5fmt.over;
    const l5u = l5fmt.under;
    const rankStr = r.rank_score != null ? r.rank_score.toFixed(2) : '—';
    const timeStr = formatGameTimeDisplay(r.game_time);
    return `<tr class="slate-row-clickable" data-slate-idx="${rowIdx}">
      <td class="scol-tier"><span class="tier-badge ${tierCls}">${r.tier || '?'}</span>${confDotHtml(r)}</td>
      <td class="scol-rank slate-rank-cell">${rankStr}</td>
      <td class="scol-player" style="color:var(--text);font-weight:600;min-width:0;max-width:100%;overflow:hidden;text-overflow:ellipsis;">${r.player || '—'}${l10StreakBadgeHtml(r)}${consLineBadgeHtml(r)}</td>
      <td class="scol-team" style="color:var(--muted);" title="${r.team || ''}">${r.team || '—'}</td>
      <td class="scol-opp" style="color:var(--muted);" title="${r.opp || ''}">${r.opp || '—'}</td>
      <td class="scol-prop" style="color:var(--text);">${r.prop || '—'}</td>
      <td class="scol-type slate-pick-type-cell ${pickCls}">${r.pick_type || '—'}</td>
      <td class="scol-line" style="font-family:'Inter',sans-serif;">${r.line != null ? r.line : '—'}</td>
      <td class="scol-dir ${dirCls}">${dirSym} ${r.dir || '—'}</td>
      <td class="scol-edge ${edgeCls}" style="font-family:'Inter',sans-serif;font-weight:700;">${edgeStr}</td>
      <td class="scol-hit" style="color:var(--cyan);font-family:'Inter',sans-serif;">${hitStr}</td>
      <td class="scol-l5o" style="color:var(--green);font-family:'Inter',sans-serif;">${l5o}</td>
      <td class="scol-l5u" style="color:var(--amber);font-family:'Inter',sans-serif;">${l5u}</td>
      <td class="scol-time slate-time-cell">${timeStr}</td>
    </tr>`;
  };

  const chunkSize = MOBILE_TABLE_QUERY.matches ? 30 : 100;
  // Virtualize large tables (MLB-scale) — keep only a window of rows in the DOM.
  const VIRTUALIZE_AT = 250;
  if (filtered.length > VIRTUALIZE_AT) {
    const wrap = tbody.closest(".slate-table-wrap") || tbody.parentElement;
    const rowH = MOBILE_TABLE_QUERY.matches ? 44 : 36;
    const buffer = 12;
    tbody.innerHTML = "";
    const topPad = document.createElement("tr");
    topPad.className = "slate-virt-pad";
    const botPad = document.createElement("tr");
    botPad.className = "slate-virt-pad";
    const mid = document.createElement("tbody");
    mid.className = "slate-virt-body";
    // Use a fragment host row-group via a nested table isn't valid; keep pads + rows in one tbody.
    const host = tbody;
    let lastStart = -1;
    const paint = () => {
      if (RENDER_TOKEN[sport] !== token) return;
      const scrollEl = wrap || host;
      const viewH = Math.max(240, (scrollEl && scrollEl.clientHeight) || 480);
      const scrollTop = (scrollEl && scrollEl.scrollTop) || 0;
      const start = Math.max(0, Math.floor(scrollTop / rowH) - buffer);
      const visible = Math.ceil(viewH / rowH) + buffer * 2;
      const end = Math.min(filtered.length, start + visible);
      if (start === lastStart && host.dataset.virtEnd === String(end)) return;
      lastStart = start;
      host.dataset.virtEnd = String(end);
      const topH = start * rowH;
      const botH = Math.max(0, (filtered.length - end) * rowH);
      const rowsHtml = filtered.slice(start, end).map((r, i) => rowHtml(r, start + i)).join("");
      host.innerHTML =
        `<tr class="slate-virt-pad" aria-hidden="true"><td colspan="14" style="height:${topH}px;padding:0;border:0;"></td></tr>` +
        rowsHtml +
        `<tr class="slate-virt-pad" aria-hidden="true"><td colspan="14" style="height:${botH}px;padding:0;border:0;"></td></tr>`;
      wireSlateRowClicks(host, filtered);
    };
    if (wrap && wrap._slateVirtHandler) {
      wrap.removeEventListener("scroll", wrap._slateVirtHandler);
    }
    const onScroll = () => {
      if (RENDER_TOKEN[sport] !== token) return;
      if (wrap._slateVirtRaf) cancelAnimationFrame(wrap._slateVirtRaf);
      wrap._slateVirtRaf = requestAnimationFrame(paint);
    };
    if (wrap) {
      wrap._slateVirtHandler = onScroll;
      wrap.addEventListener("scroll", onScroll, { passive: true });
    }
    paint();
    return;
  }

  if (filtered.length <= chunkSize) {
    tbody.innerHTML = filtered.map((r, i) => rowHtml(r, i)).join("");
    wireSlateRowClicks(tbody, filtered);
    return;
  }

  tbody.innerHTML = '';
  let idx = 0;
  const renderChunk = () => {
    if (RENDER_TOKEN[sport] !== token) return; // stale render
    const chunk = filtered.slice(idx, idx + chunkSize).map((r, i) => rowHtml(r, idx + i)).join('');
    tbody.insertAdjacentHTML('beforeend', chunk);
    idx += chunkSize;
    if (idx < filtered.length) requestAnimationFrame(renderChunk);
    else wireSlateRowClicks(tbody, filtered);
  };
  requestAnimationFrame(renderChunk);
}

function wireSlateRowClicks(tbody, filteredRows) {
  if (!tbody) return;
  tbody.onclick = (e) => {
    const tr = e.target.closest("tr[data-slate-idx]");
    if (!tr || !tbody.contains(tr)) return;
    const i = Number(tr.dataset.slateIdx);
    const pick = filteredRows[i];
    if (pick) openPropDetailPanel(pick);
  };
}

function sortSlate(sport, key) {
  const s = SLATE_STATE[sport];
  if (s.sortKey === key) s.sortDir *= -1;
  else { s.sortKey = key; s.sortDir = -1; }
  scheduleRenderSlateTable(sport);
}

function filterSlate(sport, val) {
  if (!SLATE_STATE[sport]) return;
  SLATE_STATE[sport].search = val;
  if (!window.__slateFilterDebounce) window.__slateFilterDebounce = {};
  const timers = window.__slateFilterDebounce;
  if (timers[sport]) window.clearTimeout(timers[sport]);
  timers[sport] = window.setTimeout(() => {
    timers[sport] = null;
    scheduleRenderSlateTable(sport);
  }, 300);
}

function toggleDirFilter(sport, dir, btn) {
  const s = SLATE_STATE[sport];
  if (s.dir === dir) { s.dir = null; btn.classList.remove('on'); }
  else {
    s.dir = dir;
    document.getElementById(`sfb-${sport}-over`)?.classList.remove('on');
    document.getElementById(`sfb-${sport}-under`)?.classList.remove('on');
    btn.classList.add('on');
  }
  scheduleRenderSlateTable(sport);
}

function togglePlatformFilter(sport, platformKey, btn) {
  const s = SLATE_STATE[sport];
  if (!s) return;
  if (s.platform === platformKey) {
    s.platform = null;
    btn.classList.remove('on');
  } else {
    s.platform = platformKey;
    document.getElementById(`sfb-${sport}-pp`)?.classList.remove('on');
    document.getElementById(`sfb-${sport}-ud`)?.classList.remove('on');
    btn.classList.add('on');
  }
  scheduleRenderSlateTable(sport);
}

function togglePickFilter(sport, pick, btn) {
  const s = SLATE_STATE[sport];
  if (s.pick === pick) { s.pick = null; btn.classList.remove('on'); }
  else {
    s.pick = pick;
    document.getElementById(`sfb-${sport}-goblin`)?.classList.remove('on');
    document.getElementById(`sfb-${sport}-standard`)?.classList.remove('on');
    btn.classList.add('on');
  }
  scheduleRenderSlateTable(sport);
}

function toggleL5Filter(sport, mode, btn) {
  const s = SLATE_STATE[sport];
  if (!s) return;
  if (s.l5 === mode) {
    s.l5 = null;
    btn?.classList.remove('on');
  } else {
    s.l5 = mode;
    document.getElementById(`sfb-${sport}-l5over`)?.classList.remove('on');
    document.getElementById(`sfb-${sport}-l5under`)?.classList.remove('on');
    btn?.classList.add('on');
    if (mode === 'UNDER' && s.pick && String(s.pick).toLowerCase() !== 'standard') {
      s.pick = null;
      document.getElementById(`sfb-${sport}-goblin`)?.classList.remove('on');
      document.getElementById(`sfb-${sport}-demon`)?.classList.remove('on');
      document.getElementById(`sfb-${sport}-standard`)?.classList.remove('on');
    }
  }
  scheduleRenderSlateTable(sport);
}

/** Tier chips: optional client filter; default is All (no tier constraint). */
function setSlateTierFilter(sport, tier, btn) {
  const s = SLATE_STATE[sport];
  if (!s) return;
  s.tier = tier ? String(tier).trim().toUpperCase() : null;
  const panel = document.getElementById(`sp-${sport}`);
  if (panel) panel.querySelectorAll('.slate-tier-btn').forEach(b => b.classList.remove('on'));
  if (btn) btn.classList.add('on');
  scheduleRenderSlateTable(sport);
}

// ── Combined = Full Slate: prefer Excel "Full Slate" sheet; else merged JSON (Railway-friendly) ──
function ensureFixedCombinedTheadFromNbaTemplate() {
  const table = document.getElementById('st-combined');
  const nba = document.getElementById('st-nba');
  if (!table || !nba) return;
  const src = nba.querySelector('thead tr');
  const dst = table.querySelector('thead');
  if (!src || !dst) return;
  dst.innerHTML = src.innerHTML.replace(/sortSlate\('nba'/g, "sortSlate('combined'");
}

async function loadCombinedFromMergedJson() {
  const tbody = document.getElementById('stb-combined');
  try {
    void loadSlateData().catch(() => {});
    let d = null;
    try {
      const res = await fetch('/api/slate-sport/combined', slateFetchOpts(60000));
      if (res.ok) d = await res.json();
    } catch (e) {}
    if (!d || !Array.isArray(d.rows) || !d.rows.length) {
      d = await fetchBundledSlateSportCombinedPayload();
    }
    const rows = d && Array.isArray(d.rows) ? d.rows : [];
    if (!rows.length) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="14" style="text-align:center;padding:20px;color:var(--muted2);font-size:10px;">NO COMBINED SLATE (deploy slate_latest.json or run pipeline)</td></tr>`;
      return;
    }
    delete SLATE_COLS.combined;
    SLATE_STATE.combined.sortKey = 'rank_score';
    ensureFixedCombinedTheadFromNbaTemplate();
    _setSlateSportRows('combined', rows);
    syncCardsFromCombinedRows(rows);
    scheduleRenderSlateTable('combined');
  } catch (e) {
    console.warn('combined json fallback failed:', e);
    if (tbody) tbody.innerHTML = `<tr><td colspan="14" style="text-align:center;padding:20px;color:var(--red);font-size:10px;">FAILED TO LOAD COMBINED SLATE</td></tr>`;
  }
}

async function loadSlateExcel() {
  const tbody = document.getElementById('stb-combined');
  const haveExcel = SLATE_COLS['combined'] && SLATE_DATA['combined']?.length;
  const haveJson = !SLATE_COLS['combined'] && SLATE_DATA['combined']?.length;
  if (haveExcel || haveJson) { scheduleRenderSlateTable('combined'); return; }
  if (tbody) tbody.innerHTML = `<tr><td colspan="14" style="text-align:center;padding:20px;color:var(--muted);letter-spacing:1px;font-size:10px;">LOADING…</td></tr>`;
  if (!_slateExcelPromise) {
    _slateExcelPromise = (async () => {
      try {
        const r = await fetch('/api/slate-excel', slateFetchOpts(60000));
        const d = await r.json();
        const sh = d.sheets && d.sheets.combined;
        if (sh && sh.columns && sh.rows && sh.rows.length) {
          SLATE_COLS.combined = sh.columns;
          SLATE_DATA.combined = sh.rows;
          syncCardsFromCombinedSheet(sh.columns, sh.rows);
          scheduleRenderSlateTable('combined');
          return;
        }
      } catch (e) {
        console.warn('slate-excel failed:', e);
      }
      await loadCombinedFromMergedJson();
    })();
  }
  await _slateExcelPromise;
}

function renderSlateTableDynamic(sport) {
  const cols  = SLATE_COLS[sport] || [];
  const allRows = SLATE_DATA[sport] || [];
  const state = SLATE_STATE[sport] || {};
  const tbody = document.getElementById(`stb-${sport}`);
  const thead = document.querySelector(`#st-${sport} thead`);
  const countEl = document.getElementById(`src-${sport}`);
  if (!tbody) return;

  // Build header if needed
  if (thead) {
    thead.innerHTML = '<tr>' + cols.map(c => {
      const active = state.sortKey === c;
      const cls = active ? (state.sortDir > 0 ? 'sort-asc' : 'sort-desc') : '';
      return `<th class="${cls}" onclick="sortSlateDynamic('${sport}','${c.replace(/'/g,"\\'")}')">${c}</th>`;
    }).join('') + '</tr>';
  }

  // Determine column index helpers
  const ci = name => cols.indexOf(name);
  const dirIdx    = ci('Dir') >= 0 ? ci('Dir') : ci('Direction');
  const pickIdx   = ci('Pick Type') >= 0 ? ci('Pick Type') : ci('Pick');
  const rankIdx   = ci('Rank Score') >= 0 ? ci('Rank Score') : ci('Rank');
  const timeIdx   = ci('Game Time') >= 0 ? ci('Game Time') : ci('Time');
  const playerIdx = ci('Player');
  const propIdx   = ci('Prop') >= 0 ? ci('Prop') : ci('Stat');
  const teamIdx   = ci('Team');
  const sportIdx  = ci('Sport') >= 0 ? ci('Sport') : -1;
  const l5OverIdx = ci('L5 Over') >= 0 ? ci('L5 Over') : (ci('L5 O') >= 0 ? ci('L5 O') : -1);
  const l5UnderIdx = ci('L5 Under') >= 0 ? ci('L5 Under') : (ci('L5 U') >= 0 ? ci('L5 U') : -1);
  const tierIdx   = ci('Tier') >= 0 ? ci('Tier') : -1;
  const platformIdx = ci('Platform') >= 0 ? ci('Platform') : ci('pick_platform');
  const udLineIdx = ci('Line (UD)') >= 0 ? ci('Line (UD)') : ci('line_underdog');

  // Filter
  let filtered = allRows.filter(row => {
    if (state.search) {
      const q = state.search.toLowerCase();
      const haystack = [playerIdx, propIdx, teamIdx, sportIdx].filter(i => i >= 0).map(i => String(row[i] || '').toLowerCase()).join(' ');
      if (!haystack.includes(q)) return false;
    }
    if (state.dir  && dirIdx  >= 0 && String(row[dirIdx]  || '') !== state.dir)  return false;
    if (state.pick && pickIdx >= 0 && String(row[pickIdx] || '') !== state.pick) return false;
    if (state.tier && tierIdx >= 0) {
      const tv = String(row[tierIdx] == null ? '' : row[tierIdx]).trim().toUpperCase();
      if (tv !== String(state.tier).toUpperCase()) return false;
    }
    if (state.l5 === 'OVER') {
      if (dirIdx >= 0 && String(row[dirIdx] || '').trim().toUpperCase() !== 'OVER') return false;
      if (l5OverIdx >= 0 && (_l5HitCount(row[l5OverIdx]) ?? -1) < L5_FILTER_MIN_HITS) return false;
    }
    if (state.l5 === 'UNDER') {
      const pickVal = pickIdx >= 0 ? String(row[pickIdx] || '').trim().toLowerCase() : '';
      if (pickVal === 'goblin' || pickVal === 'demon') return false;
      if (dirIdx >= 0 && String(row[dirIdx] || '').trim().toUpperCase() !== 'UNDER') return false;
      if (l5UnderIdx >= 0 && (_l5HitCount(row[l5UnderIdx]) ?? -1) < L5_FILTER_MIN_HITS) return false;
    }
    if (state.platform) {
      const faux = {
        pick_platform: platformIdx >= 0 ? row[platformIdx] : 'prizepicks',
        line_underdog: udLineIdx >= 0 ? row[udLineIdx] : null,
      };
      if (!_rowMatchesPlatformFilter(faux, state.platform)) return false;
    }
    return true;
  });

  // Sort
  if (state.sortKey) {
    const si = ci(state.sortKey);
    if (si >= 0) {
      filtered.sort((a, b) => {
        let av = a[si], bv = b[si];
        const an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return state.sortDir * (an - bn);
        if (av == null) av = ''; if (bv == null) bv = '';
        return state.sortDir * String(av).localeCompare(String(bv));
      });
    }
  }

  if (countEl) countEl.textContent = `${filtered.length} / ${allRows.length} PROPS`;

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="${cols.length}" style="text-align:center;padding:20px;color:var(--muted2);font-size:10px;letter-spacing:1px;">NO MATCHING PROPS</td></tr>`;
    return;
  }

  // Render rows — colour certain columns
  const edgeIdx = ci('Edge');
  const dirColored = (val) => {
    const v = String(val || '');
    if (v === 'OVER') return `<span class="dir-over">▲ OVER</span>`;
    if (v === 'UNDER') return `<span class="dir-under">▼ UNDER</span>`;
    return v || '—';
  };

  const pickTypeCls = (raw) => {
    const pl = String(raw || '').trim().toLowerCase();
    if (pl === 'goblin') return 'pick-goblin-cell';
    if (pl === 'demon') return 'pick-demon-cell';
    return 'pick-standard-cell';
  };

  const rowHtml = (row) => {
    const cells = cols.map((c, i) => {
      const val = row[i];
      const vStr = val == null || val === 'None' ? '—' : String(val);
      if (i === dirIdx) return `<td>${dirColored(val)}</td>`;
      if (i === edgeIdx) {
        const n = parseFloat(val);
        const cls = !isNaN(n) ? (n >= 0 ? 'edge-pos' : 'edge-neg') : '';
        const disp = !isNaN(n) ? (n >= 0 ? '+' : '') + n.toFixed(2) : vStr;
        return `<td class="${cls}" style="font-family:'Inter',sans-serif;font-weight:700;">${disp}</td>`;
      }
      if (pickIdx >= 0 && i === pickIdx) {
        const pc = pickTypeCls(val);
        return `<td class="slate-pick-type-cell ${pc}">${vStr}</td>`;
      }
      if (rankIdx >= 0 && i === rankIdx) return `<td class="slate-rank-cell">${vStr}</td>`;
      if (timeIdx >= 0 && i === timeIdx) return `<td class="slate-time-cell">${formatGameTimeDisplay(val)}</td>`;
      if (i === playerIdx) return `<td style="font-weight:600;max-width:140px;overflow:hidden;text-overflow:ellipsis;">${vStr}</td>`;
      return `<td>${vStr}</td>`;
    }).join('');
    return `<tr>${cells}</tr>`;
  };

  const token = (RENDER_TOKEN[sport] || 0) + 1;
  RENDER_TOKEN[sport] = token;
  const chunkSize = MOBILE_TABLE_QUERY.matches ? 30 : 100;
  if (filtered.length <= chunkSize) { tbody.innerHTML = filtered.map(rowHtml).join(''); return; }
  tbody.innerHTML = '';
  let idx = 0;
  const renderChunk = () => {
    if (RENDER_TOKEN[sport] !== token) return;
    tbody.insertAdjacentHTML('beforeend', filtered.slice(idx, idx + chunkSize).map(rowHtml).join(''));
    idx += chunkSize;
    if (idx < filtered.length) requestAnimationFrame(renderChunk);
  };
  requestAnimationFrame(renderChunk);
}

function sortSlateDynamic(sport, key) {
  const s = SLATE_STATE[sport];
  if (!s) return;
  if (s.sortKey === key) s.sortDir *= -1;
  else { s.sortKey = key; s.sortDir = -1; }
  scheduleRenderSlateTable(sport);
}

// Keep edge/streak/Best-to-Run sections populated; warm only the default sport table on boot.
// Mobile used to skip all slate warming (skipHeavyCombinedSlate) — Best to Run / Top Edges stayed empty.
async function loadLineTimingInsight() {
  const headline = document.getElementById("line-timing-headline");
  const windowsEl = document.getElementById("line-timing-windows");
  const tipsEl = document.getElementById("line-timing-tips");
  const metaEl = document.getElementById("line-timing-meta");
  if (!headline || !windowsEl || !tipsEl) return;
  let data = null;
  try {
    let res = await fetch("/api/line-move-timing", { cache: "no-store" });
    if (!res.ok) res = await fetch("line_move_timing.json", { cache: "no-store" });
    if (res.ok) data = await res.json();
  } catch (e) {
    console.warn("line timing load failed", e);
  }
  if (!data) {
    headline.textContent = "Line-move timing still collecting.";
    tipsEl.innerHTML = "<li>Keep 5AM + midday refreshes on to build history.</li>";
    return;
  }
  headline.textContent = data.headline || "Standard line-move timing";
  const roleColor = (role) => {
    if (role === "favorable") return "var(--green)";
    if (role === "unfavorable") return "var(--red)";
    if (role === "high_volume") return "var(--amber)";
    return "var(--muted2)";
  };
  const windows = Array.isArray(data.windows) ? data.windows : [];
  windowsEl.innerHTML = windows
    .slice(0, 4)
    .map((w) => {
      const label = w.label || w.id || "Window";
      const fav = Number(w.fav_pct);
      const unfav = Number(w.unfav_pct);
      const moves = Number(w.moves) || 0;
      const role = String(w.role || "mixed");
      return `<div class="insight-card" style="min-width:0;">
        <div class="insight-title" style="color:${roleColor(role)}">${label}</div>
        <div class="insight-body">
          <strong>${Number.isFinite(fav) ? fav.toFixed(0) : "—"}%</strong> favorable ·
          <strong>${Number.isFinite(unfav) ? unfav.toFixed(0) : "—"}%</strong> unfavorable<br/>
          <span style="opacity:.9">${moves} moves${w.days ? ` · ${w.days} days` : ""}</span>
        </div>
      </div>`;
    })
    .join("");
  const tips = Array.isArray(data.tips) ? data.tips : [];
  tipsEl.innerHTML = tips.map((t) => `<li>${String(t)}</li>`).join("");
  if (metaEl) {
    const days = data.sample_days != null ? data.sample_days : "—";
    const range = Array.isArray(data.date_range) && data.date_range[0]
      ? `${data.date_range[0]} → ${data.date_range[1] || data.date_range[0]}`
      : "";
    metaEl.textContent = `Sample: ${days} days${range ? ` (${range})` : ""}. Favorable = OVER line down / UNDER line up.`;
  }
}

(function bootHomeSlateUi() {
  try {
    injectSlatePlatformButtons();
    injectSlateL5Buttons();
    fetchSlateSport(getDefaultBootSlateSport());
    autoOpenBootSlatePanel();
    loadLineTimingInsight();
    const warmHomeCards = () => {
      try {
        loadHomeCardsFromFullSlate()
          .then(() => {
            if (ALL_SLATE.length) {
              renderEdges();
              renderBestToRun();
              renderStreaks();
            }
          })
          .catch((e) => console.warn("warmHomeCards:", e));
      } catch (e2) {
        console.warn("warmHomeCards:", e2);
      }
    };
    const warmFullSlate = () => {
      try {
        loadSlateData().catch((e) => console.warn("deferred loadSlateData:", e));
      } catch (e2) {
        console.warn("deferred loadSlateData:", e2);
      }
    };
    const skipHeavyCombinedSlate =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(max-width: 900px), (pointer: coarse)").matches;
    // Always warm Best to Run / Top Edges / L5 from combined slate JSON (mobile + desktop).
    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(warmHomeCards, { timeout: 2500 });
    } else {
      window.setTimeout(warmHomeCards, 600);
    }
    // Desktop: also merge ticket legs / history via full /api/slate.
    if (!skipHeavyCombinedSlate) {
      if (typeof window.requestIdleCallback === "function") {
        window.requestIdleCallback(warmFullSlate, { timeout: 4000 });
      } else {
        window.setTimeout(warmFullSlate, 2500);
      }
    }
    // Deep link: ?section=best
    try {
      if (new URLSearchParams(window.location.search).get("section") === "best") {
        window.setTimeout(() => {
          if (typeof jumpToBestToRun === "function") jumpToBestToRun();
        }, 900);
      }
    } catch (eDeep) {}
  } catch (e) {
    console.error("home slate UI boot:", e);
  }
})();

