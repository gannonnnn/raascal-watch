from __future__ import annotations

from raascal_watch.collectors import KalshiCollector, PolymarketCollector


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
