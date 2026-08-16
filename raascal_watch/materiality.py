from __future__ import annotations

"""Materiality gates for turning a large candidate library into a review queue.

The model is deterministic and deliberately separates three questions:

* Observed: relevant enough to retain, but no human action is required today.
* Review: a credible pathway and a current activation trigger justify review.
* Escalate: strong movement, urgency, economic activity, or abuse indicators
  justify an immediate time-bound response.

It does not infer intent or treat market activity as evidence of misconduct.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable

from .models import MarketRecord, OrganizationWatch
from .text import parse_datetime, unique_strings

GATE_RANK = {"observed": 1, "review": 2, "escalate": 3}
GATE_LABELS = {
    "observed": "Observed",
    "review": "Review today",
    "escalate": "Escalate now",
}


def _clamp(value: float | int) -> int:
    return max(0, min(100, int(round(float(value)))))


def _band(score: int) -> str:
    if score >= 80:
        return "very high"
    if score >= 65:
        return "high"
    if score >= 45:
        return "moderate"
    if score >= 25:
        return "low"
    return "minimal"


def _hours_until(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    close = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return (close - now).total_seconds() / 3600


def _threshold_score(value: float | None, thresholds: Iterable[tuple[float, int]]) -> int:
    if value is None:
        return 0
    for threshold, score in thresholds:
        if value >= threshold:
            return score
    return 0


def _number(value: float | None) -> str:
    if value is None:
        return "not reported"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def _money(value: float | None) -> str:
    if value is None:
        return "not reported"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def _economic_context(market: MarketRecord) -> dict[str, Any]:
    source = market.source.casefold()
    facts: list[str] = []
    signal_scores: list[int] = []

    if source == "kalshi":
        volume_score = _threshold_score(
            market.volume,
            ((1_000_000, 85), (250_000, 75), (100_000, 65), (25_000, 50), (5_000, 35), (1_000, 20)),
        )
        volume_24h_score = _threshold_score(
            market.volume_24h,
            ((100_000, 100), (25_000, 90), (5_000, 75), (1_000, 60), (250, 40)),
        )
        oi_score = _threshold_score(
            market.open_interest,
            ((250_000, 100), (100_000, 90), (25_000, 75), (5_000, 55), (1_000, 35)),
        )
        liquidity_score = _threshold_score(
            market.liquidity,
            ((250_000, 80), (100_000, 70), (25_000, 55), (5_000, 35)),
        )
        if market.volume is not None:
            facts.append(f"Reported lifetime volume: {_number(market.volume)} contracts")
        if market.volume_24h is not None:
            facts.append(f"Reported 24-hour volume: {_number(market.volume_24h)} contracts")
        if market.open_interest is not None:
            facts.append(f"Reported open interest: {_number(market.open_interest)} contracts")
        if market.liquidity is not None:
            facts.append(f"Reported liquidity: {_money(market.liquidity)}")
        signal_scores = [volume_score, volume_24h_score, oi_score, liquidity_score]
        caveat = (
            "Kalshi volume and open interest are contract counts, not dollars of trader profit. "
            "A winning contract pays $1, but public market data does not reveal any one participant's net exposure."
        )
        unit = "contracts"
    else:
        volume_score = _threshold_score(
            market.volume,
            ((5_000_000, 85), (1_000_000, 75), (250_000, 65), (100_000, 55), (25_000, 40), (5_000, 25)),
        )
        volume_24h_score = _threshold_score(
            market.volume_24h,
            ((250_000, 100), (100_000, 90), (25_000, 75), (5_000, 60), (1_000, 40)),
        )
        oi_score = _threshold_score(
            market.open_interest,
            ((1_000_000, 100), (250_000, 90), (50_000, 75), (10_000, 55), (1_000, 35)),
        )
        liquidity_score = _threshold_score(
            market.liquidity,
            ((250_000, 80), (100_000, 70), (25_000, 55), (5_000, 35)),
        )
        if market.volume is not None:
            facts.append(f"Reported cumulative volume: {_money(market.volume)}")
        if market.volume_24h is not None:
            facts.append(f"Reported 24-hour volume: {_money(market.volume_24h)}")
        if market.open_interest is not None:
            facts.append(f"Reported open interest: {_money(market.open_interest)}")
        if market.liquidity is not None:
            facts.append(f"Reported liquidity: {_money(market.liquidity)}")
        signal_scores = [volume_score, volume_24h_score, oi_score, liquidity_score]
        caveat = (
            "Cumulative volume is not a bounty or the amount one trader can gain. "
            "Material exposure requires position size, entry price, concentration, and holder-level evidence where public."
        )
        unit = "usd"

    strongest = max(signal_scores or [0])
    material_signals = sum(1 for score in signal_scores if score >= 55)
    score = _clamp(strongest + (10 if material_signals >= 2 else 0))
    return {
        "score": score,
        "band": _band(score),
        "label": f"{_band(score).title()} reported market activity",
        "facts": facts or ["No material volume, open-interest, or liquidity field was reported."],
        "unit": unit,
        "caveat": caveat,
    }


def _relationship_context(match_basis: str, roles: list[str]) -> dict[str, Any]:
    score_map = {
        "direct": 75,
        "verified_dependency": 88,
        "linked_dependency": 68,
        "possible_dependency": 45,
        "theme": 60,
    }
    score = score_map.get(match_basis, 50)
    if "Named subject / outcome owner" in roles:
        score = max(score, 82)
    if "Resolution-data source / oracle" in roles and match_basis == "verified_dependency":
        score = max(score, 90)
    labels = {
        "direct": "Direct monitored-entity relationship",
        "verified_dependency": "Verified source or product-family dependency",
        "linked_dependency": "Linked dependency requiring confirmation",
        "possible_dependency": "Possible dependency",
        "theme": "Configured contract-theme relationship",
    }
    rationales = {
        "direct": (
            "A configured company, product, executive, or branded-program phrase matched with phrase boundaries. "
            "That relationship starts retrieval; separate materiality dimensions decide whether a human should act."
        ),
        "verified_dependency": (
            "Source-specific product rules, identifiers, or settlement evidence connect this contract to the profile even when the company name is absent."
        ),
        "linked_dependency": (
            "Configured source-family evidence connects this contract to the profile, but the current settlement relationship still requires confirmation."
        ),
        "possible_dependency": (
            "The contract has a plausible configured dependency, but the relationship is not strong enough to treat as verified."
        ),
        "theme": (
            "A configured topic taxonomy surfaced the contract independently of any one company name; dynamic outcomes and organizational dependencies are resolved separately."
        ),
    }
    return {
        "score": score,
        "band": _band(score),
        "label": labels.get(match_basis, "Configured relationship"),
        "rationale": rationales.get(
            match_basis,
            "The relationship is backed by configured entity, theme, metric, or dependency evidence.",
        ),
        "more_than_keyword": match_basis in {"verified_dependency", "linked_dependency", "possible_dependency", "theme"},
    }


def _dimension_scores(categories: list[str], roles: list[str], profile_name: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    category_set = set(categories)
    role_set = set(roles)

    influence_candidates: list[tuple[int, str]] = []
    information_candidates: list[tuple[int, str]] = []
    downstream_candidates: list[tuple[int, str]] = []

    def add(target: list[tuple[int, str]], score: int, reason: str) -> None:
        target.append((score, reason))

    if "explicit_abuse_language" in category_set:
        add(influence_candidates, 95, "The contract language itself references manipulation, automation, disruption, or coordinated abuse.")
    if "direct_control_and_advance_knowledge" in category_set or "Direct control / advance knowledge" in role_set:
        add(influence_candidates, 90, "A person or organization may directly control the release, statement, timing, or answer.")
        add(information_candidates, 92, "A limited group may know the answer before public disclosure.")
        add(downstream_candidates, 75, "A suspected leak or controlled outcome can create legal, governance, communications, and trust costs.")
    if "platform_action" in category_set or "Decision owner" in role_set:
        add(influence_candidates, 85, "An internal platform, enforcement, pricing, or publication decision may determine the result.")
        add(information_candidates, 82, "Decision owners and reviewers may know the answer before the market.")
        add(downstream_candidates, 78, "External incentives can distort queues, enforcement, pricing, or launch decisions.")
    if "engagement_manipulation" in category_set:
        add(influence_candidates, 82, "Bots, paid acquisition, coordinated users, or promotional partners may move the measured activity.")
        add(information_candidates, 45, "Campaign and distribution partners may see non-public activity before public reporting.")
        add(downstream_candidates, 82, "A false engagement signal can redirect Product, Growth, Engineering, and Marketing resources.")
    if "popularity_and_ranking" in category_set:
        add(influence_candidates, 78, "Installs, searches, reviews, promotion, or concentrated activity may move a public ranking.")
        add(information_candidates, 45, "App, creator, or campaign teams may know planned promotion before the public chart moves.")
        add(downstream_candidates, 84, "A ranking spike can be misread as product-market fit or durable demand.")
    if "user_growth" in category_set:
        add(influence_candidates, 72, "Paid, duplicate, bot, coordinated, or low-retention cohorts may move the reported growth metric.")
        add(information_candidates, 55, "Growth, finance, and data teams may see the metric before public disclosure.")
        add(downstream_candidates, 82, "Contaminated growth signals can change spend, hiring, capacity, and roadmap decisions.")
    if "availability_and_incident" in category_set:
        add(influence_candidates, 68, "External actors or privileged operators may be able to cause, exaggerate, or time an operational incident.")
        add(information_candidates, 72, "SRE, security, vendors, and partners may know about incidents before public status updates.")
        add(downstream_candidates, 92, "Even attempted disruption can consume response capacity and harm customers or dependent services.")
    if "financial_metric" in category_set or "Reporting / KPI owner" in role_set:
        add(influence_candidates, 58, "Accounts, transactions, classification, or reporting choices may move the KPI in some contexts.")
        add(information_candidates, 88, "Finance, data, audit, and reporting personnel may have pre-public access.")
        add(downstream_candidates, 88, "A distorted KPI can affect disclosures, capital allocation, staffing, and strategy.")
    if "benchmark_and_evaluation_integrity" in category_set:
        add(influence_candidates, 64, "Submissions, test selection, evaluator access, contamination, or timing may affect the result.")
        add(information_candidates, 72, "Benchmark maintainers and evaluation partners may know results before publication.")
        add(downstream_candidates, 70, "A gamed benchmark can redirect product claims, procurement, and research priorities.")
    if "oracle_and_data_dependency" in category_set or "Resolution-data source / oracle" in role_set:
        add(influence_candidates, 38, "The source operator may publish, correct, delay, or interpret the data used in settlement.")
        add(information_candidates, 65, "Source, licensing, correction, or data-operations teams may see decisive data first.")
        add(downstream_candidates, 72, "The data provider can absorb scraping, licensing, dispute, infrastructure, and reputational costs.")
    if "Monitored theme / contract family" in role_set:
        add(influence_candidates, 45, "The theme identifies a plausible incentive pathway, but the responsible organization still needs to be resolved.")
        add(downstream_candidates, 65, "Operational teams may act on the market-implied signal before verifying the underlying data.")

    if profile_name.casefold() in {"apple app store", "app store ranking markets"}:
        add(influence_candidates, 82, "App installs, paid acquisition, reviews, searches, and promotion can affect a public App Store ranking.")
        add(information_candidates, 58, "App developers and acquisition partners may know planned campaigns before the ranking window.")
        add(downstream_candidates, 90, "A small company may treat an externally incentivized ranking spike as genuine demand and redirect Engineering or Growth.")

    def summarize(items: list[tuple[int, str]], fallback: str) -> dict[str, Any]:
        if not items:
            return {"score": 20, "band": "minimal", "label": fallback, "rationales": [fallback]}
        score = max(item[0] for item in items)
        rationales = unique_strings(reason for value, reason in sorted(items, reverse=True) if value >= score - 15)
        return {
            "score": score,
            "band": _band(score),
            "label": f"{_band(score).title()} potential",
            "rationales": rationales[:4],
        }

    return (
        summarize(influence_candidates, "No clear practical influence pathway identified."),
        summarize(information_candidates, "No narrow pre-public information group identified."),
        summarize(downstream_candidates, "Downstream operational impact is not yet clear."),
    )


def _urgency_context(closes_at: datetime | None, now: datetime) -> dict[str, Any]:
    hours = _hours_until(closes_at, now)
    if hours is None:
        score, label = 20, "Close time not reported"
    elif hours <= 0:
        score, label = 0, "Contract has already closed"
    elif hours <= 24:
        score, label = 100, "Closes within 24 hours"
    elif hours <= 72:
        score, label = 85, "Closes within 72 hours"
    elif hours <= 24 * 7:
        score, label = 70, "Closes within seven days"
    elif hours <= 24 * 14:
        score, label = 55, "Closes within 14 days"
    elif hours <= 24 * 30:
        score, label = 35, "Closes within 30 days"
    else:
        score, label = 15, "Settlement is more than 30 days away"
    return {
        "score": score,
        "band": _band(score),
        "label": label,
        "hours_until_close": hours,
    }


def _movement_context(movement: dict[str, Any] | None, source: str) -> dict[str, Any]:
    if not movement or int(movement.get("snapshot_count") or 0) < 2:
        return {
            "score": 0,
            "band": "minimal",
            "label": "No comparison yet",
            "changes": ["First observation only; no prior market snapshot is available for comparison."],
        }

    day = movement.get("day_deltas") or movement.get("deltas") or {}
    changes: list[str] = []
    scores: list[int] = []
    probability_delta = day.get("probability")
    if probability_delta is not None and abs(float(probability_delta)) > 0:
        points = abs(float(probability_delta))
        score = 100 if points >= 0.25 else 85 if points >= 0.15 else 65 if points >= 0.08 else 45 if points >= 0.04 else 20
        scores.append(score)
        changes.append(f"Displayed probability moved {float(probability_delta) * 100:+.1f} points in the available 24-hour window.")

    volume_delta = day.get("volume")
    if volume_delta is not None and float(volume_delta) > 0:
        if source.casefold() == "kalshi":
            score = _threshold_score(float(volume_delta), ((50_000, 100), (10_000, 85), (2_000, 65), (500, 45), (100, 25)))
            changes.append(f"Reported volume increased by {_number(float(volume_delta))} contracts in the available 24-hour window.")
        else:
            score = _threshold_score(float(volume_delta), ((100_000, 100), (25_000, 85), (5_000, 65), (1_000, 45), (250, 25)))
            changes.append(f"Reported cumulative volume increased by {_money(float(volume_delta))} in the available 24-hour window.")
        scores.append(score)

    oi_delta = day.get("open_interest")
    if oi_delta is not None and float(oi_delta) > 0:
        if source.casefold() == "kalshi":
            score = _threshold_score(float(oi_delta), ((25_000, 100), (5_000, 80), (1_000, 60), (250, 40)))
            changes.append(f"Reported open interest increased by {_number(float(oi_delta))} contracts.")
        else:
            score = _threshold_score(float(oi_delta), ((100_000, 100), (25_000, 80), (5_000, 60), (1_000, 40)))
            changes.append(f"Reported open interest increased by {_money(float(oi_delta))}.")
        scores.append(score)

    if movement.get("rules_changed"):
        scores.append(90)
        changes.append("The stored contract title, rules, or resolution-source text changed since the previous snapshot.")
    if movement.get("close_changed"):
        scores.append(75)
        changes.append("The contract closing or expected-expiration time changed since the previous snapshot.")
    if movement.get("status_changed"):
        scores.append(65)
        changes.append("The market status changed since the previous snapshot.")

    if not changes:
        changes.append("No material probability, activity, status, rule, or close-time change was recorded in the available 24-hour window.")
    score = max(scores or [0])
    if sum(1 for item in scores if item >= 60) >= 2:
        score = _clamp(score + 10)
    return {
        "score": score,
        "band": _band(score),
        "label": f"{_band(score).title()} observed change" if score else "No material change observed",
        "changes": changes[:5],
    }


def _calculate_gate(
    *,
    relationship: int,
    influence: int,
    information: int,
    economic: int,
    urgency: int,
    downstream: int,
    movement: int,
    categories: list[str],
    match_basis: str,
) -> tuple[str, list[str]]:
    category_set = set(categories)
    activation = economic >= 55 or urgency >= 70 or movement >= 50 or "explicit_abuse_language" in category_set
    pathway = influence >= 70 or information >= 75 or downstream >= 80
    drivers: list[str] = []

    if movement >= 80 and pathway and relationship >= 55 and economic >= 45:
        drivers.append("Material market movement is paired with a credible influence, information, or downstream-impact pathway.")
        return "escalate", drivers
    if "explicit_abuse_language" in category_set and influence >= 85 and (economic >= 55 or urgency >= 70):
        drivers.append("Explicit abuse language is paired with material activity or near-term settlement.")
        return "escalate", drivers
    if "direct_control_and_advance_knowledge" in category_set and information >= 85 and economic >= 70 and urgency >= 55:
        drivers.append("A narrow pre-public access group, meaningful market activity, and approaching settlement coincide.")
        return "escalate", drivers
    if "availability_and_incident" in category_set and influence >= 65 and economic >= 75 and urgency >= 70:
        drivers.append("An adverse operational outcome has high activity and settles soon enough to justify immediate triage.")
        return "escalate", drivers

    if relationship >= 55 and activation and pathway:
        if movement >= 50:
            drivers.append("The contract changed materially in the latest observation window.")
        if economic >= 55:
            drivers.append("Reported market activity is material enough to warrant context and ownership review.")
        if urgency >= 70:
            drivers.append("Settlement is close enough that a delayed review could miss the useful response window.")
        if influence >= 70:
            drivers.append("There is a plausible practical path to influence the measured outcome.")
        if information >= 75:
            drivers.append("A limited group may know or control the answer before public disclosure.")
        if downstream >= 80:
            drivers.append("A false or distorted signal could create meaningful downstream operating cost.")
        return "review", unique_strings(drivers)[:5]

    if match_basis == "verified_dependency" and urgency >= 55 and downstream >= 70:
        drivers.append("A verified data dependency is approaching settlement and may require source, licensing, or dispute readiness.")
        return "review", drivers

    drivers.append("The contract is relevant enough to retain, but it lacks a current activation trigger for human review.")
    return "observed", drivers


def _weighted_score(dimensions: dict[str, dict[str, Any]]) -> int:
    weights = {
        "relationship": 0.10,
        "influenceability": 0.18,
        "information_advantage": 0.16,
        "economic_exposure": 0.18,
        "settlement_urgency": 0.12,
        "downstream_impact": 0.16,
        "market_movement": 0.10,
    }
    return _clamp(sum(float(dimensions[key]["score"]) * weight for key, weight in weights.items()))


def _response_for_gate(gate: str, actions: list[str], stakeholders: list[str]) -> dict[str, Any]:
    owners = unique_strings(stakeholders)[:5]
    if gate == "escalate":
        return {
            "headline": "Open a time-bound cross-functional review now",
            "owners": owners,
            "steps": unique_strings([
                "Assign a named owner before the next scheduled scan.",
                *actions[:3],
                "Document the evidence required to distinguish a public market signal from actual misconduct or operational manipulation.",
            ])[:5],
        }
    if gate == "review":
        return {
            "headline": "Assign an owner and validate the signal today",
            "owners": owners,
            "steps": unique_strings([
                "Confirm the contract's exact settlement condition and the organization's role.",
                *actions[:3],
            ])[:5],
        }
    return {
        "headline": "Retain as observed intelligence; no human action required today",
        "owners": owners,
        "steps": [
            "Keep the contract in the observed library and promote it only if activity, urgency, rules, or a credible influence pathway changes.",
        ],
    }


def build_static_materiality(
    *,
    market: MarketRecord,
    organization: OrganizationWatch,
    match_basis: str,
    roles: list[str],
    categories: list[str],
    actions: list[str],
    stakeholders: list[str],
    dynamic_subjects: list[str],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    relationship = _relationship_context(match_basis, roles)
    influence, information, downstream = _dimension_scores(categories, roles, organization.name)
    economic = _economic_context(market)
    urgency = _urgency_context(market.closes_at, now)
    movement = _movement_context(None, market.source)
    dimensions = {
        "relationship": relationship,
        "influenceability": influence,
        "information_advantage": information,
        "economic_exposure": economic,
        "settlement_urgency": urgency,
        "downstream_impact": downstream,
        "market_movement": movement,
    }
    gate, drivers = _calculate_gate(
        relationship=relationship["score"],
        influence=influence["score"],
        information=information["score"],
        economic=economic["score"],
        urgency=urgency["score"],
        downstream=downstream["score"],
        movement=0,
        categories=categories,
        match_basis=match_basis,
    )
    response = _response_for_gate(gate, actions, stakeholders)
    return {
        "gate": gate,
        "gate_label": GATE_LABELS[gate],
        "materiality_score": _weighted_score(dimensions),
        "dimensions": dimensions,
        "drivers": drivers,
        "why_action": drivers[0],
        "what_changed": movement["changes"],
        "response": response,
        "dynamic_subjects": dynamic_subjects,
        "method_note": (
            "The gate requires both a credible pathway and a current activation trigger. "
            "A high legacy risk score alone does not place a contract in today's review queue."
        ),
    }


def apply_market_movement(
    materiality: dict[str, Any] | None,
    *,
    movement: dict[str, Any] | None,
    source: str,
    categories: list[str],
    match_basis: str,
    actions: list[str],
    stakeholders: list[str],
    closes_at: datetime | str | None = None,
) -> dict[str, Any]:
    current = deepcopy(materiality or {})
    dimensions = deepcopy(current.get("dimensions") or {})
    market_movement = _movement_context(movement, source)
    dimensions["market_movement"] = market_movement
    parsed_close = parse_datetime(closes_at) if isinstance(closes_at, str) else closes_at
    if parsed_close is not None:
        dimensions["settlement_urgency"] = _urgency_context(parsed_close, datetime.now(timezone.utc))

    # Older stored matches receive sensible defaults during migration.
    for key, fallback in (
        ("relationship", {"score": 50, "band": "moderate", "label": "Configured relationship", "rationale": "Stored before materiality scoring."}),
        ("influenceability", {"score": 40, "band": "low", "label": "Low potential", "rationales": []}),
        ("information_advantage", {"score": 40, "band": "low", "label": "Low potential", "rationales": []}),
        ("economic_exposure", {"score": 20, "band": "minimal", "label": "Minimal reported market activity", "facts": [], "caveat": ""}),
        ("settlement_urgency", {"score": 20, "band": "minimal", "label": "Close time not reported"}),
        ("downstream_impact", {"score": 40, "band": "low", "label": "Low potential", "rationales": []}),
    ):
        dimensions.setdefault(key, fallback)

    gate, drivers = _calculate_gate(
        relationship=int(dimensions["relationship"]["score"]),
        influence=int(dimensions["influenceability"]["score"]),
        information=int(dimensions["information_advantage"]["score"]),
        economic=int(dimensions["economic_exposure"]["score"]),
        urgency=int(dimensions["settlement_urgency"]["score"]),
        downstream=int(dimensions["downstream_impact"]["score"]),
        movement=int(market_movement["score"]),
        categories=categories,
        match_basis=match_basis,
    )
    current.update(
        {
            "gate": gate,
            "gate_label": GATE_LABELS[gate],
            "materiality_score": _weighted_score(dimensions),
            "dimensions": dimensions,
            "drivers": drivers,
            "why_action": drivers[0],
            "what_changed": market_movement["changes"],
            "response": _response_for_gate(gate, actions, stakeholders),
        }
    )
    return current


def aggregate_materiality(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    if not reviews:
        return {
            "gate": "observed",
            "gate_label": GATE_LABELS["observed"],
            "materiality_score": 0,
            "drivers": [],
            "what_changed": [],
            "dynamic_subjects": [],
        }
    top = max(
        reviews,
        key=lambda review: (
            GATE_RANK.get(str((review.get("materiality") or {}).get("gate")), 0),
            int((review.get("materiality") or {}).get("materiality_score") or 0),
            int(review.get("risk_score") or 0),
        ),
    )
    top_materiality = deepcopy(top.get("materiality") or {})
    top_materiality["dynamic_subjects"] = list(
        dict.fromkeys(
            subject
            for review in reviews
            for subject in (review.get("dynamic_subjects") or (review.get("materiality") or {}).get("dynamic_subjects") or [])
        )
    )
    top_materiality["profile"] = top.get("organization")
    return top_materiality
