# RaaScal Watch 0.4.0 — active review queue and contract lifecycle cleanup

Version 0.4.0 separates current review work from historical intelligence.

## Active contracts only by default

The standard dashboard now includes a contract in the review queue only when:

- its source status is not closed, inactive, resolved, settled, expired, finalized, or cancelled; and
- its recorded close time has not passed.

A past close time overrides a stale `open` status. This is important because active-only source APIs may stop returning a contract after it closes, leaving its last stored status unchanged.

Closed or expired records are **not deleted**. They move automatically to an explicit Archive view so RaaScal Watch can retain history for deduplication, backtesting, and research without presenting old contracts as current work.

## Archive is separate from review

The Archive view:

- is never the default;
- has no review dropdown;
- has no acknowledgement control;
- labels records as archived and explains why; and
- preserves old market history for research and model calibration.

The active and archive summary counts are calculated separately.

## One card per exact contract

A single public contract can match several monitored organizations. Version 0.4.0 combines those organization-specific matches on one contract card instead of repeating the title once per organization.

Each organization still receives its own role-aware review questions and recommended next steps inside the active-contract review panel.

## Related contracts are grouped

Thresholds, dates, and outcomes belonging to the same source event or Kalshi event ticker are grouped beneath a collapsible market-series header. The individual contracts remain visible when expanded, but repeated near-identical cards no longer dominate the queue.

## Cleaner titles

Polymarket cards display the specific tradable question rather than concatenating the broader event title with a nearly identical question. Stored event context remains available for matching and grouping.

## Filters no longer require an Apply button

The old Apply/Filter button has been removed. Organization, severity, source, review state, and sort selections submit automatically as soon as they change.

The dashboard also displays active filter chips and a clear-filter link. Sorting options now include:

- Highest priority
- Closing soonest
- Highest volume
- Newest match

## Review controls are lifecycle-aware

Only active contracts can be marked reviewed. The contract-level action marks every organization-specific match on that exact contract as reviewed. Archived contracts are rejected by both the dashboard and acknowledgement APIs.

## Migration behavior

No live records are deleted during the update. Existing SQLite history, source baselines, acknowledgements, notification settings, and contract-specific guidance are preserved.

The lifecycle split is calculated from stored status and close time, so expired records disappear from the active queue immediately after the update without requiring another large scan.
