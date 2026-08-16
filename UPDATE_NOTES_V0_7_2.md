# RaaScal Watch v0.7.2

## Incremental Kalshi refreshes

This maintenance release addresses recurring HTTP 403 responses that appeared late in broad Kalshi pagination. Earlier versions could replay up to roughly 100,000 open and unopened market records every scheduled scan, even after the local baseline already existed.

v0.7.2 keeps the initial baseline behavior, then changes later Kalshi scans into two bounded jobs:

1. **Refresh current matches by ticker.** Active Kalshi contracts already in the review queue are refreshed in comma-separated ticker batches so status, close time, probability, volume, liquidity, and open interest stay current.
2. **Discover new contracts incrementally.** Open and unopened discovery uses `min_created_ts` based on the last successful Kalshi scan, with a configurable overlap window to avoid missing contracts created near the boundary.

Configured priority series, including flight-cancellation families, are still queried directly before incremental discovery.

## Host behavior

Both documented Kalshi production hosts remain supported. On consumer networks, RaaScal Watch now prefers:

```text
https://api.elections.kalshi.com/trade-api/v2
```

and retains this host as automatic fallback:

```text
https://external-api.kalshi.com/trade-api/v2
```

Despite the subdomain name, the compatibility host provides all Kalshi market categories.

## New settings

```dotenv
RAASCAL_KALSHI_PREFER_COMPATIBILITY_HOST=true
RAASCAL_KALSHI_INCREMENTAL_SCAN=true
RAASCAL_KALSHI_INCREMENTAL_PAGE_SIZE=250
RAASCAL_KALSHI_INCREMENTAL_PAGE_LIMIT=12
RAASCAL_KALSHI_DISCOVERY_OVERLAP_MINUTES=180
RAASCAL_KALSHI_REFRESH_ACTIVE_MATCHES=true
RAASCAL_KALSHI_REFRESH_BATCH_SIZE=50
```

Existing `.env` files do not need to be edited. These defaults are applied by the application when the variables are absent.

## Expected behavior after updating

- The existing database, baseline, reviews, snapshots, and archive are preserved.
- The next ordinary Kalshi scan should use incremental discovery rather than a 100-page catalog replay.
- Terminal logs should include `Kalshi incremental refresh` and `Kalshi incremental discovery`.
- The request count will vary with the number of active Kalshi matches, but it should be far lower than the earlier full-catalog schedule.
- If the Kalshi baseline is explicitly reset, the next scan intentionally performs a broad baseline again.

## Limitations

- Incremental discovery finds contracts created after the last successful scan. It is not a substitute for a periodic reconciliation job if Kalshi changes old contract metadata in a way that is unrelated to an already matched contract.
- Active ticker refresh is limited to contracts already matched by an organization or monitored theme.
- A source-level outage or network block can still interrupt a refresh; stored results remain available and the next scan retries.
