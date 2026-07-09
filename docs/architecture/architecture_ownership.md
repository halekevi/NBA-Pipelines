# PropORACLE Architecture Ownership Matrix

Purpose: single-reference ownership map for runtime artifacts before further pipeline/UI refactors.

## Ownership Matrix

| Artifact category | File / path pattern | Primary location(s) | Producer script / step | Consumer (page/API/script) | Retention policy | Drift risk |
|---|---|---|---|---|---|---|
| 1) Live JSON (latest) | `tickets_latest.json`, `tickets_winrate_latest.json`, `winrate_goblin_opt3_shadow_latest.json`, `slate_latest.json`, `slate_sport_*.json`, `sport_breakdown.json` | `ui_runner/templates/` (runtime), `ui_runner/data/` (snapshot copy), `mobile/www/` (bundle copy) | `scripts/combined_slate_tickets.py` via `--write-web`; orchestrated by `run_pipeline.ps1`; mobile copy by `scripts/generate_mobile_bundle.py` | `ui_runner/app.py` endpoints/pages (`/tickets`, slate APIs), static mobile pages in `mobile/www/` | Keep latest in runtime path; archive dated history in `ui_runner/data/`; mobile keeps deploy copy | **High** (same logical "latest" exists in multiple locations) |
| 2) Dated ticket snapshots | `combined_slate_tickets_<date>.json`, `combined_slate_tickets_high_leg_<date>.json`, `combined_slate_tickets_long_parlay_<date>.json`, `combined_slate_tickets_winrate_goblin_opt3_<date>.json` | `ui_runner/data/` (historical source); optional canonical copies under `outputs/<date>/` | `scripts/combined_slate_tickets.py` + copy/archive logic in `run_pipeline.ps1` | Backtests/reviews (`scripts/slip_grade_review_by_slice.py`, model/report scripts, grading helpers) | Keep as time-series history; do not treat as runtime "latest" | Medium (history + canonical copies can diverge if copy step fails) |
| 3) Graded props JSON | `graded_props_<date>.json` | `ui_runner/templates/`, `mobile/www/`, `outputs/<date>/canonical/...` | Grader pipeline steps in `run_pipeline.ps1` (post-game grading/export) | `indexGrades.html`, grade APIs, ticket-eval builders | Keep dated history for auditing/backtests | Medium (copied into multiple surfaces) |
| 4) Grade history | `grade_history.json`, plus dates indexes (`grades_report_dates.json`, `grades_archive_dates.json`) | Canonical read path: persistent data root (`DATA_ROOT/grade_history.json`, usually `data/grade_history.json`); fallback read: `ui_runner/templates/grade_history.json`; mobile copy in `mobile/www/` | `scripts/build_ticket_eval.py` appends/updates grade history; pipeline/mobile bundling in `run_pipeline.ps1` + `scripts/generate_mobile_bundle.py` | Grades pages/API in `ui_runner/app.py` (`/api/grade-history`, income views), mobile grades views | Keep latest consolidated history in persistent data root; templates/mobile are distribution copies | **High** (same logical artifact in persistent data + templates/mobile fallback copies) |
| 5) Step8 clean workbooks per sport | `Sports/*/outputs/step8_*_direction_clean.xlsx` and related `Sports/*/step*_ranked_*.xlsx` | Sport folders under `Sports/` | Sport-specific pipeline steps (`run_pipeline.ps1` invoking sport scripts) | `scripts/combined_slate_tickets.py` input loader; graders for slate extraction | Replace per run/date source; keep dated copies under `outputs/<date>/` when produced | Medium (date mismatch warnings common if stale files reused) |
| 6) Full Slate workbook | `combined_slate_tickets_<date>.xlsx`, optional `_to_grade_tomorrow.xlsx` | Repo root (when run directly), `outputs/<date>/`, `outputs/<date>/canonical/` | `scripts/combined_slate_tickets.py` (invoked by pipeline) | Human review, downstream grading join, archive/export steps | Keep dated workbook history | Low |
| 7) Ticket eval HTML | `ticket_eval_<date>.html`, variants (`ticket_eval_high_leg_<date>.html`, `ticket_eval_long_parlay_<date>.html`, `ticket_eval_winrate_goblin_opt3_<date>.html`) | `ui_runner/templates/`, `mobile/www/`, `outputs/<date>/canonical/...` | Ticket eval build steps in `run_pipeline.ps1` + eval scripts | UI grade/eval pages and mobile mirrors | Keep dated history | Medium (many variant files across locations) |
| 8) Mobile bundle | `mobile/www/*` (pages, static, copied JSON, eval HTML) | `mobile/www/` | `scripts/generate_mobile_bundle.py` (called by `run_pipeline.ps1`) | Mobile/offline app runtime | Generated deploy artifact; can be rebuilt from template/data sources | **High** (contains transformed copies of many upstream artifacts) |
| 9) Retrain artifacts (dataset + model) | `data/retrain_dataset.csv`, `models/edge_model_unified.pkl`, `models/edge_model_metadata.json` | `data/` (dataset), `models/` (served model + metadata) | `scripts/build_retrain_dataset.py` (dataset), `scripts/train_edge_model.py` (model + metadata), orchestration via `scripts/run_enrichment_retrain_sequence.ps1` | `scripts/step7b_edge_score.py` and edge-scoring helpers used by sport pipelines; diagnostics/report scripts | Keep latest production model in `models/`; archive retrain outputs per cycle externally or by dated copies | **Medium/High** (`retrain_dataset.csv` is typically gitignored while `edge_model_unified.pkl` is committed, so reproducibility requires local rebuild inputs) |
| 10) Reports | `data/reports/*` (slice reviews, miss attribution, diversity, reliability, ladder backtests, etc.) | `data/reports/` | Reporting and analysis scripts + pipeline post-steps | Analyst workflows, tuning decisions, diagnostics | Historical append/dated outputs; prune only by policy | Low |
| 11) Cache files | `Sports/*/cache/*`, `cache/*`, sport cache CSV/JSON files | Sport folders + top-level `cache/` | Fetch/ingest scripts and pipeline pre-steps | Upstream loaders (`combined_slate_tickets.py`, sport builders) | Ephemeral/regenerable; rolling retention recommended | Medium (stale caches can silently affect inputs) |
| 12) Pipeline status | `pipeline_status.json` (and associated slate status markers, e.g. `slate_display_date.json`) | `ui_runner/templates/`, `mobile/www/`, `outputs/<date>/canonical/...` | `run_pipeline.ps1` status writers + mobile bundle step | UI freshness badges/cards; mobile status display | Latest-only runtime + dated canonical snapshots | **High** (freshness semantics split across files/surfaces) |
| 13) Rolling HR / shadow-track metrics | `data/reports/strong_player_rolling_hr.json`, `data/reports/winrate_goblin_opt3_shadow_track.json` | `data/reports/`; copied summary views may appear in template/mobile JSON aggregates | `scripts/update_strong_player_rolling_hr.py` (STEP B1 in `scripts/run_daily.ps1`) for STRONG rolling HR; shadow metrics from opt3/shadow report scripts | `scripts/combined_slate_tickets.py` `build_strong_tickets()` reads `strong_player_rolling_hr.json`; monitoring/review scripts consume shadow track JSON | Keep historical snapshots where available; latest used for gating | Medium |
| 14) Export trust infrastructure | `scripts/combined_export_trust.py` | `scripts/` | Hand-maintained shared utility module | `scripts/compare_winrate_goblin_opt3_shadow.py` (`day_export_trust`) and `scripts/daily_strong_opt3_check.py` (`classify_combined_export_file`) | Version with analysis logic changes; no generated retention semantics | Low |

## Source vs Generated Boundaries

- **Authoritative hand-edited UI source**: HTML templates/partials in `ui_runner/templates/` (non-dated page templates).
- **Generated runtime artifacts**: latest JSON in `ui_runner/templates/`; dated snapshots in `ui_runner/data/`; deploy mirror in `mobile/www/`; canonical copies in `outputs/<date>/`.
- **Model/report/data source area**: `models/`, `data/`, `data/reports/`, sport-specific `Sports/*` inputs/caches.

## Known Structural Risks (Audit Flags)

1. **`ui_runner/templates/` mixes source + generated artifacts**  
   - Hand-authored templates and generated JSON/daily HTML are co-located.
2. **Two "latest" JSON locations**  
   - Same logical artifact appears in `ui_runner/templates/` and `ui_runner/data/` (plus `mobile/www/` copy).
3. **Mobile rewrite brittleness**  
   - `scripts/generate_mobile_bundle.py` transforms web templates into offline/mobile format; tightly coupled to template structure.
4. **Dated artifact duplication**  
   - Dated eval/JSON outputs duplicated across `ui_runner/templates/`, `ui_runner/data/`, `mobile/www/`, and `outputs/<date>/canonical/`.
5. **Freshness signaling split**  
   - Freshness/state spread across `pipeline_status.json`, `slate_latest.json` timestamps, and dated eval/report files.

## Practical Ownership Rules (Recommended)

- Runtime web should read **one canonical latest JSON location**.
- Historical/diff/backtest workflows should read **dated artifacts from `ui_runner/data/`**.
- `mobile/www/` should be treated as **generated deploy output only**.
- `outputs/<date>/canonical/` should be treated as **release snapshot only**, not runtime input.
- Treat retrain reproducibility as a separate ownership concern: committed model binaries do not imply committed training dataset provenance.
