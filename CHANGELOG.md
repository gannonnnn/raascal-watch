# Changelog

## 0.2.1 — Kalshi source reliability

- Added automatic fallback from Kalshi's recommended `external-api` host to
  its officially supported `api.elections` compatibility host when the primary
  host returns HTTP 403/404 or cannot be reached.
- Preserves the working Kalshi host for later scans during the same app session.
- Added clearer HTTP diagnostics with status code and a short response-body
  preview.
- Excludes multivariate combination markets by default to reduce irrelevant
  sports-combo noise and collection volume.
- Added configurable Kalshi page size and inter-page pacing.
- Documented both Kalshi production hosts in `.env.example` and added automated
  fallback coverage.

## 0.2.0 — Multi-organization monitoring profiles

- Added enabled watch profiles for **Cloudflare**, **YouTube**, and **MrBeast / Beast Industries** while retaining Spotify.
- Added an `availability_and_incident` category for outage, DDoS, service-disruption, and security-incident contracts.
- Added a `direct_control_and_advance_knowledge` category for creator-controlled speech, upload timing, titles, scripts, and release plans.
- Added synthetic demo records showing Cloudflare availability risk and a single MrBeast contract matching both the creator and YouTube as the platform/oracle.
- Replaced the long comma-separated watchlist display with organization chips.
- Clarified dashboard labels so results are presented as market records and candidate matches rather than confirmed threats.
- Added backward compatibility for the early `RW_*` environment-variable prefix; `RAASCAL_*` remains the preferred prefix.
- Expanded automated coverage for Cloudflare, YouTube, MrBeast / Beast Industries, multi-party matches, and legacy environment settings.
