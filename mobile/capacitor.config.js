const RAILWAY_LIVE_URL = "https://web-production-f280f.up.railway.app";

// Canonical: remote Railway. Bundled www/ is fallback only (PROPORACLE_MOBILE_MODE=bundled).
const bundled =
  String(process.env.PROPORACLE_MOBILE_MODE || "").trim().toLowerCase() ===
  "bundled";
const remoteUrl = String(
  process.env.PROPORACLE_SERVER_URL || RAILWAY_LIVE_URL
).trim();

const config = {
  appId: "com.proporacle.app",
  appName: "PropORACLE",
  webDir: "www",
};

if (!bundled && remoteUrl) {
  config.server = {
    androidScheme: remoteUrl.startsWith("https:") ? "https" : "http",
    url: remoteUrl,
  };
}

module.exports = config;
