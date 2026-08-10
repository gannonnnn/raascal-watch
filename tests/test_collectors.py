from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx

from raascal_watch.collectors import KalshiCollector, PolymarketCollector
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
