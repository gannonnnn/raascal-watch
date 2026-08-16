from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from raascal_watch.db import Database
from raascal_watch.exposure import fetch_public_exposure
from raascal_watch.models import MarketRecord
from raascal_watch.risk import RiskEngine
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings
from raascal_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]
CONDITION_ID = "0x" + "a" * 64


def engine() -> RiskEngine:
    return RiskEngine(load_watchlist(ROOT / "config" / "watchlist.yaml"))


def settings_for(tmp_path: Path):
    return replace(
        get_settings(),
        db_path=tmp_path / "v07.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
        slack_webhook_url=None,
        generic_webhook_url=None,
        smtp_host=None,
        smtp_from=None,
        smtp_to=(),
    )


def spotify_market(
    *,
    probability: float = 0.2,
    volume: float = 10_000,
    closes_at: datetime | None = None,
) -> MarketRecord:
    return MarketRecord(
        source="polymarket",
        external_id="spotify-signal",
        title="Will Spotify report more than 350 million paid subscribers?",
        description="Resolves using Spotify reporting and subscriber totals.",
        status="open",
        closes_at=closes_at or datetime.now(timezone.utc) + timedelta(days=10),
        probability=probability,
        volume=volume,
        raw={
            "event": {"id": "spotify-kpi", "title": "Spotify subscriber target"},
            "market": {
                "id": "spotify-signal",
                "question": "Will Spotify report more than 350 million paid subscribers?",
                "conditionId": CONDITION_ID,
                "outcomes": '["Yes", "No"]',
            },
        },
    )


def test_incentive_map_explains_benefit_information_and_false_signal_cascade() -> None:
    result = engine().match(spotify_market(probability=0.2))[0]
    incentive = result.incentive_map

    assert incentive["benefit_sides"][0]["side"] == "YES"
    assert incentive["benefit_sides"][0]["price"] == 0.2
    assert incentive["benefit_sides"][0]["gross_upside_per_share"] == 0.8
    assert incentive["benefit_sides"][1]["price"] == 0.8
    assert incentive["information_holders"]
    assert incentive["influence_actors"]
    assert any(
        stage["stage"] in {"False signal", "Contaminated KPI"}
        for stage in incentive["downstream_cascade"]
    )
    assert any(
        "Product" in stage["detail"] or "leadership" in stage["detail"].lower()
        for stage in incentive["downstream_cascade"]
    )
    assert incentive["benefit_sides"][0]["gross_profit_per_dollar"] == 4.0
    assert incentive["evidence_ladder"][-1]["level"].startswith("5")
    assert "Profit alone is not proof" in incentive["evidence_ladder"][-1]["detail"]
    assert "does not identify an insider" in incentive["caveat"]


def test_source_traceability_is_different_for_polymarket_and_kalshi() -> None:
    polymarket_result = engine().match(spotify_market())[0]
    assert polymarket_result.incentive_map["public_traceability"]["level"] == "wallet_level"
    assert polymarket_result.incentive_map["public_traceability"]["holder_snapshot_supported"] is True

    kalshi_market = spotify_market()
    kalshi_market.source = "kalshi"
    kalshi_market.external_id = "KXSPOTIFY-TEST"
    kalshi_result = engine().match(kalshi_market)[0]
    assert kalshi_result.incentive_map["public_traceability"]["level"] == "aggregate_only"
    assert kalshi_result.incentive_map["public_traceability"]["holder_snapshot_supported"] is False


def test_polymarket_public_exposure_parses_positions_pnl_holders_and_trades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/market-positions":
            return httpx.Response(
                200,
                json=[
                    {
                        "token": "yes-token",
                        "positions": [
                            {
                                "proxyWallet": "0x1111111111111111111111111111111111111111",
                                "name": "PublicResearcher",
                                "verified": True,
                                "conditionId": CONDITION_ID,
                                "avgPrice": 0.18,
                                "size": 1000,
                                "currPrice": 1,
                                "currentValue": 1000,
                                "realizedPnl": 75,
                                "totalPnl": 820,
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
                                "proxyWallet": "0x1111111111111111111111111111111111111111",
                                "name": "PublicResearcher",
                                "displayUsernamePublic": True,
                                "amount": 1000,
                                "outcomeIndex": 0,
                            }
                        ],
                    }
                ],
            )
        if request.url.path == "/oi":
            return httpx.Response(200, json=[{"market": CONDITION_ID, "value": 1500}])
        if request.url.path == "/trades":
            return httpx.Response(
                200,
                json=[
                    {
                        "proxyWallet": "0x1111111111111111111111111111111111111111",
                        "side": "BUY",
                        "conditionId": CONDITION_ID,
                        "size": 20,
                        "price": 0.18,
                        "timestamp": 1_700_000_000,
                        "outcome": "Yes",
                        "outcomeIndex": 0,
                        "transactionHash": "0xtrade",
                    }
                ],
            )
        return httpx.Response(404, json={"error": "not found"})

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_public_exposure(
                spotify_market(),
                client=client,
                polymarket_data_api_url="https://data-api.polymarket.test",
                holder_limit=5,
                trade_limit=10,
            )

    exposure = asyncio.run(run())
    position = exposure["position_groups"][0]["positions"][0]
    assert exposure["visibility"] == "wallet_level"
    assert exposure["open_interest"] == 1500
    assert position["display_name"] == "PublicResearcher"
    assert position["average_price"] == 0.18
    assert position["total_pnl"] == 820
    assert exposure["holder_groups"][0]["holders"][0]["amount"] == 1000
    assert exposure["recent_trades"][0]["price"] == 0.18


def test_kalshi_public_exposure_fails_over_and_remains_aggregate_only() -> None:
    market = spotify_market()
    market.source = "kalshi"
    market.external_id = "KXSPOTIFY-TEST"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary.kalshi.test":
            return httpx.Response(403, json={"error": "forbidden"})
        if request.url.host == "fallback.kalshi.test":
            return httpx.Response(
                200,
                json={
                    "trades": [
                        {
                            "trade_id": "trade-1",
                            "ticker": market.external_id,
                            "count_fp": "10.00",
                            "yes_price_dollars": "0.5600",
                            "no_price_dollars": "0.4400",
                            "created_time": "2026-08-14T12:00:00Z",
                        }
                    ],
                    "cursor": "",
                },
            )
        return httpx.Response(404)

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_public_exposure(
                market,
                client=client,
                polymarket_data_api_url="https://data-api.polymarket.test",
                kalshi_base_url="https://primary.kalshi.test/trade-api/v2",
                kalshi_fallback_base_url="https://fallback.kalshi.test/trade-api/v2",
            )

    exposure = asyncio.run(run())
    assert exposure["visibility"] == "aggregate_only"
    assert exposure["recent_trades"][0]["display_name"] == "Participant not public"
    assert "fallback.kalshi.test" in exposure["source_endpoint"]


def test_market_snapshots_and_field_note_render(tmp_path: Path, monkeypatch) -> None:
    import raascal_watch.app as app_module

    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    first = spotify_market(probability=0.2, volume=10_000)
    second = spotify_market(probability=0.45, volume=35_000)

    asyncio.run(scanner.scan_records("polymarket", [first]))
    asyncio.run(scanner.scan_records("polymarket", [second]))

    contract = database.list_contract_groups(view="active")["contracts"][0]
    assert contract["movement"]["snapshot_count"] == 2
    assert contract["movement"]["deltas"]["probability"] == 0.25
    assert contract["movement"]["deltas"]["volume"] == 25_000

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "scanner", scanner)
    with TestClient(app_module.app) as client:
        dashboard = client.get("/")
        field_note = client.get(f"/field-note/{contract['market_id']}")

    assert dashboard.status_code == 200
    assert "Incentive map" in dashboard.text
    assert "Open Field Note" in dashboard.text
    assert field_note.status_code == 200
    assert "Who benefits?" in field_note.text
    assert "How could the market create a false business signal?" in field_note.text
    assert "PUBLIC MARKET SIGNAL" in field_note.text


def test_archive_exposes_post_close_visibility_without_reopening_review() -> None:
    template = (ROOT / "raascal_watch" / "templates" / "index.html").read_text()
    assert "Post-close public visibility" in template
    assert "Who publicly benefited after settlement?" in template
    assert "archived contracts are not current alerts" in template
