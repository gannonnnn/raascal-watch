# RaaScal Watch 0.3.1 — contract-specific review guidance

Version 0.3 added live-only monitoring plus FlightAware and OpenAI / ChatGPT profiles. Version 0.3.1 improves what happens after a contract is surfaced.

## What changed in the dropdown

The dropdown is no longer only a generic organization playbook. For every matched contract, RaaScal Watch now generates a deterministic review brief from:

- the exact contract title and rules
- whether the organization appears in the title or only in settlement language
- the source platform
- displayed probability, cumulative volume, open interest, and close time when available
- matched organization, product, metric, and risk-category terms
- the organization-specific watch profile

The brief shows:

1. **Likely organization role** — for example named subject, platform/metric owner, resolution-data source/oracle, direct-control party, availability target, KPI/reporting owner, benchmark participant, or decision owner.
2. **Why this contract surfaced** — the matched evidence and market context.
3. **Questions this team should answer** — specific to the contract's role and risk pathway.
4. **Recommended next steps for this contract** — including the contract title, probability, volume, close time, and relevant internal review path.
5. **Suggested initial owners** — based on the organization profile and triggered categories.

## Examples

- A FlightAware contract using the phrase “Outcome verified from FlightAware” receives data-licensing, settlement-source, API/scraping, and brand-use review steps.
- A MrBeast view market produces a creator direct-control / advance-knowledge brief for Beast Industries and a separate platform/metric-integrity brief for YouTube.
- An OpenAI model-release market asks who had pre-public access and maps announcement, launch-partner, and insider-risk review steps.
- A ChatGPT outage market emphasizes availability telemetry, status-page settlement language, incident response, and threat-intelligence correlation.

## Existing results

The update adds two fields to the existing SQLite database without deleting live history:

- `roles_json`
- `review_questions_json`

The launcher runs:

```bash
raascal-watch refresh-guidance
```

This re-analyzes existing matches locally. A new live scan is still needed to discover matches for newly added organizations, but not merely to populate the new dropdown for records already stored.

## Important limitation

The review brief is rules-based and explainable. It cannot identify trader intent, prove influence, determine privileged access, or establish misconduct from public market metadata alone.
