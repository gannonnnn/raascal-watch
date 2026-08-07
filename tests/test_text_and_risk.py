from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from raascal_watch.models import MarketRecord
from raascal_watch.risk import RiskEngine
from raascal_watch.text import contains_phrase
from raascal_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]


def test_phrase_matching_respects_word_boundaries() -> None:
    assert contains_phrase("Spotify reports subscriber growth", "Spotify")
    assert contains_phrase("Spotify's Global Top 50", "spotify")
    assert not contains_phrase("A spotified playlist", "spotify")
    assert not contains_phrase("Examples are useful", "ample")


def test_risk_engine_matches_company_and_explains_score() -> None:
    watchlist = load_watchlist(ROOT / "config" / "watchlist.yaml")
    engine = RiskEngine(watchlist)
    market = MarketRecord(
        source="test",
        external_id="1",
        title="Will an artist reach number one on Spotify after 5 million streams?",
        description="Resolves from Spotify's chart ranking.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
        volume=150_000,
        liquidity=20_000,
    )

    results = engine.match(market)

    assert len(results) == 1
    result = results[0]
    assert result.organization == "Spotify"
    assert result.risk_score >= 75
    assert result.severity == "critical"
    assert "popularity_and_ranking" in result.categories
    assert "engagement_manipulation" in result.categories
    assert any("volume" in reason.lower() for reason in result.reasons)


def test_unrelated_market_does_not_match() -> None:
    watchlist = load_watchlist(ROOT / "config" / "watchlist.yaml")
    engine = RiskEngine(watchlist)
    market = MarketRecord(
        source="test",
        external_id="2",
        title="Will the Federal Reserve cut rates?",
        volume=10_000_000,
    )
    assert engine.match(market) == []
