# Changelog

## 0.5.0 — Theme and dependency-aware flight-cancellation monitoring

- Added **Flight cancellation markets** as a monitored theme so cancellation contracts can surface without assuming one organization owns the result.
- Added configured FlightAware dependency mappings for Kalshi airport-cancellation and weekly U.S. flight-cancellation families.
- Added transparent match-basis labels: direct, verified dependency, linked dependency, possible dependency, and theme.
- Added settlement-source metadata matching so a generic source label that links to FlightAware can still create an explainable dependency match.
- Added targeted Kalshi series pulls driven by dependency rules, preventing monitored niche families from being missed by the broad page cap.
- Added Transportation-series discovery for concrete tickers matching configured family prefixes such as `KXFLYCANC...`.
- Updated the profile filter to separate organizations from monitored themes while preserving one-card multi-profile results.
- Updated stored-market backfill to search raw source metadata and ticker prefixes, with no retroactive notifications.
- Added automated coverage for direct, verified, linked, theme-only, priority-series, series-discovery, profile-sync, and dashboard-filter behavior.

## 0.4.1 — Profile synchronization and stored-market backfill

- Fixed an updater issue that preserved an older local `watchlist.yaml` without adding newly shipped profiles such as FlightAware and OpenAI / ChatGPT.
- Added a safe watchlist merge that appends missing built-in organizations, terms, playbooks, and risk categories while preserving custom organizations and local additions.
- Creates a timestamped backup before modifying an existing watchlist.
- Added `raascal-watch sync-profiles` and a watchlist fingerprint so stored markets are re-evaluated only when the configured profiles change.
- Backfills organization matches from the existing SQLite market library without sending retroactive notifications.
- The organization filter now lists every enabled profile, including profiles with zero active matches, and displays active/archive counts.
- Added a clearer empty state distinguishing an enabled profile with no current match from a missing profile.
- Added automated coverage for legacy-watchlist migration, FlightAware backfill, zero-match filter visibility, and no-op repeat launches.

## 0.4.0 — Active review queue and lifecycle-aware UI

- Made the standard review queue active-only using both source status and closing time.
- Added a separate Archive view for closed, inactive, settled, finalized, cancelled, and expired contracts.
- Removed review and acknowledgement controls from historical records.
- Changed dashboard summary counts and filter options to reflect the selected active/archive lifecycle view.
- Added one contract card per exact market and combined multi-organization matches on that card.
- Grouped related dates, thresholds, and outcomes beneath collapsible source-event series.
- Cleaned repetitive Polymarket titles while preserving broader event context for matching and grouping.
- Removed the unreliable Apply button and added automatic filter submission, active-filter chips, and clear-filter navigation.
- Added sorting by priority, closing time, cumulative volume, and newest match.
- Added contract-level review acknowledgement and blocked archived contracts from acknowledgement APIs.
- Changed CLI exports to active-only by default, with explicit `--view archive` and `--view all` options.
- Added automated coverage for lifecycle filtering, archived-record preservation, grouping, title cleanup, multi-organization cards, sorting, and the new filter UI.

## 0.3.1 — Contract-specific review guidance

- Replaced the generic “Review rationale and playbook” dropdown with **Review this specific contract**.
- Added role inference for named subjects, platform/metric owners, resolution-data sources/oracles, direct controllers, availability targets, reporting/KPI owners, benchmark participants, and decision owners.
- Added contract-specific review questions and next steps generated from the actual title, rules, source, probability, cumulative volume, open interest, close time, matched metrics, and organization profile.
- Added clear economic-context language distinguishing cumulative volume from a trader's potential payout.
- Added database migration support for role and review-question fields while preserving existing live history, baselines, alert states, and acknowledgements.
- Added `raascal-watch refresh-guidance` to update existing live matches locally without another API scan.
- Included the new fields in dashboard APIs, CSV/JSON exports, email/console alerts, Slack, and generic webhook payloads.
- Added automated coverage for FlightAware oracle guidance, YouTube platform guidance, MrBeast/OpenAI advance-knowledge guidance, database migration, persistence, and local guidance refresh.

## 0.3.0 — Live-only monitoring and new topical profiles

- Removed automatic synthetic demo seeding from normal startup.
- Added `raascal-watch purge-demo` and automatic cleanup of demo records while preserving all live Kalshi and Polymarket history.
- Dashboard totals, filters, recent scans, APIs, and exports now exclude demo records by default.
- Added a new `start-raascal-watch.command` launcher; the older `start-demo.command` remains as a compatibility wrapper.
- Added enabled profiles for **FlightAware** and **OpenAI / ChatGPT**.
- Added `oracle_and_data_dependency` scoring for contracts that depend on a company's data, public counter, status page, or named settlement source.
- Added `benchmark_and_evaluation_integrity` scoring for AI leaderboards, arena scores, benchmarks, and model rankings.
- Clarified dashboard labels as live public-market records and live candidate matches.
- Added tests for live-only queries, demo purging, FlightAware settlement-source matching, OpenAI release/outage matching, and AI benchmark integrity.

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
