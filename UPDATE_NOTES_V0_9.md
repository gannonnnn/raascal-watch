# RaaScal Watch v0.9.0

## Earnings-call mention markets and corporate-controlled outcomes

Version 0.9 adds a monitored theme for prediction-market contracts resolved by words, phrases, mention counts, or other language delivered during a company earnings call or investor call.

The theme is designed around a distinct risk pathway:

- a relatively small group may have pre-public access to prepared remarks, scripts, rehearsals, webcast systems, call audio, or transcript feeds;
- some of those people may be able to directly add, remove, repeat, or avoid the deciding language;
- a contract can therefore create both an information-advantage question and a direct-control question;
- a public market signal is still not evidence that anyone traded improperly or misused information.

## New monitored theme

The default watchlist now includes:

- **Earnings-call mention markets** — a theme covering earnings-call, investor-call, transcript, exact-word, exact-phrase, and mention-threshold contracts.

The profile is routed toward:

- Corporate Compliance
- Insider Risk
- Legal
- Investor Relations
- Communications
- Corporate Secretary
- Vendor Risk

The theme does not permanently create an organization profile for every company that appears in a contract. Instead, it extracts the changing company and controlled outcome dynamically.

## Dynamic company and outcome extraction

RaaScal Watch now extracts descriptive labels such as:

```text
Company: Dell
Controlled outcome: Agentic
```

The extractor uses source metadata and normalized contract titles, including Polymarket event/child-market structures and Kalshi subtitle fields. Dynamic labels are descriptive only; they do not identify a trader, prove access, or establish misconduct.

## Materiality behavior

Earnings-call mention contracts receive a separate **corporate-controlled outcome** pathway. The materiality model considers:

- direct ability to control the deciding language;
- narrow pre-public access to scripts, approvals, rehearsals, audio, and transcripts;
- reported market activity;
- time remaining before the call or settlement;
- recorded probability, volume, open-interest, rule, or close-time movement; and
- downstream compliance, vendor, disclosure, employee-trust, and reputational cost.

A theme match alone remains **Observed** unless a current activation trigger is present. Near-term settlement or material economic activity can place the contract in **Review today**. Escalation still requires stronger overlap among access, control, activity, urgency, movement, or other independent evidence.

## Contract-specific review guidance

For an earnings-call mention contract, RaaScal Watch now asks:

- Which company and exact word, phrase, or mention threshold determine settlement?
- Who had pre-public access to prepared remarks, scripts, rehearsals, call audio, transcripts, or production systems?
- Could anyone with access directly alter the deciding language?
- Do employee, contractor, vendor, adviser, household, and related-person policies cover prediction markets and event contracts?
- Did price, volume, open interest, or holder concentration move before a legitimate public catalyst?

Suggested first steps include preserving the contract and official settlement language, mapping pre-public access, reviewing policy coverage, comparing market movement with the drafting and approval timeline, and escalating only when market activity overlaps with credible access or control.

## Incentive Map and Field Note

The Incentive Map now presents earnings-call contracts as company-controlled language or disclosure outcomes. It identifies plausible:

- YES and NO beneficiaries;
- pre-public information holders;
- direct outcome controllers;
- official audio, webcast, prepared remarks, or transcript sources;
- internal teams that may absorb investigation and governance costs; and
- evidence still required before any misconduct conclusion.

The default Field Note headline for this theme is:

> **What if the answer is already in the script?**

## Theme-specific guidance correction

Earlier versions used flight-cancellation questions as the generic fallback for every monitored theme. Version 0.9 separates guidance for:

- flight-cancellation markets;
- App Store ranking markets;
- earnings-call mention markets; and
- future generic themes.

This prevents an App Store or earnings-call result from receiving airport-specific questions or next steps.

## Migration

The updater:

- merges the new theme and category into the existing watchlist;
- preserves custom organizations, aliases, metrics, stakeholders, playbooks, and disabled-profile choices;
- creates a timestamped watchlist backup when the file changes;
- re-evaluates stored Kalshi and Polymarket records for the new theme;
- refreshes materiality, Incentive Maps, dynamic subjects, and guidance; and
- preserves the SQLite database, reviewer decisions, market history, public-visibility snapshots, `.env`, `.venv`, and notification settings.

## Limitations

- Contract wording and source metadata vary, so the company or controlled phrase may occasionally require reviewer correction.
- A profitable or well-timed position does not establish identity, access, duty, intent, or wrongdoing.
- A company-controlled outcome may be operationally relevant even when the amount of reported market activity is modest, but that does not make it automatically actionable.
- RaaScal Watch does not monitor employee brokerage or prediction-market accounts and does not replace exchange, employer, or regulator surveillance.

## Validation

The release includes automated coverage for:

- Polymarket event and child-market extraction;
- Kalshi earnings-call subtitle extraction;
- dynamic company and controlled-outcome labels;
- corporate-controlled outcome materiality;
- profile synchronization and stored-market backfilling;
- dashboard and Field Note rendering; and
- protection against unrelated generic earnings forecasts and flight-specific guidance leakage.

The full project test suite contains 97 automated tests. The earnings-call examples were validated with representative source metadata. A live scan on the installation machine remains the final check that the currently available market records use the expected fields and wording.
