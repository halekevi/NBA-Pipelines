# PropORACLE historical storage

Long-term review/analysis data lives in **three tiers**. Do not delete historical
artifacts unless they already exist in a higher-priority tier.

## Tier 1 — Daily pipeline runs (primary)

| Location | What | Notes |
|----------|------|-------|
| `outputs/<YYYY-MM-DD>/` | Full slate artifacts: step8, combined tickets, grades, status JSON | **Canonical**. Gitignored. Treat as immutable run history. |
| `outputs/<YYYY-MM-DD>/<sport>/` | Sport-scoped copies when the runner uses dated OutDirs | Preferred live write target for new runs |

## Tier 2 — Analytical databases (queryable)

| Location | What |
|----------|------|
| `data/line_history.db` | Line / board snapshots over time (`scripts/line_history_archive.py`) |
| `data/cache/{sport}_props_history.db` | Graded prop outcomes (`scripts/step_archive.py`) |
| `data/reports/` | Derived reports (many dated files; some gitignored) |
| `ui_runner/data/*_latest.json` + dated tickets | App “latest” + review snapshots |

## Tier 3 — Migrated sport-folder clutter (this tree)

Former duplicates that used to sit under `Sports/<Sport>/` and
`Sports/<Sport>/outputs/` after the canonical dated tree already existed.

| Path | Contents |
|------|----------|
| `sport_outputs/<Sport>/` | Former `Sports/<Sport>/outputs/**` (dated folders + loose May-era steps) |
| `sport_root_backups/<Sport>/` | Former `Sports/<Sport>/*.bak_*` (NoOverwrite preserves next to live step8) |
| `sport_root_stale/<Sport>/<date>/` | Intermediate step1–7 / old step CSVs cleared from sport roots |

**Live pointers left in place** (Railway + combined loaders):

- `Sports/<Sport>/step8_*_direction_clean.xlsx` (current only — no `.bak_*` beside it)
- Runtime caches (`*_espn_cache.csv`, id caches, defense summaries)
- Step Python/PS1 scripts and `Sports/<Sport>/data/`

## Operator script

```powershell
# Preview
pwsh -File scripts/archive_sport_pipeline_artifacts.ps1

# Apply
pwsh -File scripts/archive_sport_pipeline_artifacts.ps1 -Execute
```

Re-run anytime sport roots accumulate `.bak_*` or loose `outputs/` trees.

Working copies may reappear under `Sports/<Sport>/outputs/` during a sport
pipeline run (e.g. Soccer still uses that as its OutDir). Those are current-run
scratch, not the long-term store — re-run the archive script periodically, or
after large catchups, to sweep them into this tree again.

## Going forward

1. Write dated history only under `outputs/<date>/` (see `utils/pipeline_dated_outputs.py`).
2. Keep a single live step8 at the sport root for Railway/combined.
3. NoOverwrite backups of sport-root step8 go under `sport_root_backups/`, not next to the live file.
4. Do not recreate large dated trees under `Sports/*/outputs/`.
