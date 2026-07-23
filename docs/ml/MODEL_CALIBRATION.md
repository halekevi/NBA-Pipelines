# Model & calibration workflow

## Production model (do not replace casually)

| Artifact | Holdout AUC | Role |
|----------|-------------|------|
| `models/edge_model_unified.pkl` | **0.7567** (trained 2026-06-13) | **Live production** — loaded by `edge_predict_utils.load_unified_edge_model` |
| `models/edge_model_unified_pre_enrichment.pkl` | 0.7546 | Archive / fallback reference |

**Live health ≠ holdout.** Rolling graded AUC (Std+Gob, Jul 2026 window) is much weaker on MLB (~0.52–0.61) and WNBA (~0.54). Treat holdout AUC as a training check, not ticket trust.

Promotion gate: new model overall holdout AUC **> 0.7567** on temporal holdout with enrichment columns **>10% fill** in `data/retrain_dataset.csv`, **and** rolling 30d graded AUC / calibration gap must not regress vs current live metrics in `data/model_performance_log.jsonl`.

### 2026-07-18 scalar refresh (ticket-eligible)

Re-fit linear scalars from graded props `min_date>=2026-06-20` (Demons excluded):

- **MLB** Goblin OVER / Std OVER / Std UNDER — cut overconfidence (`mean ml_prob` was ~0.76 vs ~0.59 HR on Goblin OVER)
- **WNBA** Goblin OVER / Std OVER / Std UNDER — mild recalibration
- **Skipped Tennis Goblin** — already calibrated (~0.33 vs 0.32); policy target 0.50 would *inflate* probs
- **Ticket cash models** remain shadow/`model_allowed: false` (overconfident cash bins)

### 2026-07-18 ticket generation alignment

| Knob | New default | Why |
|------|-------------|-----|
| `PROPORACLE_STRONG_MAX_LEGS` | **3** (hard cap) | Jul 17 STRONG ≤3 → ~73% ticket WR |
| STRONG `min_p_win` 2/3 | **0.45 / 0.38** | Toward 70% ticket WR target |
| `PROPORACLE_MAIN_MAX_LEGS` | **3** (hard cap) | Production boards are 2–3 only |
| `PROPORACLE_LONG_PARLAY` | **0** (off) | Disables 5–6 long-parlay sidecar |
| MLB Goblin OVER MAIN floor | **0.68** (stress props **0.72**) | Miss concentration + overconfidence |
| STRONG MLB props | Drop Hits / Total Bases | Same miss anatomy |
| STRONG min leg_prob | **0.65** (MLB **0.70**) | Match calibrated reality |

## Calibration stack (inference order)

1. **XGBoost** → raw score  
2. **Platt** (`LogisticRegression` on holdout) → `p_platt`  
3. **Slice isotonic** (`models/edge_slice_calibrators.pkl`) — per `(sport, pick_type, direction)` when `n >= 200`  
4. **Linear scalars** (`ML_PROB_CALIBRATION_SCALARS` in `scripts/edge_predict_utils.py`)

## When stats.nba.com is up (enrichment retrain)

```powershell
py -3.14 scripts/verify_enrichment_ready.py --smoke-test
pwsh -File scripts\run_enrichment_retrain_sequence.ps1 -Date (Get-Date -Format yyyy-MM-dd)
```

Compare `models/edge_model_metadata.json` to `edge_model_metadata_pre_enrichment.json` before swapping production pickle.

## Without full retrain (graded archive only)

### 1. Refresh linear scalars (WNBA now has 200+ graded rows)

```powershell
py -3.14 scripts\recalibrate_ml_prob_scalars.py --sport WNBA --min-n 50
py -3.14 scripts\recalibrate_ml_prob_scalars.py --sport WNBA --apply
```

All sports report:

```powershell
py -3.14 scripts\recalibrate_ml_prob_scalars.py --min-n 100
```

Output: `outputs/calibration/ml_prob_scalar_recommendations.csv`

### 2. Refresh slice isotonic (no XGBoost retrain)

Uses **pre-enrichment** model + full graded history:

```powershell
py -3.14 scripts\refresh_slice_isotonic.py
```

Writes `models/edge_slice_calibrators.pkl` and `models/edge_slice_isotonic_refresh.json`.

## WNBA

- Graded archive: **200+** rows required for isotonic slice (`WNBA_SLICE_ISOTONIC_MIN_N = 200` in `train_edge_model.py`).
- Scalars were `1.0` placeholders; run `recalibrate_ml_prob_scalars.py --sport WNBA --apply` after each major model swap.

## NBA scalars

Comment in `edge_predict_utils.py`: recalibrate after enrichment retrain when `usage_pct` / `team_pace` columns survive the 60% fill filter in training.

## Still blocked

| Item | Blocker |
|------|---------|
| Enrichment retrain | stats.nba.com HTTP 500 |
| NBA/WNBA usage% in training | Same |
| Model promotion | Retrain AUC vs 0.7546 |
