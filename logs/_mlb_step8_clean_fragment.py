def _prepare_clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df2 = df.copy()
    df2 = df2.where(pd.notna(df2), None)
    if "minutes_tier" in df2.columns:
        _mt_num = pd.to_numeric(df2["minutes_tier"], errors="coerce")
        _mt_valid = _mt_num.notna()
        if _mt_valid.any():
            df2.loc[_mt_valid, "minutes_tier"] = (
                _mt_num[_mt_valid].round().astype(int).map(_MIN_TIER_NUM_MAP).fillna(
                    df2.loc[_mt_valid, "minutes_tier"]
                )
            )
    df2["game_time"] = pd.to_datetime(df2.get("start_time", ""), errors="coerce").dt.strftime("%-I:%M %p")
    _gd = _row_game_datetimes(df2)
    df2["slate_game_date"] = _gd.dt.strftime("%Y-%m-%d").where(_gd.notna(), "").fillna("")

    if "line" in df2.columns:
        df2 = finalize_l10_ui_columns(df2, line_col="line")
    df2 = attach_hit_tracking_columns(df2, "MLB")

    keep = [
        "tier", "rank_score",
        "player", "pos", "player_type_norm", "team", "opp_team", "days_rest", "is_back_to_back", "opp_days_rest", "opp_b2b",
        "h2h_avg", "h2h_over_pct", "h2h_games", "h2h_last",
        "game_total", "spread", "game_time", "slate_game_date",
        "prop_type", "pick_type", "line",
        "final_bet_direction",
        "edge", "projection",
        "ml_prob",
        "hit_rate", "hit_rate_l5", "hit_rate_l10",
        "strat_hit_rate", "strat_n",
        "player_hr_historical", "opp_hr_historical",
        "sport_signal_maturity", "confidence_tier", "confidence_score", "confidence_note",
        "edge_score",
        "blended_score",
        "line_hit_rate_over_ou_5",
        "hit_rate_status", "reliability_note",
        "stat_last5_avg", "stat_season_avg",
        "last5_over", "last5_under",
        "l10_over", "l10_under", "l10_over_pct", "l10_streak", "l10_games_played",
        "OVERALL_DEF_RANK", "DEF_TIER",
        "HITS_ALLOWED_RANK", "RUNS_ALLOWED_RANK", "HR_ALLOWED_RANK",
        "HITS_PER_GAME", "RUNS_PER_GAME",
        "minutes_tier", "batting_order_tier", "pitcher_role",
        "lineup_confirmed", "batting_order_pos",
        "opp_starter_name", "opp_starter_hand",
        "opp_starter_era", "opp_starter_whip",
        "opp_closer_name", "opp_closer_hand", "opp_closer_era", "opp_closer_saves",
        "opp_sp1_name", "opp_sp1_hand", "opp_sp2_name", "opp_sp2_hand",
        "opp_sp3_name", "opp_sp3_hand",
        "opp_staff_lhp", "opp_staff_rhp",
        "opp_pitcher_era_vs_batter_hand", "opp_pitcher_whip_vs_batter_hand",
        "park_factor_hr", "park_hr_rank", "park_hr_tier", "park_tier",
        "top_of_order", "bottom_of_order", "line_moved_up", "line_moved_down",
        "player_on_il", "injury_status", "injury_type", "days_since_injury_report",
        "pitcher_scratched", "opp_starter_on_il",
        "elite_starter_fade", "context_proj_adj", "context_hr_prior", "prop_def_rank_used",
        "same_series_hit_rate",
        "void_reason",
        "open_line",
        "line_movement",
        "line_direction_shift",
        "implied_prob",
        "implied_prob_over",
        "implied_prob_under",
        "consistency_grade",
        "team_top3_rank",
        "team_bottom3_rank",
        "def_boost_hist",
        "top3_weak_overperformer",
        "top3_elite_fader",
    ]
    keep = [c for c in keep if c in df2.columns]
    stat_g_cols = sorted(
        (c for c in df2.columns if c.startswith("stat_g") and c[6:].isdigit()),
        key=lambda c: int(c[6:]),
    )
    for c in stat_g_cols:
        if c not in keep:
            keep.append(c)
    for c in ("distribution_std", "distribution_n"):
        if c in df2.columns and c not in keep:
            keep.append(c)
    clean = df2[keep].copy()

    for col in [
        "rank_score", "edge", "abs_edge", "projection", "ml_prob", "edge_score", "blended_score",
        "line_hit_rate_over_ou_5", "same_series_hit_rate", "open_line", "line_movement",
        "implied_prob", "implied_prob_over", "implied_prob_under",
    ]:
        if col in clean.columns:
            if col in ("implied_prob", "implied_prob_over", "implied_prob_under"):
                rnd = 4
            else:
                rnd = 4 if col in ("ml_prob", "edge_score", "blended_score") else (3 if col == "line_movement" else 2)
            clean[col] = pd.to_numeric(clean[col], errors="coerce").round(rnd)
    if "line_direction_shift" in clean.columns:
        clean["line_direction_shift"] = (
            clean["line_direction_shift"].astype(str).str.strip().replace({"nan": "", "None": ""})
        )
        clean.loc[clean["line_direction_shift"].eq(""), "line_direction_shift"] = "stable"
    for col in ["stat_last5_avg", "stat_season_avg"]:
        if col in clean.columns:
            clean[col] = pd.to_numeric(clean[col], errors="coerce").round(1)
    for col in ["last5_over", "last5_under"]:
        if col in clean.columns:
            clean[col] = pd.to_numeric(clean[col], errors="coerce").astype("Int64")
    if "batting_order_pos" in clean.columns:
        clean["batting_order_pos"] = pd.to_numeric(clean["batting_order_pos"], errors="coerce").astype("Int64")
    for col in ("opp_pitcher_era_vs_batter_hand", "opp_pitcher_whip_vs_batter_hand"):
        if col in clean.columns:
            clean[col] = pd.to_numeric(clean[col], errors="coerce").round(2)
    if "distribution_std" in clean.columns:
        clean["distribution_std"] = pd.to_numeric(clean["distribution_std"], errors="coerce").round(4)
    if "distribution_n" in clean.columns:
        clean["distribution_n"] = pd.to_numeric(clean["distribution_n"], errors="coerce").astype("Int64")

    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    clean["_tier_sort"] = clean["tier"].map(tier_order)
    clean = clean.sort_values(["_tier_sort", "rank_score"], ascending=[True, False]).drop(columns="_tier_sort")

    rename = {
        "tier": "Tier", "rank_score": "Rank Score",
        "player": "Player", "pos": "Pos", "player_type_norm": "Player Type",
        "team": "Team", "opp_team": "Opp", "game_time": "Game Time",
        "days_rest": "Days Rest",
        "is_back_to_back": "B2B",
        "opp_days_rest": "Opp Rest",
        "opp_b2b": "Opp B2B",
        "h2h_avg": "H2H Avg",
        "h2h_over_pct": "H2H Over%",
        "h2h_games": "H2H Games",
        "h2h_last": "H2H Last",
        "game_total": "Game Total",
        "spread": "Spread",
        "slate_game_date": "Game Date",
        "prop_type": "Prop", "pick_type": "Pick Type", "line": "Line",
        "final_bet_direction": "Direction",
        "edge": "Edge", "abs_edge": "Abs Edge", "projection": "Projection",
        "ml_prob": "ML Prob",
        "edge_score": "Edge Score",
        "blended_score": "Blended Score",
        "line_hit_rate_over_ou_5": "Hit Rate (5g)",
        "hit_rate_status": "Hit Rate Status",
        "reliability_note": "Reliability Note",
        "stat_last5_avg": "Last 5 Avg", "stat_season_avg": "Season Avg",
        "last5_over": "L5 Over", "last5_under": "L5 Under",
        "OVERALL_DEF_RANK": "Def Rank", "DEF_TIER": "Def Tier",
        "HITS_ALLOWED_RANK": "Opp Hits Allowed Rank",
        "RUNS_ALLOWED_RANK": "Opp Runs Allowed Rank",
        "HR_ALLOWED_RANK": "Opp HR Allowed Rank",
        "minutes_tier": "Min Tier", "batting_order_tier": "Bat Order",
        "pitcher_role": "Pitcher Role",
        "lineup_confirmed": "Lineup Confirmed",
        "batting_order_pos": "Batting Order Pos",
        "opp_starter_name": "Opp Starter Name",
        "opp_starter_hand": "Opp Starter Hand",
        "opp_starter_era": "Opp Starter ERA (Season)",
        "opp_starter_whip": "Opp Starter WHIP (Season)",
        "opp_closer_name": "Opp Closer Name",
        "opp_closer_hand": "Opp Closer Hand",
        "opp_closer_era": "Opp Closer ERA",
        "opp_closer_saves": "Opp Closer Saves",
        "opp_sp1_name": "Opp SP1 Name",
        "opp_sp1_hand": "Opp SP1 Hand",
        "opp_sp2_name": "Opp SP2 Name",
        "opp_sp2_hand": "Opp SP2 Hand",
        "opp_sp3_name": "Opp SP3 Name",
        "opp_sp3_hand": "Opp SP3 Hand",
        "opp_staff_lhp": "Opp Staff LHP",
        "opp_staff_rhp": "Opp Staff RHP",
        "park_factor_hr": "Park HR Factor",
        "park_hr_rank": "Park HR Rank",
        "park_hr_tier": "Park HR Tier",
        "park_tier": "Park Tier",
        "opp_pitcher_era_vs_batter_hand": "Opp Starter ERA",
        "opp_pitcher_whip_vs_batter_hand": "Opp Starter WHIP",
        "top_of_order": "Top Of Order",
        "bottom_of_order": "Bottom Of Order",
        "line_moved_up": "Line Moved Up",
        "line_moved_down": "Line Moved Down",
        "player_on_il": "Player On IL",
        "injury_status": "Injury Status",
        "injury_type": "Injury Type",
        "days_since_injury_report": "Days Since Injury",
        "pitcher_scratched": "Pitcher Scratched",
        "opp_starter_on_il": "Opp Starter On IL",
        "same_series_hit_rate": "Series HR",
        "void_reason": "Void Reason",
        **HIT_TRACKING_RENAME,
    }
    _lm_cols = (
        "open_line", "line_movement", "line_direction_shift",
        "implied_prob", "implied_prob_over", "implied_prob_under",
    )
    rename = {k: v for k, v in rename.items() if k not in _lm_cols}
    clean = clean.rename(columns=rename)
    return clean.where(pd.notna(clean), None)


def build_clean_xlsx(df: pd.DataFrame, xlsx_path: str, *, styled: bool = False) -> None:
    """Write MLB clean workbook. Fast path = single ALL sheet (seconds vs minutes)."""
    clean = _prepare_clean_frame(df)
    tmp_path = str(Path(xlsx_path).with_suffix(".tmp.xlsx"))
    Path(xlsx_path).parent.mkdir(parents=True, exist_ok=True)

    if (not styled) or len(clean) >= 1500:
        with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
            clean.to_excel(writer, sheet_name="ALL", index=False)
        os.replace(tmp_path, xlsx_path)
        print(f"Clean XLSX saved (fast) -> {xlsx_path}  rows={len(clean)}")
        return

    wb = Workbook()
    wb.remove(wb.active)
    write_sheet(wb, "ALL", clean, HEADER_COLOR)
    for tier in ["A", "B", "C", "D"]:
        subset = clean[clean["Tier"] == tier].copy()
        if len(subset):
            tier_bg = TIER_COLORS.get(tier, ("333333",))[0]
            write_sheet(wb, f"Tier {tier}", subset, tier_bg)
    if "Player Type" in clean.columns:
        pitchers = clean[clean["Player Type"].astype(str).str.lower() == "pitcher"].copy()
        hitters = clean[clean["Player Type"].astype(str).str.lower() == "hitter"].copy()
        if len(pitchers):
            write_sheet(wb, "Pitchers", pitchers, PITCHER_TAB_COLOR)
        if len(hitters):
            write_sheet(wb, "Hitters", hitters, HITTER_TAB_COLOR)
    wb.save(tmp_path)
    os.replace(tmp_path, xlsx_path)
    print(f"Clean XLSX saved -> {xlsx_path}")

