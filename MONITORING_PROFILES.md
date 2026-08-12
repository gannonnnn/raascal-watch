# RaaScal Watch monitoring profiles

RaaScal Watch treats every result as a **candidate match**, not proof of abuse. The current profiles are designed to test distinct operational-risk surfaces.

## Spotify — engagement and reporting integrity

**What is monitored:** streams, listeners, subscriber growth, downloads, chart position, editorial decisions, and branded products.

**Why it matters:** externally incentivized engagement can contaminate discovery systems, product analytics, fraud models, marketing decisions, and leadership reporting.

**Likely owners:** Trust & Safety, Fraud, Data Science, and Product Analytics.

## Cloudflare — availability and attack incentive

**What is monitored:** outages, critical incidents, service disruption, downtime, latency, DDoS activity, DNS disruption, security incidents, and status-page outcomes.

**Why it matters:** a contract can attach financial exposure to a service interruption. A sudden market move may also warrant review for advance knowledge of an incident or vulnerability. Neither condition is proof of misconduct.

**Likely owners:** Security Operations, Threat Intelligence, Site Reliability Engineering, Incident Response, and Legal.

## FlightAware — data, brand, and settlement-source dependency

**What is monitored:** flight cancellations, delays, diversions, airport closures, flight status, cancellation rates, and contracts that name FlightAware data or products as a verification source.

**Why it matters:** a data provider may be neither the subject nor the operator of a market, yet its name, API, dashboard, or trademark can become part of the mechanism that determines who gets paid. That can create data-licensing, brand, safety, contractual, operational, and product-integrity questions.

**Likely owners:** Legal, Data Licensing, Data Partnerships, Brand Protection, Product Integrity, and Aviation Operations.

## YouTube — platform integrity and public-counter risk

**What is monitored:** video views, watch time, subscribers, likes, comments, trending position, upload timing, and public counters.

**Why it matters:** YouTube may be both the platform where behavior is influenced and the public data source used to settle the contract. The affected creator and YouTube can therefore have different but overlapping risks.

**Likely owners:** Trust & Safety, Abuse Prevention, Creator Integrity, Product Analytics, and Security.

## MrBeast / Beast Industries — creator control and advance knowledge

**What is monitored:** next-video timing, titles, words or brands mentioned, view milestones, subscriber milestones, episode releases, and product launches.

**Why it matters:** some outcomes can be directly controlled by the creator or known in advance by employees, production partners, agencies, sponsors, and vendors. Other outcomes require audience or platform manipulation. The response should distinguish those pathways.

**Likely owners:** Creator Operations, Legal, Compliance, Insider Risk, Security, and Analytics.

## OpenAI / ChatGPT — releases, availability, benchmarks, and insider access

**What is monitored:** model-release timing, ChatGPT outages, benchmark and leaderboard performance, product pricing, App Store rankings, valuation, IPO outcomes, and other announcements.

**Why it matters:** these markets can involve several distinct pathways: direct control over launch or pricing, advance knowledge among employees or partners, externally measured benchmark integrity, public status data, and financial-reporting outcomes.

**Likely owners:** Insider Risk, Legal & Compliance, Product Security, Site Reliability Engineering, AI Evaluation, Communications, and Finance.

## The roles RaaScal Watch is testing

A named organization is not always the only organization that should receive an alert.

- **Subject:** the company, creator, product, or event being bet on.
- **Controller:** a person or system capable of directly changing the outcome.
- **Resolution oracle:** the chart, counter, data provider, status page, transcript, or announcement used to settle the contract.
- **Downstream risk bearer:** the organization that absorbs legal exposure, investigation cost, distorted data, operational disruption, or bad decisions.

A flight-cancellation contract may concern airlines and airports while FlightAware acts as the data source. An AI-release contract may concern OpenAI while employees, deployment partners, benchmark operators, and public status systems play different roles. Multiple profiles can therefore match one contract intentionally.

## Contract-specific review briefs

The profile is only the starting context. Version 0.3.1 also evaluates where the organization appears, which categories fired, the exact market metadata, and likely organizational role. This lets two matches for the same organization produce different questions and next steps—for example, an OpenAI release contract, ChatGPT outage contract, and AI benchmark contract are routed through different review pathways.
