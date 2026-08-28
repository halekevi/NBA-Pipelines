# PropORACLE — Architecture & User Interactions

> **Diagrams in this doc** render natively in GitHub, GitLab, and Cursor's Markdown preview (Mermaid support built-in). For full UML notation (ovals, stick figures, `<<include>>`), open the `.puml` files in `docs/diagrams/` with the PlantUML extension or paste into [plantuml.com](https://www.plantuml.com/plantuml).

---

## Table of contents

1. [C4 Level 1 — System context](#c4-level-1--system-context)
2. [C4 Level 2 — Containers](#c4-level-2--containers)
3. [C4 Level 3 — Flask API components](#c4-level-3--flask-api-components)
4. [Use case summary](#use-case-summary)
5. [Sport pipeline coverage](#sport-pipeline-coverage)
6. [Related files](#related-files)

---

## C4 Level 1 — System context

Who uses PropORACLE and what external systems it depends on.

```mermaid
C4Context
  title PropORACLE — System Context

  Person(bettor,     "Bettor / Analyst",  "Reviews daily props, EV scores, tickets, grades, and P&L")
  Person(operator,   "Operator",          "Runs pipelines, retrains ML model, grades slates")

  System(prop,       "PropORACLE",        "Multi-sport prop-betting analytics platform")

  System_Ext(sb,     "Sportsbook APIs",   "Odds and lines feed")
  System_Ext(stats,  "Stats APIs",        "ESPN / boxscores / match logs")
  System_Ext(wt,     "Chrome CDP :9222",  "In-page PrizePicks fetch (Soccer/Tennis/WNBA/MLB)")
  System_Ext(gh,     "GitHub origin/main","tickets_latest.json (Goblin-70 + mixer)")
  System_Ext(rail,   "Railway",           "Cloud hosting")
  System_Ext(pp,     "PrizePicks",        "Real-money entries (outside system)")

  Rel(bettor,    prop,  "Views props, tickets, grades, income", "HTTPS")
  Rel(operator,  prop,  "Runs pipelines, grades, publishes",    "PS1 / HTTPS")
  Rel(prop,      sb,    "Fetches odds + lines")
  Rel(prop,      stats, "Fetches player + game stats")
  Rel(prop,      wt,    "CDP-first step1 when debug Chrome is warm")
  Rel(prop,      gh,    "Publishes tickets_latest.json")
  Rel(rail,      gh,    "Reads live tickets JSON")
  Rel(prop,      rail,  "Web + API deployed on")
  Rel(bettor,    pp,    "Places entries (external)")
```

---

## C4 Level 2 — Containers

Which container each user touches and how data flows through the system.

```mermaid
C4Container
  title PropORACLE — Containers

  Person(bettor,   "Bettor / Analyst")
  Person(operator, "Operator")

  System_Boundary(sys, "PropORACLE") {
    Container(web,      "Web App",       "Jinja2 + JS · Railway",         "Goblin-70 + mixer /tickets, grades, income, payout")
    Container(mob,      "Mobile App",    "Capacitor · Railway server.url", "Same live site as browser; OTA off")
    Container(api,      "Flask API",     "Python · Gunicorn · Railway",   "/api/props /api/grades /api/tickets")
    Container(pipeline, "Pipeline",      "Python · run_daily.ps1",        "Steps 1–8 per sport, daily PS1 orch.")
    Container(g70,      "Goblin-70",     "build_goblin70_tickets.py",     "Goblin-70 first; merges mixer from grade pool")
    Container(ml,       "ML Model",      "XGBoost · edge_model_unified",  "AUC 0.7567 (2026-06-13)")
    ContainerDb(cache,  "JSON Cache",    "Flat-file · GitHub / Railway",  "step8 + tickets_latest.json (origin/main is live)")
    Container(ps1,      "run_daily.ps1", "PowerShell · local",            "Daily run + Publish-LiveSite.ps1")
  }

  System_Ext(sb,    "Sportsbook APIs")
  System_Ext(stats, "Stats APIs")
  System_Ext(wt,    "Chrome CDP :9222")

  Rel(bettor,    web,      "Views picks, grades, income",   "HTTPS")
  Rel(bettor,    mob,      "Views top edges on mobile",     "HTTPS")
  Rel(operator,  ps1,      "Triggers daily + refresh tasks", "PowerShell / Task Scheduler")
  Rel(operator,  web,      "Monitors pipeline, views data", "HTTPS")
  Rel(web,       api,      "Reads props, grades, tickets",  "JSON / HTTP")
  Rel(mob,       api,      "Reads top edges, sparklines",   "JSON / HTTP")
  Rel(api,       cache,    "Reads cached output",           "File I/O")
  Rel(ps1,       pipeline, "Triggers sport pipelines",      "subprocess")
  Rel(pipeline,  ml,       "Scores props via step7",        "pkl · predict_proba")
  Rel(pipeline,  cache,    "Writes step8 JSON output",      "File I/O")
  Rel(ps1,       g70,      "Rebuilds Goblin-70, patches mixer", "--write-web")
  Rel(g70,       cache,    "Writes dual tickets_latest.json", "File I/O")
  Rel(pipeline,  sb,       "Fetches odds + lines")
  Rel(pipeline,  stats,    "Fetches player + game stats")
  Rel(pipeline,  wt,       "CDP step1 for Soccer/Tennis/WNBA/MLB")
```

---

## C4 Level 3 — Flask API components

Internal structure of the Flask API container.

```mermaid
C4Component
  title PropORACLE — Flask API Components

  Container_Boundary(api, "Flask API · Python / Gunicorn") {
    Component(home,    "Home route",          "/  /api/run",          "Slate UI, pipeline trigger")
    Component(tickets, "Tickets route",       "/tickets /api/tickets","Goblin-70 first, graded-main mixer under")
    Component(grades,  "Grades route",        "/grades /api/grades",  "Hub iframe, graded props feed")
    Component(income,  "Income route",        "/income",              "P&L dashboard")
    Component(payout,  "Payout route",        "/payout",              "Multiplier, rate cards, log")

    Component(train,   "train_edge_model",    "scripts/",             "XGBoost retrain, temporal split")
  }

  Container(g70,     "Goblin-70 builder", "build_goblin70_tickets.py")
  Container(teval,   "Ticket eval",       "build_ticket_eval.py")
  ContainerDb(cache, "JSON Cache", "tickets_latest.json + eval HTML")
  Container(ml,      "ML Model",   "XGBoost pkl · AUC 0.7567")

  Rel(tickets, cache, "reads prebuilt dual card")
  Rel(grades,  cache, "reads graded props / eval HTML")
  Rel(g70,     cache, "writes Goblin-70 + mixer")
  Rel(teval,   cache, "writes ticket_eval HTML")
  Rel(home,    train, "triggers retrain")
  Rel(train,   ml,    "writes new pkl")
```

---

## Use case summary

### Actors

| Actor | Type | Description |
|---|---|---|
| Bettor / Analyst | Person | Primary consumer — browses slate, tickets, grades, income, payout tools, and mobile app |
| Operator | Person | Runs pipelines, grades slates, retrains model, publishes artifacts; also browses as Bettor |
| Task Scheduler | System actor | Automated — triggers `run_daily.ps1` and grader on schedule |
| PrizePicks | External | Real-money entries happen here; PropORACLE only supports research and ticket building |

### Use case packages

| Package | Use cases |
|---|---|
| **Slate & research** | View home slate, browse by sport, hot players / consistency, model performance, export Excel |
| **Tickets** | Goblin-70 + mixer (latest), by date, EV & win-rate summaries, ticket backtest |
| **Grades & evaluation** | Grades hub, browse graded props, slate eval report, ticket eval report |
| **Income & tracking** | Income / P&L dashboard, grade history & sport breakdown |
| **Payout tools** | Estimate multiplier, rate cards & combo table, log observation, payout ladder, export logs |
| **Mobile app** | Remote Railway in Capacitor shell (canonical). Bundled `www/` + OTA are offline fallback only. |
| **Pipeline & ops** | Run step from UI, monitor job, daily / sport pipeline, grade slate, Goblin-70 --write-web, publish artifacts |

### Key `<<include>>` relationships

```
Run daily pipeline  ──includes──►  Run sport pipeline
Run sport pipeline  ──includes──►  Fetch PrizePicks slate
Run sport pipeline  ──includes──►  Enrich & rank props
Run sport pipeline  ──includes──►  Build combined tickets
Build combined tickets ─includes─►  Goblin-70 --write-web
Goblin-70 --write-web ──includes──►  Publish UI artifacts
Run daily pipeline  ──includes──►  Publish UI artifacts
Grade completed slate ─includes──► Publish UI artifacts
Run pipeline step (UI) ─includes─► Monitor pipeline job
OTA bundle update   ──extends───►  Verify deploy / health   (bundled fallback only; remote app skips OTA)
```

---

## Sport pipeline coverage

| Sport | AUC (2026-05-25) | Step8 join rate | Notes |
|---|---|---|---|
| MLB | 0.7268 | ~99.1% | Strong — name_aliases fix resolved join rate |
| NBA | 0.6175 | — | Watch |
| NBA1H | 0.4511 | — | ⚠ Below random on May slice — suppress or investigate |
| NHL | 0.6905 | ~38% | ⚠ Low join rate — backfill 13 dates (Feb/Mar) |
| Soccer | 0.7478 | — | Strong — Level 2 opponent context planned |
| WNBA | 0.6954 | — | CDP browser-first when `:9222` listening |
| Tennis | 0.6624 | ~4% | Step1 `--cdp` / `--fail-fast`; excluded from Jun-13 tree retrain |

**Overall model AUC:** see [CURRENT_STATE.md](../CURRENT_STATE.md) (production artifact may differ from May-25 holdout numbers above).

**Fetch note (2026-07-20):** Summer boards prefer **CDP-first** via `utils/prizepicks_cdp.py` when Chrome debug is warm; HTTP-only stacks hang on DataDome. Ops cadence: [guides/DAILY_OPS_OVERVIEW.md](../guides/DAILY_OPS_OVERVIEW.md).

---

## Related files

| File | Purpose |
|---|---|
| `docs/diagrams/c4-context.puml` | C4 Level 1 — System context (PlantUML) |
| `docs/diagrams/c4-containers.puml` | C4 Level 2 — Containers (PlantUML) |
| `docs/diagrams/c4-components-flask.puml` | C4 Level 3 — Flask API components (PlantUML) |
| `docs/diagrams/proporacle-use-cases.puml` | Full UML use case diagram (PlantUML) |
| `docs/architecture/USE_CASE_DIAGRAM.md` | Use case catalog + render instructions |
| `docs/PROJECT_LAYOUT.md` | Folder contracts |
| `docs/guides/DAILY_OPS_OVERVIEW.md` | Audiences + scheduled program structure |
| `utils/prizepicks_cdp.py` | Shared CDP attach + in-page projections fetch |
| `utils/step8_edge_direction.py` | Canonical edge computation (pipeline, not `/tickets` request path) |
| `scripts/train_edge_model.py` | ML model retraining (`--temporal-split`) |
| `scripts/build_ticket_eval.py` | Ticket eval + void-aware settlement (Grades) |
| `scripts/build_goblin70_tickets.py` | Live `/tickets` dual card (`--write-web`) |
| `scripts/Publish-LiveSite.ps1` | Push `tickets_latest.json` to origin/main |
| `scripts/run_daily.ps1` | Full daily pipeline orchestration |
