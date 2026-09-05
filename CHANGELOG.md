# Changelog

## 0.9.1

Fix blocked dashboard during first scans; offload scoring/writes into bounded batches; add 202 scan jobs, lightweight progress, cooperative cancellation, worker-safe SQLite transactions, responsive request handlers, root-file regression checks and clean-start CI. See UPDATE_NOTES_V0_9_1.md.


## 0.9.0 — Earnings-call mention markets and corporate-controlled outcomes

- Added the **Earnings-call mention markets** monitored theme.
- Extracts the changing company and exact controlled word, phrase, or threshold from Kalshi and Polymarket metadata.
- Added a **corporate-controlled outcome** risk pathway with direct-control, pre-public-access, policy-coverage, and vendor-access analysis.
- Added earnings-call-specific materiality, review questions, next steps, Incentive Maps, and Field Note headline.
- Corrected theme guidance so App Store and earnings-call markets no longer receive flight-cancellation questions.
- Added migration coverage for watchlist merging and stored-market re-evaluation.

## 0.8.0 — Materiality gates and App Store ranking monitoring

- Added **Observed**, **Review today**, and **Escalate now** materiality gates so broad candidate retrieval no longer becomes the default human queue.
- Replaced the primary active-candidate count with **Contracts warranting review today** and retained lower-materiality results under Observed.
- Added deterministic dimensions for relationship evidence, influenceability, information advantage, economic exposure, settlement urgency, downstream impact, and market movement.
- Added a transparent legacy retrieval-score breakdown so a 100/100 score can be traced to additive components and distinguished from the materiality decision.
- Added latest/approximately 24-hour probability, volume, open-interest, rule, status, and close-time change analysis from stored snapshots.
- Added source-aware economic context: Kalshi volume/open interest are displayed as contract counts, while Polymarket values retain reported currency context.
- Added gate-aware next steps and ordinary notification suppression for newly observed contracts that do not warrant human review.
- Added **Apple App Store** as a metric-owner / resolution-source profile and **App Store ranking markets** as a monitored theme.
- Added dynamic extraction of changing app/company outcomes from App Store ranking listings.
- Added App Store-specific influence and downstream-cost guidance, including install quality, paid acquisition, reviews, ranking movement, retention, and false product-demand signals.
- Added a direct human-confirmed actionable rate to reviewer calibration.
- Added `raascal-watch materiality-summary` and materiality/risk/dynamic-subject fields to standard exports.
- Added SQLite migrations for materiality analysis, risk-score breakdowns, dynamic subjects, close-time history, and rule hashes while preserving existing data and reviews.
- Added automated coverage for gate separation, movement promotion, source units, App Store profiles, dynamic subjects, UI explanation, snapshots, and CLI summaries.

## 0.7.2 — Incremental Kalshi refreshes

- Prefer Kalshi's officially supported compatibility host on consumer networks while retaining automatic host failover.
- After the first successful baseline, discover only newly created open and unopened contracts using a timestamp overlap.
- Refresh already matched active Kalshi contracts in bounded ticker batches so probability, volume, status, and close times remain current.
- Avoid re-reading roughly 100,000 Kalshi catalog records every 15 minutes.
- Preserve full-catalog pagination for a true first baseline or an explicit baseline reset.
- Add source-context tests and database helpers for incremental collectors.

## 0.7.1 — Source refresh resilience

- Stops treating configured Kalshi family prefixes as exact `series_ticker` values.
- Verifies exact Kalshi series through `GET /series/{series_ticker}` and discovers concrete prefixed series before targeted market pulls.
- Isolates optional priority-series failures so one niche contract family cannot abort the entire Kalshi refresh.
- Adds clearer DNS-resolution diagnostics for Polymarket and other source transport failures.
- Clarifies in the dashboard that stored results remain available while a source refresh is incomplete.

## 0.7.0 — Incentive Maps and post-close public visibility

- Added a deterministic **Incentive Map** to every profile match, including YES/NO beneficiary sides, displayed-price payout math, plausible information holders, influence pathways, settlement sources, cost bearers, and evidence limits.
- Added an explicit information-advantage assessment and an evidence ladder that separates a financial incentive from identity, access, anomalous timing, and independently corroborated misconduct.
- Added operational-waterfall guidance showing how a financially incentivized metric can become a false internal signal and redirect Product, Engineering, Growth, Fraud, Security, Finance, or leadership decisions.
- Added market snapshots for probability, volume, 24-hour volume, liquidity, open interest, and status changes.
- Added on-demand source-aware public-exposure snapshots. Polymarket can return public wallet positions, average price, size, realized/total P&L, top holders, open interest, and trades; Kalshi remains aggregate-only for public participant analysis.
- Added post-close public visibility to Archive so historical contracts can be examined without reopening them as active alerts.
- Added a screenshot- and print-friendly Field Note view for each contract/profile relationship.
- Made the Mac launcher more explicit and removed slow pre-dashboard summary queries from the startup path.
- Added Incentive Maps to webhook payloads, plain-text alerts, database persistence, API results, and standard exports.
- Added SQLite migrations for market movement and public-exposure history while preserving existing contracts, reviews, baselines, and custom profiles.
- Added automated coverage for payout math, source-specific traceability, public position/P&L parsing, Kalshi trade failover, movement snapshots, archive evidence review, and Field Note rendering.

## 0.6.0 — Reviewer feedback and calibration

- Added structured profile-match decisions: **Actionable**, **Monitor**, **Informational**, and **False positive**.
- Added optional reason tags, guidance-usefulness ratings, corrected-role fields, better-owner suggestions, and reviewer notes.
- Added a persistent `review_feedback` SQLite table that migrates into existing local databases without resetting market history.
- Replaced the binary card-level review control with profile-level assessment progress so one multi-organization contract can receive different decisions for each affected party.
- Added reviewer-decision filters and **Unreviewed first** sorting.
- Added a calibration panel with reviewed/unreviewed counts, actionable-or-monitor rate, false-positive rate, guidance usefulness, and breakdowns by profile and risk pathway.
- Preserved structured assessments when contracts move to Archive while removing editing controls from historical records.
- Added `/api/matches/{match_id}/feedback`, `/api/calibration`, and `/api/feedback` endpoints.
- Added `raascal-watch export-feedback` and included feedback fields in the standard CSV/JSON match export.
- Retained legacy acknowledgements separately so earlier review work is not falsely treated as structured calibration data.
- Added automated coverage for schema migration, API validation, decision filtering, multi-profile progress, archive preservation, calibration metrics, export, and unreviewed-first sorting.

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
