"""Personal P&L for slips marked Placed. N-correct / To Win only — never 1st place."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

_VOID = {"void", "push", "no contest", "no_contest", "dnp"}
_HIT = {"hit", "win", "1", "true"}
_MISS = {"miss", "loss", "0", "false"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def fmt_line(x: Any) -> str:
    try:
        if x is None:
            return ""
        xf = float(x)
        if not math.isfinite(xf):
            return str(x)
        if abs(xf - round(xf)) < 1e-9:
            return str(int(round(xf)))
        return f"{xf:.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(x or "").strip()


def ticket_fingerprint(legs: Any) -> str:
    parts: list[str] = []
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        player = str(leg.get("player") or "").strip().lower()
        if not player:
            continue
        prop = str(leg.get("prop_type") or leg.get("prop") or "").strip().lower()
        line = fmt_line(leg.get("line"))
        direction = str(leg.get("direction") or leg.get("dir") or "").strip().upper()
        if direction == "LOWER":
            direction = "UNDER"
        parts.append(f"{player}|{prop}|{line}|{direction}")
    parts.sort()
    return ";".join(parts)


def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _dir(s: Any) -> str:
    u = str(s or "").strip().upper()
    if u == "LOWER":
        return "UNDER"
    return u


def _line_key(v: Any) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return fmt_line(v) or "0.00"


def product_from_group(group_name: str, ticket: dict[str, Any] | None = None) -> str:
    name = str(group_name or "").lower()
    t = ticket or {}
    if "flex" in name:
        return "Flex"
    if t.get("flex_payout") not in (None, "", 0, 0.0) and "power" not in name:
        if str(t.get("mode") or "").lower().find("flex") >= 0:
            return "Flex"
    return "Power"


def n_correct_table(ticket: dict[str, Any]) -> dict[int, float]:
    """N-correct multipliers only. Ignores 1st-place / sweep_payout."""
    pay = ticket.get("payout") if isinstance(ticket.get("payout"), dict) else {}
    raw = pay.get("n_correct") if isinstance(pay, dict) else None
    if not isinstance(raw, dict):
        raw = ticket.get("n_correct")
    out: dict[int, float] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                n = int(k)
                xf = float(v)
            except (TypeError, ValueError):
                continue
            if n > 0 and math.isfinite(xf) and xf > 0:
                out[n] = xf
    return out


def snapshot_from_ticket(
    ticket: dict[str, Any],
    *,
    group_name: str = "",
    stake: float = 20.0,
) -> dict[str, Any]:
    legs_in = ticket.get("legs") or []
    legs: list[dict[str, Any]] = []
    for leg in legs_in:
        if not isinstance(leg, dict):
            continue
        legs.append(
            {
                "sport": str(leg.get("sport") or ""),
                "player": str(leg.get("player") or ""),
                "prop_type": str(leg.get("prop_type") or leg.get("prop") or ""),
                "direction": _dir(leg.get("direction") or leg.get("dir")),
                "line": leg.get("line"),
                "pick_type": str(leg.get("pick_type") or ""),
            }
        )
    gname = str(group_name or ticket.get("web_group_name") or ticket.get("group_name") or "")
    table = n_correct_table(ticket)
    display = ticket.get("display_min_x")
    try:
        display_f = float(display) if display is not None else None
    except (TypeError, ValueError):
        display_f = None
    return {
        "group_name": gname,
        "product": product_from_group(gname, ticket),
        "n_legs": len(legs),
        "n_correct": {str(k): v for k, v in sorted(table.items())},
        "display_min_x": display_f,
        "power_payout": ticket.get("power_payout") or ticket.get("base_power_payout"),
        "flex_payout": ticket.get("flex_payout"),
        "stake": float(stake),
        "legs": legs,
        "fingerprint": ticket_fingerprint(legs),
    }


_PAYOUT_SKIP = {"first_place", "sweep_payout", "sweep", "1st", "first", "firstplace"}


def parse_n_correct(raw: Any) -> dict[int, float]:
    """N-correct / To Win only. Drops 1st-place and sweep keys."""
    if isinstance(raw, dict) and isinstance(raw.get("n_correct"), dict):
        raw = raw.get("n_correct")
    out: dict[int, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        key = str(k).strip().lower().replace(" ", "_")
        if key in _PAYOUT_SKIP or "first" in key or "sweep" in key or "place" in key:
            continue
        try:
            n = int(k)
            xf = float(v)
        except (TypeError, ValueError):
            continue
        if n > 0 and math.isfinite(xf) and xf > 0:
            out[n] = xf
    return out


def snapshot_from_custom(
    legs: list[dict[str, Any]],
    *,
    product: str = "Power",
    n_correct: Any = None,
    stake: float = 20.0,
    group_name: str = "My slip",
) -> dict[str, Any]:
    prod = "Flex" if "flex" in str(product or "").lower() else "Power"
    table = parse_n_correct(n_correct)
    n_legs = sum(1 for x in legs if isinstance(x, dict) and str(x.get("player") or "").strip())
    ticket = {
        "web_group_name": f"{group_name} {prod}",
        "payout": {"n_correct": {str(k): v for k, v in sorted(table.items())}},
        "legs": legs,
        "display_min_x": table.get(n_legs),
        "flex_payout": table.get(n_legs) if prod == "Flex" else None,
        "power_payout": table.get(n_legs) if prod == "Power" else None,
    }
    snap = snapshot_from_ticket(ticket, group_name=f"{group_name} {prod}", stake=stake)
    snap["product"] = prod
    return snap


def family_from_legs(legs: list[dict[str, Any]]) -> str:
    n_g = 0
    n_s = 0
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        pick = str(leg.get("pick_type") or leg.get("pick") or "").strip().lower()
        if "gob" in pick:
            n_g += 1
        else:
            n_s += 1
    if n_g and n_s:
        return "mix"
    if n_g:
        return "goblin"
    return "standard"


def legs_from_fingerprint(fp: str) -> list[dict[str, Any]]:
    legs: list[dict[str, Any]] = []
    for part in str(fp or "").split(";"):
        bits = part.split("|")
        if len(bits) != 4:
            continue
        player, prop, line, direction = bits
        legs.append(
            {
                "player": player,
                "prop_type": prop,
                "line": line,
                "direction": direction,
            }
        )
    return legs


def _tickets_paths(root: Path) -> list[Path]:
    ui = root / "ui_runner"
    return [
        ui / "runtime" / "tickets_latest.json",
        ui / "templates" / "tickets_latest.json",
        ui / "data" / "tickets_latest.json",
        root / "tickets_latest.json",
    ]


def find_ticket(fingerprint: str, *, root: Path | None = None) -> tuple[dict[str, Any], str] | None:
    fp = str(fingerprint or "").strip()
    if not fp:
        return None
    base = root or _repo_root()
    for path in _tickets_paths(base):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for group in data.get("groups") or []:
            if not isinstance(group, dict):
                continue
            gname = str(group.get("group_name") or "")
            for ticket in group.get("tickets") or []:
                if not isinstance(ticket, dict):
                    continue
                if ticket_fingerprint(ticket.get("legs") or []) == fp:
                    return ticket, gname
    return None


def _graded_paths(root: Path, date: str) -> list[Path]:
    ui = root / "ui_runner"
    name = f"graded_props_{date}.json"
    return [
        ui / "templates" / name,
        root / "mobile" / "www" / name,
        ui / "runtime" / name,
    ]


@lru_cache(maxsize=16)
def _load_grade_index(path_str: str, mtime: float) -> dict[tuple[str, str, str, str], str]:
    _ = mtime
    path = Path(path_str)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = data.get("props") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[tuple[str, str, str, str], str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (
            _norm(row.get("player")),
            _norm(row.get("prop") or row.get("prop_type")),
            _line_key(row.get("line")),
            _dir(row.get("direction") or row.get("over_under")),
        )
        grade = _row_grade(row)
        if grade and key not in out:
            out[key] = grade
        if grade:
            out[key] = grade
    return out


def _row_grade(row: dict[str, Any]) -> str:
    raw = str(row.get("result") or row.get("grade") or "").strip().lower()
    if raw in _VOID:
        return "VOID"
    if raw in _HIT:
        return "HIT"
    if raw in _MISS:
        return "MISS"
    note = str(row.get("void_reason") or "").strip()
    if note and not str(row.get("actual_value") or "").strip():
        return "VOID"
    actual = row.get("actual_value")
    line = row.get("line")
    direction = _dir(row.get("direction") or row.get("over_under"))
    try:
        act_f = float(actual)
        line_f = float(line)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(act_f) or not math.isfinite(line_f):
        return ""
    if abs(act_f - line_f) < 1e-9:
        return "VOID"
    if direction == "OVER":
        return "HIT" if act_f > line_f else "MISS"
    if direction == "UNDER":
        return "HIT" if act_f < line_f else "MISS"
    return ""


def load_grades(date: str, *, root: Path | None = None) -> dict[tuple[str, str, str, str], str]:
    day = str(date or "").strip()[:10]
    if not day:
        return {}
    base = root or _repo_root()
    for path in _graded_paths(base, day):
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        idx = _load_grade_index(str(path.resolve()), mtime)
        if idx:
            return idx
    return {}


def _lookup_leg_grade(leg: dict[str, Any], grades: dict[tuple[str, str, str, str], str]) -> str:
    key = (
        _norm(leg.get("player")),
        _norm(leg.get("prop_type") or leg.get("prop")),
        _line_key(leg.get("line")),
        _dir(leg.get("direction") or leg.get("dir")),
    )
    return grades.get(key) or ""


def _mult_from_table(table: dict[int, float], n: int, fallback: float | None) -> float:
    if n in table:
        return float(table[n])
    if fallback is not None and math.isfinite(fallback) and fallback > 0:
        return float(fallback)
    return 0.0


def _has_payout_ladder(snap: dict[str, Any]) -> bool:
    raw = snap.get("n_correct")
    if isinstance(raw, dict) and raw:
        return True
    for key in ("display_min_x", "power_payout", "flex_payout"):
        try:
            xf = float(snap.get(key)) if snap.get(key) is not None else 0.0
        except (TypeError, ValueError):
            continue
        if math.isfinite(xf) and xf > 0:
            return True
    return False


def payout_text(table: dict[int, float], product: str, n_legs: int) -> str:
    """Human N-correct / To Win quote. Empty if we never stored a ladder."""
    if not table:
        return ""
    if str(product).lower() == "flex":
        parts = [f"{k} correct {table[k]:g}x" for k in sorted(table, reverse=True)]
        return " / ".join(parts)
    n = n_legs if n_legs in table else max(table)
    return f"{n} correct {table[n]:g}x"


def _leg_caption(leg: dict[str, Any]) -> str:
    player = str(leg.get("player") or "").strip()
    direction = _dir(leg.get("direction") or leg.get("dir"))
    line = fmt_line(leg.get("line"))
    prop = str(leg.get("prop_type") or leg.get("prop") or "").strip()
    bits = [b for b in (player, direction, line, prop) if b]
    return " ".join(bits)


def settle_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    fingerprint: str,
    slate_date: str,
    stake: float | None,
    grades: dict[tuple[str, str, str, str], str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    try:
        stake_f = float(stake if stake is not None else (snapshot or {}).get("stake") or 20)
    except (TypeError, ValueError):
        stake_f = 20.0
    if not math.isfinite(stake_f) or stake_f < 0:
        stake_f = 20.0
    snap = dict(snapshot or {})
    if not _has_payout_ladder(snap):
        found = find_ticket(fingerprint, root=root)
        if found:
            ticket, gname = found
            snap = snapshot_from_ticket(ticket, group_name=gname, stake=stake_f)
    legs = snap.get("legs") if isinstance(snap.get("legs"), list) else None
    if not legs:
        legs = legs_from_fingerprint(fingerprint)
    product = str(snap.get("product") or product_from_group(str(snap.get("group_name") or "")))
    table: dict[int, float] = {}
    raw_table = snap.get("n_correct")
    if isinstance(raw_table, dict):
        for k, v in raw_table.items():
            try:
                table[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
    try:
        fallback = float(snap.get("display_min_x")) if snap.get("display_min_x") is not None else None
    except (TypeError, ValueError):
        fallback = None
    if fallback is None:
        try:
            fallback = float(snap.get("power_payout")) if product != "Flex" else float(snap.get("flex_payout"))
        except (TypeError, ValueError):
            fallback = None

    grade_map = grades if grades is not None else load_grades(slate_date, root=root)
    marks: list[str] = []
    pending = False
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        g = _lookup_leg_grade(leg, grade_map)
        if not g:
            pending = True
            marks.append("PENDING")
        else:
            marks.append(g)

    group = str(snap.get("group_name") or "")
    captions = [
        _leg_caption(leg)
        for leg in legs
        if isinstance(leg, dict) and str(leg.get("player") or "").strip()
    ]
    label = group or "Placed slip"
    if captions:
        label = f"{label} — {'; '.join(captions[:3])}"
        if len(captions) > 3:
            label += f" +{len(captions) - 3}"

    n_legs_n = len(marks) or int(snap.get("n_legs") or 0) or len(captions)
    quoted = None
    if n_legs_n in table:
        quoted = float(table[n_legs_n])
    elif fallback is not None and math.isfinite(fallback) and fallback > 0:
        quoted = float(fallback)
    base = {
        "slate_date": slate_date,
        "fingerprint": fingerprint,
        "group_name": group,
        "label": label,
        "product": product,
        "stake": round(stake_f, 2),
        "n_legs": n_legs_n,
        "legs": marks,
        "n_correct": {str(k): v for k, v in sorted(table.items())},
        "payout_text": payout_text(table, product, n_legs_n),
        "quoted_x": quoted,
    }
    if not marks:
        return {**base, "status": "pending", "result": "PENDING", "multiplier": None, "returned": None, "net": None}
    if pending:
        return {**base, "status": "pending", "result": "PENDING", "multiplier": None, "returned": None, "net": None}
    if not table and not (fallback is not None and math.isfinite(fallback) and fallback > 0):
        return {**base, "status": "pending", "result": "PENDING", "multiplier": None, "returned": None, "net": None}

    hits = sum(1 for g in marks if g == "HIT")
    misses = sum(1 for g in marks if g == "MISS")
    voids = sum(1 for g in marks if g == "VOID")
    playable = hits + misses
    if playable == 0:
        return {
            **base,
            "status": "void",
            "result": "REFUND",
            "multiplier": 1.0,
            "returned": round(stake_f, 2),
            "net": 0.0,
        }
    if playable == 1 and voids:
        return {
            **base,
            "status": "void",
            "result": "REFUND",
            "multiplier": 1.0,
            "returned": round(stake_f, 2),
            "net": 0.0,
        }

    if product == "Flex":
        mult = float(table.get(hits) or 0.0)
        if misses == 0 and playable == len(marks) and mult <= 0 and fallback:
            mult = float(fallback)
        if misses == 0:
            result = "WIN" if mult > 0 else "LOSS"
        else:
            result = "CASH" if mult > 0 else "LOSS"
    else:
        if misses:
            mult = 0.0
            result = "LOSS"
        else:
            mult = _mult_from_table(table, playable, fallback)
            result = "WIN" if mult > 0 else "LOSS"

    returned = round(stake_f * mult, 2)
    net = round(returned - stake_f, 2)
    status = "win" if net > 0 else ("loss" if net < 0 else "even")
    if result == "LOSS":
        status = "loss"
    elif result in ("WIN", "CASH") and net >= 0:
        status = "win" if net > 0 else "even"
    return {
        **base,
        "status": status,
        "result": result,
        "multiplier": round(mult, 4) if mult else 0.0,
        "returned": returned,
        "net": net,
        "hits": hits,
        "misses": misses,
        "voids": voids,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pending = [r for r in rows if r.get("status") == "pending"]
    risk = [r for r in rows if r.get("status") in ("win", "loss", "even")]
    voids = [r for r in rows if r.get("status") == "void"]
    at_risk = sum(float(r.get("stake") or 0) for r in risk)
    pending_stake = sum(float(r.get("stake") or 0) for r in pending)
    returned = sum(float(r.get("returned") or 0) for r in risk)
    net = sum(float(r.get("net") or 0) for r in risk)
    wins = sum(1 for r in risk if r.get("result") == "WIN")
    cash = sum(1 for r in risk if r.get("result") == "CASH")
    losses = sum(1 for r in risk if r.get("result") == "LOSS")
    roi = (net / at_risk * 100.0) if at_risk > 0 else None
    return {
        "placed": len(rows),
        "pending": len(pending),
        "decided": len(risk),
        "wins": wins,
        "cash": cash,
        "losses": losses,
        "refunds": len(voids),
        "staked": round(at_risk + pending_stake, 2),
        "staked_pending": round(pending_stake, 2),
        "returned": round(returned, 2),
        "net": round(net, 2),
        "roi_pct": round(roi, 1) if roi is not None else None,
        "rows": rows,
    }
