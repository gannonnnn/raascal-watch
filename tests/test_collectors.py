from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx

from raascal_watch.collectors import (
    CollectorTransportError,
    KalshiCollector,
    PolymarketCollector,
    get_json,
)
from raascal_watch.settings import get_settings


def test_kalshi_parser_normalizes_market() -> None:
    item = {
        "ticker": "KXSPOTIFY-26",
        "event_ticker": "KXSPOTIFY",
        "title": "Will Spotify report subscriber growth?",
        "subtitle": "Above 10%",
        "created_time": "2026-08-05T15:00:00Z",
        "close_time": "2026-08-31T20:00:00Z",
        "last_price_dollars": "0.6200",
        "volume_fp": "125000.00",
        "volume_24h_fp": "14000.00",
        "liquidity_dollars": "8500.00",
        "open_interest_fp": "21000.00",
        "rules_primary": "Resolves from published results.",
        "status": "open",
    }
    market = KalshiCollector.parse_market(item)
    assert market is not None
    assert market.external_id == "KXSPOTIFY-26"
    assert market.probability == 0.62
    assert market.volume == 125000.0
    assert "Above 10%" in market.title
    assert market.url.endswith("/kxspotify")


def test_polymarket_parser_uses_event_context() -> None:
    event = {
        "id": "event-1",
        "slug": "spotify-chart-demo",
        "title": "Spotify chart performance",
        "description": "A demo event.",
        "createdAt": "2026-08-05T15:00:00Z",
        "endDate": "2026-08-31T20:00:00Z",
        "markets": [
            {
                "id": "market-1",
                "slug": "will-artist-x-rank-number-one",
                "question": "Will Artist X rank number one?",
                "outcomePrices": '["0.41", "0.59"]',
                "volumeNum": 225000,
                "liquidityNum": 17000,
                "active": True,
                "closed": False,
            }
        ],
    }
    records = PolymarketCollector.parse_event(event)
    assert len(records) == 1
    market = records[0]
    assert market.external_id == "market-1"
    assert market.probability == 0.41
    assert market.volume == 225000.0
    assert "Spotify chart performance" in market.title
    assert "Will Artist X rank number one?" in market.title
    assert market.url.endswith("/will-artist-x-rank-number-one")


def test_kalshi_falls_back_to_supported_host_after_403() -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        assert request.url.params.get("mve_filter") == "exclude"
        assert request.url.params.get("limit") == "1000"
        if request.url.host == "external-api.kalshi.com":
            return httpx.Response(403, text="Forbidden", request=request)
        return httpx.Response(
            200,
            json={
                "markets": [
                    {
                        "ticker": "KXFALLBACK-26",
                        "event_ticker": "KXFALLBACK",
                        "title": "Will the supported fallback work?",
                        "status": "open",
                    }
                ],
                "cursor": "",
            },
            request=request,
        )

    async def run() -> tuple[object, list[str]]:
        settings = replace(
            get_settings(),
            max_pages_per_source=2,
            kalshi_base_url="https://external-api.kalshi.com/trade-api/v2",
            kalshi_fallback_base_url=(
                "https://api.elections.kalshi.com/trade-api/v2"
            ),
            kalshi_priority_series_scan=False,
            kalshi_prefer_compatibility_host=False,
        )
        collector = KalshiCollector()
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            result = await collector.fetch(client, settings)
        return result, requested_hosts

    result, hosts = asyncio.run(run())
    assert result.error is None
    assert result.pages == 2
    assert len(result.markets) == 1
    assert result.markets[0].external_id == "KXFALLBACK-26"
    assert hosts[0] == "external-api.kalshi.com"
    assert hosts[1:] == [
        "api.elections.kalshi.com",
        "api.elections.kalshi.com",
    ]


def test_kalshi_remembers_working_fallback_for_session() -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        if request.url.host == "external-api.kalshi.com":
            return httpx.Response(403, text="Forbidden", request=request)
        return httpx.Response(200, json={"markets": [], "cursor": ""}, request=request)

    async def run() -> None:
        settings = replace(
            get_settings(),
            max_pages_per_source=2,
            kalshi_base_url="https://external-api.kalshi.com/trade-api/v2",
            kalshi_fallback_base_url=(
                "https://api.elections.kalshi.com/trade-api/v2"
            ),
            kalshi_priority_series_scan=False,
            kalshi_prefer_compatibility_host=False,
        )
        collector = KalshiCollector()
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await collector.fetch(client, settings)
            second = await collector.fetch(client, settings)
        assert first.error is None
        assert second.error is None

    asyncio.run(run())
    assert requested_hosts.count("external-api.kalshi.com") == 1
    assert requested_hosts[-1] == "api.elections.kalshi.com"


def test_kalshi_priority_series_pull_surfaces_flight_cancellation_family() -> None:
    requests_seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        requests_seen.append(params)
        if request.url.path.endswith("/series/KXUSFLYCAN"):
            return httpx.Response(
                200,
                json={"series": {"ticker": "KXUSFLYCAN"}},
                request=request,
            )
        series = params.get("series_ticker")
        if series == "KXUSFLYCAN" and params.get("status") == "open":
            return httpx.Response(
                200,
                json={
                    "markets": [
                        {
                            "ticker": "KXUSFLYCAN-26AUG14-T5000",
                            "event_ticker": "KXUSFLYCAN-26AUG14",
                            "series_ticker": "KXUSFLYCAN",
                            "title": "US flight cancellations for the week ending August 14",
                            "rules_primary": "Outcome verified from Primary Source Agency.",
                            "status": "open",
                        }
                    ],
                    "cursor": "",
                },
                request=request,
            )
        return httpx.Response(200, json={"markets": [], "cursor": ""}, request=request)

    async def run():
        settings = replace(
            get_settings(),
            max_pages_per_source=1,
            kalshi_base_url="https://api.elections.kalshi.com/trade-api/v2",
            kalshi_fallback_base_url=None,
            kalshi_priority_series_scan=True,
            kalshi_priority_series_page_limit=2,
        )
        collector = KalshiCollector()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collector.fetch(client, settings)

    result = asyncio.run(run())

    assert result.error is None
    assert any(
        item.get("series_ticker") == "KXUSFLYCAN"
        for item in requests_seen
    )
    assert {market.external_id for market in result.markets} == {
        "KXUSFLYCAN-26AUG14-T5000"
    }


def test_kalshi_discovers_prefixed_airport_cancellation_series() -> None:
    requested_series: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/series"):
            return httpx.Response(
                200,
                json={
                    "series": [
                        {
                            "ticker": "KXFLYCANCJFK",
                            "title": "JFK flight cancellations",
                            "category": "Transportation",
                            "settlement_sources": [
                                {
                                    "name": "Primary Source Agency",
                                    "url": "https://www.flightaware.com/",
                                }
                            ],
                            "contract_terms_url": "https://assets.kalshi.com/AIRPORTDELAY.pdf",
                        }
                    ]
                },
                request=request,
            )
        params = dict(request.url.params)
        series = params.get("series_ticker")
        if series:
            requested_series.append(series)
        if series == "KXFLYCANCJFK" and params.get("status") == "open":
            return httpx.Response(
                200,
                json={
                    "markets": [
                        {
                            "ticker": "KXFLYCANCJFK-26AUG15-T50",
                            "event_ticker": "KXFLYCANCJFK-26AUG15",
                            "series_ticker": "KXFLYCANCJFK",
                            "title": "Will at least 50% of scheduled passenger flights at JFK be cancelled?",
                            "rules_primary": "Outcome verified from Primary Source Agency.",
                            "status": "open",
                        }
                    ],
                    "cursor": "",
                },
                request=request,
            )
        return httpx.Response(200, json={"markets": [], "cursor": ""}, request=request)

    async def run():
        settings = replace(
            get_settings(),
            max_pages_per_source=1,
            kalshi_base_url="https://api.elections.kalshi.com/trade-api/v2",
            kalshi_fallback_base_url=None,
            kalshi_priority_series_scan=True,
            kalshi_priority_series_page_limit=2,
        )
        collector = KalshiCollector()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collector.fetch(client, settings)

    result = asyncio.run(run())

    assert result.error is None
    assert "KXFLYCANCJFK" in requested_series
    assert "KXFLYCANC" not in requested_series
    market = next(
        item
        for item in result.markets
        if item.external_id == "KXFLYCANCJFK-26AUG15-T50"
    )
    assert "FlightAware" not in market.description
    assert market.raw["_raascal_series"]["ticker"] == "KXFLYCANCJFK"
    assert market.raw["_raascal_series"]["settlement_sources"][0]["url"].endswith("flightaware.com/")


def test_kalshi_priority_series_failure_does_not_abort_broad_scan() -> None:
    requests_seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        series = params.get("series_ticker")
        requests_seen.append((path, series))

        if path.endswith("/series"):
            return httpx.Response(
                200,
                json={
                    "series": [
                        {
                            "ticker": "KXFLYCANCJFK",
                            "title": "JFK flight cancellations",
                            "category": "Transportation",
                        }
                    ]
                },
                request=request,
            )
        if "/series/" in path:
            ticker = path.rsplit("/", 1)[-1]
            if ticker == "KXUSFLYCAN":
                return httpx.Response(
                    200,
                    json={"series": {"ticker": ticker}},
                    request=request,
                )
            return httpx.Response(404, text="not found", request=request)
        if series == "KXFLYCANCJFK":
            return httpx.Response(403, text="Forbidden", request=request)
        if series == "KXUSFLYCAN":
            return httpx.Response(200, json={"markets": [], "cursor": ""}, request=request)
        if not series and params.get("status") == "open":
            return httpx.Response(
                200,
                json={
                    "markets": [
                        {
                            "ticker": "KXBROAD-26",
                            "event_ticker": "KXBROAD",
                            "title": "Broad scan still succeeds",
                            "status": "open",
                        }
                    ],
                    "cursor": "",
                },
                request=request,
            )
        return httpx.Response(200, json={"markets": [], "cursor": ""}, request=request)

    async def run():
        settings = replace(
            get_settings(),
            max_pages_per_source=2,
            kalshi_base_url="https://api.elections.kalshi.com/trade-api/v2",
            kalshi_fallback_base_url=None,
            kalshi_priority_series_scan=True,
            kalshi_priority_series_page_limit=2,
        )
        collector = KalshiCollector()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collector.fetch(client, settings)

    result = asyncio.run(run())

    assert result.error is None
    assert any(market.external_id == "KXBROAD-26" for market in result.markets)
    assert any(series == "KXFLYCANCJFK" for _, series in requests_seen)


def test_get_json_explains_dns_resolution_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "[Errno 8] nodename nor servname provided, or not known",
            request=request,
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            try:
                await get_json(
                    client,
                    "https://gamma-api.polymarket.com/events/keyset",
                    attempts=1,
                )
            except CollectorTransportError as exc:
                assert "DNS lookup failed for gamma-api.polymarket.com" in str(exc)
                assert "next scheduled scan will retry" in str(exc)
            else:
                raise AssertionError("Expected a DNS-specific CollectorTransportError")

    asyncio.run(run())


def test_kalshi_incremental_refresh_uses_active_tickers_and_created_overlap() -> None:
    from datetime import datetime, timezone

    from raascal_watch.models import CollectorContext

    requests_seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        requests_seen.append(params)
        tickers = params.get("tickers")
        if tickers:
            markets = [
                {
                    "ticker": ticker,
                    "event_ticker": ticker.split("-")[0],
                    "title": f"Refresh {ticker}",
                    "status": "open",
                }
                for ticker in tickers.split(",")
            ]
            return httpx.Response(
                200, json={"markets": markets, "cursor": ""}, request=request
            )
        return httpx.Response(200, json={"markets": [], "cursor": ""}, request=request)

    async def run():
        settings = replace(
            get_settings(),
            kalshi_base_url="https://external-api.kalshi.com/trade-api/v2",
            kalshi_fallback_base_url="https://api.elections.kalshi.com/trade-api/v2",
            kalshi_prefer_compatibility_host=True,
            kalshi_priority_series_scan=False,
            kalshi_incremental_scan=True,
            kalshi_incremental_page_size=250,
            kalshi_incremental_page_limit=12,
            kalshi_discovery_overlap_minutes=180,
            kalshi_refresh_active_matches=True,
            kalshi_refresh_batch_size=2,
        )
        context = CollectorContext(
            source_initialized=True,
            last_success_at=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
            active_external_ids=("KXA-1", "KXB-1", "KXC-1"),
        )
        collector = KalshiCollector()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collector.fetch(client, settings, context)

    result = asyncio.run(run())
    assert result.error is None
    assert result.pages == 4  # two ticker batches plus open/unopened discovery
    ticker_requests = [item for item in requests_seen if item.get("tickers")]
    discovery_requests = [item for item in requests_seen if item.get("status")]
    assert [item["tickers"] for item in ticker_requests] == ["KXA-1,KXB-1", "KXC-1"]
    assert {item["status"] for item in discovery_requests} == {"open", "unopened"}
    assert all(item["limit"] == "250" for item in discovery_requests)
    assert all("min_created_ts" in item for item in discovery_requests)
    assert {market.external_id for market in result.markets} == {
        "KXA-1",
        "KXB-1",
        "KXC-1",
    }


def test_kalshi_initial_baseline_keeps_full_catalog_pagination() -> None:
    requests_seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        requests_seen.append(params)
        return httpx.Response(200, json={"markets": [], "cursor": ""}, request=request)

    async def run():
        settings = replace(
            get_settings(),
            max_pages_per_source=4,
            kalshi_page_size=1000,
            kalshi_priority_series_scan=False,
            kalshi_prefer_compatibility_host=True,
        )
        collector = KalshiCollector()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collector.fetch(client, settings)

    result = asyncio.run(run())
    assert result.error is None
    discovery_requests = [item for item in requests_seen if item.get("status")]
    assert {item["status"] for item in discovery_requests} == {"open", "unopened"}
    assert all(item["limit"] == "1000" for item in discovery_requests)
    assert all("min_created_ts" not in item for item in discovery_requests)
