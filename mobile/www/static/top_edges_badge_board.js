/** Top Edges badge board — same filters as scripts/rank_best_props_today.py */
(function (root) {
  const SPORTS = ["WNBA", "MLB", "SOCCER", "TENNIS"];
  const SKIP_PROPS = /fantasy(\s+score)?/i;
  const ATP_ELITE = 10;
  const ATP_ABOVE = 25;
  const ATP_AVG = 50;
  const ATP_BELOW = 100;
  const UNKNOWN_OPP = new Set(["unknown_opp", "unk", "unknown", ""]);
  const BADGE_ORDER = { Gold: 0, Silver: 1, Bronze: 2 };

  function num(v) {
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  function intNum(v) {
    const n = num(v);
    return n == null ? null : Math.round(n);
  }
  function clean(v) {
    const s = String(v == null ? "" : v).trim();
    return !s || /^(nan|none|null)$/i.test(s) ? "" : s;
  }
  function sportOf(p) {
    return String(p?.sport || "").trim().toUpperCase();
  }
  function pickOf(p) {
    const t = String(p?.pick || p?.pick_type || "").trim().toLowerCase();
    if (t.includes("dem")) return "Demon";
    if (t.includes("gob")) return "Goblin";
    if (t.includes("std") || t === "standard" || t === "") return "Standard";
    return String(p?.pick || p?.pick_type || "Standard").trim();
  }
  function dirOf(p) {
    const d = String(p?.dir || p?.direction || p?.final_bet_direction || "").trim().toUpperCase();
    return d === "OVER" || d === "UNDER" ? d : "";
  }
  function l5Of(p, over) {
    if (over) return intNum(p?.l5_over) ?? intNum(p?.last5_over);
    return intNum(p?.l5_under) ?? intNum(p?.last5_under);
  }
  function l10Of(p, over) {
    if (over) return intNum(p?.l10_over);
    return intNum(p?.l10_under);
  }
  function avgOf(p) {
    const seas = num(p?.season_avg) ?? num(p?.stat_season_avg) ?? num(p?.l5_avg);
    if (seas != null && !(seas > 0 && seas <= 1 && num(p?.line) >= 3)) return seas;
    const vals = [];
    for (let i = 1; i <= 20; i++) {
      const v = num(p?.[`stat_g${i}`] ?? p?.[`g${i}`]);
      if (v != null) vals.push(v);
    }
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }
  function atpTier(rank) {
    const v = intNum(rank);
    if (v == null || v <= 0) return "";
    if (v <= ATP_ELITE) return "Elite";
    if (v <= ATP_ABOVE) return "Above Avg";
    if (v <= ATP_AVG) return "Avg";
    if (v <= ATP_BELOW) return "Below Avg";
    return "Weak";
  }
  function oppName(p) {
    return clean(p?.opp || p?.opp_team).toLowerCase();
  }
  function defRankOf(p) {
    const sp = sportOf(p);
    if (sp === "TENNIS") {
      if (UNKNOWN_OPP.has(oppName(p))) return null;
      const v = intNum(p?.opponent_rank) ?? intNum(p?.opponent_def_rank);
      return v != null && v > 0 ? v : null;
    }
    const v = intNum(p?.opponent_def_rank) ?? intNum(p?.OVERALL_DEF_RANK) ?? intNum(p?.def_rank);
    return v != null && v > 0 ? v : null;
  }
  function defTierOf(p) {
    const sp = sportOf(p);
    if (sp === "TENNIS") return atpTier(defRankOf(p));
    const raw = clean(p?.stat_def_tier || p?.DEF_TIER || p?.def_tier || p?.opp_def_tier);
    const low = raw.toLowerCase();
    if (!low || low === "n/a" || low === "na") return "";
    if (low === "weak" || low.includes("easy")) return "Weak";
    if (low.includes("below")) return "Below Avg";
    if (low === "elite" || low.includes("hard") || low.includes("elite")) return "Elite";
    if (low.includes("above")) return "Above Avg";
    return raw;
  }
  function overDOk(sport, tier) {
    if (sport === "WNBA" || sport === "MLB") return tier === "Weak";
    if (sport === "SOCCER" || sport === "TENNIS") return tier === "Weak" || tier === "Below Avg";
    return false;
  }
  function underDOk(sport, tier) {
    if (sport === "WNBA" || sport === "MLB") return tier === "Elite";
    if (sport === "SOCCER" || sport === "TENNIS") return tier === "Elite" || tier === "Above Avg";
    return false;
  }
  function dAligns(tier, over) {
    const low = String(tier || "").trim().toLowerCase();
    if (!low) return false;
    if (over) return low === "weak" || low.includes("below") || low.includes("easy");
    return low === "elite" || low.includes("above") || low.includes("hard") || low.includes("elite");
  }
  function badgeOf(rec) {
    const over = rec.side === "OVER";
    const l5 = over ? rec.l5_over : rec.l5_under;
    const checks = {};
    checks.L5 = l5 == null ? null : l5 >= 4;
    if (rec.cover == null) checks.Cover = null;
    else if (over) checks.Cover = rec.cover > 0;
    else if (rec.side === "UNDER") checks.Cover = rec.cover < 0;
    else checks.Cover = null;
    if (rec.cover == null || rec.line == null) checks.Delta = null;
    else {
      const need = Math.max(0.5, Math.abs(rec.line) * 0.15);
      checks.Delta = over ? rec.cover >= need : rec.cover <= -need;
    }
    const model = rec.model_dir || "";
    if (!model) checks.Dir = null;
    else if (rec.pick_type === "Goblin") checks.Dir = model === "OVER";
    else checks.Dir = model === rec.side;

    const skip = !rec.def && rec.def_rank == null;
    if (skip) {
      checks.D = null;
      checks.Rank = null;
    } else {
      checks.D = rec.def ? dAligns(rec.def, over) : null;
      if (rec.def_rank == null) checks.Rank = null;
      else if (rec.sport === "TENNIS") checks.Rank = over ? rec.def_rank > ATP_AVG : rec.def_rank <= ATP_ABOVE;
      else checks.Rank = over ? rec.def_rank >= 8 : rec.def_rank <= 6;
    }
    const applicable = Object.entries(checks).filter(([, v]) => v != null);
    const misses = applicable.filter(([, v]) => v === false).map(([k]) => k);
    let badge = "";
    if (applicable.length >= 4) {
      if (!misses.length) badge = "Gold";
      else if (misses.length === 1) badge = "Silver";
      else if (misses.length === 2) badge = "Bronze";
    }
    return { checks, misses, badge, miss_s: misses.join(", ") };
  }
  function toRec(p) {
    const sport = sportOf(p);
    const prop = String(p?.prop || p?.prop_type || "").trim();
    if (!prop || SKIP_PROPS.test(prop)) return null;
    const pick_type = pickOf(p);
    if (pick_type === "Demon") return null;
    const side = dirOf(p);
    const line = num(p?.line);
    const avg = avgOf(p);
    const cover = avg == null || line == null ? null : avg - line;
    const rec = {
      pick: p,
      sport,
      player: String(p?.player || "").trim(),
      prop,
      line,
      pick_type,
      side,
      model_dir: String(p?.model_dir || "").trim().toUpperCase(),
      l5_over: l5Of(p, true),
      l5_under: l5Of(p, false),
      l10_over: l10Of(p, true),
      l10_under: l10Of(p, false),
      season_avg: avg == null ? null : Math.round(avg * 100) / 100,
      cover: cover == null ? null : Math.round(cover * 100) / 100,
      def: defTierOf(p),
      def_rank: defRankOf(p),
      matchup: [clean(p?.team), clean(p?.opp || p?.opp_team)].filter(Boolean).join(" vs "),
    };
    Object.assign(rec, badgeOf(rec));
    return rec;
  }
  function sortBucket(list, over) {
    const seen = new Set();
    const out = [];
    list
      .slice()
      .sort((a, b) => {
        const ba = BADGE_ORDER[a.badge] ?? 3;
        const bb = BADGE_ORDER[b.badge] ?? 3;
        if (ba !== bb) return ba - bb;
        const l5a = (over ? a.l5_over : a.l5_under) || 0;
        const l5b = (over ? b.l5_over : b.l5_under) || 0;
        if (l5b !== l5a) return l5b - l5a;
        const ca = a.cover == null ? 0 : over ? -a.cover : a.cover;
        const cb = b.cover == null ? 0 : over ? -b.cover : b.cover;
        if (ca !== cb) return ca - cb;
        return String(a.player).localeCompare(String(b.player));
      })
      .forEach((r) => {
        const k = `${r.player}|${r.prop}|${r.line}`;
        if (seen.has(k)) return;
        seen.add(k);
        out.push(r);
      });
    return out;
  }
  function bucket(recs, sport) {
    const stdO = [];
    const stdU = [];
    const gob = [];
    recs.forEach((r) => {
      if (r.sport !== sport) return;
      if (r.pick_type === "Standard" && r.side === "OVER" && (r.l5_over || 0) >= 4 && overDOk(sport, r.def)) {
        stdO.push(r);
      } else if (r.pick_type === "Standard" && r.side === "UNDER" && (r.l5_under || 0) >= 4 && underDOk(sport, r.def)) {
        stdU.push(r);
      } else if (r.pick_type === "Goblin" && r.side === "OVER" && (r.l5_over || 0) >= 4 && overDOk(sport, r.def)) {
        gob.push(r);
      }
    });
    return { stdO: sortBucket(stdO, true), stdU: sortBucket(stdU, false), gob: sortBucket(gob, true) };
  }
  function rankFromSlate(picks) {
    const recs = (picks || []).map(toRec).filter(Boolean);
    const out = {};
    SPORTS.forEach((sp) => {
      out[sp] = bucket(recs, sp);
    });
    return out;
  }

  root.TopEdgesBadgeBoard = {
    SPORTS,
    rankFromSlate,
    toRec,
    overDOk,
    underDOk,
    defTierOf,
    atpTier,
  };
})(typeof window !== "undefined" ? window : globalThis);
