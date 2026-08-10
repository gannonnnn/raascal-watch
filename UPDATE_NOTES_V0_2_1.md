# RaaScal Watch 0.2.1 — Kalshi source reliability patch

This patch addresses an environment-specific `403 Forbidden` response from
Kalshi's recommended `external-api.kalshi.com` hostname.

## What changed

- Tries Kalshi's recommended external API host first.
- Automatically fails over to Kalshi's officially supported
  `api.elections.kalshi.com` compatibility host on HTTP 403/404 or a transport
  failure.
- Keeps using the working host for the remainder of the scan.
- Preserves HTTP status and response detail in source-health errors.
- Excludes multivariate combination markets by default to reduce irrelevant
  sports-combo noise and collection volume.
- Adds a short configurable pause between Kalshi pages.

## What this does not imply

A 403 from one host does not establish that Kalshi has blocked RaaScal Watch or
public market-data access generally. The public market-data endpoint remains
unauthenticated, and both production hostnames are documented by Kalshi.
