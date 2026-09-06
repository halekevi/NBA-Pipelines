"""CFB prop-aware defense/unit axis (pass, rush, TDs, kick, INT, sacks, tackles).

Rank 1 on *allowed* / sacks-taken / plays / INTs-forced = fewest (harder overs).
Rank 1 on defense *production* (sacks/tackles/TFL for) = most — those are
context columns, not OVERALL_DEF_RANK for player props.

Sack props use the opponent's sacks-taken (OL) rank. Tackle/TFL props use
opponent offensive plays (volume).
"""

from __future__ import annotations

import re

AXIS_RANK_KEYS: dict[str, tuple[str, str, str]] = {
    # (rank_nat, tier_nat, avg_col) on the normalized rankings payload
    "pass": ("pass_def_rank_nat", "pass_def_tier_nat", "pass_def_yds_pg"),
    "rush": ("rush_def_rank_nat", "rush_def_tier_nat", "rush_def_yds_pg"),
    "pass_td": ("pass_td_def_rank_nat", "pass_td_def_tier_nat", "pass_td_def_pg"),
    "rush_td": ("rush_td_def_rank_nat", "rush_td_def_tier_nat", "rush_td_def_pg"),
    "rec_td": ("rec_td_def_rank_nat", "rec_td_def_tier_nat", "rec_td_def_pg"),
    "td": ("td_def_rank_nat", "td_def_tier_nat", "td_def_pg"),
    "fg": ("fg_def_rank_nat", "fg_def_tier_nat", "fg_def_pg"),
    "pat": ("pat_def_rank_nat", "pat_def_tier_nat", "pat_def_pg"),
    "kick": ("kick_pts_def_rank_nat", "kick_pts_def_tier_nat", "kick_pts_def_pg"),
    "int": ("int_def_rank_nat", "int_def_tier_nat", "int_def_pg"),
    "sack": ("sacks_taken_rank_nat", "sacks_taken_tier_nat", "sacks_taken_pg"),
    "tfl": ("sacks_taken_rank_nat", "sacks_taken_tier_nat", "sacks_taken_pg"),
    "tackle": ("plays_off_rank_nat", "plays_off_tier_nat", "plays_off_pg"),
    "points": ("overall_def_rank_nat", "overall_def_tier_nat", "total_def_yds_pg"),
}


def _norm_prop(raw: object) -> str:
    s = str(raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def prop_def_axis(prop: object) -> str:
    """Unit used for OVERALL_DEF_RANK / def_tier on this CFB prop."""
    p = _norm_prop(prop)
    if p in ("fg_made", "field_goals", "field_goals_made", "fg") or "field_goal" in p:
        return "fg"
    if p in ("pat_made", "extra_points", "xp_made", "pat", "xp") or (
        "pat" in p and "made" in p
    ):
        return "pat"
    if "kick" in p:
        return "kick"
    if p in ("int", "interceptions", "interception", "interceptions_thrown") or (
        "interception" in p
    ):
        return "int"
    if "sack" in p:
        return "sack"
    if "tfl" in p or "tackles_for_loss" in p or "tackle_for_loss" in p:
        return "tfl"
    if "tackle" in p:
        return "tackle"
    # Combo yard props: one honest points-D axis, not pass-only or rush-only.
    if p in ("pass_rush_yds", "rush_rec_yds") or (
        "pass" in p and "rush" in p and "yd" in p
    ) or (
        "rush" in p and "rec" in p and "yd" in p
    ):
        return "points"
    # All-purpose TDs must beat the generic "pass"+"td" → pass_td branch.
    if p in (
        "player_td",
        "player_touchdowns",
        "touchdowns",
        "tds",
        "pass_rush_rec_td",
        "pass_rush_rec_tds",
    ) or ("pass" in p and "rush" in p and "rec" in p and "td" in p) or (
        "player" in p and "td" in p
    ):
        return "td"
    if ("pass" in p or p == "passing_tds") and "td" in p:
        return "pass_td"
    if ("rush" in p or p == "rushing_tds") and "td" in p:
        return "rush_td"
    if ("rec" in p or "receiv" in p) and "td" in p:
        return "rec_td"
    if p in ("pass_long", "longest_completion") or (
        "longest" in p and "completion" in p
    ):
        return "pass"
    if p in ("rush_long", "longest_rush") or ("longest" in p and "rush" in p):
        return "rush"
    if p in ("rec_long", "longest_reception", "longest_rec") or (
        "longest" in p and ("rec" in p or "reception" in p)
    ):
        return "pass"
    if p in ("rec_tgt", "rec_targets", "targets") or "target" in p:
        return "pass"
    if "pass" in p or p in ("pass_yds", "pass_cmp", "pass_att", "completions") or "completion" in p:
        return "pass"
    if "rush" in p or p in ("rush_yds", "rush_att", "carries"):
        return "rush"
    if "rec" in p or "receiv" in p or p in ("rec", "receptions"):
        return "pass"
    return "points"


def prop_def_keys(prop: object) -> tuple[str, str, str]:
    """Return (rank_col, tier_col, avg_col) on the normalized rankings payload."""
    axis = prop_def_axis(prop)
    return AXIS_RANK_KEYS.get(axis, AXIS_RANK_KEYS["points"])
