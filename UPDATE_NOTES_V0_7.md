# RaaScal Watch v0.7.0

## Incentive Maps

Each matched organization or monitored theme now receives an explainable Incentive Map:

- **Who benefits?** YES and NO holders, using the displayed price to show illustrative gross upside per winning share.
- **Who may know first?** Plausible employees, contractors, vendors, partners, data operators, or other parties with pre-public access.
- **Who could influence it?** Actors capable of moving the underlying metric, event, operational condition, decision, or settlement data.
- **Whose data or decision settles it?** Named and inferred resolution sources.
- **Who bears the cost?** Teams, customers, partners, or leadership affected by the operational response or false signal.
- **What can public data show?** Source-specific visibility and its limits.

The map is deterministic and derived from the contract, market metadata, inferred organization role, matched risk pathways, and configured watchlist. It is not an accusation or an insider-trading detector.

## False-signal and operational-waterfall analysis

The review panel and Field Note explain how the external incentive could create a misleading internal signal. Depending on the pathway, this can include:

1. money attached to a metric or outcome;
2. artificial, concentrated, leaked, or otherwise non-organic activity;
3. Product, Engineering, Growth, Fraud, Security, Finance, or leadership treating the activity as genuine; and
4. roadmap, staffing, spend, customer-experience, disclosure, incident-response, or reputational cost.

## Market movement history

RaaScal Watch stores a snapshot when probability, volume, 24-hour volume, liquidity, open interest, or source status changes. The dashboard shows the latest change when multiple snapshots exist.

This is not yet a full time-series alerting model. A later release can add configurable velocity and probability-movement thresholds after reviewer feedback establishes which movements matter.

## Public exposure snapshots

Use **Capture public visibility** on an active contract or **Post-close public visibility** in Archive.

### Polymarket

When its public endpoints return the data, RaaScal Watch can preserve:

- wallet-level position size;
- average entry price;
- current, realized, and total P&L;
- top holders by outcome;
- open interest; and
- market-scoped public trades.

Wallets may be pseudonymous. A public profile, position, profit, or well-timed trade does not prove a real-world identity, privileged access, influence, intent, breach of duty, or misconduct.

### Kalshi

RaaScal Watch can preserve aggregate public prices, volume, open interest, and trade timing. Public market data does not provide public participant-level positions or identities. Participant attribution generally requires the account holder, exchange, or an authorized regulator.

## Field Notes

Each contract card now includes **Open Field Note**. The page is designed for screenshots or printing and presents:

- the contract and current market context;
- beneficiary sides;
- actor and information-access pathways;
- the downstream false-signal cascade;
- public versus restricted evidence; and
- a prominent non-accusatory caveat.

## Faster, clearer startup

The Mac launcher now prints each startup step and opens the dashboard before calculating large active/archive and reviewer-calibration summaries. Those totals load in the browser instead of making Terminal appear frozen.

## Database migration

The update adds:

- `matches.incentive_map_json`;
- `market_snapshots`; and
- `public_exposure_snapshots`.

Existing market history, active/archive status, baselines, reviewer feedback, acknowledgements, custom watchlist profiles, `.env`, and notification settings are preserved.

The updater runs `raascal-watch refresh-guidance` so existing stored matches receive Incentive Maps without requiring another full market scan.
