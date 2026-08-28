# Live JSON (disk canonical)

Generated latest tickets/slate/status JSON belongs here.

- **This folder** is the canonical *disk* copy for Flask when running locally.
- **`ui_runner/templates/`** still holds the same files because Railway reads them from GitHub raw `origin/main`. Do not drop that mirror until the GitHub URL cutover is done.
- **`ui_runner/data/`** is dated history / snapshots, not the live board.
- **`mobile/www/`** is not live. The Android app loads the Railway site remotely.

Writers (`combined_slate_tickets.py`, `build_goblin70_tickets.py`) mirror live `*_latest.json` and `slate_sport_*.json` into this directory automatically.
