# RaaScal Watch monitoring profiles

RaaScal Watch treats every result as a **candidate match**, not proof of abuse. Version 0.5 separates organization relationships from monitored topics.

## Flight cancellation markets — monitored theme

**What is monitored:** cancellation counts and rates, flights cancelled or canceled, airport-specific thresholds, nationwide weekly totals, airport closures, and related operational outcomes.

**Why it matters:** a cancellation contract can create several possible incentive or information pathways involving airlines, airports, source agencies, labor groups, weather services, government authorities, and market participants. The topic should be surfaced before the correct organizational owner is known.

**What the theme does not claim:** a theme match does not mean FlightAware supplies the data or that anyone is manipulating an outcome.

**Likely owners:** Aviation Operations, Data Governance, Threat Intelligence, and Legal.

## FlightAware — resolution-data dependency

**What is monitored:** direct FlightAware references, known Kalshi cancellation families whose terms or public evidence connect FlightAware to settlement, and Kalshi series metadata that identifies or links to FlightAware as a source.

**Why it matters:** a data provider may be neither the subject nor operator of a market, yet its API, dashboard, brand, or classifications can help determine who gets paid. That can create data-licensing, brand, safety, contractual, operational, and product-integrity questions.

**Relationship confidence:** airport-level Kalshi cancellation contracts in the configured `KXFLYCANC...` family are marked **verified dependency** based on the applicable product terms. The `KXUSFLYCAN` weekly family is marked **linked dependency** and should be confirmed against the current contract rules or source link before escalation. Other cancellation contracts remain theme-only unless a source relationship is established.

**Likely owners:** Legal, Data Licensing, Data Partnerships, Brand Protection, Product Integrity, and Aviation Operations.

## Spotify — engagement and reporting integrity

**What is monitored:** streams, listeners, subscriber growth, downloads, chart position, editorial decisions, and branded products.

**Why it matters:** externally incentivized engagement can contaminate discovery systems, product analytics, fraud models, marketing decisions, and leadership reporting.

**Likely owners:** Trust & Safety, Fraud, Data Science, and Product Analytics.

## Cloudflare — availability and attack incentive

**What is monitored:** outages, critical incidents, service disruption, downtime, latency, DDoS activity, DNS disruption, security incidents, and status-page outcomes.

**Why it matters:** a contract can attach financial exposure to a service interruption. A sudden market move may also warrant review for advance knowledge of an incident or vulnerability. Neither condition is proof of misconduct.

**Likely owners:** Security Operations, Threat Intelligence, Site Reliability Engineering, Incident Response, and Legal.

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

## Relationship labels

- **Direct:** the organization is visible in the title, rules, or description.
- **Verified dependency:** configured product terms or source metadata establish the organization’s role.
- **Linked dependency:** evidence connects the family to the organization, but the current iteration should be confirmed.
- **Possible dependency:** a plausible but unverified relationship requiring research.
- **Theme:** the topic is relevant, but no organization relationship is asserted.

## The roles RaaScal Watch is testing

- **Subject:** the company, creator, product, or event being bet on.
- **Controller:** a person or system capable of directly changing the outcome.
- **Resolution oracle:** the chart, counter, data provider, status page, transcript, or announcement used to settle the contract.
- **Downstream risk bearer:** the organization that absorbs legal exposure, investigation cost, distorted data, operational disruption, or bad decisions.

A single contract can therefore have one topic match and several organization relationships while remaining one card in the dashboard.
