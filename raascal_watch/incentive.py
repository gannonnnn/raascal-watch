from __future__ import annotations

"""Explain who can benefit, know, influence, define, and absorb a contract.

The output is intentionally deterministic and conservative. It describes
potential incentive and information pathways; it never identifies an insider,
attributes intent, or treats a profitable position as proof of misconduct.
"""

from typing import Any

from .models import MarketRecord, OrganizationWatch
from .text import parse_jsonish, unique_strings


def _clip_probability(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def _position_side(side: str, price: float | None, condition: str) -> dict[str, Any]:
    if price is None or price <= 0:
        upside = None
        gross_return_multiple = None
        gross_profit_per_dollar = None
    else:
        upside = max(0.0, 1.0 - price)
        gross_return_multiple = 1.0 / price
        gross_profit_per_dollar = upside / price
    return {
        "side": side,
        "holder_label": f"{side}-position holders",
        "condition": condition,
        "price": price,
        "gross_upside_per_share": upside,
        "gross_return_multiple": gross_return_multiple,
        "gross_profit_per_dollar": gross_profit_per_dollar,
        "note": (
            "A winning share settles at $1. Figures use the displayed market price "
            "and exclude fees, entry timing, position changes, and total position size."
        ),
    }


def _outcome_focus(categories: list[str], roles: list[str]) -> str:
    category_set = set(categories)
    if "availability_and_incident" in category_set:
        return "Adverse operational event"
    if "oracle_and_data_dependency" in category_set or any(
        "Resolution-data" in role for role in roles
    ):
        return "Data-defined settlement outcome"
    if category_set.intersection(
        {"engagement_manipulation", "user_growth", "popularity_and_ranking"}
    ):
        return "Public metric, adoption, or ranking threshold"
    if "financial_metric" in category_set:
        return "Reported company KPI or financial threshold"
    if category_set.intersection(
        {"direct_control_and_advance_knowledge", "platform_action"}
    ):
        return "Controlled decision, release, statement, or enforcement outcome"
    if "benchmark_and_evaluation_integrity" in category_set:
        return "Benchmark, leaderboard, or evaluation result"
    if "Monitored theme / contract family" in roles:
        return "Monitored contract theme"
    return "Referenced real-world outcome"


def _organization_access_context(name: str) -> list[str]:
    lowered = name.casefold()
    if "openai" in lowered or "chatgpt" in lowered:
        return [
            "Product, model, launch, communications, and finance personnel with pre-public access",
            "Contractors, cloud providers, evaluation partners, and launch partners with advance context",
        ]
    if "mrbeast" in lowered or "beast industries" in lowered:
        return [
            "Production staff, editors, sponsors, agencies, and distribution partners",
            "People with pre-public access to upload timing, content, promotion, or product placement",
        ]
    if "youtube" in lowered:
        return [
            "Creator, partner-management, trust-and-safety, and platform-integrity teams",
            "Promotion, measurement, or distribution partners with early campaign visibility",
        ]
    if "spotify" in lowered:
        return [
            "Artist, label, distributor, playlist, growth, and platform-integrity teams",
            "Partners with advance campaign, release, or subscriber information",
        ]
    if "cloudflare" in lowered:
        return [
            "SRE, network, security, incident-response, and status-communications personnel",
            "Infrastructure vendors or customers with early operational telemetry",
        ]
    if "flightaware" in lowered:
        return [
            "Data operations, licensing, corrections, and source-governance personnel",
            "Airline, airport, and data partners with early cancellation or status information",
        ]
    if "apple app store" in lowered or "app store ranking" in lowered:
        return [
            "App developers, Growth teams, acquisition agencies, and distribution partners with advance campaign plans",
            "Apple App Store integrity, chart, developer-relations, and measurement teams",
        ]
    return []


def _information_holders(
    organization: OrganizationWatch, categories: list[str], roles: list[str]
) -> list[str]:
    category_set = set(categories)
    items = _organization_access_context(organization.name)

    if category_set.intersection(
        {"direct_control_and_advance_knowledge", "platform_action"}
    ) or any("Direct control" in role for role in roles):
        items.extend(
            [
                "Employees or executives who control the decision, wording, release, or announcement",
                "Contractors, vendors, agencies, or partners with pre-public access",
            ]
        )
    if "availability_and_incident" in category_set:
        items.extend(
            [
                "SRE, security, incident-response, and infrastructure personnel",
                "Vendors or partners with operational telemetry before public status updates",
            ]
        )
    if "financial_metric" in category_set:
        items.extend(
            [
                "Finance, data, investor-relations, audit, and reporting personnel",
                "Partners with pre-public access to the controlled KPI definition or result",
            ]
        )
    if "oracle_and_data_dependency" in category_set or any(
        "Resolution-data" in role for role in roles
    ):
        items.extend(
            [
                f"{organization.name} teams that publish, correct, license, or interpret the resolving data",
                "Parties with early access to the source data or correction process",
            ]
        )
    if category_set.intersection(
        {"engagement_manipulation", "user_growth", "popularity_and_ranking"}
    ):
        items.extend(
            [
                "Platform-integrity, growth, creator, promotion, and measurement teams",
                "Campaign or distribution partners who can see activity before public reporting",
            ]
        )
    if "benchmark_and_evaluation_integrity" in category_set:
        items.extend(
            [
                "Benchmark maintainers, evaluators, model teams, and submission partners",
                "People with pre-public access to evaluation rules or final scores",
            ]
        )

    if not items:
        items.append(
            "Employees, contractors, vendors, or partners with legitimate pre-public knowledge of the resolving event"
        )
    return unique_strings(items)[:6]


def _influence_actors(categories: list[str], roles: list[str]) -> list[str]:
    category_set = set(categories)
    items: list[str] = []

    if category_set.intersection(
        {"engagement_manipulation", "user_growth", "popularity_and_ranking"}
    ):
        items.extend(
            [
                "Bot, automation, account-farm, or coordinated-user operators",
                "Paid acquisition, promotion, creator, affiliate, or distribution partners",
                "Users or communities capable of concentrating activity around the measured metric",
            ]
        )
    if "availability_and_incident" in category_set:
        items.extend(
            [
                "External disruption or attack actors",
                "Internal operators or vendors with privileged technical access",
                "Dependent infrastructure providers whose failure can affect the outcome",
            ]
        )
    if "oracle_and_data_dependency" in category_set or any(
        "Resolution-data" in role for role in roles
    ):
        items.extend(
            [
                "The source operator that publishes, corrects, delays, or interprets the deciding data",
                "Actors able to alter data collection, source availability, or the evidence used in settlement",
            ]
        )
    if "financial_metric" in category_set:
        items.extend(
            [
                "Account farms, transaction or subscription manipulators, and acquisition partners",
                "Internal teams that define, classify, or report the KPI",
            ]
        )
    if category_set.intersection(
        {"direct_control_and_advance_knowledge", "platform_action"}
    ):
        items.append(
            "The person or organization that directly controls the announcement, release, wording, pricing, enforcement, or decision"
        )
    if "benchmark_and_evaluation_integrity" in category_set:
        items.extend(
            [
                "Benchmark submitters, evaluators, voters, or rule-set maintainers",
                "Actors able to contaminate, game, selectively disclose, or time the evaluation",
            ]
        )

    if not items:
        items.append(
            "Actors capable of moving the underlying outcome or the public signal used to measure it"
        )
    return unique_strings(items)[:6]



def _information_advantage(categories: list[str], roles: list[str]) -> dict[str, str]:
    category_set = set(categories)
    role_set = set(roles)
    if role_set.intersection(
        {
            "Direct control / advance knowledge",
            "Reporting / KPI owner",
            "Benchmark / evaluation participant",
            "Decision owner",
        }
    ) or category_set.intersection(
        {"direct_control_and_advance_knowledge", "financial_metric", "platform_action"}
    ):
        return {
            "level": "high",
            "label": "Narrow pre-public access group is plausible",
            "detail": (
                "A limited set of employees, contractors, vendors, advisers, or partners may "
                "know or directly control the answer before public disclosure. A well-timed "
                "position becomes meaningful only when paired with credible access, a duty, "
                "or other evidence—not because it was profitable."
            ),
        }
    if role_set.intersection(
        {
            "Availability / incident target",
            "Resolution-data source / oracle",
            "Platform / metric owner",
        }
    ) or category_set.intersection(
        {
            "availability_and_incident",
            "oracle_and_data_dependency",
            "engagement_manipulation",
            "user_growth",
            "popularity_and_ranking",
        }
    ):
        return {
            "level": "moderate",
            "label": "Operational information advantage is plausible",
            "detail": (
                "Internal telemetry, campaign plans, source-data corrections, or incident "
                "information may be visible to a narrower group before public confirmation."
            ),
        }
    return {
        "level": "contextual",
        "label": "No narrow pre-public access group is obvious",
        "detail": (
            "The market may still influence behavior, but public contract metadata does not "
            "identify a clear nonpublic-information pathway."
        ),
    }


def _cost_bearers(
    organization: OrganizationWatch,
    categories: list[str],
    roles: list[str],
) -> list[str]:
    category_set = set(categories)
    role_set = set(roles)
    items: list[str] = []

    if category_set.intersection(
        {"engagement_manipulation", "user_growth", "popularity_and_ranking"}
    ) or "Platform / metric owner" in role_set:
        items.extend(
            [
                f"{organization.name} Product, Engineering, Growth, Analytics, and Trust & Safety teams",
                "Customers or creators whose recommendations, ranking, or experience is distorted",
                "Leadership and investors relying on the metric as evidence of genuine demand",
            ]
        )
    if "financial_metric" in category_set or "Reporting / KPI owner" in role_set:
        items.extend(
            [
                "Finance, Investor Relations, planning, and executive teams",
                "Employees and customers affected by capital, hiring, or roadmap decisions built on a distorted KPI",
            ]
        )
    if "availability_and_incident" in category_set or "Availability / incident target" in role_set:
        items.extend(
            [
                f"{organization.name} Security, SRE, Support, Engineering, Legal, and Communications teams",
                "Customers, partners, and dependent services absorbing the disruption or response cost",
            ]
        )
    if "oracle_and_data_dependency" in category_set or "Resolution-data source / oracle" in role_set:
        items.extend(
            [
                f"{organization.name} data, licensing, product, legal, and support teams",
                "Market participants and customers affected by source outages, corrections, or settlement disputes",
            ]
        )
    if category_set.intersection(
        {"direct_control_and_advance_knowledge", "platform_action"}
    ) or "Direct control / advance knowledge" in role_set:
        items.extend(
            [
                f"{organization.name} Legal, Compliance, Communications, and people-management teams",
                "Employees, vendors, and partners subject to investigation after a suspected information leak",
            ]
        )
    if "benchmark_and_evaluation_integrity" in category_set:
        items.extend(
            [
                "Research, Product, Procurement, Marketing, and customers relying on the published evaluation",
                "Teams whose roadmap or claims are redirected toward a gamed benchmark",
            ]
        )
    if "Monitored theme / contract family" in role_set:
        items.extend(
            [
                "Operational teams, partners, and customers acting on a market-implied disruption before the underlying data is verified",
            ]
        )

    if not items:
        items.append(
            f"{organization.name} teams that act on the referenced outcome before validating whether the signal is organic"
        )
    return unique_strings(items)[:6]

def _resolution_sources(market: MarketRecord, organization: OrganizationWatch, roles: list[str]) -> list[str]:
    raw = market.raw or {}
    items: list[str] = []

    series = raw.get("_raascal_series")
    if isinstance(series, dict):
        sources = series.get("settlement_sources") or series.get("settlementSources")
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict):
                    label = str(source.get("name") or source.get("title") or "").strip()
                    if label:
                        items.append(label)
                elif str(source).strip():
                    items.append(str(source).strip())

    event = raw.get("event") if isinstance(raw.get("event"), dict) else {}
    market_raw = raw.get("market") if isinstance(raw.get("market"), dict) else {}
    for container in (market_raw, event, raw):
        if not isinstance(container, dict):
            continue
        for key in (
            "resolutionSource",
            "resolution_source",
            "resolutionSourceUrl",
            "resolution_source_url",
            "sourceAgency",
            "source_agency",
        ):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                items.append(value.strip())

    if any("Resolution-data source" in role for role in roles):
        items.insert(0, organization.name)

    items.append(f"The published {market.source.title()} contract rules and named settlement source")
    return unique_strings(items)[:4]


def _cascade(categories: list[str], metric_label: str) -> list[dict[str, str]]:
    category_set = set(categories)

    if category_set.intersection(
        {"engagement_manipulation", "user_growth", "popularity_and_ranking"}
    ):
        return [
            {
                "stage": "External incentive",
                "detail": f"Money is attached to moving or correctly anticipating {metric_label}.",
            },
            {
                "stage": "False signal",
                "detail": "Unusual traffic, installs, streams, subscribers, reviews, or engagement appears legitimate in company dashboards.",
            },
            {
                "stage": "Internal decision",
                "detail": "Product, Growth, or Engineering treats the lift as genuine demand and redirects roadmap, capacity, or spend.",
            },
            {
                "stage": "Potential cost",
                "detail": "The company invests in a false signal, delays higher-value work, degrades customer experience, or reports misleading success.",
            },
        ]

    if "financial_metric" in category_set:
        return [
            {
                "stage": "External incentive",
                "detail": f"A financial position benefits from a reported {metric_label} outcome.",
            },
            {
                "stage": "Contaminated KPI",
                "detail": "Manufactured accounts, subscriptions, transactions, or classification choices can make the metric look stronger or weaker than underlying demand.",
            },
            {
                "stage": "Internal decision",
                "detail": "Leadership, Finance, Product, or Investor Relations relies on the apparent KPI when allocating capital or communicating performance.",
            },
            {
                "stage": "Potential cost",
                "detail": "Strategy, forecasts, disclosures, budgets, or staffing may be based on a distorted measure.",
            },
        ]

    if "availability_and_incident" in category_set:
        return [
            {
                "stage": "External incentive",
                "detail": "A market position benefits from the occurrence or non-occurrence of an outage, incident, disruption, or failure.",
            },
            {
                "stage": "Operational signal",
                "detail": "Real attacks, rumors, partial degradation, or noisy telemetry can move both the service and the market price.",
            },
            {
                "stage": "Internal decision",
                "detail": "Security, SRE, Support, and Engineering divert capacity into containment, investigation, communications, or control changes.",
            },
            {
                "stage": "Potential cost",
                "detail": "Even an unsuccessful attempt can create response expense, customer loss, roadmap delay, and reputational damage.",
            },
        ]

    if "oracle_and_data_dependency" in category_set:
        return [
            {
                "stage": "External incentive",
                "detail": "A financial contract depends on a company’s data, status page, public counter, API, or correction process.",
            },
            {
                "stage": "Data pressure",
                "detail": "Scraping, source outages, interpretation disputes, correction requests, or attempts to influence publication can increase around settlement.",
            },
            {
                "stage": "Internal decision",
                "detail": "Data, Legal, Product, and Operations must determine source authority, licensing, correction, and escalation responsibilities.",
            },
            {
                "stage": "Potential cost",
                "detail": "The company can absorb infrastructure, licensing, dispute, and reputational costs without being the subject of the bet.",
            },
        ]

    if "benchmark_and_evaluation_integrity" in category_set:
        return [
            {
                "stage": "External incentive",
                "detail": "Money is attached to a benchmark, leaderboard, model ranking, or evaluation result.",
            },
            {
                "stage": "Distorted evaluation",
                "detail": "Selective submissions, contamination, evaluator access, or timing can change the public result.",
            },
            {
                "stage": "Internal decision",
                "detail": "Product, Research, Marketing, or leadership treats the ranking as evidence of capability or market demand.",
            },
            {
                "stage": "Potential cost",
                "detail": "Roadmaps, claims, spend, and customer expectations can be shaped by an evaluation that does not generalize.",
            },
        ]

    if category_set.intersection(
        {"direct_control_and_advance_knowledge", "platform_action"}
    ):
        return [
            {
                "stage": "External incentive",
                "detail": "A market position benefits from a decision, statement, launch, release, enforcement action, or controlled event.",
            },
            {
                "stage": "Information advantage",
                "detail": "A small group may know or directly determine the answer before public disclosure.",
            },
            {
                "stage": "Market effect",
                "detail": "Trading can move before the announcement, or the controlled decision can be influenced by the existence of the position.",
            },
            {
                "stage": "Potential cost",
                "detail": "The organization faces insider-risk, communications, legal, governance, and trust consequences.",
            },
        ]

    return [
        {
            "stage": "External incentive",
            "detail": "A financial position is attached to a real-world outcome connected to the monitored profile.",
        },
        {
            "stage": "Observed signal",
            "detail": "The company or public may interpret activity around the outcome as organic information.",
        },
        {
            "stage": "Internal decision",
            "detail": "Teams may investigate, communicate, or reallocate resources around that signal.",
        },
        {
            "stage": "Potential cost",
            "detail": "Time, capital, reputation, or customer experience can be affected even when no manipulation is proven.",
        },
    ]


def _traceability(source: str) -> dict[str, Any]:
    normalized = source.strip().lower()
    if normalized == "polymarket":
        return {
            "level": "wallet_level",
            "label": "Higher public traceability",
            "holder_snapshot_supported": True,
            "detail": (
                "Polymarket exposes public market-holder, position, and trade activity by wallet. "
                "A wallet can be pseudonymous, positions can change before settlement, and profit "
                "does not establish identity, nonpublic access, or misconduct."
            ),
            "after_close": (
                "The public may be able to review wallet-level exposure, P&L, and trading timing, "
                "but linking a wallet to a real person and proving an information advantage requires independent evidence."
            ),
            "public_checks": [
                "Outcome-side holder concentration and position size",
                "Wallet-level average price, current or realized P&L, and trade timing where published",
                "Public pseudonym or profile attached to a wallet, when the holder chose to expose it",
                "Movement before and after a legitimate public catalyst",
            ],
            "restricted_checks": [
                "Verified real-world identity behind a pseudonymous wallet",
                "Employment, vendor, or access relationship with the affected organization",
                "Whether confidential information was obtained or used in breach of a duty",
            ],
        }
    if normalized == "kalshi":
        return {
            "level": "aggregate_only",
            "label": "Limited public attribution",
            "holder_snapshot_supported": False,
            "detail": (
                "Kalshi exposes public market and trade data, while individual user positions "
                "and identities are not publicly attributable through the public market-data API."
            ),
            "after_close": (
                "The public can examine aggregate prices, volume, open interest, and trades, "
                "but participant-level gains generally require exchange, account-holder, or regulator access."
            ),
            "public_checks": [
                "Aggregate price, volume, open-interest, and trade timing",
                "Movement before and after announcements, incidents, or metric releases",
                "Whether the pattern is unusual enough to preserve and refer for exchange review",
            ],
            "restricted_checks": [
                "The account holder's identity, complete position, and realized profit",
                "KYC, employment, access, and internal surveillance records held by the exchange or regulator",
            ],
        }
    return {
        "level": "unknown",
        "label": "Public attribution unknown",
        "holder_snapshot_supported": False,
        "detail": "The source’s public participant-visibility model has not been mapped.",
        "after_close": "Treat participant attribution as unavailable unless independently verified.",
        "public_checks": ["Contract outcome, price, volume, and public source material when available"],
        "restricted_checks": ["Participant identity, position, and access relationship unless the source publishes them"],
    }

def _post_close_checks(source: str, metric_label: str) -> list[str]:
    checks = [
        "Compare trade and price timing with the public announcement, incident, metric update, or settlement-source change.",
        f"Compare the company’s internal {metric_label} telemetry with the public value used to settle the contract.",
        "Review whether activity arrived through an unusual channel, cohort, geography, partner, device pattern, or account-age segment.",
        "Preserve the contract rules, settlement source, market activity, and relevant internal logs before retention windows expire.",
    ]
    if source.strip().lower() == "polymarket":
        checks.insert(
            1,
            "Review public wallet-level positions and trade history where available, without treating a wallet, position, or profit as proof of identity or insider status.",
        )
    elif source.strip().lower() == "kalshi":
        checks.insert(
            1,
            "Review aggregate public trade, price, volume, and open-interest patterns; public participant attribution is generally unavailable.",
        )
    return checks[:6]


def _field_note_headline(categories: list[str], roles: list[str], profile_name: str = "") -> str:
    category_set = set(categories)
    if profile_name.casefold() in {"apple app store", "app store ranking markets"}:
        return "The metric moved. Did demand?"
    if "oracle_and_data_dependency" in category_set or any(
        "Resolution-data" in role for role in roles
    ):
        return "The company may not be the subject of the bet. Its data can still decide who gets paid."
    if "availability_and_incident" in category_set:
        return "An operational failure can become someone else’s financial position."
    if category_set.intersection(
        {"engagement_manipulation", "user_growth", "popularity_and_ranking"}
    ):
        return "A product metric can become both an internal signal and a trading target."
    if category_set.intersection(
        {"direct_control_and_advance_knowledge", "platform_action"}
    ):
        return "The people who control the answer may also know it before the market does."
    if "financial_metric" in category_set:
        return "A company KPI can become a traded outcome before it becomes a public number."
    if "benchmark_and_evaluation_integrity" in category_set:
        return "A benchmark can become a product narrative and a traded outcome at the same time."
    return "A prediction market can change the incentives around a company before it changes the outcome."



def _evidence_ladder(source: str) -> list[dict[str, str]]:
    source_name = source.strip().title() or "The market"
    return [
        {
            "level": "1 · Incentive exists",
            "detail": f"A public {source_name} contract creates a financial position tied to the outcome.",
        },
        {
            "level": "2 · Exposure is observable",
            "detail": (
                "Prices, volume, timing, and—on some sources—wallet-level positions can show who or what side benefited. "
                "They do not establish identity or intent."
            ),
        },
        {
            "level": "3 · Access or influence overlaps",
            "detail": (
                "Concern rises when a beneficiary also had legitimate pre-public access, direct control, privileged technical access, "
                "or a realistic pathway to influence the measured outcome."
            ),
        },
        {
            "level": "4 · Timing or behavior is anomalous",
            "detail": (
                "Unusual trading before disclosure, concentrated activity, a sudden metric spike, or an unexplained channel shift can justify review."
            ),
        },
        {
            "level": "5 · Independent evidence is required",
            "detail": (
                "A misconduct conclusion requires corroborating evidence such as identity, duty, access, communications, internal logs, "
                "or exchange/regulator findings. Profit alone is not proof."
            ),
        },
    ]

def build_incentive_map(
    *,
    market: MarketRecord,
    organization: OrganizationWatch,
    roles: list[str],
    categories: list[str],
    metric_label: str,
) -> dict[str, Any]:
    probability = _clip_probability(market.probability)
    yes_price = probability
    no_price = None if probability is None else 1.0 - probability

    return {
        "version": 1,
        "headline": _field_note_headline(categories, roles, organization.name),
        "outcome_focus": _outcome_focus(categories, roles),
        "benefit_sides": [
            _position_side(
                "YES",
                yes_price,
                "Benefits if the contract’s stated condition occurs.",
            ),
            _position_side(
                "NO",
                no_price,
                "Benefits if the contract’s stated condition does not occur.",
            ),
        ],
        "information_holders": _information_holders(organization, categories, roles),
        "influence_actors": _influence_actors(categories, roles),
        "information_advantage": _information_advantage(categories, roles),
        "resolution_sources": _resolution_sources(market, organization, roles),
        "cost_bearers": _cost_bearers(organization, categories, roles),
        "downstream_cascade": _cascade(categories, metric_label),
        "public_traceability": _traceability(market.source),
        "evidence_ladder": _evidence_ladder(market.source),
        "post_close_checks": _post_close_checks(market.source, metric_label),
        "caveat": (
            "This map identifies plausible incentive, access, and operational pathways. "
            "It does not identify an insider, attribute intent, or prove manipulation, "
            "information misuse, or misconduct."
        ),
    }


def polymarket_condition_id(raw: dict[str, Any]) -> str | None:
    market = raw.get("market") if isinstance(raw.get("market"), dict) else raw
    if not isinstance(market, dict):
        return None
    for key in ("conditionId", "condition_id", "conditionID"):
        value = market.get(key)
        if value and str(value).strip():
            clean = str(value).strip()
            if clean.startswith("0x") and len(clean) == 66:
                return clean
    return None


def polymarket_outcomes(raw: dict[str, Any]) -> list[str]:
    market = raw.get("market") if isinstance(raw.get("market"), dict) else raw
    if not isinstance(market, dict):
        return ["Yes", "No"]
    value = parse_jsonish(market.get("outcomes"))
    if isinstance(value, list) and value:
        return [str(item) for item in value]
    return ["Yes", "No"]
