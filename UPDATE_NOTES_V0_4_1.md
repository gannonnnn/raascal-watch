# RaaScal Watch v0.4.1

## Why this patch exists

Earlier updaters intentionally preserved an existing `config/watchlist.yaml` so a user's custom configuration would not be overwritten. That safeguard had an unintended effect: a project originally installed from v0.2 could receive the new application code and documentation while its local watchlist still contained only the older organizations. FlightAware and OpenAI / ChatGPT could therefore be described as included without appearing in the filter or receiving matches.

v0.4.1 fixes both halves of that problem.

## What changes

### Every enabled profile appears in the organization filter

The filter is populated from the enabled watchlist, not only from organizations that already have an active match. Each option includes the number of active or archived contracts in the current view.

A zero beside an organization means the profile is configured correctly but no current stored contract matches it. It no longer means the profile is missing.

### Built-in profiles merge safely into older local watchlists

The launcher and updater now merge the packaged research profiles into the existing local watchlist. The merge:

- Adds missing built-in organizations such as FlightAware and OpenAI / ChatGPT.
- Adds newly shipped aliases, products, metrics, stakeholders, playbook steps, and risk categories.
- Preserves user-created organizations and local additions.
- Preserves an explicit user choice to disable a profile.
- Creates a timestamped backup before changing the file.

### Stored markets are re-evaluated

Adding a profile should not require waiting for a market to be fetched again. After the watchlist changes, RaaScal Watch re-evaluates its existing SQLite market library and creates missing organization matches.

Backfilled matches are marked historical and do not generate retroactive Slack, email, webhook, or console alerts. Active matching contracts can still enter the active review queue; expired matches remain in Archive.

### Repeat launches remain fast

RaaScal Watch stores a fingerprint of the synchronized watchlist. A later launch skips the re-index when the profile configuration has not changed.

## New command

```bash
raascal-watch sync-profiles --defaults ./config/watchlist.defaults.yaml
```

Use `--force` to re-evaluate stored market records even when the watchlist fingerprint is unchanged.

## Expected FlightAware behavior

After installing v0.4.1:

1. FlightAware appears in the organization filter even before it has a match.
2. The local market library is re-evaluated for FlightAware references in titles and rules.
3. A new live scan checks the current Kalshi and Polymarket listings using the synchronized profile.
4. Matching active contracts appear in the Active review queue; expired contracts remain in Archive.
