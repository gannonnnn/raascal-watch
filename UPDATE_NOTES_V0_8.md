# RaaScal Watch v0.8.0

## Materiality gate: from candidate volume to human review

Earlier versions were intentionally sensitive: they retrieved candidate relationships first and left reviewers to separate signal from noise. That proved coverage, but a large queue can deter review and make a high additive score look more certain than it is.

v0.8.0 separates retrieval from action:

| Gate | Meaning | Default human action |
|---|---|---|
| **Observed** | Relevant intelligence, but no current activation trigger | Retain and continue automated monitoring |
| **Review today** | Credible influence, information, dependency, or downstream-impact pathway plus activity, urgency, movement, or explicit abuse language | Assign an owner and validate the signal |
| **Escalate now** | Strong movement or a concentrated, urgent, economically material pathway | Open a time-bound cross-functional review |

The default dashboard is **Review today**. Observed contracts remain available under their own tab and under All active.

## The eight questions shown under each profile relationship

1. **Is this more than a sophisticated keyword monitor?**  
   The panel identifies whether the relationship came from a direct configured identity phrase, a monitored theme, a verified product-family dependency, or a linked/possible dependency. A direct phrase can start retrieval, but it cannot independently place a contract in Review today.

2. **Why does this contract require action?**  
   The materiality gate lists the current drivers, such as approaching settlement, material reported activity, credible influenceability, narrow pre-public access, downstream operating cost, or recorded market movement.

3. **Why is the retrieval score 100 rather than 70?**  
   The legacy score now has a component-by-component explanation. Additive scores are capped at 100. The UI explicitly distinguishes this retrieval score from the materiality decision.

4. **What changed today?**  
   Stored snapshots compare the latest observation with the previous and approximately 24-hour observation window. The panel can show probability, volume, open-interest, rule, close-time, or status changes. A first observation is labeled as such.

5. **Is the amount of money or activity material?**  
   Economic context is source-aware. Kalshi volume and open interest are contract counts, not dollars of profit. Polymarket volume/liquidity/open-interest fields retain their reported currency context. Neither cumulative volume nor open interest equals one trader's possible gain.

6. **Could anyone realistically influence the outcome?**  
   Influenceability is derived from the contract pathway: engagement manipulation, ranking movement, direct control, platform action, availability incidents, data/oracle corrections, benchmark mechanics, growth metrics, or reported KPIs.

7. **What would the company do differently after the alert?**  
   Gate-aware next steps tell the reviewer whether to retain, validate today, or escalate now. Organization playbooks remain contract-specific and source-aware.

8. **How many surfaced results become genuinely actionable?**  
   The reviewer calibration panel now shows a direct human-confirmed actionable rate, the actionable-or-monitor rate, false-positive rate, and results by profile and pathway.

## App Store ranking markets

v0.8.0 adds two complementary profiles:

- **App Store ranking markets** — a monitored theme that surfaces relevant contracts without asserting that one company owns or manipulated the result.
- **Apple App Store** — the public metric owner and potential settlement source when the contract uses App Store Top Charts or related ranking data.

RaaScal Watch dynamically extracts the apps or companies named as outcomes. These dynamic subjects appear on the contract card and Field Note but do not become permanent organization profiles automatically.

The initial influence pathway considers:

- paid or incentivized installs;
- concentrated search or promotional activity;
- ratings and review velocity;
- geography and device concentration;
- paid-acquisition overlap;
- low-retention or low-quality cohorts; and
- the possibility that a company mistakes a market-linked ranking spike for durable demand.

The operational cascade can include Product, Growth, Engineering, Marketing, Finance, or leadership reallocating resources around a contaminated signal.

## Notifications

New matches classified as **Observed** are retained without ordinary notifications. New **Review** and **Escalate** matches remain eligible for configured notifications. Explicit developer/demo `force_notify` behavior is unchanged.

A future movement-alert release can separately notify when an existing Observed contract is promoted after material probability, activity, rule, or settlement changes.

## Database migration

The updater adds or backfills:

- `risk_breakdown_json`
- `materiality_json`
- `dynamic_subjects_json`
- market-snapshot close time
- market-snapshot rules hash

Existing contracts, review feedback, public-exposure snapshots, custom profiles, baselines, notification settings, and archive state are preserved.

The updater merges the App Store profiles into the local watchlist, creates a timestamped backup, and re-evaluates stored markets without retroactive notifications.

## Limitations

- Materiality thresholds are deterministic starting assumptions, not validated industry standards.
- Influenceability identifies a plausible pathway; it does not prove that anyone used it.
- The model does not know one trader's actual net exposure unless a source publicly exposes sufficient position data.
- Dynamic subject extraction depends on source metadata and may require reviewer correction for unusual titles.
- “What changed today” becomes more informative only after repeated scans create comparable snapshots.
- Reviewer decisions are directional calibration data, not legal or factual determinations.
