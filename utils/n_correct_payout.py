"""Resolve PrizePicks N-correct / To Win multipliers from live scrapes.

Never use 1st-place. Goblin distance moves the rate, so a composition-only
median (the old 2.9x) is not a live quote.

Lookup order:
  1. Live CDP scrape with matching composition + Goblin-Δ (prefer slate date)
  2. mix_by_delta cell built from those scrapes
  3. Dated slip pin (emergency only)
  4. Hardcoded last-known fallback
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_LATEST = ROOT / "data" / "reports" / "payout_overrides_latest.json"
LIVE_CDP = ROOT / "ui_runner" / "data" / "payout_ladder_live_cdp.json"
MIX_TABLES = ROOT / "data" / "reports" / "predicted_payout_tables_latest.json"

# Last-resort tables. Goblin Power/Flex pins are the 2026-08-27 live slips.
PAY_FALLBACK: dict[tuple[str, int, str], dict[str, Any]] = {
    ("goblin", 3, "Power"): {
        "n_correct": {3: 2.0},
        "note": "0S+3G Power fallback 2x",
    },
    ("goblin", 2, "Power"): {
        "n_correct": {2: 2.2},
        "note": "0S+2G Power fallback 2.2x — confirm on the slip",
    },
    ("goblin", 3, "Flex"): {
        "n_correct": {3: 1.7, 2: 0.5},
        "note": "0S+3G Flex fallback 1.7x / 0.5x",
    },
    ("goblin", 4, "Power"): {
        "n_correct": {4: 2.4},
        "note": "0S+4G Power fallback 2.4x",
    },
    ("goblin", 4, "Flex"): {
        "n_correct": {4: 1.9, 3: 0.5},
        "note": "0S+4G Flex fallback 1.9x / 0.5x",
    },
    ("mix", 4, "Flex"): {
        "n_correct": {4: 3.0, 3: 0.75},
        "note": "1S+3G Flex fallback 3x / 0.75x",
    },
    ("standard", 3, "Flex"): {
        "n_correct": {3: 2.25, 2: 1.25},
        "note": "3S Flex canonical 2.25x / 1.25x",
    },
    ("nflp", 3, "Power"): {
        "n_correct": {3: 2.0},
        "note": "NFLP Goblin Power fallback 2x",
    },
    ("nflp", 2, "Power"): {
        "n_correct": {2: 2.2},
        "note": "NFLP Goblin Power 2 fallback 2.2x",
    },
    ("nflp_std", 3, "Power"): {
        "n_correct": {3: 6.0},
        "note": "3S Power canonical 6x",
    },
    ("nflp_std", 2, "Power"): {
        "n_correct": {2: 3.0},
        "note": "2S Power canonical 3x",
    },
}


def _f(raw: object) -> float | None:
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def pick_type_norm(raw: object) -> str:
    s = str(raw or "").strip().lower()
    if "gob" in s:
        return "Goblin"
    if "std" in s or s == "standard":
        return "Standard"
    return str(raw or "").strip() or "Unknown"


def composition_from_legs(legs: list[dict]) -> tuple[int, int, int]:
    n_g = sum(1 for x in legs if pick_type_norm(x.get("pick_type")) == "Goblin")
    n_s = sum(1 for x in legs if pick_type_norm(x.get("pick_type")) == "Standard")
    n = len(legs)
    if n_s + n_g < n:
        n_g = n - n_s
    return n_s, n_g, n


def goblin_delta_sig(legs: list[dict]) -> str:
    parts: list[float] = []
    for x in legs:
        if pick_type_norm(x.get("pick_type")) != "Goblin":
            continue
        line = _f(x.get("line"))
        std = _f(x.get("standard_line"))
        if line is None or std is None:
            continue
        d = abs(std - line)
        if d >= 0.25:
            parts.append(d)
    if not parts:
        return ""
    return "+".join(f"{v:g}" for v in sorted(parts))


def _norm_delta_sig(raw: object) -> str:
    if isinstance(raw, (list, tuple)):
        vals: list[float] = []
        for part in raw:
            v = _f(part)
            if v is not None:
                vals.append(v)
        return "+".join(f"{v:g}" for v in sorted(vals))
    text = str(raw or "").strip()
    if not text or text in {"—", "-", "unknown"}:
        return ""
    vals = []
    for part in text.replace("|", "+").replace(",", "+").split("+"):
        v = _f(part)
        if v is not None:
            vals.append(v)
    return "+".join(f"{v:g}" for v in sorted(vals))


def _int_ladder(raw: object) -> dict[int, float]:
    out: dict[int, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            hits = int(k)
        except (TypeError, ValueError):
            continue
        fx = _f(v)
        if fx is not None:
            out[hits] = fx
    return out


def _result(
    table: dict[int, float],
    *,
    note: str,
    source: str,
    captured_at: str | None = None,
) -> dict[str, Any]:
    out = {
        "n_correct": {int(k): float(v) for k, v in table.items()},
        "note": note,
        "payout_source": source,
    }
    if captured_at:
        out["captured_at"] = str(captured_at)
    return out


def fallback_pay(family: str, n_legs: int, product: str) -> dict[str, Any]:
    pay = PAY_FALLBACK.get((family, n_legs, product))
    if pay is None:
        pay = PAY_FALLBACK.get(("goblin", n_legs, product))
    if pay is None:
        return _result({n_legs: 2.0}, note="missing payout table — confirm on the slip", source="n_correct_median")
    return _result(pay["n_correct"], note=str(pay["note"]), source="n_correct_median")


def load_overrides(date: str, *, repo: Path | None = None) -> list[dict[str, Any]]:
    root = repo or ROOT
    dated = root / "data" / "reports" / f"payout_overrides_{date}.json"
    latest = root / "data" / "reports" / "payout_overrides_latest.json"
    payload = _load_json(dated) or _load_json(latest)
    if str(payload.get("date") or "")[:10] != str(date or "")[:10]:
        return []
    entries = payload.get("entries") or []
    return [e for e in entries if isinstance(e, dict)]


def _match_entry(entry: dict[str, Any], n_s: int, n_g: int, n_legs: int, product: str) -> bool:
    if int(entry.get("n_legs") or 0) != n_legs:
        return False
    if str(entry.get("product") or "").strip().lower() != product.lower():
        return False
    if "n_s" in entry and int(entry.get("n_s") or 0) != n_s:
        return False
    if "n_g" in entry and int(entry.get("n_g") or 0) != n_g:
        return False
    return True


def lookup_override(
    date: str,
    n_s: int,
    n_g: int,
    n_legs: int,
    product: str,
    *,
    repo: Path | None = None,
) -> dict[str, Any] | None:
    for entry in load_overrides(date, repo=repo):
        if not _match_entry(entry, n_s, n_g, n_legs, product):
            continue
        table = _int_ladder(entry.get("n_correct"))
        if not table:
            continue
        return _result(
            table,
            note=str(entry.get("note") or f"slip pin {date} N-correct / To Win"),
            source="n_correct_live",
        )
    return None


def lookup_live_cdp_scrape(
    date: str,
    n_s: int,
    n_g: int,
    n_legs: int,
    product: str,
    delta_sig: str,
    *,
    repo: Path | None = None,
) -> dict[str, Any] | None:
    """N-correct from PrizePicks CDP scrapes (payout_ladder_live_cdp.json)."""
    if not delta_sig:
        return None
    root = repo or ROOT
    payload = _load_json(root / "ui_runner" / "data" / "payout_ladder_live_cdp.json")
    hits: list[dict[str, Any]] = []
    want = f"{n_s}S+{n_g}G"
    for rec in payload.get("rows") or []:
        if not isinstance(rec, dict):
            continue
        src = str(rec.get("source") or "").strip().lower()
        if src and src not in {"live_cdp", "cdp", "live", "ok"}:
            continue
        try:
            rec_n = int(float(rec.get("n_legs") or 0))
        except (TypeError, ValueError):
            continue
        if rec_n != n_legs:
            continue
        comp = str(rec.get("leg_composition") or rec.get("composition") or "").upper().replace(" ", "")
        if want not in comp:
            continue
        rec_sig = _norm_delta_sig(rec.get("goblin_deltas") or rec.get("goblin_delta_sig"))
        if rec_sig != delta_sig:
            continue
        hits.append(rec)
    if not hits:
        return None
    date_s = str(date or "")[:10]
    hits.sort(
        key=lambda r: (
            1 if str(r.get("date") or "")[:10] == date_s else 0,
            str(r.get("last_captured_at") or r.get("captured_at") or ""),
            str(r.get("date") or ""),
            str(r.get("ticket_id") or ""),
        )
    )
    rec = hits[-1]
    rec_date = str(rec.get("date") or "")[:10]
    captured_at = str(rec.get("last_captured_at") or rec.get("captured_at") or "").strip() or None
    if product.lower() == "flex":
        table = _int_ladder(rec.get("flex_n_correct"))
        if not table:
            return None
        return _result(
            table,
            note=f"CDP scrape Flex {want} Δ={delta_sig} ({rec_date})",
            source="n_correct_live",
            captured_at=captured_at,
        )
    power = _f(rec.get("power_payout_x") or rec.get("power_min_x"))
    if power is None:
        return None
    return _result(
        {n_legs: power},
        note=f"CDP scrape Power {want} Δ={delta_sig} ({rec_date})",
        source="n_correct_live",
        captured_at=captured_at,
    )


lookup_live_cdp_today = lookup_live_cdp_scrape


def lookup_mix_by_delta(
    n_s: int,
    n_g: int,
    n_legs: int,
    product: str,
    delta_sig: str,
    *,
    repo: Path | None = None,
) -> dict[str, Any] | None:
    if not delta_sig:
        return None
    root = repo or ROOT
    payload = _load_json(root / "data" / "reports" / "predicted_payout_tables_latest.json")
    want = f"{n_s}S+{n_g}G"
    for rec in payload.get("mix_by_delta") or []:
        if not isinstance(rec, dict):
            continue
        if int(rec.get("n_legs") or 0) != n_legs:
            continue
        if str(rec.get("composition") or "") != want:
            continue
        if _norm_delta_sig(rec.get("goblin_delta_sig")) != delta_sig:
            continue
        if product.lower() == "flex":
            table = _int_ladder(rec.get("flex_ladder"))
            if not table:
                return None
            return _result(
                table,
                note=f"mix_by_delta Flex {want} Δ={delta_sig}",
                source="n_correct_delta",
            )
        power = _f(rec.get("power_x"))
        if power is None:
            continue
        return _result(
            {n_legs: power},
            note=f"mix_by_delta Power {want} Δ={delta_sig}",
            source="n_correct_delta",
        )
    return None


def resolve_n_correct(
    legs: list[dict],
    product: str,
    family: str,
    *,
    date: str = "",
    repo: Path | None = None,
) -> dict[str, Any]:
    n_s, n_g, n_legs = composition_from_legs(legs)
    if n_legs <= 0:
        n_legs = len(legs)
    delta_sig = goblin_delta_sig(legs)
    found = lookup_live_cdp_scrape(
        date, n_s, n_g, n_legs, product, delta_sig, repo=repo
    )
    if found:
        return found
    found = lookup_mix_by_delta(n_s, n_g, n_legs, product, delta_sig, repo=repo)
    if found:
        return found
    found = lookup_override(date, n_s, n_g, n_legs, product, repo=repo)
    if found:
        return found
    return fallback_pay(family, n_legs, product)
