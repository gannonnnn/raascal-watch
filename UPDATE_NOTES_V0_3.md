# RaaScal Watch 0.3.0 — live-only monitoring and topical profiles

## Goal 1: remove demo results

Normal startup no longer seeds synthetic records. The updater and launcher run:

```bash
raascal-watch purge-demo
```

This removes only `demo` source records. All Kalshi and Polymarket records, matches, baselines, acknowledgements, and scan history are preserved.

The dashboard also excludes demo data by default, even if a manually seeded fixture remains in the database.

## Goal 2: add two research profiles

### FlightAware

Designed to surface flight-cancellation, delay, airport-closure, and aviation-disruption contracts that name FlightAware or its products in titles, rules, or settlement language. The response playbook emphasizes data licensing, brand use, operational safety, and settlement-source dependency.

### OpenAI / ChatGPT

Designed to surface model-release timing, ChatGPT outages, benchmark and leaderboard performance, pricing, App Store rankings, valuation, IPO, and related announcement markets. The playbook separates direct-control, advance-knowledge, availability, evaluation-integrity, and financial-reporting pathways.

## Goal 3: create better public findings

Version 0.3 adds two general categories that support stronger analysis:

- **Oracle and data dependency:** whose data, counter, status page, API, or trademark determines who gets paid?
- **Benchmark and evaluation integrity:** could a public leaderboard, evaluation, submission process, or disclosure timing affect the result?

These categories are intended to generate review questions, not findings of wrongdoing.
