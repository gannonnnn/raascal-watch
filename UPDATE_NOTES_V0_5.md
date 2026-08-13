# RaaScal Watch v0.5.0

## Flight-cancellation themes and FlightAware dependencies

Version 0.5.0 separates **what a contract is about** from **which organization supplies data or otherwise participates in settlement**.

### Two filters, one contract

A qualifying cancellation contract can now be found under:

- **Flight cancellation markets** — a topic-level theme that does not assume one company owns the result.
- **FlightAware** — only when a direct mention, configured contract-family rule, or settlement-source link establishes a relationship.

The same exact contract appears once and can carry both profile labels. Each profile keeps separate role-aware questions and next steps inside the review panel.

### Match-basis labels

The review panel distinguishes:

- **Direct** — FlightAware is named in visible contract text.
- **Verified dependency** — official product terms, known series metadata, or a settlement-source link establishes the relationship.
- **Linked dependency** — public evidence links the contract family to FlightAware, but the current iteration should be confirmed before escalation.
- **Theme** — the contract concerns flight cancellations; this is not an attribution to FlightAware.

### Priority Kalshi collection

The broad Kalshi collector can reach a page cap before a niche family appears. Version 0.5.0 therefore:

1. Reads priority Kalshi series from configured dependency rules.
2. Inspects the Transportation series list for concrete tickers matching configured prefixes.
3. Queries open and unopened markets for those series directly.
4. Deduplicates those records against the broad Kalshi pull.

This directly targets the weekly `KXUSFLYCAN` family and discovers airport-specific `KXFLYCANC...` series when Kalshi exposes them in series metadata.

### Existing installations

The updater:

- merges the new theme and dependency rules into the existing watchlist;
- creates a timestamped backup of the prior watchlist;
- re-evaluates the existing SQLite library for matching ticker families and settlement-source metadata;
- preserves `.env`, `.venv`, market history, baselines, acknowledgements, and custom profiles;
- does not send retroactive notifications for backfilled relationships.

### Important limitation

RaaScal Watch does not assume that every flight-cancellation contract uses FlightAware. Unverified contracts remain under the **Flight cancellation markets** theme only. Dependency mappings should be reviewed when an exchange changes its rules, source agency, ticker family, or settlement link.
