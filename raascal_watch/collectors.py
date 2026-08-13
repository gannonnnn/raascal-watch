from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

import httpx

from .models import MarketRecord, SourceFetchResult
from .settings import Settings
from .watchlist import WatchlistError, load_watchlist
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


class CollectorHTTPError(CollectorError):
    """HTTP failure that preserves status and response detail for failover."""

    def __init__(self, url: str, status_code: int, detail: str | None = None):
        self.url = url
        self.status_code = status_code
        self.detail = detail
        message = f"HTTP {status_code} for {url}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class CollectorTransportError(CollectorError):
    """Network-layer failure such as DNS, connection, or timeout errors."""


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    attempts: int = 4,
) -> dict[str, Any]:
    """Fetch JSON with conservative retries and diagnostic HTTP errors."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params)
        except httpx.RequestError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            await asyncio.sleep(min(8.0, 2**attempt))
            continue

        if response.status_code == 429 or response.status_code >= 500:
            if attempt < attempts - 1:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = (
                        float(retry_after)
                        if retry_after
                        else min(8.0, 2**attempt)
                    )
                except (TypeError, ValueError):
                    delay = min(8.0, 2**attempt)
                await asyncio.sleep(delay)
                continue

        if response.is_error:
            detail = " ".join(response.text.strip().split())[:500] or None
            raise CollectorHTTPError(
                str(response.request.url), response.status_code, detail
            )

        try:
            payload = response.json()
        except ValueError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            await asyncio.sleep(min(8.0, 2**attempt))
            continue

        if not isinstance(payload, dict):
            last_error = CollectorError(f"Expected JSON object from {url}")
            if attempt == attempts - 1:
                break
            await asyncio.sleep(min(8.0, 2**attempt))
            continue
        return payload

    if isinstance(last_error, httpx.RequestError):
        raise CollectorTransportError(f"Request failed for {url}: {last_error}")
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

    @staticmethod
    def _base_urls(settings: Settings) -> list[str]:
        """Return the official Kalshi hosts in priority order without duplicates."""
        values = [settings.kalshi_base_url, settings.kalshi_fallback_base_url]
        return list(dict.fromkeys(value.rstrip("/") for value in values if value))

    @staticmethod
    def _priority_series_tickers(settings: Settings) -> list[str]:
        """Return configured Kalshi series families that deserve targeted pulls.

        Broad market pagination can hit its safety cap before a niche contract
        family is encountered. Dependency rules in the watchlist provide a
        transparent, configuration-backed list of series to query directly.
        """
        if not settings.kalshi_priority_series_scan:
            return []
        try:
            watchlist = load_watchlist(settings.watchlist_path)
        except (FileNotFoundError, WatchlistError, OSError) as exc:
            logger.warning("Kalshi priority-series discovery skipped: %s", exc)
            return []

        values: list[str] = []
        for profile in watchlist.organizations:
            for rule in profile.dependency_rules:
                if rule.source and rule.source != "kalshi":
                    continue
                values.extend(rule.series_ticker_prefixes)
        return list(
            dict.fromkeys(value.strip().upper() for value in values if value.strip())
        )

    async def fetch(
        self, client: httpx.AsyncClient, settings: Settings
    ) -> SourceFetchResult:
        records: dict[str, MarketRecord] = {}
        pages = 0
        configured_base_urls = self._base_urls(settings)
        working_base_url = getattr(self, "_working_base_url", None)
        base_urls = list(
            dict.fromkeys(
                value
                for value in (working_base_url, *configured_base_urls)
                if value
            )
        )
        active_base_index = 0

        async def fetch_endpoint(
            path: str, params: dict[str, Any]
        ) -> dict[str, Any]:
            """Fetch a public Kalshi endpoint with supported-host failover."""
            nonlocal active_base_index
            last_error: CollectorError | None = None

            for index in range(active_base_index, len(base_urls)):
                base_url = base_urls[index]
                endpoint = f"{base_url}/{path.lstrip('/')}"
                try:
                    payload = await get_json(client, endpoint, params=params)
                    if index != active_base_index:
                        logger.warning(
                            "Kalshi collector switched to supported fallback host %s",
                            base_url,
                        )
                    active_base_index = index
                    self._working_base_url = base_url
                    return payload
                except CollectorHTTPError as exc:
                    last_error = exc
                    can_fallback = index + 1 < len(base_urls)
                    if can_fallback and exc.status_code in {403, 404}:
                        logger.warning(
                            "Kalshi host %s returned HTTP %s; trying %s",
                            base_url,
                            exc.status_code,
                            base_urls[index + 1],
                        )
                        continue
                    raise
                except CollectorTransportError as exc:
                    last_error = exc
                    if index + 1 < len(base_urls):
                        logger.warning(
                            "Kalshi host %s was unreachable; trying %s",
                            base_url,
                            base_urls[index + 1],
                        )
                        continue
                    raise

            raise last_error or CollectorError("No Kalshi API host is configured")

        async def fetch_page(params: dict[str, Any]) -> dict[str, Any]:
            return await fetch_endpoint("markets", params)

        try:
            if not base_urls:
                raise CollectorError("No Kalshi API host is configured")

            series_metadata: dict[str, dict[str, Any]] = {}

            def parse_payload(payload: dict[str, Any]) -> str | None:
                items = payload.get("markets", [])
                if not isinstance(items, list):
                    raise CollectorError(
                        "Kalshi response field 'markets' was not a list"
                    )
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    parsed = self.parse_market(item)
                    if parsed:
                        series_ticker = str(item.get("series_ticker") or "").strip().upper()
                        metadata = series_metadata.get(series_ticker)
                        if metadata:
                            # Preserve source-family evidence without injecting it
                            # into searchable contract text. This keeps a linked or
                            # verified dependency distinct from a direct name mention.
                            parsed.raw = {**parsed.raw, "_raascal_series": metadata}
                        records[parsed.external_id] = parsed
                next_cursor = payload.get("cursor")
                return str(next_cursor) if next_cursor else None

            # Discover concrete series tickers matching configured family prefixes.
            # This catches families whose actual series ticker adds an airport or
            # geography suffix (for example a KXFLYCANC... airport series).
            priority_prefixes = self._priority_series_tickers(settings)
            priority_series = list(priority_prefixes)
            if priority_prefixes:
                try:
                    series_payload = await fetch_endpoint(
                        "series",
                        {
                            "category": "Transportation",
                            "include_product_metadata": "true",
                        },
                    )
                    pages += 1
                    series_items = series_payload.get("series", [])
                    if isinstance(series_items, list):
                        for item in series_items:
                            if not isinstance(item, dict):
                                continue
                            ticker = str(item.get("ticker") or "").strip().upper()
                            if not ticker or not any(
                                ticker.startswith(prefix)
                                for prefix in priority_prefixes
                            ):
                                continue
                            series_metadata[ticker] = item
                            if ticker not in priority_series:
                                priority_series.append(ticker)
                except CollectorError as exc:
                    logger.warning(
                        "Kalshi priority-series discovery failed; continuing with configured series: %s",
                        exc,
                    )

            # Query configured niche series first. This prevents a broad page cap
            # from hiding a monitored contract family such as KXUSFLYCAN.
            for series_ticker in priority_series:
                for status in ("open", "unopened"):
                    cursor: str | None = None
                    series_pages = 0
                    while series_pages < settings.kalshi_priority_series_page_limit:
                        params: dict[str, Any] = {
                            "status": status,
                            "series_ticker": series_ticker,
                            "limit": settings.kalshi_page_size,
                        }
                        if settings.kalshi_exclude_multivariate:
                            params["mve_filter"] = "exclude"
                        if cursor:
                            params["cursor"] = cursor

                        payload = await fetch_page(params)
                        pages += 1
                        series_pages += 1
                        next_cursor = parse_payload(payload)
                        if not next_cursor or next_cursor == cursor:
                            break
                        cursor = next_cursor
                        if settings.kalshi_page_delay_seconds > 0:
                            await asyncio.sleep(settings.kalshi_page_delay_seconds)
                    if series_pages >= settings.kalshi_priority_series_page_limit and cursor:
                        logger.warning(
                            "Kalshi priority series %s reached its page limit",
                            series_ticker,
                        )

            # Open and unopened are fetched separately because Kalshi supports one
            # status filter per request. Unopened contracts matter for early alerts.
            broad_pages = 0
            for status in ("open", "unopened"):
                cursor = None
                while broad_pages < settings.max_pages_per_source:
                    params = {
                        "status": status,
                        "limit": settings.kalshi_page_size,
                    }
                    if settings.kalshi_exclude_multivariate:
                        # Combination markets add substantial noise and volume but
                        # rarely help company-risk monitoring.
                        params["mve_filter"] = "exclude"
                    if cursor:
                        params["cursor"] = cursor

                    payload = await fetch_page(params)
                    pages += 1
                    broad_pages += 1
                    next_cursor = parse_payload(payload)
                    if not next_cursor or next_cursor == cursor:
                        break
                    cursor = next_cursor
                    if settings.kalshi_page_delay_seconds > 0:
                        await asyncio.sleep(settings.kalshi_page_delay_seconds)

                if broad_pages >= settings.max_pages_per_source:
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
            # Keep event context in the stored searchable title so organization
            # references in a broad event name are not lost. The dashboard uses
            # raw market metadata to display only the specific tradable question.
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
