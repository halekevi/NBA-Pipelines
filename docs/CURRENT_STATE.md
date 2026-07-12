# PropORACLE — current state

Living one-pager for after a break. Update when something big ships (model promote, pool-mode change, sport season flip, experiment ship/kill). Not a C4 diagram.

**As of:** 2026-07-12

---

## Production knobs

| Item | Value | Notes |
|------|--------|------|
| **Active edge model** | `models/edge_model_unified.pkl` | Trained **2026-06-13**; overall AUC **0.7567** (calibrated = same). Tennis excluded from tree training. |
| **Edge metadata** | `models/edge_model_metadata.json` | Points at the Jun-13 no-tennis artifact; slice isotonic refresh exists separately. |
| **Jul 9 candidate** | `models/edge_model_candidate.pkl` | Evaluated; **production kept** (not promoted). |
| **Active MAIN pool mode** | `goblin_only_3leg` | `MAIN_POOL_MODE` in `scripts/combined_slate_tickets.py` (from ~Jul 10 policy). |
| **STRONG gate** | Rolling HR + player appearance cap | Exclude players with rolling HR &lt; 0.25 when n ≥ 20; max appearances per slate (env `PROPORACLE_STRONG_MAX_PLAYER_APPS`, default 2). |
| **Ticket model** | `models/ticket_model*.pkl` | Registry refreshed 2026-07-09; combined AUC test ~0.67 (cash label). Secondary to edge model for day-to-day. |
| **Next edge retrain** | **~2026-08-14** | ~2 months after Jun-13 promote; see **Aug 14 retrain pre-work** below. |
| **Live payout rate card** | `data/reports/payout_rate_card.json` | Mix-grid fit 2026-07-11: `goblin_discount_per_unit` bucket **1.0 = 0.1521** (n=4). Fill **1.5 / 2.0** buckets before treating curve as final. |
| **Post-ticket payout scrape** | `scripts/run_live_payout_capture.ps1` | Runs after combined tickets (`Run-Combined` + `run_daily` STEP D-payout). CDP → `power_min_x` → `payout_source=live_cdp` on slips; else board-avg. Skip: `-SkipLivePayoutCapture` / `PROPORACLE_SKIP_LIVE_PAYOUT=1`. After capture, **prunes unplayable slips from live** `tickets_latest.json` only. |
| **Ticket run archive** | `ui_runner/data/ticket_runs/{date}/{run_id}/` | Immutable per-emit snapshots (`scripts/ticket_run_archive.py`). Grade pool = `ui_runner/data/combined_slate_tickets_{date}.json` (union of runs). Live site/app = playable-only `tickets_latest.json`. |

---

## Aug 14 retrain pre-work

Do **not** retrain or retune Goblin score weights before this date. Gates already encode ticket-pattern evidence (Goblin-only MAIN, STRONG, tier-def). Hold 3-leg conclusions until **n≈20**; opt3 until clean **n≈30**.

1. Stratify temporal test by `pick_type` (Demon / Goblin / Standard balanced)
2. Wire WNBA `usage_pct` into `scripts/build_retrain_dataset.py`
3. Add live-slate scoring check to retrain gate
4. **Check Goblin `ml_prob` calibration post-retrain**
   - Baseline (2026-07-11, mobile graded Jul 4–10): Goblin ticket legs n=812, actual HR **0.643**, mean `ml_prob` **0.578**, corr **0.060** (flat; mass in 0.5–0.6)
   - Target: correlation **> 0.15** on Goblin ticket legs
   - If still flat after retrain → Goblin needs its own calibration pass

Until then: Goblin selection stays on **tier + HOT + hit rate** (not `ml_prob`).

---

## Sports

| Status | Sports |
|--------|--------|
| **Active** | MLB, WNBA, Tennis, Golf, Soccer (WC / in-season slate) |
| **Paused / off-season** | NBA, NBA1H, NBA1Q, NHL (grading/pipeline season-gated) |
| **Season / input gated** | CBB, WCBB, CFB, NFL — present in tree; not daily drivers right now |

---

## Open experiments

| Experiment | Status | Why |
|------------|--------|-----|
| **opt3 goblin Tier-A shadow** | **Hold** | `data/reports/winrate_goblin_opt3_shadow_track.json` (updated 2026-07-09): shadow hit ~28.9% vs baseline ~25.1% on decided tickets, but `ready_to_ship=false` — two-regime variance (pre- vs post-outage); wait for clean pipeline days. |
| **STRONG Path B** | Watch | Post-gate sample still thin (`n≈0` meaningful Path-B tickets after rolling-HR / appearance gates). Do not treat as a live product track yet. |
| **Probability ladder / high-leg / long-parlay** | Side tracks | Built alongside MAIN; not the default cash pool. |

---

## Where to look next

| Need | Path |
|------|------|
| Run commands | `docs/runbooks/PROPORACLE_RUN_COMMANDS.md` |
| Who owns which artifact | `docs/architecture/architecture_ownership.md` |
| Model promote / calibration | `docs/ml/MODEL_CALIBRATION.md` |
| Folder contracts | `docs/PROJECT_LAYOUT.md` |
| Opt3 shadow track | `data/reports/winrate_goblin_opt3_shadow_track.json` |
| STRONG rolling HR | `data/reports/strong_player_rolling_hr.json` |

---

## How to update this file

When you change a production knob, edit the table row and bump **As of**. Do not expand this into architecture essays — keep it one screen.
