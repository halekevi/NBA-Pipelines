# PropORACLE Mobile App Structure

This map outlines the relationship between the **live Railway site** (canonical Android UI) and the optional bundled `www/` fallback.

## Canonical runtime
- **Android WebView** loads `https://web-production-f280f.up.railway.app` (`mobile/capacitor.config.js` `server.url`).
- Live tickets/slate come from Railway → GitHub raw `ui_runner/templates/*_latest.json` after `Publish-LiveSite.ps1`.
- OTA is **off**. Do not treat `mobile/www/` JSON as the live board.

## Project Roots
- **Mobile Root**: `mobile/`
- **Capacitor Project Config**: `mobile/capacitor.config.js`
- **Mobile NPM Scripts**: `mobile/package.json` (`sync:remote` canonical; `sync:bundle` offline fallback)

## Web UI Source (bundled fallback only)
- **Offline copy**: `mobile/www/` (from `scripts/generate_mobile_bundle.py`)
- **Payout Logger Source**: `mobile/www/payout_log.html`
- **Shared Templates (Server-side)**: `ui_runner/templates/payout_log.html`

## Android Native Project
- **Android Root**: `mobile/android/`
- **App Module**: `mobile/android/app/`
- **Android Manifest**: `mobile/android/app/src/main/AndroidManifest.xml`
- **MainActivity**: `mobile/android/app/src/main/java/com/proporacle/app/MainActivity.java`

## Bundled Assets (Inside APK)
- **Bundled Web Assets**: `mobile/android/app/src/main/assets/public/` (unused while `server.url` is set)
- **Capacitor Runtime Config**: `mobile/android/app/src/main/assets/capacitor.config.json`
