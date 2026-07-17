#!/usr/bin/env python3
"""
WNBA postponed / canceled schedule helpers.

When a slate game is postponed, boxscores never arrive and legs grade as VOID + NO_ACTUAL.
Relabel those to POSTPONED (like MLB) so Grades/tickets show the real reason.

Uses ESPN scoreboard: site.api.espn.com/.../wnba/scoreboard?dates=YYYYMMDD
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
    "?dates={yyyymmdd}"
)

# ESPN abbreviations → PrizePicks / slate team codes used on props.
_ESPN_TO_SLATE: dict[str, str] = {
    "NY": "NYL",
    "NYL": "NYL",
    "DAL": "DAL",
    "CON": "CON",
    "CONN": "CON",
    "LV": "LVA",
    "LVA": "LVA",
    "LA": "LAS",
    "LAS": "LAS",
    "PHX": "PHO",
    "PHO": "PHO",
    "SEA": "SEA",
    "MIN": "MIN",
    "CHI": "CHI",
    "ATL": "ATL",
    "IND": "IND",
    "WAS": "WAS",
    "WSH": "WAS",
    "GSV": "GSV",
    "GS": "GSV",
    "PDX": "PDX",
    "POR": "PDX",
}


def _norm_team(raw: str) -> str:
    t = str(raw or "").strip().upper()
    if not t:
        return ""
    return _ESPN_TO_SLATE.get(t, t)


def _postponed_void_label_from_event(event: dict[str, Any]) -> str:
    status = (event.get("status") or {}).get("type") or {}
    detail = str(status.get("detail") or status.get("description") or "").strip()
    name = str(event.get("shortName") or event.get("name") or "").strip()
    parts = ["POSTPONED"]
    if name:
        parts.append(name)
    if detail and detail.lower() not in ("postponed", "canceled", "cancelled"):
        parts.append(detail[:48] + ("…" if len(detail) > 48 else ""))
    return " · ".join(parts)


def _team_abbrs_for_event(event: dict[str, Any]) -> set[str]:
    abbrs: set[str] = set()
    comps = ((event.get("competitions") or [None])[0] or {})
    for c in comps.get("competitors") or []:
        team = c.get("team") or {}
        for key in ("abbreviation", "shortDisplayName", "displayName"):
            v = team.get(key)
            if not v:
                continue
            # shortDisplayName may be full name — only keep short codes
            s = str(v).strip().upper()
            if key != "abbreviation" and len(s) > 4:
                continue
            n = _norm_team(s)
            if n:
                abbrs.add(n)
        ab = _norm_team(str(team.get("abbreviation") or ""))
        if ab:
            abbrs.add(ab)
    return abbrs


def _event_is_postponed_or_canceled(event: dict[str, Any]) -> bool:
    status = (event.get("status") or {}).get("type") or {}
    blob = " ".join(
        str(status.get(k) or "")
        for k in ("name", "state", "description", "detail", "completed")
    ).lower()
    if "postpon" in blob or "cancel" in blob:
        return True
    # ESPN sometimes uses name=STATUS_POSTPONED
    name = str(status.get("name") or "").upper()
    return "POSTPON" in name or "CANCEL" in name


def wnba_postponed_team_labels_for_date(iso_date: str) -> dict[str, str]:
    """
    Map slate team abbreviation → void_reason label for postponed/canceled games
    on ``iso_date`` (YYYY-MM-DD).
    """
    d = str(iso_date or "").strip()[:10]
    if len(d) < 10:
        return {}
    yyyymmdd = d.replace("-", "")
    try:
        import requests
    except ImportError:
        return {}
    try:
        r = requests.get(ESPN_SCOREBOARD.format(yyyymmdd=yyyymmdd), timeout=30)
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:
        print(f"  WARNING: WNBA scoreboard fetch failed for {d}: {exc}")
        return {}

    labels: dict[str, str] = {}
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        if not _event_is_postponed_or_canceled(event):
            continue
        label = _postponed_void_label_from_event(event)
        for ab in _team_abbrs_for_event(event):
            prev = labels.get(ab)
            if prev is None or (len(label) > len(prev)):
                labels[ab] = label
    return labels


def wnba_postponed_team_abbrs_for_date(iso_date: str) -> set[str]:
    return set(wnba_postponed_team_labels_for_date(iso_date).keys())


def _team_tokens(team_raw: str) -> set[str]:
    """Split combo/slash team fields into normalized abbreviations."""
    s = str(team_raw or "").strip().upper()
    if not s:
        return set()
    parts = []
    for chunk in s.replace("|", "/").replace(",", "/").split("/"):
        tok = chunk.strip()
        if not tok:
            continue
        # Drop long display names in rare full-name fields
        if len(tok) > 5 and " " in tok:
            continue
        parts.append(_norm_team(tok.split()[0] if " " in tok else tok))
    return {p for p in parts if p}


def apply_wnba_postponed_void_labels(graded: pd.DataFrame, iso_date: str) -> int:
    """
    Relabel VOID + NO_ACTUAL rows to POSTPONED when the row's team had a
    postponed/canceled game on ``iso_date``. Returns count patched.
    """
    team_labels = wnba_postponed_team_labels_for_date(iso_date)
    if not team_labels or graded is None or graded.empty:
        return 0

    # Prefer void_reason_grade (slate_grader), fall back to void_reason.
    vr_col = None
    for c in ("void_reason_grade", "void_reason", "Void Reason"):
        if c in graded.columns:
            vr_col = c
            break
    result_col = next((c for c in ("result", "Result", "RESULT") if c in graded.columns), None)
    if vr_col is None or result_col is None:
        return 0
    team_col = None
    for c in ("team", "Team", "TEAM"):
        if c in graded.columns:
            team_col = c
            break
    if team_col is None:
        return 0

    actual_col = next((c for c in ("actual", "Actual", "actual_value") if c in graded.columns), None)
    patched = 0
    for idx in graded.index:
        if str(graded.at[idx, result_col]).strip().upper() != "VOID":
            continue
        vr = str(graded.at[idx, vr_col] or "").strip().upper()
        if vr and not vr.startswith("NO_ACTUAL"):
            # Already labeled (DNP, PUSH, etc.) — leave alone
            if "POSTPON" in vr:
                continue
            if vr not in ("", "NO_ACTUAL", "MISSING_ACTUAL", "PENDING"):
                continue
        if actual_col is not None:
            act = graded.at[idx, actual_col]
            if act is not None and not (isinstance(act, float) and np.isnan(act)):
                try:
                    if str(act).strip() not in ("", "-", "--", "nan", "None"):
                        continue
                except Exception:
                    pass
        tokens = _team_tokens(str(graded.at[idx, team_col] or ""))
        hit = next((team_labels[t] for t in tokens if t in team_labels), None)
        if not hit:
            # Also check opp_team if present
            for oc in ("opp_team", "Opp", "opp", "opponent"):
                if oc in graded.columns:
                    tokens |= _team_tokens(str(graded.at[idx, oc] or ""))
            hit = next((team_labels[t] for t in tokens if t in team_labels), None)
        if hit:
            graded.at[idx, vr_col] = hit
            # Keep void_reason in sync when both columns exist
            if vr_col != "void_reason" and "void_reason" in graded.columns:
                graded.at[idx, "void_reason"] = hit
            if "Void Reason" in graded.columns and vr_col != "Void Reason":
                graded.at[idx, "Void Reason"] = hit
            patched += 1
    if patched:
        sample = next(iter(team_labels.values()), "POSTPONED")
        print(
            f"  [WNBA] Set postponed void_reason on {patched} leg(s) "
            f"({iso_date}; teams: {', '.join(sorted(team_labels))}; e.g. {sample!r})"
        )
    return patched


def relabel_void_reason_if_postponed(
    *,
    sport: str,
    team: str,
    opp_team: str = "",
    void_reason: str,
    result: str,
    iso_date: str,
    team_labels: dict[str, str] | None = None,
) -> str:
    """Lightweight per-row relabel for graded_props JSON export."""
    if str(sport or "").strip().upper() != "WNBA":
        return void_reason
    if str(result or "").strip().upper() != "VOID":
        return void_reason
    vr = str(void_reason or "").strip()
    vr_up = vr.upper()
    if vr_up.startswith("POSTPON"):
        return void_reason
    if vr_up and not vr_up.startswith("NO_ACTUAL") and vr_up not in ("", "MISSING_ACTUAL", "PENDING"):
        return void_reason
    labels = team_labels if team_labels is not None else wnba_postponed_team_labels_for_date(iso_date)
    if not labels:
        return void_reason
    tokens = _team_tokens(team) | _team_tokens(opp_team)
    for t in tokens:
        if t in labels:
            return labels[t]
    return void_reason
