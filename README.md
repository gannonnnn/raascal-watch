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
- Automatically retries Kalshi through its supported compatibility host when the preferred host returns HTTP 403/404 or cannot be reached
- Matches contracts against configurable organization profiles and monitored themes
- Maps configured source/product families to organizations whose data may determine settlement
- Directly queries priority Kalshi series so niche monitored families are not lost behind the broad page cap
- Detects references to companies, products, executives, public data sources, monitored metrics, and contract topics
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
- Automatically applies filters and supports priority, closing-time, volume, and recency sorting
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

It also includes the monitored theme **Flight cancellation markets**, which surfaces relevant contracts without automatically attributing them to FlightAware. A single contract may intentionally carry both a theme and one or more organization relationships. See `MONITORING_PROFILES.md` for the rationale.

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

1. A collector retrieves public market listings and directly queries configured priority Kalshi series.
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
