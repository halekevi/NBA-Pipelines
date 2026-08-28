# PropORACLE Mobile (Capacitor)

**Canonical Android project (this machine):** `H:\PropORACLE\mobile\android`  
Always run **`npm run sync:*`**, **`npx cap copy android`**, and Android Studio from the **`H:\PropORACLE\mobile`** folder so Gradle and `app/src/main/assets/public` stay in sync. If you also have a OneDrive clone, do **not** open `...\OneDrive\...\mobile\android` for builds — use the H: tree, or run **`npm run open:android:studio`**.

The APK is a **native shell around a WebView**. **Canonical mode is remote Railway:** the app loads the live site (`https://web-production-f280f.up.railway.app`), same as a phone browser. `/tickets` and slate JSON update when `Publish-LiveSite.ps1` lands on `origin/main` — no APK rebuild.

OTA (`ota-config.json`) stays **off**. Remote mode does not need a `www/` zip.

| Mode | What loads | When to use |
|------|------------|-------------|
| **Remote (canonical)** | Railway URL in `capacitor.config.js` (`server.url`) | Daily use. Live `/tickets` after every refresh. |
| **Bundled (fallback)** | Files under `mobile/www/` in the APK | Offline / no Railway. Requires `npm run sync:bundle` and an APK rebuild after UI changes. |

## Remote build (canonical)

`capacitor.config.js` already points at Railway. From `mobile/`:

```powershell
npm run sync:remote
```

That syncs Android with the Railway URL (or `$env:PROPORACLE_SERVER_URL` if you override it). Then Android Studio: **Build → Clean Project**, then **Run**.

Override URL (LAN Flask, different Railway hostname):

```powershell
cd mobile
$env:PROPORACLE_SERVER_URL="https://your-real-app.up.railway.app"
npm run sync:remote
```

(`sync:remote` requires `https://` when you set the env var.) **Railway “Not Found”** means the hostname is wrong or no service is listening — fix the Railway project or the URL, not the Capacitor shell.

LAN dev (device on same Wi‑Fi as PC):

```powershell
npm run sync:dev
# or
npm run sync:url --url=http://YOUR_LAN_IP:5173
```

## Bundled fallback (offline only)

Sets `PROPORACLE_MOBILE_MODE=bundled` so `server.url` is omitted and the WebView uses `www/`:

```powershell
cd mobile
npm run sync:bundle
```

Then rebuild the APK. Refresh `www/` with `scripts/generate_mobile_bundle.py` first if you need current HTML/JSON inside the package.

Python does **not** run inside the WebView. Bundled mode is static files only.

## What reaches users without a new APK

| Change | Remote (canonical) | Bundled fallback |
|--------|--------------------|------------------|
| Flask templates / `ui_runner/static` on **Railway** | **Yes** — reopen the app or refresh | No — rebuild APK |
| `mobile/www/` files | N/A (site owns UI) | After `sync:bundle` + rebuild |
| `capacitor.config.js`, Gradle, native code | New sync + rebuild | New sync + rebuild |

## Reinstall checklist

1. Uninstall the old app if you switched **bundled ↔ remote**.
2. Run `npm run sync:remote` (or `sync:bundle` for offline).
3. **Build → Clean Project** → Run.

## Troubleshooting

* **`ERR_CONNECTION_ABORTED` to `http://10.x.x.x:5173`:** LAN remote; PC unreachable or IP changed. Use **`npm run sync:remote`** for Railway, or fix LAN and `sync:url`.

* **Railway “Not Found” / train page:** `server.url` points at a hostname with **no active Railway service**. Set `PROPORACLE_SERVER_URL` to the public URL shown in Railway, then `npm run sync:remote`.

* **Stale URL after switching modes:** Uninstall the app, then sync + reinstall.

## Recent fixes

* **MainActivity.java:** WebView listener hides duplicate chrome where needed.
* **colors.xml:** Resolves missing resource warnings in Android Studio.
