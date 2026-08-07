from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

import httpx

from .models import MarketRecord, SourceFetchResult
from .settings import Settings
from .text import (
    coerce_float,
    first_present,
    parse_datetime,
    parse_jsonish,
    probability,
    unique_strings,
)

logger = logging.getLogger(__name__)


class CollectorError(RuntimeError):
    pass


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    attempts: int = 4,
) -> dict[str, Any]:
    """Fetch JSON with conservative retry handling for transient API failures."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == attempts - 1:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(8.0, 2**attempt)
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise CollectorError(f"Expected JSON object from {url}")
            return payload
        except (httpx.HTTPError, ValueError, CollectorError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            await asyncio.sleep(min(8.0, 2**attempt))
    raise CollectorError(f"Request failed for {url}: {last_error}")


class MarketCollector(ABC):
    name: str

    @abstractmethod
    async def fetch(
        self, client: httpx.AsyncClient, settings: Settings
    ) -> SourceFetchResult:
        raise NotImplementedError


class KalshiCollector(MarketCollector):
    name = "kalshi"

    @staticmethod
    def parse_market(item: dict[str, Any]) -> MarketRecord | None:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            return None

        title_parts = unique_strings(
            str(value)
            for value in (
                item.get("title"),
                item.get("subtitle"),
                item.get("yes_sub_title"),
            )
            if value
        )
        title = " — ".join(title_parts) or ticker
        description = "\n\n".join(
            unique_strings(
                str(value)
                for value in (item.get("rules_primary"), item.get("rules_secondary"))
                if value
            )
        )

        event_ticker = str(item.get("event_ticker") or ticker).strip().lower()
        market_url = f"https://kalshi.com/markets/{quote(event_ticker, safe='-')}"

        raw_probability = first_present(
            item,
            (
                "last_price_dollars",
                "yes_ask_dollars",
                "yes_bid_dollars",
                "last_price",
                "yes_ask",
                "yes_bid",
            ),
        )
        return MarketRecord(
            source="kalshi",
            external_id=ticker,
            title=title,
            description=description,
            url=market_url,
            status=str(item.get("status") or "unknown"),
            created_at=parse_datetime(item.get("created_time")),
            closes_at=parse_datetime(
                first_present(
                    item,
                    (
                        "expected_expiration_time",
                        "expiration_time",
                        "close_time",
                        "latest_expiration_time",
                    ),
                )
            ),
            probability=probability(raw_probability),
            volume=coerce_float(first_present(item, ("volume_fp", "volume"))),
            volume_24h=coerce_float(
                first_present(item, ("volume_24h_fp", "volume_24h"))
            ),
            liquidity=coerce_float(
                first_present(item, ("liquidity_dollars", "liquidity"))
            ),
            open_interest=coerce_float(
                first_present(item, ("open_interest_fp", "open_interest"))
            ),
            raw=item,
        )

    async def fetch(
        self, client: httpx.AsyncClient, settings: Settings
    ) -> SourceFetchResult:
        records: dict[str, MarketRecord] = {}
        pages = 0
        endpoint = f"{settings.kalshi_base_url}/markets"
        try:
            # Open and unopened are fetched separately because Kalshi supports one
            # status filter per request. Unopened contracts matter for early alerts.
            for status in ("open", "unopened"):
                cursor: str | None = None
                while pages < settings.max_pages_per_source:
                    params: dict[str, Any] = {"status": status, "limit": 1000}
                    if cursor:
                        params["cursor"] = cursor
                    payload = await get_json(client, endpoint, params=params)
                    pages += 1
                    items = payload.get("markets", [])
                    if not isinstance(items, list):
                        raise CollectorError("Kalshi response field 'markets' was not a list")
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        parsed = self.parse_market(item)
                        if parsed:
                            records[parsed.external_id] = parsed
                    next_cursor = payload.get("cursor")
                    if not next_cursor or next_cursor == cursor:
                        break
                    cursor = str(next_cursor)
                if pages >= settings.max_pages_per_source:
                    logger.warning("Kalshi scan reached the configured page limit")
                    break
            return SourceFetchResult(self.name, list(records.values()), pages)
        except Exception as exc:  # collector boundary: preserve other sources
            logger.exception("Kalshi collection failed")
            return SourceFetchResult(self.name, list(records.values()), pages, str(exc))


class PolymarketCollector(MarketCollector):
    name = "polymarket"

    @staticmethod
    def _outcome_probability(market: dict[str, Any]) -> float | None:
        direct = first_present(
            market,
            ("lastTradePrice", "last_trade_price", "bestAsk", "bestBid"),
        )
        direct_probability = probability(direct)
        if direct_probability is not None:
            return direct_probability
        outcome_prices = parse_jsonish(
            first_present(market, ("outcomePrices", "outcome_prices"))
        )
        if isinstance(outcome_prices, list) and outcome_prices:
            return probability(outcome_prices[0])
        if isinstance(outcome_prices, dict):
            for key in ("yes", "Yes", "YES"):
                if key in outcome_prices:
                    return probability(outcome_prices[key])
        return None

    @staticmethod
    def parse_event(event: dict[str, Any]) -> list[MarketRecord]:
        event_id = str(event.get("id") or "").strip()
        event_title = str(event.get("title") or event.get("question") or "").strip()
        event_slug = str(event.get("slug") or "").strip()
        event_description = "\n\n".join(
            unique_strings(
                str(value)
                for value in (
                    event.get("description"),
                    event.get("resolutionSource"),
                    event.get("resolution_source"),
                )
                if value
            )
        )
        markets = event.get("markets")
        if not isinstance(markets, list) or not markets:
            markets = [event]

        event_raw = {key: value for key, value in event.items() if key != "markets"}
        records: list[MarketRecord] = []
        for market in markets:
            if not isinstance(market, dict):
                continue
            market_id = str(
                market.get("id")
                or market.get("conditionId")
                or market.get("condition_id")
                or market.get("slug")
                or event_id
            ).strip()
            if not market_id:
                continue

            question = str(market.get("question") or market.get("title") or "").strip()
            if event_title and question and event_title.lower() != question.lower():
                title = f"{event_title} — {question}"
            else:
                title = question or event_title or market_id

            market_description = str(market.get("description") or "").strip()
            description = "\n\n".join(
                unique_strings([event_description, market_description])
            )
            market_slug = str(market.get("slug") or "").strip()
            if market_slug:
                url = f"https://polymarket.com/market/{quote(market_slug, safe='-')}"
            elif event_slug:
                url = f"https://polymarket.com/event/{quote(event_slug, safe='-')}"
            else:
                url = "https://polymarket.com/"

            closed = bool(market.get("closed", event.get("closed", False)))
            active = market.get("active", event.get("active", True))
            status = "closed" if closed else ("open" if active is not False else "inactive")

            created_at = parse_datetime(
                first_present(
                    market,
                    ("createdAt", "created_at", "createdDate", "creationDate"),
                )
                or first_present(event, ("createdAt", "created_at", "creationDate"))
            )
            closes_at = parse_datetime(
                first_present(
                    market,
                    ("endDate", "end_date", "endDateIso", "end_date_iso"),
                )
                or first_present(event, ("endDate", "end_date", "endDateIso"))
            )

            records.append(
                MarketRecord(
                    source="polymarket",
                    external_id=market_id,
                    title=title,
                    description=description,
                    url=url,
                    status=status,
                    created_at=created_at,
                    closes_at=closes_at,
                    probability=PolymarketCollector._outcome_probability(market),
                    volume=coerce_float(
                        first_present(market, ("volumeNum", "volume", "volume_num"))
                        or first_present(event, ("volumeNum", "volume"))
                    ),
                    volume_24h=coerce_float(
                        first_present(
                            market,
                            ("volume24hr", "volume24Hr", "volume_24h", "volume24h"),
                        )
                        or first_present(
                            event,
                            ("volume24hr", "volume24Hr", "volume_24h", "volume24h"),
                        )
                    ),
                    liquidity=coerce_float(
                        first_present(
                            market,
                            ("liquidityNum", "liquidity", "liquidity_num"),
                        )
                        or first_present(event, ("liquidityNum", "liquidity"))
                    ),
                    open_interest=coerce_float(
                        first_present(market, ("openInterest", "open_interest"))
                    ),
                    raw={"event": event_raw, "market": market},
                )
            )
        return records

    async def fetch(
        self, client: httpx.AsyncClient, settings: Settings
    ) -> SourceFetchResult:
        records: dict[str, MarketRecord] = {}
        pages = 0
        cursor: str | None = None
        endpoint = f"{settings.polymarket_base_url}/events/keyset"
        try:
            while pages < settings.max_pages_per_source:
                params: dict[str, Any] = {"closed": "false", "limit": 100}
                if cursor:
                    params["after_cursor"] = cursor
                payload = await get_json(client, endpoint, params=params)
                pages += 1
                events = payload.get("events", [])
                if not isinstance(events, list):
                    raise CollectorError("Polymarket response field 'events' was not a list")
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    for parsed in self.parse_event(event):
                        records[parsed.external_id] = parsed
                next_cursor = payload.get("next_cursor")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = str(next_cursor)
            if pages >= settings.max_pages_per_source:
                logger.warning("Polymarket scan reached the configured page limit")
            return SourceFetchResult(self.name, list(records.values()), pages)
        except Exception as exc:  # collector boundary: preserve other sources
            logger.exception("Polymarket collection failed")
            return SourceFetchResult(self.name, list(records.values()), pages, str(exc))


def enabled_collectors(settings: Settings) -> list[MarketCollector]:
    collectors: list[MarketCollector] = []
    if settings.enable_kalshi:
        collectors.append(KalshiCollector())
    if settings.enable_polymarket:
        collectors.append(PolymarketCollector())
    return collectors
