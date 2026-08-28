# Templates vs generated JSON

**Hand-edit here:** Jinja HTML (`index.html`, `indexGrades.html`, `_site_nav.html`, etc.) and static page templates.

**Generated (do not hand-edit):** `tickets_latest.json`, `slate_latest.json`, `slate_sport_*.json`, `pipeline_status.json`, `slate_display_date.json`, dated `ticket_eval_*.html` / `graded_props_*.json`.

Those JSON files stay in this folder because **GitHub raw + Railway** poll `ui_runner/templates/<name>` from `origin/main`. The canonical disk copy is `ui_runner/runtime/`. See `utils/ui_live_json.py`.
