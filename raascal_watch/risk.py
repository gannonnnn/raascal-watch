from __future__ import annotations

from datetime import datetime, timezone

from .models import MarketRecord, MatchResult, OrganizationWatch, Watchlist
from .text import find_phrases, unique_strings


DEFAULT_ACTIONS = (
    "Validate the referenced outcome against a trusted internal data source.",
    "Preserve a timestamped snapshot of the market, odds, volume, and settlement terms.",
    "Assess whether customers, bots, employees, vendors, or partners could influence the outcome.",
)

DEFAULT_STAKEHOLDERS = ("Risk", "Product Analytics")


def severity_for(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


class RiskEngine:
    """Transparent, deterministic scoring for an early-stage product.

    Scores are prioritization aids, not evidence that a market or user activity is abusive.
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

        metric_hits = find_phrases(text, organization.metrics)
        score = 15
        reasons = [
            f"Referenced monitored identity: {', '.join(identity_hits[:5])}."
        ]
        categories: list[str] = []
        stakeholders = list(DEFAULT_STAKEHOLDERS) + list(organization.stakeholders)
        actions = list(DEFAULT_ACTIONS) + list(organization.playbook)

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
            actions.extend(category.actions)

        volume = market.volume or 0.0
        if volume >= 1_000_000:
            score += 20
            reasons.append("Reported market volume is at least $1 million.")
        elif volume >= 100_000:
            score += 15
            reasons.append("Reported market volume is at least $100,000.")
        elif volume >= 10_000:
            score += 10
            reasons.append("Reported market volume is at least $10,000.")
        elif volume >= 1_000:
            score += 5
            reasons.append("Reported market volume is at least $1,000.")

        liquidity = market.liquidity or 0.0
        if liquidity >= 100_000:
            score += 10
            reasons.append("Reported liquidity is at least $100,000.")
        elif liquidity >= 10_000:
            score += 5
            reasons.append("Reported liquidity is at least $10,000.")

        now = datetime.now(timezone.utc)
        if market.closes_at:
            close = market.closes_at
            if close.tzinfo is None:
                close = close.replace(tzinfo=timezone.utc)
            hours = (close - now).total_seconds() / 3600
            if 0 <= hours <= 24:
                score += 15
                reasons.append("The contract is scheduled to close within 24 hours.")
            elif 24 < hours <= 24 * 7:
                score += 10
                reasons.append("The contract is scheduled to close within seven days.")
            elif 24 * 7 < hours <= 24 * 30:
                score += 5
                reasons.append("The contract is scheduled to close within 30 days.")

        # A contract that references a company but contains none of the configured
        # manipulability terms remains visible at low severity rather than disappearing.
        score = max(0, min(100, score))
        return MatchResult(
            organization=organization.name,
            matched_identity_terms=unique_strings(identity_hits),
            matched_metric_terms=unique_strings(metric_hits),
            categories=unique_strings(categories),
            risk_score=score,
            severity=severity_for(score),
            reasons=unique_strings(reasons),
            stakeholders=unique_strings(stakeholders),
            actions=unique_strings(actions),
        )
