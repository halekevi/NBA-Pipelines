/** Build a personal PrizePicks slip from Home cards / slate. Track P&L only — no auto-bet. */
(function (root) {
  const KEY = "proporacle-my-slip";
  const MAX = 6;

  function state() {
    try {
      const raw = sessionStorage.getItem(KEY);
      const parsed = raw ? JSON.parse(raw) : null;
      if (parsed && Array.isArray(parsed.legs)) return parsed;
    } catch (_e) {}
    return { legs: [], product: "Power", stake: "", n_correct: {}, min: false };
  }
  function save(s) {
    try {
      sessionStorage.setItem(KEY, JSON.stringify(s));
    } catch (_e) {}
  }

  function slateDate() {
    const el = document.getElementById("slate-date");
    const t = String((el && el.textContent) || "").trim();
    const m = t.match(/(\d{4}-\d{2}-\d{2})/);
    if (m) return m[1];
    return new Date().toISOString().slice(0, 10);
  }

  function pickToLeg(p) {
    if (!p || typeof p !== "object") return null;
    let direction = String(p.dir || p.direction || "").trim().toUpperCase();
    if (direction === "LOWER") direction = "UNDER";
    const player = String(p.player || "").trim();
    if (!player || (direction !== "OVER" && direction !== "UNDER")) return null;
    return {
      sport: String(p.sport || ""),
      player: player,
      prop_type: String(p.prop || p.prop_type || "").trim(),
      direction: direction,
      line: p.line,
      pick_type: String(p.pick || p.pick_type || "Standard").trim(),
      standard_line: p.standard_line || p.book_line || null,
    };
  }

  function encodeLeg(p) {
    const leg = pickToLeg(p);
    if (!leg) return "";
    try {
      return encodeURIComponent(JSON.stringify(leg));
    } catch (_e) {
      return "";
    }
  }

  function decodeLeg(raw) {
    try {
      const obj = JSON.parse(decodeURIComponent(String(raw || "")));
      return pickToLeg(obj);
    } catch (_e) {
      return null;
    }
  }

  function fpPart(leg) {
    const line = leg.line == null ? "" : String(leg.line);
    return [String(leg.player || "").toLowerCase(), String(leg.prop_type || "").toLowerCase(), line, String(leg.direction || "").toUpperCase()].join("|");
  }

  function toast(msg, ok) {
    const el = document.getElementById("my-slip-msg");
    if (!el) return;
    el.className = "my-slip-msg " + (ok ? "ok" : "err");
    el.textContent = msg || "";
  }

  function render() {
    const s = state();
    const dock = document.getElementById("my-slip-dock");
    if (!dock) return;
    dock.classList.toggle("is-open", s.legs.length > 0);
    dock.classList.toggle("is-min", !!s.min);
    document.body.classList.toggle("my-slip-padded", s.legs.length > 0);
    const count = document.getElementById("my-slip-count");
    if (count) count.textContent = s.legs.length + " / " + MAX;
    const list = document.getElementById("my-slip-legs");
    if (list) {
      list.innerHTML = s.legs
        .map(function (leg, i) {
          const pick = String(leg.pick_type || "");
          const line = leg.line == null ? "" : leg.line;
          return (
            "<li><button type='button' class='rm' data-i='" +
            i +
            "' aria-label='Remove'>×</button><span>" +
            escapeHtml(leg.player) +
            " · " +
            escapeHtml(leg.direction) +
            " " +
            escapeHtml(String(line)) +
            " " +
            escapeHtml(leg.prop_type) +
            (pick ? " · " + escapeHtml(pick) : "") +
            "</span></li>"
          );
        })
        .join("");
    }
    const prod = document.getElementById("my-slip-product");
    if (prod) prod.value = s.product === "Flex" ? "Flex" : "Power";
    const stake = document.getElementById("my-slip-stake");
    if (stake && s.stake !== "" && stake.value === "") stake.value = s.stake;
    fillNCorrectInputs(s);
    document.querySelectorAll(".my-slip-add").forEach(function (btn) {
      const host = btn.closest("[data-my-slip-leg]") || btn;
      const encoded = host.getAttribute("data-my-slip-leg") || btn.getAttribute("data-my-slip-leg") || "";
      const leg = decodeLeg(encoded);
      const on = !!(leg && s.legs.some(function (x) { return fpPart(x) === fpPart(leg); }));
      btn.classList.toggle("is-on", on);
      if (btn.id === "prop-detail-add") btn.textContent = on ? "On my slip" : "Add to my slip";
    });
    const saveBtn = document.getElementById("my-slip-save");
    if (saveBtn) saveBtn.disabled = s.legs.length < 2;
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function nKeys(product, n) {
    if (product === "Flex") {
      const keys = [];
      for (let k = n; k >= Math.max(2, n - 2); k--) keys.push(k);
      return keys;
    }
    return n > 0 ? [n] : [];
  }

  function fillNCorrectInputs(s) {
    const host = document.getElementById("my-slip-ncorrect");
    if (!host) return;
    const keys = nKeys(s.product, s.legs.length);
    host.innerHTML = keys
      .map(function (k) {
        const val = s.n_correct && s.n_correct[String(k)] != null ? s.n_correct[String(k)] : "";
        return (
          "<label>" +
          k +
          " correct" +
          "<input type='number' min='0.01' step='0.01' data-nk='" +
          k +
          "' value='" +
          escapeHtml(String(val)) +
          "' placeholder='x'/></label>"
        );
      })
      .join("");
  }

  function readNCorrect() {
    const out = {};
    document.querySelectorAll("#my-slip-ncorrect input[data-nk]").forEach(function (inp) {
      const k = inp.getAttribute("data-nk");
      const v = parseFloat(inp.value);
      if (k && Number.isFinite(v) && v > 0) out[k] = v;
    });
    return out;
  }

  function add(leg) {
    if (!leg) {
      toast("Could not read that prop.");
      return;
    }
    const s = state();
    if (s.legs.some(function (x) { return fpPart(x) === fpPart(leg); })) {
      toast("Already on the slip.");
      openDock();
      return;
    }
    if (s.legs.length >= MAX) {
      toast("PrizePicks max is 6 legs.");
      openDock();
      return;
    }
    s.legs.push(leg);
    s.min = false;
    save(s);
    openDock();
    render();
    hint();
  }

  function openDock() {
    const s = state();
    s.min = false;
    save(s);
    const dock = document.getElementById("my-slip-dock");
    if (dock) dock.classList.add("is-open");
  }

  function hint() {
    const s = state();
    if (s.legs.length < 2) return;
    fetch("/api/account/payout-hint", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ legs: s.legs, product: s.product, slate_date: slateDate() }),
    })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data) return;
        const note = document.getElementById("my-slip-hint");
        if (note) {
          note.textContent = (data.note || "Confirm N-correct on PrizePicks.") +
            (data.needs_confirm ? " Type the To Win line if this looks off." : "");
        }
        if (data.n_correct && Object.keys(data.n_correct).length) {
          const cur = state();
          cur.n_correct = data.n_correct;
          save(cur);
          fillNCorrectInputs(cur);
        }
      })
      .catch(function () {});
  }

  function place() {
    const s = state();
    if (s.legs.length < 2) {
      toast("Need at least 2 legs.");
      return;
    }
    const n_correct = readNCorrect();
    if (!Object.keys(n_correct).length) {
      toast("Enter N-correct / To Win from PrizePicks — not 1st place.");
      return;
    }
    const stakeEl = document.getElementById("my-slip-stake");
    const stakeRaw = stakeEl ? String(stakeEl.value || "").trim() : "";
    const body = {
      slate_date: slateDate(),
      product: s.product,
      legs: s.legs,
      n_correct: n_correct,
    };
    if (stakeRaw) body.stake = Number(stakeRaw);
    const btn = document.getElementById("my-slip-save");
    if (btn) btn.disabled = true;
    fetch("/api/account/custom-slip", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        if (res.status === 401) {
          window.location.href = "/account?next=" + encodeURIComponent("/");
          return null;
        }
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (pack) {
        if (!pack) return;
        if (!pack.ok) {
          toast((pack.data && pack.data.error) || "Could not save slip.");
          return;
        }
        toast("Saved to Account. Grades fill in after the slate.", true);
        const next = state();
        next.legs = [];
        next.n_correct = {};
        save(next);
        render();
      })
      .catch(function () { toast("Network error."); })
      .finally(function () { if (btn) btn.disabled = false; });
  }

  function onClick(ev) {
    const addBtn = ev.target.closest(".my-slip-add");
    if (addBtn) {
      ev.preventDefault();
      ev.stopPropagation();
      const host = addBtn.closest("[data-my-slip-leg]") || addBtn;
      add(decodeLeg(host.getAttribute("data-my-slip-leg") || addBtn.getAttribute("data-my-slip-leg") || ""));
      return;
    }
    const rm = ev.target.closest("#my-slip-legs .rm");
    if (rm) {
      const i = Number(rm.getAttribute("data-i"));
      const s = state();
      s.legs.splice(i, 1);
      save(s);
      render();
      hint();
    }
  }

  function bind() {
    const dock = document.getElementById("my-slip-dock");
    if (!dock) return;
    document.addEventListener("click", onClick, true);
    const hd = document.getElementById("my-slip-hd");
    if (hd) {
      hd.addEventListener("click", function () {
        const s = state();
        s.min = !s.min;
        save(s);
        render();
      });
    }
    const prod = document.getElementById("my-slip-product");
    if (prod) {
      prod.addEventListener("change", function () {
        const s = state();
        s.product = prod.value === "Flex" ? "Flex" : "Power";
        save(s);
        render();
        hint();
      });
    }
    const saveBtn = document.getElementById("my-slip-save");
    if (saveBtn) saveBtn.addEventListener("click", place);
    render();
  }

  root.MySlip = {
    encodeLeg: encodeLeg,
    pickToLeg: pickToLeg,
    addPick: function (p) { add(pickToLeg(p)); },
    render: render,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
})(window);
