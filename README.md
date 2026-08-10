# RaaScal Watch

**External incentive intelligence for operational risk teams**

> **Status:** Experimental prototype. Not intended for production decision-making.

RaaScal Watch monitors public prediction-market listings for contracts that reference a company, its products, executives, or important business metrics. It then creates an explainable operational-risk alert showing what changed, why it may matter, who should review it, and what the first response steps could be.

The core question is not simply **“Was our company mentioned?”** It is:

> Has a new outside financial incentive appeared that could make manipulation of our platform, data, enforcement systems, or customer behavior economically rational?

## Why this matters

A prediction-market contract can create a financial incentive to influence streams, rankings, downloads, daily active users, GMV, enforcement decisions, or other measurable outcomes.

Even when manipulation is unsuccessful, distorted activity can still create downstream costs:

- Product or Engineering resources may be redirected around a false signal.
- Fraud or Trust & Safety teams may investigate behavior that is not organic.
- Models or thresholds may be changed in response to contaminated data.
- Leadership may treat inflated activity as a legitimate business win.

RaaScal Watch is intended to surface the changed incentive environment before those signals are accepted at face value.

## What the prototype does

- Collects public market listings from Kalshi and Polymarket
- Matches contracts against a configurable company watchlist
- Detects references to companies, products, executives, and monitored metrics
- Assigns a transparent operational-risk score
- Explains the terms and market attributes that contributed to the score
- Recommends stakeholder teams and initial investigation steps
- Supports a local dashboard, Slack, email, console, and generic webhooks
- Creates a silent first-scan baseline to reduce alert noise
- Stores market and alert history in SQLite
- Includes offline demonstration data and automated tests

The prototype only reads public market-listing data. It does not place trades, access private accounts, or identify individual traders.

## Included research profiles

Version 0.2 includes enabled profiles for:

- **Spotify** — engagement, streams, rankings, and product analytics
- **Cloudflare** — availability, incidents, DDoS, and security operations
- **YouTube** — views, subscribers, trending, platform integrity, and public counters
- **MrBeast / Beast Industries** — creator-controlled outcomes, advance knowledge, and engagement milestones

A single contract may intentionally match more than one organization. For example, a MrBeast video-view contract may affect Beast Industries as the subject while YouTube acts as the platform and resolution oracle. See `MONITORING_PROFILES.md` for the full rationale.

## Example alert

**Monitored organization:** Spotify  
**Market:** Will an artist reach Spotify’s Global Top 50 this week?  
**Potentially affected metrics:** Streams and chart ranking  
**Suggested owners:** Fraud, Trust & Safety, Product Analytics  
**Why it was surfaced:** The contract creates a financial incentive around a metric that may be influenced by coordinated or automated activity.

> An alert identifies a changed external incentive. It is not proof of manipulation, misconduct, or platform abuse.

## Start with the offline demo

Python 3.11 or newer is required.

On a Mac, double-click `start-demo.command`.

For manual setup:

```bash
cd raascal-watch
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

raascal-watch validate-config
raascal-watch seed-demo
raascal-watch serve
```

Open `http://127.0.0.1:8000` in a browser.

## Run a live scan

```bash
raascal-watch scan
```

The first successful scan of each source creates a silent baseline. Matching contracts remain visible in the dashboard, but existing contracts are not pushed as “new” alerts. Contracts first observed during later scans can trigger notifications.

To deliberately alert on all currently matching contracts during the first scan:

```bash
raascal-watch scan --alert-on-first-scan
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
      - Your Rewards Program

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

    playbook:
      - Compare the affected metric by account age, device, and geography.
      - Flag affected dashboards so teams know the signal may be externally incentivized.
```

A company identity term must match before generic metric terms are scored. This helps prevent words such as “downloads” or “revenue” from creating unrelated alerts.

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

Never commit a populated `.env` file. The repository includes only `.env.example`, which contains placeholders.

## How detection works

1. A collector retrieves public market listings.
2. Each contract is normalized into a common record.
3. The record is stored or updated in SQLite.
4. At least one monitored company identity term must match.
5. The risk engine checks monitored metrics and manipulability categories.
6. Volume, liquidity, and time to settlement can increase urgency.
7. A newly observed matching contract is routed to configured notification channels.

The MVP uses a rule-based score so every point can be traced to a matching term or market attribute.

## Current limitations

This is a customer-discovery and testing prototype, not a production multi-tenant security product.

- Matching is phrase-based and may miss indirect references or nicknames absent from the watchlist.
- It does not yet alert on rapid odds or volume changes within an existing contract.
- It does not correlate market activity with internal customer, device, transaction, stream, or product telemetry.
- It does not include production authentication or role-based access controls.
- SQLite is suitable for a local pilot, not a large multi-client deployment.
- Public APIs and source schemas can change.

## Responsible interpretation

RaaScal Watch surfaces public contracts that may alter the economic incentive to influence a monitored company or metric. It does not determine intent, identify wrongdoing, or establish that manipulation occurred. Alerts should be treated as contextual intelligence and reviewed alongside internal data and normal investigative controls.

## About

RaaScal Watch is being developed as a potential product of **RaaScal Advisory**.
