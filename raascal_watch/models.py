from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MarketRecord:
    source: str
    external_id: str
    title: str
    description: str = ""
    url: str = ""
    status: str = "unknown"
    created_at: datetime | None = None
    closes_at: datetime | None = None
    probability: float | None = None
    volume: float | None = None
    volume_24h: float | None = None
    liquidity: float | None = None
    open_interest: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def searchable_text(self) -> str:
        return " ".join(part for part in (self.title, self.description) if part)


@dataclass(slots=True, frozen=True)
class OrganizationWatch:
    name: str
    aliases: tuple[str, ...]
    products: tuple[str, ...] = ()
    executives: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    stakeholders: tuple[str, ...] = ()
    playbook: tuple[str, ...] = ()
    enabled: bool = True

    @property
    def identity_terms(self) -> tuple[str, ...]:
        values = [*self.aliases, *self.products, *self.executives]
        return tuple(dict.fromkeys(term.strip() for term in values if term.strip()))


@dataclass(slots=True, frozen=True)
class RiskCategory:
    name: str
    weight: int
    terms: tuple[str, ...]
    stakeholders: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class Watchlist:
    organizations: tuple[OrganizationWatch, ...]
    categories: tuple[RiskCategory, ...]


@dataclass(slots=True)
class MatchResult:
    organization: str
    matched_identity_terms: list[str]
    matched_metric_terms: list[str]
    categories: list[str]
    risk_score: int
    severity: str
    reasons: list[str]
    stakeholders: list[str]
    actions: list[str]


@dataclass(slots=True)
class SourceFetchResult:
    source: str
    markets: list[MarketRecord]
    pages: int
    error: str | None = None


@dataclass(slots=True)
class ScanSourceSummary:
    source: str
    fetched: int = 0
    new_markets: int = 0
    matches: int = 0
    new_matches: int = 0
    notifications: int = 0
    baseline_suppressed: int = 0
    pages: int = 0
    error: str | None = None


@dataclass(slots=True)
class ScanSummary:
    started_at: datetime
    finished_at: datetime
    sources: list[ScanSourceSummary]

    @property
    def fetched(self) -> int:
        return sum(item.fetched for item in self.sources)

    @property
    def new_markets(self) -> int:
        return sum(item.new_markets for item in self.sources)

    @property
    def matches(self) -> int:
        return sum(item.matches for item in self.sources)

    @property
    def notifications(self) -> int:
        return sum(item.notifications for item in self.sources)
