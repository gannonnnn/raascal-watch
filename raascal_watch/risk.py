from __future__ import annotations

from datetime import datetime, timezone

from .models import MarketRecord, MatchResult, OrganizationWatch, Watchlist
from .text import find_phrases, unique_strings


DEFAULT_STAKEHOLDERS = ("Risk", "Product Analytics")


def severity_for(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _short(value: str, limit: int = 140) -> str:
    clean = " ".join(value.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _money(value: float | None) -> str:
    if value is None:
        return "not reported"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def _percent(value: float | None) -> str:
    if value is None:
        return "not reported"
    return f"{value * 100:.1f}%"


def _close_label(value: datetime | None) -> str:
    if value is None:
        return "an unreported close time"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")


def _hours_until(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    close = value
    if close.tzinfo is None:
        close = close.replace(tzinfo=timezone.utc)
    return (close - now).total_seconds() / 3600


def _metric_phrase(metric_hits: list[str], categories: list[str]) -> str:
    if metric_hits:
        # Prefer the most specific phrase when a watchlist contains both a broad
        # term and a longer version, such as "views" and "view count".
        selected: list[str] = []
        for term in sorted(unique_strings(metric_hits), key=len, reverse=True):
            lowered = term.lower()
            if any(lowered in existing.lower() or existing.lower() in lowered for existing in selected):
                continue
            selected.append(term)
            if len(selected) == 2:
                break
        return ", ".join(selected)
    category_fallbacks = {
        "availability_and_incident": "availability or incident outcome",
        "oracle_and_data_dependency": "resolution data or public evidence",
        "benchmark_and_evaluation_integrity": "benchmark or evaluation result",
        "direct_control_and_advance_knowledge": "announcement or controlled outcome",
        "engagement_manipulation": "public engagement metric",
        "user_growth": "user-growth metric",
        "financial_metric": "reported financial or company metric",
        "platform_action": "platform or company decision",
        "popularity_and_ranking": "ranking or popularity metric",
    }
    for category in categories:
        if category in category_fallbacks:
            return category_fallbacks[category]
    return "referenced outcome"


def _infer_roles(
    *,
    title_identity_hits: list[str],
    description_identity_hits: list[str],
    categories: list[str],
) -> list[str]:
    category_set = set(categories)
    roles: list[str] = []

    if title_identity_hits:
        roles.append("Named subject / outcome owner")

    if "oracle_and_data_dependency" in category_set:
        roles.append("Resolution-data source / oracle")

    if category_set.intersection(
        {"engagement_manipulation", "user_growth", "popularity_and_ranking"}
    ) and (description_identity_hits or not title_identity_hits):
        roles.append("Platform / metric owner")

    if (
        category_set.intersection(
            {"direct_control_and_advance_knowledge", "platform_action"}
        )
        and title_identity_hits
    ):
        roles.append("Direct control / advance knowledge")

    if "availability_and_incident" in category_set and title_identity_hits:
        roles.append("Availability / incident target")

    if "financial_metric" in category_set and title_identity_hits:
        roles.append("Reporting / KPI owner")

    if "benchmark_and_evaluation_integrity" in category_set and title_identity_hits:
        roles.append("Benchmark / evaluation participant")

    if "platform_action" in category_set and title_identity_hits:
        roles.append("Decision owner")

    if not roles:
        roles.append("Referenced organization")

    return unique_strings(roles)


def _build_review_questions(
    *,
    organization: OrganizationWatch,
    roles: list[str],
    metric_label: str,
    market: MarketRecord,
) -> list[str]:
    role_set = set(roles)
    questions: list[str] = [
        "What exact condition resolves this contract, and which source has final authority?"
    ]

    if "Resolution-data source / oracle" in role_set:
        questions.append(
            f"Is {organization.name} the primary resolution source, a fallback source, or only supporting evidence—and is that use authorized?"
        )

    if "Platform / metric owner" in role_set:
        questions.append(
            f"Does the public {metric_label} match controlled internal telemetry, and which abuse patterns could move it before settlement?"
        )

    if "Direct control / advance knowledge" in role_set:
        questions.append(
            "Who can directly control the answer or know it before public release—employees, contractors, vendors, launch partners, creators, or agencies?"
        )

    if "Availability / incident target" in role_set:
        questions.append(
            "Could an external actor realistically cause, exaggerate, or obtain advance knowledge of the incident at a cost justified by the possible market upside?"
        )

    if "Reporting / KPI owner" in role_set:
        questions.append(
            f"Is the market using the same definition of {metric_label} as the company's controlled reporting, and who has pre-public access to that figure?"
        )

    if "Benchmark / evaluation participant" in role_set:
        questions.append(
            "Could submissions, voting, benchmark selection, contamination, disclosure timing, or evaluator access change the result?"
        )

    if "Decision owner" in role_set:
        questions.append(
            "Can reports, complaints, publication timing, pricing, enforcement, or another internal decision directly determine the outcome?"
        )

    if market.volume is not None or market.open_interest is not None:
        questions.append(
            "Is economic exposure concentrated among a small number of holders, and did price or volume move without a clear public catalyst?"
        )

    return unique_strings(questions)[:6]


def _build_contract_actions(
    *,
    organization: OrganizationWatch,
    market: MarketRecord,
    roles: list[str],
    categories: list[str],
    metric_label: str,
    now: datetime,
) -> list[str]:
    role_set = set(roles)
    category_set = set(categories)
    contract_title = _short(market.title, 110)
    close_label = _close_label(market.closes_at)
    actions: list[str] = [
        (
            f"Preserve a timestamped snapshot of this {market.source.title()} contract—“{contract_title}”—including the full rules, URL, displayed probability ({_percent(market.probability)}), volume ({_money(market.volume)}), and close time ({close_label})."
        )
    ]

    if "Resolution-data source / oracle" in role_set:
        actions.append(
            f"Confirm exactly how {organization.name} is used to settle this contract: primary source, fallback source, public counter, status page, API, trademark reference, or supporting evidence. Record the applicable data-license and brand-use terms."
        )

    if "Platform / metric owner" in role_set:
        actions.append(
            f"Validate the referenced {metric_label} against the canonical internal measure, then segment unusual movement by account age, device, geography, referral source, paid promotion, automation indicators, and retention."
        )

    if "Direct control / advance knowledge" in role_set:
        actions.append(
            f"Map the people and third parties with pre-public access to the {metric_label} or announcement timeline, and preserve the relevant access, approval, production, and release records through settlement."
        )

    if "Availability / incident target" in role_set:
        actions.append(
            "Compare contract creation and material odds or volume changes with availability telemetry, security alerts, vulnerability disclosures, incident-response activity, and partner notifications; do not treat the market itself as proof of an attack."
        )

    if "Reporting / KPI owner" in role_set:
        actions.append(
            f"Reconcile the market threshold and definition for {metric_label} to controlled finance or reporting data, identify everyone with pre-public access, and keep market activity separate from disclosure or product decisions."
        )

    if "Benchmark / evaluation participant" in role_set:
        actions.append(
            "Confirm the exact benchmark, version, evaluator, submission rules, and cutoff; review whether contamination, voting, test selection, disclosure timing, or partner access could affect the result."
        )

    if "Decision owner" in role_set:
        actions.append(
            "Identify the internal decision owner and test whether reports, complaints, queue pressure, publication timing, pricing, or enforcement actions could be used to influence the result before close."
        )

    if "explicit_abuse_language" in category_set:
        actions.append(
            "Open a time-bound abuse review now and preserve relevant logs under the incident-retention policy, because the contract language itself references manipulation, automation, disruption, or coordinated activity."
        )

    if market.volume is not None or market.open_interest is not None:
        exposure_parts = []
        if market.volume is not None:
            exposure_parts.append(f"reported cumulative volume is {_money(market.volume)}")
        if market.open_interest is not None:
            exposure_parts.append(f"reported open interest is {_money(market.open_interest)}")
        exposure = " and ".join(exposure_parts)
        actions.append(
            f"Review holder concentration, open interest, and sharp price or volume changes when public data permits. For context, {exposure}; cumulative volume is not the amount any one trader stands to gain."
        )

    hours = _hours_until(market.closes_at, now)
    if hours is not None and hours >= 0:
        if hours <= 72:
            actions.append(
                f"Assign a named owner immediately and monitor through {close_label}; use a tighter review cadence in the final 72 hours."
            )
        elif hours <= 24 * 14:
            actions.append(
                f"Assign a review owner now and schedule a final check inside the last 72 hours before {close_label}."
            )
        else:
            actions.append(
                f"Set a re-review milestone before {close_label}, with an earlier escalation if odds, volume, internal telemetry, or public reporting changes materially."
            )

    # Organization playbooks remain useful context, but contract-generated steps
    # come first and the list is intentionally capped to keep the dropdown usable.
    actions.extend(organization.playbook[:2])
    actions.append(
        "Escalate only when the contract is paired with a concrete concern—such as unexplained market movement, anomalous internal telemetry, unauthorized data use, nonpublic access, or a plausible influence path."
    )

    return unique_strings(actions)[:8]


class RiskEngine:
    """Transparent, deterministic scoring and contract-specific review guidance.

    Scores are prioritization aids, not evidence that a market or user activity is abusive.
    The review brief is generated from the specific contract title, rules, market
    metadata, matched organization role, and configured watchlist—not from an LLM.
    """

    def __init__(self, watchlist: Watchlist):
        self.watchlist = watchlist

    def match(self, market: MarketRecord) -> list[MatchResult]:
        results: list[MatchResult] = []
        for organization in self.watchlist.organizations:
            result = self._match_organization(market, organization)
            if result:
                results.append(result)
        return results

    def _match_organization(
        self, market: MarketRecord, organization: OrganizationWatch
    ) -> MatchResult | None:
        text = market.searchable_text
        identity_hits = find_phrases(text, organization.identity_terms)
        if not identity_hits:
            return None

        title_identity_hits = find_phrases(market.title, organization.identity_terms)
        description_identity_hits = find_phrases(
            market.description, organization.identity_terms
        )
        metric_hits = find_phrases(text, organization.metrics)
        score = 15
        reasons = [f"Referenced monitored identity: {', '.join(identity_hits[:5])}."]
        categories: list[str] = []
        stakeholders = list(DEFAULT_STAKEHOLDERS) + list(organization.stakeholders)

        if title_identity_hits:
            reasons.append(
                f"{organization.name} appears in the contract title, which is more consistent with a named subject or outcome owner."
            )
        elif description_identity_hits:
            reasons.append(
                f"{organization.name} appears in the rules or description rather than the title, which may indicate a platform, data-source, oracle, or supporting-evidence role."
            )

        if len(identity_hits) > 1:
            score += min(10, (len(identity_hits) - 1) * 3)
            reasons.append("Multiple monitored company, product, or executive terms matched.")

        if metric_hits:
            score += min(20, 8 + (len(metric_hits) - 1) * 3)
            reasons.append(
                f"Referenced monitored metric or behavior: {', '.join(metric_hits[:6])}."
            )

        for category in self.watchlist.categories:
            hits = find_phrases(text, category.terms)
            if not hits:
                continue
            score += category.weight
            categories.append(category.name)
            reasons.append(
                f"{category.name.replace('_', ' ').title()} signal: {', '.join(hits[:6])}."
            )
            stakeholders.extend(category.stakeholders)

        volume = market.volume or 0.0
        if volume >= 1_000_000:
            score += 20
            reasons.append("Reported cumulative market volume is at least $1 million.")
        elif volume >= 100_000:
            score += 15
            reasons.append("Reported cumulative market volume is at least $100,000.")
        elif volume >= 10_000:
            score += 10
            reasons.append("Reported cumulative market volume is at least $10,000.")
        elif volume >= 1_000:
            score += 5
            reasons.append("Reported cumulative market volume is at least $1,000.")

        liquidity = market.liquidity or 0.0
        if liquidity >= 100_000:
            score += 10
            reasons.append("Reported liquidity is at least $100,000.")
        elif liquidity >= 10_000:
            score += 5
            reasons.append("Reported liquidity is at least $10,000.")

        if market.probability is not None:
            reasons.append(
                f"Displayed market probability is {_percent(market.probability)}; this is market pricing, not a measured likelihood of abuse."
            )

        now = datetime.now(timezone.utc)
        hours = _hours_until(market.closes_at, now)
        if hours is not None:
            if 0 <= hours <= 24:
                score += 15
                reasons.append("The contract is scheduled to close within 24 hours.")
            elif 24 < hours <= 24 * 7:
                score += 10
                reasons.append("The contract is scheduled to close within seven days.")
            elif 24 * 7 < hours <= 24 * 30:
                score += 5
                reasons.append("The contract is scheduled to close within 30 days.")

        roles = _infer_roles(
            title_identity_hits=title_identity_hits,
            description_identity_hits=description_identity_hits,
            categories=categories,
        )
        reasons.append(f"Likely organizational role: {', '.join(roles)}.")
        metric_label = _metric_phrase(metric_hits, categories)
        review_questions = _build_review_questions(
            organization=organization,
            roles=roles,
            metric_label=metric_label,
            market=market,
        )
        actions = _build_contract_actions(
            organization=organization,
            market=market,
            roles=roles,
            categories=categories,
            metric_label=metric_label,
            now=now,
        )

        score = max(0, min(100, score))
        return MatchResult(
            organization=organization.name,
            matched_identity_terms=unique_strings(identity_hits),
            matched_metric_terms=unique_strings(metric_hits),
            categories=unique_strings(categories),
            risk_score=score,
            severity=severity_for(score),
            roles=roles,
            reasons=unique_strings(reasons),
            review_questions=review_questions,
            stakeholders=unique_strings(stakeholders),
            actions=actions,
        )
