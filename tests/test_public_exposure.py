from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from raascal_watch.exposure import fetch_public_exposure
from raascal_watch.models import MarketRecord

CONDITION_ID = "0x" + "b" * 64
WALLET = "0x" + "c" * 40


def polymarket_record() -> MarketRecord:
    return MarketRecord(
        source="polymarket",
        external_id="poly-exposure",
        title="Will the metric cross a threshold?",
        probability=0.45,
        raw={
            "market": {
                "conditionId": CONDITION_ID,
                "outcomes": '["Yes", "No"]',
            }
        },
    )


def test_polymarket_exposure_parses_positions_holders_trades_and_pnl() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/market-positions":
            assert request.url.params["market"] == CONDITION_ID
            assert request.url.params["sortBy"] == "TOTAL_PNL"
            return httpx.Response(
                200,
                json=[
                    {
                        "token": "yes-token",
                        "positions": [
                            {
                                "proxyWallet": WALLET,
                                "name": "Public Researcher",
                                "verified": True,
                                "conditionId": CONDITION_ID,
                                "avgPrice": 0.18,
                                "size": 1000,
                                "currPrice": 0.45,
                                "currentValue": 450,
                                "cashPnl": 270,
                                "realizedPnl": 50,
                                "totalPnl": 320,
                                "outcome": "Yes",
                                "outcomeIndex": 0,
                            }
                        ],
                    }
                ],
            )
        if request.url.path == "/holders":
            return httpx.Response(
                200,
                json=[
                    {
                        "token": "yes-token",
                        "holders": [
                            {
                                "proxyWallet": WALLET,
                                "amount": 1000,
                                "outcomeIndex": 0,
                                "name": "Public Researcher",
                                "displayUsernamePublic": True,
                            }
                        ],
                    }
                ],
            )
        if request.url.path == "/oi":
            return httpx.Response(200, json=[{"market": CONDITION_ID, "value": 12345.67}])
        if request.url.path == "/trades":
            return httpx.Response(
                200,
                json=[
                    {
                        "proxyWallet": WALLET,
                        "side": "BUY",
                        "conditionId": CONDITION_ID,
                        "size": 25,
                        "price": 0.2,
                        "timestamp": 1_700_000_000,
                        "outcome": "Yes",
                        "outcomeIndex": 0,
                        "transactionHash": "0xtrade",
                    }
                ],
            )
        return httpx.Response(404)

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_public_exposure(
                polymarket_record(),
                client=client,
                polymarket_data_api_url="https://data.test",
                holder_limit=5,
                trade_limit=10,
            )

    result = asyncio.run(run())
    assert result["visibility"] == "wallet_level"
    assert result["open_interest"] == 12345.67
    position = result["position_groups"][0]["positions"][0]
    assert position["display_name"] == "Public Researcher"
    assert position["verified_profile"] is True
    assert position["average_price"] == 0.18
    assert position["total_pnl"] == 320
    assert result["holder_groups"][0]["holders"][0]["amount"] == 1000
    assert result["recent_trades"][0]["side"] == "BUY"


def test_polymarket_positions_failure_falls_back_to_holders() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/market-positions":
            return httpx.Response(401, json={"error": "not available"})
        if request.url.path == "/holders":
            return httpx.Response(
                200,
                json=[
                    {
                        "token": "yes-token",
                        "holders": [
                            {"proxyWallet": WALLET, "amount": 55, "outcomeIndex": 0}
                        ],
                    }
                ],
            )
        if request.url.path in {"/oi", "/trades"}:
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_public_exposure(
                polymarket_record(),
                client=client,
                polymarket_data_api_url="https://data.test",
            )

    result = asyncio.run(run())
    assert result["position_groups"] == []
    assert result["holder_groups"][0]["holders"][0]["amount"] == 55
    assert "401" in result["positions_error"]


def test_kalshi_exposure_is_aggregate_and_does_not_claim_public_identity() -> None:
    market = MarketRecord(
        source="kalshi",
        external_id="KXTEST-YES",
        title="Will the event occur?",
        probability=0.5,
        open_interest=1000,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/markets/trades")
        return httpx.Response(
            200,
            json={
                "trades": [
                    {
                        "trade_id": "trade-1",
                        "count": 50,
                        "yes_price": 44,
                        "no_price": 56,
                        "created_time": datetime.now(timezone.utc).isoformat(),
                    }
                ]
            },
        )

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_public_exposure(
                market,
                client=client,
                polymarket_data_api_url="https://data.test",
                kalshi_base_url="https://kalshi.test/trade-api/v2",
            )

    result = asyncio.run(run())
    assert result["visibility"] == "aggregate_only"
    assert result["position_groups"] == []
    assert result["recent_trades"][0]["display_name"] == "Participant not public"
    assert result["recent_trades"][0]["yes_price"] == 0.44
    assert result["recent_trades"][0]["no_price"] == 0.56
    assert "does not publicly attribute" in result["detail"]


def test_polymarket_partial_endpoint_failure_keeps_trade_snapshot_useful() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/market-positions":
            return httpx.Response(503, json={"error": "positions temporarily unavailable"})
        if request.url.path == "/holders":
            return httpx.Response(503, json={"error": "holders temporarily unavailable"})
        if request.url.path == "/oi":
            return httpx.Response(503, json={"error": "open interest temporarily unavailable"})
        if request.url.path == "/trades":
            return httpx.Response(
                200,
                json=[
                    {
                        "proxyWallet": WALLET,
                        "side": "SELL",
                        "conditionId": CONDITION_ID,
                        "size": 10,
                        "price": 0.72,
                        "timestamp": 1_700_000_000,
                        "outcome": "No",
                        "outcomeIndex": 1,
                    }
                ],
            )
        return httpx.Response(404)

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_public_exposure(
                polymarket_record(),
                client=client,
                polymarket_data_api_url="https://data.test",
            )

    result = asyncio.run(run())
    assert result["position_groups"] == []
    assert result["holder_groups"] == []
    assert result["recent_trades"][0]["side"] == "SELL"
    assert "503" in result["positions_error"]
    assert "503" in result["holders_error"]
    assert "503" in result["open_interest_error"]
    assert result["trades_error"] is None
