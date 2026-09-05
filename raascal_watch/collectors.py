from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlsplit

import httpx

from .models import CollectorContext, MarketRecord, SourceFetchResult
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
    attempts: int = 5,
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
        host = urlsplit(url).hostname or url
        detail = str(last_error)
        lowered = detail.lower()
        if any(
            marker in lowered
            for marker in (
                "nodename nor servname",
                "name or service not known",
                "temporary failure in name resolution",
                "getaddrinfo failed",
            )
        ):
            raise CollectorTransportError(
                f"DNS lookup failed for {host}. Check the current Wi-Fi, VPN, "
                "Private Relay, or DNS connection; stored results remain available "
                "and the next scheduled scan will retry."
            )
        raise CollectorTransportError(f"Request failed for {url}: {last_error}")
    raise CollectorError(f"Request failed for {url}: {last_error}")


class MarketCollector(ABC):
    name: str
    progress_callback: Callable[..., None] | None = None

    def report_progress(self, **values: Any) -> None:
        if self.progress_callback is not None:
            self.progress_callback(**values)

    @abstractmethod
    async def fetch(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        context: CollectorContext | None = None,
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
        """Return officially supported Kalshi hosts in local priority order."""
        primary = settings.kalshi_base_url
        compatibility = settings.kalshi_fallback_base_url
        if settings.kalshi_prefer_compatibility_host and compatibility:
            values = [compatibility, primary]
        else:
            values = [primary, compatibility]
        return list(dict.fromkeys(value.rstrip("/") for value in values if value))

    @staticmethod
    def _chunks(values: Iterable[str], size: int) -> Iterable[tuple[str, ...]]:
        batch: list[str] = []
        for value in values:
            clean = str(value).strip()
            if not clean:
                continue
            batch.append(clean)
            if len(batch) >= size:
                yield tuple(batch)
                batch = []
        if batch:
            yield tuple(batch)

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
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        context: CollectorContext | None = None,
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
        preferred_base_url = working_base_url if working_base_url in base_urls else (
            base_urls[0] if base_urls else None
        )

        async def fetch_endpoint(
            path: str, params: dict[str, Any]
        ) -> dict[str, Any]:
            """Fetch a public Kalshi endpoint with supported-host failover."""
            nonlocal preferred_base_url
            last_error: CollectorError | None = None
            candidates = list(
                dict.fromkeys(
                    value for value in (preferred_base_url, *base_urls) if value
                )
            )

            for index, base_url in enumerate(candidates):
                endpoint = f"{base_url}/{path.lstrip('/')}"
                try:
                    payload = await get_json(client, endpoint, params=params)
                    if base_url != preferred_base_url:
                        logger.warning(
                            "Kalshi collector switched to supported host %s",
                            base_url,
                        )
                    preferred_base_url = base_url
                    self._working_base_url = base_url
                    return payload
                except CollectorHTTPError as exc:
                    last_error = exc
                    if index + 1 < len(candidates) and exc.status_code in {403, 404}:
                        logger.warning(
                            "Kalshi host %s returned HTTP %s; trying %s",
                            base_url,
                            exc.status_code,
                            candidates[index + 1],
                        )
                        continue
                    raise
                except CollectorTransportError as exc:
                    last_error = exc
                    if index + 1 < len(candidates):
                        logger.warning(
                            "Kalshi host %s was unreachable; trying %s",
                            base_url,
                            candidates[index + 1],
                        )
                        continue
                    raise

            raise last_error or CollectorError(
                "No available Kalshi API host remains for this request"
            )

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
                self.report_progress(pages=pages, downloaded=len(records))
                next_cursor = payload.get("cursor")
                return str(next_cursor) if next_cursor else None

            # Discover concrete series tickers matching configured family prefixes.
            # A dependency rule may intentionally contain a family prefix such as
            # KXFLYCANC, while the actual tradable series are KXFLYCANCJFK,
            # KXFLYCANCLAX, and so on. A prefix must never be sent to Kalshi as if
            # it were an exact series ticker.
            priority_prefixes = self._priority_series_tickers(settings)
            priority_series: list[str] = []
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
                        "Kalshi priority-series list discovery failed; exact series "
                        "checks will continue: %s",
                        exc,
                    )

                # Some monitored families are themselves exact series tickers
                # (for example KXUSFLYCAN). Verify each configured value through
                # the single-series endpoint before querying /markets. Prefix-only
                # values return 404/403 on some Kalshi hosts and are simply ignored.
                for candidate in priority_prefixes:
                    if candidate in priority_series:
                        continue
                    try:
                        payload = await fetch_endpoint(
                            f"series/{quote(candidate, safe='-')}", {}
                        )
                        pages += 1
                    except CollectorError as exc:
                        logger.info(
                            "Kalshi configured series value %s is a family prefix or "
                            "is currently unavailable; it will not be queried as an "
                            "exact series: %s",
                            candidate,
                            exc,
                        )
                        continue
                    item = payload.get("series")
                    if not isinstance(item, dict):
                        continue
                    ticker = str(item.get("ticker") or "").strip().upper()
                    if ticker != candidate:
                        continue
                    series_metadata[ticker] = item
                    priority_series.append(ticker)

            # Query verified niche series first. A failure in one optional series
            # must not abort the entire Kalshi source; the broad open-market scan
            # remains useful and may still contain the same contracts.
            for series_ticker in priority_series:
                try:
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
                        if (
                            series_pages >= settings.kalshi_priority_series_page_limit
                            and cursor
                        ):
                            logger.warning(
                                "Kalshi priority series %s reached its page limit",
                                series_ticker,
                            )
                except CollectorError as exc:
                    logger.warning(
                        "Kalshi priority series %s could not be refreshed; continuing "
                        "with the remaining series and broad scan: %s",
                        series_ticker,
                        exc,
                    )
                    continue

            incremental = bool(
                settings.kalshi_incremental_scan
                and context is not None
                and context.source_initialized
                and context.last_success_at is not None
            )

            # Keep existing active matches current without traversing the full
            # catalog. Kalshi supports comma-separated ticker retrieval, so the
            # reviewer queue can refresh price, volume, status, and close times in
            # bounded batches. Optional batch failures do not block discovery.
            if (
                incremental
                and settings.kalshi_refresh_active_matches
                and context is not None
                and context.active_external_ids
            ):
                refreshed_batches = 0
                for batch in self._chunks(
                    context.active_external_ids, settings.kalshi_refresh_batch_size
                ):
                    params: dict[str, Any] = {
                        "tickers": ",".join(batch),
                        "limit": min(1000, max(1, len(batch))),
                    }
                    if settings.kalshi_exclude_multivariate:
                        params["mve_filter"] = "exclude"
                    try:
                        payload = await fetch_page(params)
                        pages += 1
                        refreshed_batches += 1
                        parse_payload(payload)
                    except CollectorError as exc:
                        logger.warning(
                            "Kalshi active-match refresh batch failed; continuing "
                            "with discovery: %s",
                            exc,
                        )
                    if settings.kalshi_page_delay_seconds > 0:
                        await asyncio.sleep(settings.kalshi_page_delay_seconds)
                logger.info(
                    "Kalshi incremental refresh checked %s active matched contract(s) "
                    "in %s batch(es)",
                    len(context.active_external_ids),
                    refreshed_batches,
                )

            # Open and unopened are fetched separately because Kalshi supports one
            # status filter per request. After a successful baseline, discovery is
            # incremental: only contracts created since the last successful scan
            # (with a safety overlap) are paged. This avoids re-reading roughly
            # 100,000 catalog records every fifteen minutes.
            broad_pages = 0
            page_limit = (
                settings.kalshi_incremental_page_limit
                if incremental
                else settings.max_pages_per_source
            )
            page_size = (
                settings.kalshi_incremental_page_size
                if incremental
                else settings.kalshi_page_size
            )
            min_created_ts: int | None = None
            if incremental and context is not None and context.last_success_at is not None:
                discovery_start = context.last_success_at - timedelta(
                    minutes=settings.kalshi_discovery_overlap_minutes
                )
                min_created_ts = max(0, int(discovery_start.timestamp()))
                logger.info(
                    "Kalshi incremental discovery begins at %s with a %s-minute overlap",
                    discovery_start.isoformat(),
                    settings.kalshi_discovery_overlap_minutes,
                )

            for status in ("open", "unopened"):
                cursor = None
                while broad_pages < page_limit:
                    params = {
                        "status": status,
                        "limit": page_size,
                    }
                    if min_created_ts is not None:
                        params["min_created_ts"] = min_created_ts
                    if settings.kalshi_exclude_multivariate:
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

                if broad_pages >= page_limit:
                    mode = "incremental" if incremental else "baseline"
                    self.report_progress(warning="Catalog discovery reached its local page cap; coverage may be partial.")
                    logger.warning(
                        "Kalshi %s discovery reached the configured page limit", mode
                    )
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
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        context: CollectorContext | None = None,
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
                self.report_progress(pages=pages, downloaded=len(records))
                next_cursor = payload.get("next_cursor")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = str(next_cursor)
            if pages >= settings.max_pages_per_source and next_cursor:
                self.report_progress(warning="Catalog discovery reached its local page cap; coverage may be partial.")
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
