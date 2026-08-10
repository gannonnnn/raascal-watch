# RaaScal Watch monitoring profiles

RaaScal Watch treats every result as a **candidate match**, not proof of abuse. The current profiles are designed to test four different operational-risk surfaces.

## Spotify — engagement and ranking integrity

**What is monitored:** streams, listeners, subscriber growth, downloads, chart position, editorial decisions, and branded products.

**Why it matters:** externally incentivized engagement can contaminate discovery systems, product analytics, fraud models, marketing decisions, and leadership reporting.

**Likely owners:** Trust & Safety, Fraud, Data Science, and Product Analytics.

## Cloudflare — availability and attack incentive

**What is monitored:** outages, critical incidents, service disruption, downtime, latency, DDoS activity, DNS disruption, security incidents, and status-page outcomes.

**Why it matters:** a contract can create a direct financial incentive to cause or accelerate a service interruption. A sudden market move may also warrant review for advance knowledge of an incident or vulnerability. Neither condition is proof of misconduct.

**Likely owners:** Security Operations, Threat Intelligence, Site Reliability Engineering, Incident Response, and Legal.

## YouTube — platform integrity and resolution-oracle risk

**What is monitored:** video views, watch time, subscribers, likes, comments, trending position, upload timing, and public counters.

**Why it matters:** YouTube may be both the platform where behavior is influenced and the public data source used to settle the contract. The affected creator and YouTube can therefore have different but overlapping risks.

**Likely owners:** Trust & Safety, Abuse Prevention, Creator Integrity, Product Analytics, and Security.

## MrBeast / Beast Industries — creator control and advance knowledge

**What is monitored:** next-video timing, titles, words or brands mentioned, view milestones, subscriber milestones, episode releases, and product launches.

**Why it matters:** some outcomes can be directly controlled by the creator or known in advance by employees, production partners, agencies, sponsors, and vendors. Other outcomes require audience or platform manipulation. The response should distinguish those two pathways.

**Likely owners:** Creator Operations, Legal, Compliance, Insider Risk, Security, and Analytics.

## The four roles RaaScal Watch is testing

A named organization is not always the only organization that should receive an alert.

- **Subject:** the company, creator, product, or event being bet on.
- **Controller:** a person or system capable of directly changing the outcome.
- **Resolution oracle:** the chart, counter, status page, transcript, or announcement used to settle the contract.
- **Downstream risk bearer:** the organization that absorbs investigation cost, distorted data, operational disruption, or bad decisions.

A MrBeast views market, for example, may make Beast Industries the subject and partial controller, while YouTube is the platform and resolution oracle. Both profiles can match the same contract intentionally.
