from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable

from .incentive import build_incentive_map
from .materiality import build_static_materiality
from .models import (
    DependencyRule,
    MarketRecord,
    MatchResult,
    OrganizationWatch,
    Watchlist,
)
from .subjects import extract_dynamic_subjects
from .text import find_phrases, unique_strings


DEFAULT_STAKEHOLDERS = ("Risk", "Product Analytics")
_CONFIDENCE_RANK = {"possible": 1, "linked": 2, "verified": 3}


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
        selected: list[str] = []
        for term in sorted(unique_strings(metric_hits), key=len, reverse=True):
            lowered = term.lower()
            if any(
                lowered in existing.lower() or existing.lower() in lowered
                for existing in selected
            ):
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


def _raw_value(raw: dict, *names: str) -> str:
    for name in names:
        value = raw.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _starts_with_any(value: str, prefixes: Iterable[str]) -> bool:
    clean = value.strip().upper()
    return bool(clean) and any(clean.startswith(prefix.strip().upper()) for prefix in prefixes)


def _dependency_rule_matches(market: MarketRecord, rule: DependencyRule) -> bool:
    if rule.source and market.source.strip().lower() != rule.source:
        return False

    raw = market.raw or {}
    external_match = _starts_with_any(market.external_id, rule.external_id_prefixes)
    event_match = _starts_with_any(
        _raw_value(raw, "event_ticker", "eventTicker"),
        rule.event_ticker_prefixes,
    )
    series_match = _starts_with_any(
        _raw_value(raw, "series_ticker", "seriesTicker"),
        rule.series_ticker_prefixes,
    )
    has_prefix_rule = bool(
        rule.external_id_prefixes
        or rule.event_ticker_prefixes
        or rule.series_ticker_prefixes
    )
    evidence_text = json.dumps(market.raw or {}, ensure_ascii=False, default=str)
    evidence_match = bool(find_phrases(evidence_text, rule.evidence_terms))
    if has_prefix_rule or rule.evidence_terms:
        return external_match or event_match or series_match or evidence_match

    return bool(find_phrases(market.searchable_text, rule.terms))


def _matching_dependency_rules(
    market: MarketRecord, organization: OrganizationWatch
) -> list[DependencyRule]:
    matches = [
        rule
        for rule in organization.dependency_rules
        if _dependency_rule_matches(market, rule)
    ]
    return sorted(
        matches,
        key=lambda rule: _CONFIDENCE_RANK.get(rule.confidence, 0),
        reverse=True,
    )


def _infer_roles(
    *,
    title_identity_hits: list[str],
    description_identity_hits: list[str],
    categories: list[str],
    match_basis: str,
    is_theme: bool,
) -> list[str]:
    category_set = set(categories)
    roles: list[str] = []

    if is_theme:
        roles.append("Monitored theme / contract family")
        return roles

    if match_basis.endswith("_dependency"):
        roles.append("Resolution-data source / oracle")
        roles.append(match_basis.replace("_", " ").title())

    if title_identity_hits:
        roles.append("Named subject / outcome owner")

    if "oracle_and_data_dependency" in category_set and not any(
        "Resolution-data" in role for role in roles
    ):
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

    if "Monitored theme / contract family" in role_set:
        questions.extend(
            [
                "Which organization supplies the primary and fallback cancellation data for this exact contract family?",
                "Does the contract measure a cancellation count, rate, threshold, airport-specific outcome, or nationwide total?",
                "Which actors could know or influence the result—airlines, airport operators, data providers, labor groups, weather services, or public authorities?",
            ]
        )

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

    return unique_strings(questions)[:7]


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
    activity_label = (
        f"{market.volume:,.0f} contracts" if market.source == "kalshi" and market.volume is not None
        else _money(market.volume)
    )
    actions: list[str] = [
        (
            f"Preserve a timestamped snapshot of this {market.source.title()} contract—“{contract_title}”—including the full rules, URL, displayed probability ({_percent(market.probability)}), reported activity ({activity_label}), and close time ({close_label})."
        )
    ]

    if "Monitored theme / contract family" in role_set:
        actions.extend(
            [
                "Identify the market's product family, threshold, airport or geography, time window, and primary/fallback source agency before assigning an organizational owner.",
                "Map the parties that may possess advance operational information, including airlines, airport operators, air-traffic authorities, labor groups, data vendors, and government agencies.",
            ]
        )

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
            if market.source == "kalshi":
                exposure_parts.append(f"reported cumulative volume is {market.volume:,.0f} contracts")
            else:
                exposure_parts.append(f"reported cumulative volume is {_money(market.volume)}")
        if market.open_interest is not None:
            if market.source == "kalshi":
                exposure_parts.append(f"reported open interest is {market.open_interest:,.0f} contracts")
            else:
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

    actions.extend(organization.playbook[:2])
    actions.append(
        "Escalate only when the contract is paired with a concrete concern—such as unexplained market movement, anomalous internal telemetry, unauthorized data use, nonpublic access, or a plausible influence path."
    )

    return unique_strings(actions)[:9]


class RiskEngine:
    """Transparent, deterministic scoring and relationship-aware guidance."""

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
        dependency_rules = _matching_dependency_rules(market, organization)

        if not identity_hits and not dependency_rules:
            return None

        score = 0
        score_components: list[dict[str, object]] = []

        def add_points(
            points: int,
            label: str,
            evidence: str,
            *,
            component_type: str = "score",
        ) -> None:
            nonlocal score
            score += points
            score_components.append(
                {
                    "label": label,
                    "points": points,
                    "evidence": evidence,
                    "type": component_type,
                }
            )

        if organization.is_theme:
            match_basis = "theme"
            add_points(
                8,
                "Monitored theme relationship",
                "The listing fits a configured contract theme; this does not assign the outcome to one company.",
            )
        elif identity_hits:
            match_basis = "direct"
            add_points(
                15,
                "Direct monitored-identity reference",
                f"Matched: {', '.join(identity_hits[:5])}.",
            )
        else:
            confidence = dependency_rules[0].confidence if dependency_rules else "possible"
            match_basis = f"{confidence}_dependency"
            base_points = {"verified": 18, "linked": 12, "possible": 8}.get(
                confidence, 8
            )
            add_points(
                base_points,
                f"{confidence.title()} dependency relationship",
                dependency_rules[0].evidence if dependency_rules else "Configured dependency relationship.",
            )

        title_identity_hits = (
            find_phrases(market.title, organization.identity_terms)
            if identity_hits
            else []
        )
        description_identity_hits = (
            find_phrases(market.description, organization.identity_terms)
            if identity_hits
            else []
        )
        metric_hits = find_phrases(text, organization.metrics)
        reasons: list[str] = []
        categories: list[str] = []
        stakeholders = list(DEFAULT_STAKEHOLDERS) + list(organization.stakeholders)

        if match_basis == "theme":
            reasons.append(
                f"Matched monitored theme: {', '.join(identity_hits[:5])}. This is a topic-level review profile, not an assertion that one company owns the outcome."
            )
        elif match_basis == "direct":
            reasons.append(
                f"Referenced monitored identity: {', '.join(identity_hits[:5])}."
            )
            if title_identity_hits:
                reasons.append(
                    f"{organization.name} appears in the contract title, which is more consistent with a named subject or outcome owner."
                )
            elif description_identity_hits:
                reasons.append(
                    f"{organization.name} appears in the rules or description rather than the title, which may indicate a platform, data-source, oracle, or supporting-evidence role."
                )
        else:
            for rule in dependency_rules:
                label = rule.confidence.title()
                reasons.append(
                    f"{label} dependency match via {rule.name}. {rule.evidence}".strip()
                )
            reasons.append(
                f"{organization.name} does not need to appear in the visible contract text for this configured source/product-family dependency to surface."
            )

        if match_basis == "direct" and len(identity_hits) > 1:
            points = min(10, (len(identity_hits) - 1) * 3)
            add_points(
                points,
                "Additional identity evidence",
                "Multiple monitored company, product, or executive terms matched.",
            )
            reasons.append("Multiple monitored company, product, or executive terms matched.")

        if metric_hits:
            points = min(20, 8 + (len(metric_hits) - 1) * 3)
            add_points(
                points,
                "Monitored metric or behavior",
                f"Matched: {', '.join(metric_hits[:6])}.",
            )
            reasons.append(
                f"Referenced monitored metric or behavior: {', '.join(metric_hits[:6])}."
            )

        category_by_name = {category.name: category for category in self.watchlist.categories}
        for category in self.watchlist.categories:
            hits = find_phrases(text, category.terms)
            if not hits:
                continue
            add_points(
                category.weight,
                category.name.replace("_", " ").title(),
                f"Matched: {', '.join(hits[:6])}.",
            )
            categories.append(category.name)
            reasons.append(
                f"{category.name.replace('_', ' ').title()} signal: {', '.join(hits[:6])}."
            )
            stakeholders.extend(category.stakeholders)

        for rule in dependency_rules:
            for category_name in rule.categories:
                if category_name in categories:
                    continue
                category = category_by_name.get(category_name)
                categories.append(category_name)
                if category:
                    add_points(
                        category.weight,
                        f"Dependency-mapped {category_name.replace('_', ' ')}",
                        rule.evidence or f"Added by dependency rule {rule.name}.",
                    )
                    stakeholders.extend(category.stakeholders)
                    reasons.append(
                        f"{category_name.replace('_', ' ').title()} was added by the configured dependency mapping."
                    )

        volume = market.volume or 0.0
        if volume >= 1_000_000:
            points = 20
            threshold = "1 million"
        elif volume >= 100_000:
            points = 15
            threshold = "100,000"
        elif volume >= 10_000:
            points = 10
            threshold = "10,000"
        elif volume >= 1_000:
            points = 5
            threshold = "1,000"
        else:
            points = 0
            threshold = ""
        if points:
            unit = "contracts" if market.source == "kalshi" else "reported currency units"
            add_points(
                points,
                "Reported cumulative activity",
                f"Lifetime volume is at least {threshold} {unit}.",
            )
            if market.source == "kalshi":
                reasons.append(
                    f"Reported cumulative market volume is at least {threshold} contracts; this is not a dollar-profit figure."
                )
            else:
                reasons.append(
                    f"Reported cumulative market volume is at least ${threshold}."
                )

        liquidity = market.liquidity or 0.0
        if liquidity >= 100_000:
            add_points(
                10,
                "Reported liquidity",
                "Reported liquidity is at least $100,000.",
            )
            reasons.append("Reported liquidity is at least $100,000.")
        elif liquidity >= 10_000:
            add_points(
                5,
                "Reported liquidity",
                "Reported liquidity is at least $10,000.",
            )
            reasons.append("Reported liquidity is at least $10,000.")

        if market.probability is not None:
            score_components.append(
                {
                    "label": "Displayed market probability",
                    "points": 0,
                    "evidence": f"{_percent(market.probability)}; market pricing is not a measured likelihood of abuse.",
                    "type": "context",
                }
            )
            reasons.append(
                f"Displayed market probability is {_percent(market.probability)}; this is market pricing, not a measured likelihood of abuse."
            )

        now = datetime.now(timezone.utc)
        hours = _hours_until(market.closes_at, now)
        if hours is not None:
            if 0 <= hours <= 24:
                add_points(15, "Settlement urgency", "The contract is scheduled to close within 24 hours.")
                reasons.append("The contract is scheduled to close within 24 hours.")
            elif 24 < hours <= 24 * 7:
                add_points(10, "Settlement urgency", "The contract is scheduled to close within seven days.")
                reasons.append("The contract is scheduled to close within seven days.")
            elif 24 * 7 < hours <= 24 * 30:
                add_points(5, "Settlement urgency", "The contract is scheduled to close within 30 days.")
                reasons.append("The contract is scheduled to close within 30 days.")

        roles = _infer_roles(
            title_identity_hits=title_identity_hits,
            description_identity_hits=description_identity_hits,
            categories=categories,
            match_basis=match_basis,
            is_theme=organization.is_theme,
        )
        reasons.append(f"Likely profile role: {', '.join(roles)}.")
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
        incentive_map = build_incentive_map(
            market=market,
            organization=organization,
            roles=roles,
            categories=categories,
            metric_label=metric_label,
        )
        dynamic_subjects = extract_dynamic_subjects(
            market,
            profile_name=organization.name,
            categories=categories,
        )

        raw_score = score
        score = max(0, min(100, raw_score))
        risk_breakdown = {
            "raw_score": raw_score,
            "score": score,
            "cap_applied": raw_score > 100,
            "components": score_components,
            "explanation": (
                "The legacy risk score is an additive retrieval-priority score. "
                "The materiality gate separately decides whether the contract belongs in today's human review queue."
            ),
        }
        materiality = build_static_materiality(
            market=market,
            organization=organization,
            match_basis=match_basis,
            roles=roles,
            categories=categories,
            actions=actions,
            stakeholders=unique_strings(stakeholders),
            dynamic_subjects=dynamic_subjects,
        )

        matched_terms = (
            unique_strings(identity_hits)
            if identity_hits
            else unique_strings(rule.name for rule in dependency_rules)
        )
        return MatchResult(
            organization=organization.name,
            matched_identity_terms=matched_terms,
            matched_metric_terms=unique_strings(metric_hits),
            categories=unique_strings(categories),
            risk_score=score,
            severity=severity_for(score),
            match_basis=match_basis,
            roles=roles,
            reasons=unique_strings(reasons),
            review_questions=review_questions,
            stakeholders=unique_strings(stakeholders),
            actions=actions,
            incentive_map=incentive_map,
            risk_breakdown=risk_breakdown,
            materiality=materiality,
            dynamic_subjects=dynamic_subjects,
        )
