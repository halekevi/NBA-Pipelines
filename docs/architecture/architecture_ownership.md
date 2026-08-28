# PropORACLE Architecture Ownership Matrix

Purpose: single-reference ownership map for runtime artifacts before further pipeline/UI refactors.

## Ownership Matrix

| Artifact category | File / path pattern | Primary location(s) | Producer script / step | Consumer (page/API/script) | Retention policy | Drift risk |
|---|---|---|---|---|---|---|
| 1) Live tickets JSON | `tickets_latest.json` | **Disk:** `ui_runner/runtime/` (canonical). **GitHub raw / Railway:** `ui_runner/templates/` (publish contract). Snapshot: `ui_runner/data/`. **Not live:** `mobile/www/` (Android loads Railway remotely). | Mixer from `scripts/combined_slate_tickets.py --write-web`; dual card from `scripts/build_goblin70_tickets.py --write-web`; `scripts/Publish-LiveSite.ps1` pushes templates (+ runtime) to origin/main | `ui_runner/app.py` `/tickets` (disk prefers runtime, Railway fetches GitHub templates/) | Keep latest in runtime + templates mirror; archive dated history in `ui_runner/data/` | **High** (local checkout is not what Railway serves) |
| 1b) Live slate / winrate JSON | `tickets_winrate_latest.json`, `slate_latest.json`, `slate_sport_*.json`, `sport_breakdown.json` | Same as tickets: runtime disk + templates GitHub raw | `scripts/combined_slate_tickets.py` via `--write-web`; `run_pipeline.ps1` | Slate APIs and High Leg HR panel on `/tickets` | Keep latest in runtime + templates; archive in `ui_runner/data/` | **Medium** (two copies by design: disk vs GitHub raw) |
| 2) Dated ticket snapshots | `combined_slate_tickets_<date>.json`, `combined_slate_tickets_high_leg_<date>.json`, `combined_slate_tickets_long_parlay_<date>.json`, `combined_slate_tickets_winrate_goblin_opt3_<date>.json` | `ui_runner/data/` (historical source); optional canonical copies under `outputs/<date>/` | `scripts/combined_slate_tickets.py` + copy/archive logic in `run_pipeline.ps1` | Backtests/reviews (`scripts/slip_grade_review_by_slice.py`, model/report scripts, grading helpers) | Keep as time-series history; do not treat as runtime "latest" | Medium (history + canonical copies can diverge if copy step fails) |
| 3) Graded props JSON | `graded_props_<date>.json` | `ui_runner/templates/`, `mobile/www/`, `outputs/<date>/canonical/...` | Grader pipeline steps in `run_pipeline.ps1` (post-game grading/export) | `indexGrades.html`, grade APIs, ticket-eval builders | Keep dated history for auditing/backtests | Medium (copied into multiple surfaces) |
| 4) Grade history | `grade_history.json`, plus dates indexes (`grades_report_dates.json`, `grades_archive_dates.json`) | Canonical read path: persistent data root (`DATA_ROOT/grade_history.json`, usually `data/grade_history.json`); fallback read: `ui_runner/templates/grade_history.json`; mobile copy in `mobile/www/` | `scripts/build_ticket_eval.py` appends/updates grade history; pipeline/mobile bundling in `run_pipeline.ps1` + `scripts/generate_mobile_bundle.py` | Grades pages/API in `ui_runner/app.py` (`/api/grade-history`, income views), mobile grades views | Keep latest consolidated history in persistent data root; templates/mobile are distribution copies | **High** (same logical artifact in persistent data + templates/mobile fallback copies) |
| 5) Step8 clean workbooks per sport | `Sports/*/step8_*_direction_clean.xlsx` (live Railway/combined pointer); dated copies under `outputs/<date>/` | Sport roots + `outputs/<date>/` | Sport pipelines + STEP D2 copy in `run_daily.ps1` | `scripts/combined_slate_tickets.py`; graders | Keep dated copies under `outputs/<date>/`; NoOverwrite baks go to `data/historical/sport_root_backups/` | Medium (stale sport-root pointer if D2 skipped) |
| 6) Full Slate workbook | `combined_slate_tickets_<date>.xlsx`, optional `_to_grade_tomorrow.xlsx` | Repo root (when run directly), `outputs/<date>/`, `outputs/<date>/canonical/` | `scripts/combined_slate_tickets.py` (invoked by pipeline) | Human review, downstream grading join, archive/export steps | Keep dated workbook history | Low |
| 7) Ticket eval HTML | `ticket_eval_<date>.html`, variants (`ticket_eval_high_leg_<date>.html`, `ticket_eval_long_parlay_<date>.html`, `ticket_eval_winrate_goblin_opt3_<date>.html`) | `ui_runner/templates/`, `mobile/www/`, `outputs/<date>/canonical/...` | Ticket eval build steps in `run_pipeline.ps1` + eval scripts | UI grade/eval pages and mobile mirrors | Keep dated history | Medium (many variant files across locations) |
| 8) Mobile bundle | `mobile/www/*` (pages, static, copied JSON, eval HTML) | `mobile/www/` | `scripts/generate_mobile_bundle.py` (called by `run_pipeline.ps1`) | Mobile/offline app runtime | Generated deploy artifact; can be rebuilt from template/data sources | **High** (contains transformed copies of many upstream artifacts) |
| 9) Retrain artifacts (dataset + model) | `data/retrain_dataset.csv`, `models/edge_model_unified.pkl`, `models/edge_model_metadata.json` | `data/` (dataset), `models/` (served model + metadata) | `scripts/build_retrain_dataset.py` (dataset), `scripts/train_edge_model.py` (model + metadata), orchestration via `scripts/run_enrichment_retrain_sequence.ps1` | `scripts/step7b_edge_score.py` and edge-scoring helpers used by sport pipelines; diagnostics/report scripts | Keep latest production model in `models/`; archive retrain outputs per cycle externally or by dated copies | **Medium/High** (`retrain_dataset.csv` is typically gitignored while `edge_model_unified.pkl` is committed, so reproducibility requires local rebuild inputs) |
| 10) Reports | `data/reports/*` (slice reviews, miss attribution, diversity, reliability, ladder backtests, etc.) | `data/reports/` | Reporting and analysis scripts + pipeline post-steps | Analyst workflows, tuning decisions, diagnostics | Historical append/dated outputs; prune only by policy | Low |
| 11) Cache files | `Sports/*/cache/*`, `cache/*`, sport cache CSV/JSON files | Sport folders + top-level `cache/` | Fetch/ingest scripts and pipeline pre-steps | Upstream loaders (`combined_slate_tickets.py`, sport builders) | Ephemeral/regenerable; rolling retention recommended | Medium (stale caches can silently affect inputs) |
| 12) Pipeline status | `pipeline_status.json` (and associated slate status markers, e.g. `slate_display_date.json`) | `ui_runner/templates/`, `mobile/www/`, `outputs/<date>/canonical/...` | `run_pipeline.ps1` status writers + mobile bundle step | UI freshness badges/cards; mobile status display | Latest-only runtime + dated canonical snapshots | **High** (freshness semantics split across files/surfaces) |
| 13) Rolling HR / shadow-track metrics | `data/reports/strong_player_rolling_hr.json`, `data/reports/winrate_goblin_opt3_shadow_track.json` | `data/reports/`; copied summary views may appear in template/mobile JSON aggregates | `scripts/update_strong_player_rolling_hr.py` (STEP B1 in `scripts/run_daily.ps1`) for STRONG rolling HR; shadow metrics from opt3/shadow report scripts | `scripts/combined_slate_tickets.py` `build_strong_tickets()` reads `strong_player_rolling_hr.json`; monitoring/review scripts consume shadow track JSON | Keep historical snapshots where available; latest used for gating | Medium |
| 14) Export trust infrastructure | `scripts/combined_export_trust.py` | `scripts/` | Hand-maintained shared utility module | `scripts/compare_winrate_goblin_opt3_shadow.py` (`day_export_trust`) and `scripts/daily_strong_opt3_check.py` (`classify_combined_export_file`) | Version with analysis logic changes; no generated retention semantics | Low |
| 15) PrizePicks fetch helpers | `utils/prizepicks_http.py`, `utils/prizepicks_cdp.py` | `utils/` | Hand-maintained shared modules | Sport step1 (Soccer/Tennis/WNBA/MLB), `scripts/run_nba_late_fetch.ps1`, `scripts/run_wnba_pipeline.ps1` | Version with DataDome / attach-timeout changes | Medium (HTTP vs CDP path drift) |
| 16) Daily / refresh lock + slate status | `data/cache/refresh.lock`, `outputs/<date>/pipeline_slate_status.json` | `data/cache/`, `outputs/<date>/` | `scripts/run_refresh_with_log.ps1`, `run_pipeline.ps1` / daily orch. | Operator catchup; soft-skip exit codes; UI freshness | Lock is ephemeral (90 min TTL); slate status dated | Medium |

## Source vs Generated Boundaries

- **Authoritative hand-edited UI source**: HTML templates/partials in `ui_runner/templates/` (non-dated page templates). See `ui_runner/templates/README.md`.
- **Generated live JSON**: canonical disk `ui_runner/runtime/`; GitHub-raw publish mirror `ui_runner/templates/` (Railway polls this). Dated snapshots in `ui_runner/data/`. `mobile/www/` is bundled-fallback only (app is remote Railway).
- **Model/report/data source area**: `models/`, `data/`, `data/reports/`, sport-specific `Sports/*` inputs/caches.

## Known Structural Risks (Audit Flags)

1. **`ui_runner/templates/` still holds a GitHub-raw JSON mirror**  
   - Hand-authored HTML and generated JSON remain co-located *for Railway*. Disk canonical is `ui_runner/runtime/`. Do not delete the templates JSON until the GitHub URL cutover.
2. **Two "latest" JSON locations by design**  
   - `ui_runner/runtime/` (disk) and `ui_runner/templates/` (GitHub raw). `ui_runner/data/` is history. `mobile/www/` is not live.
3. **Mobile rewrite brittleness (bundled fallback only)**  
   - `scripts/generate_mobile_bundle.py` transforms web templates into offline `www/`; canonical app loads Railway and does not use that copy.
4. **Dated artifact duplication**  
   - Dated eval/JSON outputs duplicated across `ui_runner/templates/`, `ui_runner/data/`, `mobile/www/`, and `outputs/<date>/canonical/`.
5. **Freshness signaling split**  
   - Freshness/state spread across `pipeline_status.json`, `slate_latest.json` timestamps, and dated eval/report files.
6. **Live `/tickets` is origin/main, not this checkout**  
   - Railway reads `tickets_latest.json` from GitHub raw. Writing the file locally does not update the site until `Publish-LiveSite.ps1` (or equivalent push) lands on `main`.

## Practical Ownership Rules (Recommended)

- Runtime `/tickets` should read **prebuilt** `tickets_latest.json` (Goblin-70 + mixer). Do not rebuild slips on the Flask request.
- Live Railway `/tickets` should read **origin/main** `ui_runner/templates/tickets_latest.json`, not an unpushed local checkout. Local Flask prefers `ui_runner/runtime/`.
- Historical/diff/backtest workflows should read **dated artifacts from `ui_runner/data/`**.
- `mobile/www/` is **bundled fallback only**. Canonical Android loads Railway (`server.url`).
- `outputs/<date>/canonical/` should be treated as **release snapshot only**, not runtime input.
- Treat retrain reproducibility as a separate ownership concern: committed model binaries do not imply committed training dataset provenance.
