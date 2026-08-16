# RaaScal Watch v0.7.1

## Source refresh resilience

This maintenance release fixes two source-refresh problems exposed during live use.

### Kalshi priority-series fix

Flight-cancellation dependency rules can contain a family prefix such as `KXFLYCANC`, while the tradable Kalshi series use concrete tickers such as airport-specific variants. Earlier code could send the family prefix to Kalshi as if it were an exact `series_ticker`. A rejection from that optional targeted request could then stop the complete Kalshi refresh.

v0.7.1 now:

- discovers concrete series tickers from Kalshi series metadata;
- verifies exact configured series with the official single-series endpoint;
- never queries an unverified family prefix as an exact series; and
- continues the broad Kalshi scan when one optional priority series is unavailable.

### Polymarket DNS diagnostics

A message such as `nodename nor servname provided, or not known` is a DNS-resolution failure on the current device or network, not a market-data parsing failure. The collector still retries conservatively, and the dashboard now provides a clearer explanation that stored results remain available while the next scheduled scan retries.

### Data safety

This update does not delete the local database, reviewer feedback, source history, watchlist customizations, public-visibility snapshots, or notification settings.
