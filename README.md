# RaaScal Watch

**External incentive intelligence for operational risk teams**

> **Status:** Experimental prototype. Not intended for production decision-making.

RaaScal Watch monitors public prediction-market listings for contracts that reference a company, its products, executives, data sources, or important business metrics. It creates an explainable candidate alert showing what changed, why it may matter, who could own the review, and what the first response steps could be.

The core question is not simply **“Was our company mentioned?”** It is:

> Has a new outside financial incentive appeared around our platform, data, brand, operational event, or internal decision?

## Why this matters

A prediction-market contract can attach money to streams, rankings, downloads, subscriber counts, outages, flight cancellations, product releases, benchmark scores, pricing decisions, enforcement outcomes, and other measurable events.

The company named in the market is not always the only party exposed. An organization may be:

- the **subject** of the contract;
- a **controller** with the ability or advance knowledge to affect the outcome;
- the **resolution oracle** whose counter, data, status page, or report determines who gets paid; or
- the **downstream risk bearer** that absorbs investigation cost, contaminated data, legal exposure, operational disruption, or poor decisions.

RaaScal Watch is intended to surface that changed incentive environment before the signal is accepted at face value.

## Version 0.9.1: responsive scans and visible progress

This maintenance release fixes the frozen-dashboard behavior during a large
first scan. Matching and SQLite writes now run in bounded worker batches;
filters and status checks remain available while the scan processes records.
A progress panel shows downloaded versus saved records, and **Stop scan** retains
committed work without marking an unfinished source successful.

The full local scan can still take minutes. Page caps still limit source coverage.
See `UPDATE_NOTES_V0_9_1.md` for the fix, tests, API change, and limitations.

For a clean engineering check after installing the project:

```bash
python -m pytest
python tools/smoke_startup.py
```

The second command uses a temporary database and no external API calls. A new
`.github/workflows/tests.yml` runs both checks on GitHub for future pushes and
pull requests. GitHub Actions must be enabled for that workflow to run.

## Version 0.9: earnings-call mention markets and corporate-controlled outcomes

RaaScal Watch now includes **Earnings-call mention markets** as a monitored theme. It surfaces contracts resolved by a company saying, mentioning, repeating, or avoiding a specific word or phrase during an earnings call or investor call.

The theme dynamically extracts the company and controlled outcome from source metadata, for example:

```text
Company: Dell
Controlled outcome: Agentic
```

These contracts create a different risk pathway from metric manipulation. A relatively small group may have pre-public access to prepared remarks, scripts, rehearsals, webcast systems, call audio, or transcript feeds—and some participants may be able to directly alter the deciding language.

The materiality gate evaluates:

- direct control over the statement or transcript;
- narrow pre-public information access;
- reported economic activity and settlement proximity;
- probability, volume, open-interest, rule, and close-time movement; and
- potential compliance, vendor, disclosure, employee-trust, and reputational cost.

A theme match is not an accusation and does not automatically create an investigation. RaaScal Watch places the contract in **Review today** only when a credible access or control pathway is paired with a current activation trigger. It still requires independent evidence before any conclusion about information misuse or misconduct.

The contract-specific review now asks who had access, who could change the answer, whether employee and vendor policies cover prediction markets, which official audio or transcript settles the outcome, and whether market movement preceded a legitimate public catalyst.

The Field Note headline for this theme is:

> **What if the answer is already in the script?**

Version 0.9 also corrects theme-specific guidance so App Store ranking and earnings-call contracts no longer inherit flight-cancellation questions or next steps.

See `UPDATE_NOTES_V0_9.md` for the dynamic extraction, materiality behavior, migration details, and limitations.

## Version 0.8: materiality gates and App Store ranking monitoring

RaaScal Watch now separates the full candidate library from the small set of contracts that warrant human attention today. The default dashboard is no longer a wall of high-scoring matches. It uses three materiality gates:

- **Observed** — relevant intelligence retained without human action today.
- **Review today** — a credible influence, information, data-dependency, or downstream-impact pathway is paired with a current activation trigger such as material activity, approaching settlement, or market movement.
- **Escalate now** — strong movement, urgency, economic activity, explicit abuse language, or a narrow pre-public access pathway justifies immediate time-bound triage.

The hero metric is **Contracts warranting review today**. Observed contracts remain searchable, but they no longer compete for reviewer attention or generate ordinary notifications.

Every profile review now answers eight practical questions:

1. How was the relationship established, and is it more than a direct phrase match?
2. Why does this contract require action now?
3. Why is the legacy retrieval score 100 rather than 70?
4. What changed in the latest observation window?
5. Is the reported economic activity material, using source-appropriate units?
6. Is there a realistic influence or advance-information pathway?
7. What should the affected company do differently after receiving the signal?
8. What percentage of reviewed results were actually labeled Actionable by a human?

The legacy risk score remains visible as a transparent retrieval score with additive components. It does **not** determine the human queue by itself. The materiality gate uses separate dimensions for relationship strength, influenceability, information advantage, economic exposure, settlement urgency, downstream impact, and observed market movement.

Version 0.8 also adds:

- **Apple App Store** as a metric-owner and resolution-source profile;
- **App Store ranking markets** as a monitored theme; and
- dynamic extraction of the apps or companies named as outcomes, without requiring a static watchlist entry for each app.

This is designed to surface the operational waterfall behind a ranking market: financially incentivized installs, searches, reviews, or promotion may move a public chart; the affected company may interpret the spike as organic demand; Product, Growth, Engineering, or leadership may then reallocate resources around a false signal.

See `UPDATE_NOTES_V0_8.md` for the gate logic, App Store profile, source-unit handling, migration details, and limitations.

## Version 0.7.2: incremental Kalshi refreshes

RaaScal Watch no longer re-reads the entire Kalshi catalog every 15 minutes after a successful baseline.

- A true first baseline still uses broad open/unopened pagination.
- Later scans refresh already matched active Kalshi contracts in bounded ticker batches.
- New-contract discovery uses Kalshi's `min_created_ts` filter with a configurable overlap window.
- The incremental discovery pass uses smaller pages and a separate safety cap.
- The officially supported compatibility host is preferred by default on consumer networks, with the dedicated external host retained as automatic fallback.
- Priority series such as flight-cancellation families are still queried directly before broad discovery.

This reduces request volume substantially while keeping the active review queue and newly created contract discovery current. See `UPDATE_NOTES_V0_7_2.md` for settings and limitations.

## Version 0.7: Incentive Maps and post-close public visibility

RaaScal Watch now explains the economic and operational pathway behind each surfaced contract, rather than relying on a single priority score. Each matched profile receives an **Incentive Map** showing:

- who benefits from the YES and NO outcomes at the displayed market price;
- who may know the answer before public disclosure;
- who could influence the measured event, metric, decision, or data source;
- whose data, status page, counter, report, or decision determines settlement;
- who may absorb the downstream operational cost; and
- how a financially incentivized signal could distort internal Product, Engineering, Growth, Fraud, Security, Finance, or leadership decisions.

The dashboard stores market snapshots when probability, volume, liquidity, open interest, or status changes. It shows the latest movement and creates a screenshot-friendly **Field Note** for each profile relationship.

A source-aware public-exposure check is available on demand. Polymarket snapshots may include public wallet-level positions, average price, size, P&L, top holders, and trades. Kalshi snapshots remain aggregate because public market data does not identify individual account positions. Archived contracts retain a **Post-close public visibility** panel so reviewers can preserve the observable benefit and timing after settlement.

These data are review clues—not an insider-trading determination. A profitable wallet, concentrated position, or well-timed trade does not establish a real-world identity, privileged access, influence, intent, breach of duty, or misconduct.

See `UPDATE_NOTES_V0_7.md` for the evidence model and limitations.

## Version 0.6: reviewer feedback and calibration

RaaScal Watch now measures whether surfaced profile relationships are useful rather than treating every match as equally valuable. Each organization or theme attached to an active contract can receive one structured reviewer assessment:

- **Actionable** — an owner should investigate or change a control now.
- **Monitor** — relevant enough to track, but not an immediate action.
- **Informational** — useful context with no current operational response.
- **False positive** — not meaningfully connected to the profile or risk pathway.

Reviewers can also record why they chose that label, rate the suggested guidance, correct the inferred organizational role, propose a better owner, and add a note. A multi-profile contract is reviewed at the profile-match level because the same market may be actionable for one organization and merely informational for another.

The dashboard includes a calibration snapshot showing structured-review counts, actionable/monitor rate, false-positive rate, guidance usefulness, and breakdowns by profile and risk pathway. The active queue can be filtered by reviewer decision and sorted with unreviewed work first. Structured feedback remains attached when a contract later moves to Archive.

Reviewer assessments are calibration data, not ground truth. They do not prove abuse, trader intent, or misconduct.

See `UPDATE_NOTES_V0_6.md` for the schema, decision definitions, and migration behavior.

## Version 0.5: topic and dependency-aware monitoring

RaaScal Watch can now surface a contract even when the affected organization is absent from the visible title or rules. The first implementation covers flight-cancellation markets.

- **Flight cancellation markets** is a monitored theme. Any qualifying cancellation contract can be filtered under the theme without assuming that one company owns the underlying data.
- **FlightAware** is a separate organization profile. Known Kalshi contract families appear under FlightAware only when a configured product-family rule or settlement-source link establishes a direct, verified, or linked dependency.
- A single contract can appear once with both profiles attached: for example, `Flight cancellation markets` as the topic and `FlightAware` as a resolution-data dependency.
- The review panel labels the match basis as **Direct**, **Verified Dependency**, **Linked Dependency**, or **Theme**, and explains the evidence and confidence.
- Kalshi series referenced by dependency rules are queried directly before the broad market pull. This prevents a niche monitored family from being missed when the broad collector reaches its page cap.
- Kalshi Transportation series are inspected for matching ticker prefixes, allowing airport-specific series such as `KXFLYCANC...` to be discovered even when the series ticker adds an airport suffix.

See `UPDATE_NOTES_V0_5.md` for the relationship model, limitations, and migration behavior.

## Version 0.4: active review queue and historical archive

The normal dashboard now treats **active monitoring** and **historical intelligence** as separate workflows.

- Only contracts whose closing time is still in the future and whose source status is not final appear in the review queue.
- A past close time removes a contract from current review even when the last stored source status still says `open`.
- Closed and expired records are preserved in a separate Archive view for deduplication, backtesting, and research.
- Archive records have no review dropdown and cannot be acknowledged as current work.
- One exact contract appears once, even when it matches several organizations. Each organization retains its own tailored review guidance inside the card.
- Related dates, thresholds, and outcomes are grouped beneath one collapsible event or series.
- Organization, severity, source, state, and sort selections update automatically; there is no Apply button.
- Sorting is available by priority, closing soonest, cumulative volume, or newest match.

See `UPDATE_NOTES_V0_4.md` for the lifecycle rules and migration details.

## Version 0.3.1: contract-specific review briefs

The dashboard dropdown now changes with the individual contract rather than repeating only a generic organization playbook. RaaScal Watch infers the organization’s likely role, records why the listing surfaced, asks role-specific review questions, and generates next steps using the exact title, rules, source, displayed probability, volume, open interest, close time, matched terms, and configured profile.

Typical roles include:

- Named subject or outcome owner
- Platform or public-metric owner
- Resolution-data source or oracle
- Direct-control or advance-knowledge party
- Availability or incident target
- Reporting or KPI owner
- Benchmark or evaluation participant
- Internal decision owner

The launcher also runs `raascal-watch refresh-guidance`, which updates existing locally stored matches without requiring a fresh network scan. See `UPDATE_NOTES_V0_3_1.md` for examples and limitations.

## Version 0.3: synthetic demo data removed from normal use

The normal dashboard now shows **live public-market records only**.

- Synthetic demo records are no longer loaded during startup.
- Any demo records created by earlier versions are removed by the standard launcher.
- Dashboard totals, filters, scan history, APIs, and exports exclude demo records by default.
- Developers can still seed synthetic fixtures explicitly with `raascal-watch seed-demo`.

## What the prototype does

- Collects public market listings from Kalshi and Polymarket
- Uses Kalshi's supported compatibility host first on consumer networks and retains automatic failover to the dedicated external host
- Matches contracts against configurable organization profiles and monitored themes
- Maps configured source/product families to organizations whose data may determine settlement
- Directly queries priority Kalshi series so niche monitored families are not lost behind the broad page cap
- After baseline, refreshes active matched Kalshi contracts by ticker and discovers only newly created contracts with an overlap window
- Detects references to companies, products, executives, public data sources, monitored metrics, and contract topics
- Extracts dynamic companies, apps, and controlled word/phrase outcomes from theme-based contract families
- Distinguishes company-controlled disclosure outcomes from metric manipulation, outages, reporting metrics, and data dependencies
- Labels each relationship as direct, verified dependency, linked dependency, possible dependency, or theme
- Assigns a transparent rule-based priority score
- Explains the terms and market attributes that contributed to the score
- Infers whether the organization is the subject, platform/metric owner, resolution-data source, direct controller, availability target, reporting owner, or benchmark participant
- Generates contract-specific review questions and first steps from the actual title, rules, probability, volume, close time, matched role, and company watchlist
- Recommends stakeholder teams and initial review steps
- Supports a local dashboard, console, Slack, email, and generic webhooks
- Creates a silent first-scan baseline to reduce alert noise
- Stores active and archived market history in SQLite
- Keeps expired contracts out of the current review queue while retaining them for research
- Collapses exact contract duplicates and groups related event thresholds/dates
- Automatically applies filters and supports priority, unreviewed-first, closing-time, volume, and recency sorting
- Captures structured reviewer decisions, reasons, guidance ratings, role corrections, owner corrections, and notes at the profile-match level
- Shows calibration metrics by organization/theme and risk pathway
- Builds an Incentive Map for each profile relationship: beneficiaries, information holders, influence pathways, settlement sources, cost bearers, and evidence limits
- Stores market snapshots when probability, volume, liquidity, open interest, or status changes
- Provides on-demand source-aware public exposure snapshots, including wallet-level Polymarket positions/P&L when publicly available and aggregate-only Kalshi trade visibility
- Keeps post-close public visibility available in Archive without reopening historical contracts as current review work
- Generates a screenshot- and print-friendly Field Note for each contract/profile relationship
- Exports structured review feedback and Incentive Maps to CSV or JSON
- Includes automated tests and optional synthetic fixtures for development

The prototype only reads public market-listing data. It does not place trades, access private accounts, or identify individual traders.

## Included research profiles

The default watchlist includes enabled organization profiles for:

- **Spotify** — engagement, streams, rankings, subscriber reporting, and product analytics
- **Cloudflare** — availability, incidents, DDoS, status data, and security operations
- **FlightAware** — verified or linked settlement-data dependencies, flight operations, data licensing, and brand use
- **YouTube** — views, subscribers, trending, platform integrity, and public counters
- **MrBeast / Beast Industries** — creator-controlled outcomes, advance knowledge, and engagement milestones
- **OpenAI / ChatGPT** — release timing, outages, benchmark integrity, pricing, rankings, valuation, and advance knowledge
- **Apple App Store** — public ranking metrics, chart integrity, dynamic app outcomes, and resolution-source dependencies

It also includes monitored themes for:

- **Flight cancellation markets** — operational disruption and source-data dependencies without automatically attributing every contract to FlightAware;
- **App Store ranking markets** — dynamic app outcomes and false-demand signals; and
- **Earnings-call mention markets** — company-controlled words, phrases, transcripts, and pre-public access pathways.

A single contract may intentionally carry a theme and one or more organization relationships. See `MONITORING_PROFILES.md` for the rationale.

## Start RaaScal Watch on a Mac

Python 3.11 or newer is required.

Double-click or run:

```bash
bash start-raascal-watch.command
```

The earlier `start-demo.command` filename remains as a backward-compatible launcher, but it no longer seeds demo data.

For manual setup:

```bash
cd raascal-watch
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

raascal-watch validate-config
raascal-watch purge-demo
raascal-watch serve
```

Open `http://127.0.0.1:8000` in a browser.

## Run a live scan

```bash
raascal-watch scan
```

The first successful scan of each source creates a silent baseline. Matching contracts remain visible, but existing contracts are not pushed as “new” alerts. Contracts first observed during later scans can trigger notifications.

For Kalshi, later scans are incremental: active matched contracts are refreshed in bounded ticker batches, while open and unopened discovery uses a timestamp overlap rather than replaying the full catalog. Resetting the Kalshi baseline intentionally returns the next scan to broad-baseline behavior.

To deliberately alert on all currently matching contracts during the first scan:

```bash
raascal-watch scan --alert-on-first-scan
```

## Remove synthetic records from an older installation

```bash
raascal-watch purge-demo
```

This removes only records whose source is `demo`. It preserves all Kalshi and Polymarket market history, matches, baselines, and acknowledgements.

## Optional developer demo view

Synthetic data is available only when deliberately seeded:

```bash
raascal-watch seed-demo
```

The live dashboard continues to hide it. To inspect the fixtures explicitly, open:

```text
http://127.0.0.1:8000/?source=demo&include_demo=true
```

## Review and calibrate candidate matches

Open **Review guidance and record an assessment** on an active contract. Each matched organization or theme has its own assessment form. Choose one decision, optionally add reason tags or corrections, and save.

Use the **Reviewer decision** filter to isolate unreviewed, actionable, monitor, informational, false-positive, or legacy-reviewed matches. Use **Unreviewed first** sorting to work through the queue.

Export the structured feedback with:

```bash
raascal-watch export-feedback --format csv --view all --output ./exports/reviewer_feedback.csv
```

The normal `raascal-watch export` command also includes the latest structured feedback fields alongside each match.

## Configure a company watchlist

Edit `config/watchlist.yaml`:

```yaml
organizations:
  - name: Your Company
    enabled: true

    aliases:
      - Your Company
      - YourCo

    products:
      - Your App
      - Your Public Status Page

    executives:
      - Full Executive Name

    metrics:
      - daily active users
      - app store ranking
      - payment volume

    stakeholders:
      - Fraud
      - Product Analytics
      - Security
      - Legal

    playbook:
      - Compare the affected metric by account age, device, and geography.
      - Preserve the contract rules and identify the data source used for settlement.
```

Most organization profiles still require a direct identity match before generic metrics are scored. Two explicit exceptions are supported:

1. A **theme profile** can match topic language such as flight cancellations without claiming one company owns the outcome.
2. A **dependency rule** can connect a source/product family or settlement-source link to an organization even when the company name is absent from the visible listing.

Those exceptions are configuration-backed and display their match basis and evidence in the review panel.

A simplified theme and dependency example:

```yaml
organizations:
  - name: FlightAware
    profile_type: organization
    aliases: [FlightAware]
    dependency_rules:
      - name: Kalshi airport cancellation family
        source: kalshi
        series_ticker_prefixes: [KXFLYCANC]
        confidence: verified
        categories: [oracle_and_data_dependency]
        evidence: Official product terms identify FlightAware as the primary source agency.

  - name: Flight cancellation markets
    profile_type: theme
    aliases:
      - flight cancellations
      - cancelled flights
      - canceled flights
```

Validate changes with:

```bash
raascal-watch validate-config
```

## Notifications

Copy `.env.example` to `.env` and configure one or more optional channels.

### Slack

```dotenv
RAASCAL_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

### Generic webhook

```dotenv
RAASCAL_GENERIC_WEBHOOK_URL=https://your-company.example/risk-events
```

### Email

```dotenv
RAASCAL_SMTP_HOST=smtp.example.com
RAASCAL_SMTP_PORT=587
RAASCAL_SMTP_USERNAME=alerts@example.com
RAASCAL_SMTP_PASSWORD=replace-me
RAASCAL_SMTP_FROM=alerts@example.com
RAASCAL_SMTP_TO=risk@example.com,product-analytics@example.com
RAASCAL_SMTP_USE_TLS=true
```

Never commit a populated `.env` file. The repository includes only `.env.example`, which contains blank placeholders.

## How detection works

1. A collector retrieves public market listings, directly queries configured priority Kalshi series, and uses incremental Kalshi discovery after the baseline.
2. Each contract is normalized into a common record and stored or updated in SQLite.
3. The risk engine checks for a direct organization reference, a monitored theme, or a configured dependency relationship.
4. Known source/product-family rules and settlement-source metadata can connect a contract to an organization without inventing a direct mention.
5. Organization-specific metrics and shared risk categories contribute to an explainable priority score.
6. Volume, liquidity, and time to settlement can increase urgency.
7. One contract card combines all matched profiles while preserving profile-specific guidance.
8. A newly observed matching contract is routed to configured notification channels.

The MVP uses a deterministic score so every point can be traced to a matching term or market attribute. The score is a review-priority aid, not a finding of misconduct.

### Contract-specific review guidance

Open **Review this active contract** on any current result to see:

- the likely role the monitored organization plays in that contract;
- why the result surfaced;
- questions an investigator should answer;
- suggested owners; and
- first review steps that quote the contract title and incorporate its source, probability, volume, close time, matched metrics, and risk pathway.

The guidance is deterministic and explainable; it does not require an LLM or model training. Human reviewer feedback is still necessary to calibrate usefulness, eliminate irrelevant recommendations, and improve organization-specific playbooks.

After upgrading an existing installation, regenerate guidance for records already stored locally without another API pull:

```bash
raascal-watch refresh-guidance
```

## Current limitations

This is a customer-discovery and testing prototype, not a production multi-tenant security product.

- Direct and theme matching remain phrase-based. Dependency mappings improve indirect discovery but must be maintained when an exchange changes ticker families, settlement sources, or rule documents.
- A single score can still flatten different exposures; future work should separate influenceability, advance knowledge, economic exposure, oracle dependence, and downstream impact.
- Related-event grouping depends on source event identifiers; records without usable event metadata remain standalone cards.
- It does not yet alert on rapid odds, volume, holder-concentration, or open-interest changes within an existing contract.
- It does not correlate market activity with internal customer, device, transaction, stream, incident, or product telemetry.
- It does not include production authentication or role-based access controls.
- SQLite is suitable for a local pilot, not a large multi-client deployment.
- Public APIs and source schemas can change or temporarily fail.

## Responsible interpretation

RaaScal Watch surfaces public contracts that may alter the economic incentive around a monitored organization, metric, data source, or operational event. It does not determine intent, identify wrongdoing, or establish that manipulation occurred. Alerts should be treated as contextual intelligence and reviewed alongside internal data, legal obligations, and normal investigative controls.

## About

RaaScal Watch is being developed as a potential product of **RaaScal Advisory**.

## Profile synchronization

RaaScal Watch keeps the local watchlist and the stored market library in sync. On launch, it safely merges newly shipped research profiles into `config/watchlist.yaml`, preserves custom organizations and terms, and creates a timestamped backup before any change. When the watchlist changes, existing stored markets are re-evaluated so a newly added organization can receive matches without waiting for every contract to be fetched again.

The profile filter always lists every enabled organization and monitored theme. A profile with `0 active` is configured correctly; it simply has no current active match in the local database.
