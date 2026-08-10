from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from raascal_watch.models import MarketRecord
from raascal_watch.risk import RiskEngine
from raascal_watch.text import contains_phrase
from raascal_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]


def engine() -> RiskEngine:
    return RiskEngine(load_watchlist(ROOT / "config" / "watchlist.yaml"))


def test_phrase_matching_respects_word_boundaries() -> None:
    assert contains_phrase("Spotify reports subscriber growth", "Spotify")
    assert contains_phrase("Spotify's Global Top 50", "spotify")
    assert not contains_phrase("A spotified playlist", "spotify")
    assert not contains_phrase("Examples are useful", "ample")


def test_risk_engine_matches_company_and_explains_score() -> None:
    market = MarketRecord(
        source="test",
        external_id="1",
        title="Will an artist reach number one on Spotify after 5 million streams?",
        description="Resolves from Spotify's chart ranking.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
        volume=150_000,
        liquidity=20_000,
    )

    results = engine().match(market)

    assert len(results) == 1
    result = results[0]
    assert result.organization == "Spotify"
    assert result.risk_score >= 75
    assert result.severity == "critical"
    assert "popularity_and_ranking" in result.categories
    assert "engagement_manipulation" in result.categories
    assert any("volume" in reason.lower() for reason in result.reasons)


def test_cloudflare_outage_matches_availability_profile() -> None:
    market = MarketRecord(
        source="test",
        external_id="cloudflare-1",
        title="Will Cloudflare report a critical service outage this month?",
        description="Resolves from the Cloudflare status page after a network incident.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=5),
        volume=1_400_000,
        liquidity=150_000,
    )

    results = engine().match(market)

    assert [result.organization for result in results] == ["Cloudflare"]
    result = results[0]
    assert "availability_and_incident" in result.categories
    assert result.severity == "critical"
    assert "Security Operations" in result.stakeholders
    assert any("availability" in action.lower() for action in result.actions)


def test_mrbeast_youtube_market_matches_subject_and_platform() -> None:
    market = MarketRecord(
        source="test",
        external_id="creator-1",
        title="Will MrBeast's next YouTube video reach 100 million views in its first week?",
        description="Resolves using the public YouTube view count seven days after upload.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=12),
        volume=450_000,
        liquidity=60_000,
    )

    results = engine().match(market)
    organizations = {result.organization for result in results}

    assert organizations == {"YouTube", "MrBeast / Beast Industries"}
    for result in results:
        assert "engagement_manipulation" in result.categories
        assert result.severity in {"high", "critical"}
    creator = next(
        result for result in results if result.organization == "MrBeast / Beast Industries"
    )
    assert "direct_control_and_advance_knowledge" in creator.categories
    assert "Insider Risk" in creator.stakeholders


def test_generic_cloud_reference_does_not_match_cloudflare() -> None:
    market = MarketRecord(
        source="test",
        external_id="cloud-generic",
        title="Will cloud computing revenue grow this quarter?",
        volume=10_000_000,
    )
    assert engine().match(market) == []


def test_unrelated_market_does_not_match() -> None:
    market = MarketRecord(
        source="test",
        external_id="2",
        title="Will the Federal Reserve cut rates?",
        volume=10_000_000,
    )
    assert engine().match(market) == []
