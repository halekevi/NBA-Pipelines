# Canonical Pipelines and Scripts

This file defines the primary scripts to run and maintain. Prefer these over machine-specific variants or backups.

## Daily production pipeline

- `run_pipeline.ps1` - top-level daily orchestration entrypoint.
- `scripts/run_daily.ps1` - core daily data pipeline (includes WNBA via `run_pipeline.ps1`; NFL/CBB are season/input-gated).
- `scripts/run_daily_1am.ps1` - scheduled 1AM wrapper (complete all-sport fetch + `run_daily.ps1`; skips grader/A1).
- `scripts/run_grader_evening.ps1` - scheduled 3AM grader + A1 (split from 1AM for RAM/CPU).
- `scripts/run_daily_5am.ps1` - unscheduled manual full-daily catchup (same pipeline; 1AM owns the clock).
- `scripts/run_tennis_early_3am.ps1` - retired from scheduler (tennis is part of Daily 1AM).
- `scripts/run_refresh_with_log.ps1` - line-move refresh wrapper (lock + PRE/POST prop snapshot).
- `scripts/run_nba_late_fetch.ps1` - multi-sport step1 append + pipeline `-SkipFetch` (CDP-first when `:9222` up; per-sport wall-clock timeouts).
- `scripts/run_post_pipeline_grader.ps1` - post-pipeline grading follow-up.
- `scripts/run_live_payout_capture.ps1` - live CDP MAIN floors (11:00 task; midday `-UpdateOnly`).

## Ticket generation and grading

- `scripts/combined_slate_tickets.py` - canonical ticket generator (Standard prop×direction gates; MAIN pool modes).
- `scripts/combined_ticket_grader.py` - canonical ticket grader.
- `scripts/build_ticket_eval.py` - ticket eval HTML + void-aware reduced-slip settlement.
- `scripts/run_grader.ps1` - canonical grader wrapper for daily/manual runs.

## PrizePicks fetch helpers (DataDome)

- `utils/prizepicks_http.py` - shared curl_cffi HTTP projections fetch.
- `utils/prizepicks_cdp.py` - shared CDP attach + in-page `fetch()` (30s attach timeout, AbortController).
- Sport step1 with `--cdp` / `--fail-fast`: Soccer, Tennis; WNBA via `run_wnba_pipeline.ps1 -CdpWhenListening`; MLB HTTP→CDP→Playwright.

## Backtest and model comparison

- `scripts/backtest_ticket_generation_dates.py` - grade archived generated tickets across date ranges.
- `scripts/replay_new_generator_backtest.py` - replay generator on historical days and grade outputs.
- `scripts/ab_new_vs_old_tickets_last10.py` - 10-day old vs new arm comparison.

## ML training and evaluation

- `scripts/build_ticket_training_dataset.py` - builds ticket-level training/eval dataset from graded history.
- `scripts/train_ticket_model.py` - trains ticket-level cash probability model.
- `scripts/evaluate_ticket_model.py` - evaluates EV-only vs model rerank by date and top-N.

## Sport-specific helpers still in active use

- `scripts/run_wnba_pipeline.ps1` (steps 1–8 + **step7b** edge overlay like NBA, then step9 local tickets; writes `step8_wnba_direction_clean.xlsx` and copies to `WNBA/data/outputs/` for `Run-Combined`)
- `scripts/run_wnba_grader.ps1`
- `Soccer/scripts/run_soccer_pipeline.ps1`
- `Tennis/scripts/step1_fetch_prizepicks_tennis.py` (CDP/fail-fast)

## Archival policy

- Machine-specific script variants (for example `*-Travel-PC*`, `*-DESKTOP-*`) are archived under `archive/script_cleanup/`.
- Backup files (`*.bak`) should not live beside canonical scripts; archive them or delete after validation.
- When adding a new orchestrator, update this file and deprecate/repoint older entrypoints in the same change.

## Related

- Operator cadence / audiences: [../guides/DAILY_OPS_OVERVIEW.md](../guides/DAILY_OPS_OVERVIEW.md)
