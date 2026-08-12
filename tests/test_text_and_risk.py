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


def test_flightaware_settlement_source_matches_data_dependency() -> None:
    market = MarketRecord(
        source="test",
        external_id="flightaware-1",
        title="US flight cancellations for the week ending Friday",
        description=(
            "Outcome verified from FlightAware. The relevant value is the total "
            "number of cancelled flights shown by FlightAware."
        ),
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
        volume=45_000,
    )

    results = engine().match(market)

    assert [result.organization for result in results] == ["FlightAware"]
    result = results[0]
    assert "oracle_and_data_dependency" in result.categories
    assert "availability_and_incident" in result.categories
    assert "Data Licensing" in result.stakeholders
    assert result.severity in {"high", "critical"}


def test_openai_release_market_matches_direct_control_profile() -> None:
    market = MarketRecord(
        source="test",
        external_id="openai-release-1",
        title="When will OpenAI release GPT-6?",
        description="Resolves based on an official OpenAI announcement of the model release date.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=14),
        volume=1_200_000,
        liquidity=100_000,
    )

    results = engine().match(market)

    assert [result.organization for result in results] == ["OpenAI / ChatGPT"]
    result = results[0]
    assert "direct_control_and_advance_knowledge" in result.categories
    assert "platform_action" in result.categories
    assert "Insider Risk" in result.stakeholders
    assert result.severity == "critical"


def test_chatgpt_outage_market_matches_availability_profile() -> None:
    market = MarketRecord(
        source="test",
        external_id="chatgpt-outage-1",
        title="# of ChatGPT outage days in August 2026?",
        description="Resolves using incidents recorded on the OpenAI status page.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=20),
        volume=40_000,
    )

    results = engine().match(market)

    assert [result.organization for result in results] == ["OpenAI / ChatGPT"]
    result = results[0]
    assert "availability_and_incident" in result.categories
    assert "oracle_and_data_dependency" in result.categories
    assert "Site Reliability Engineering" in result.stakeholders


def test_openai_benchmark_market_matches_evaluation_integrity() -> None:
    market = MarketRecord(
        source="test",
        external_id="openai-benchmark-1",
        title="Which company has the best AI model at the end of August? — OpenAI",
        description="Resolves using the public LMArena leaderboard and arena score.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=18),
        volume=400_000,
    )

    results = engine().match(market)

    assert [result.organization for result in results] == ["OpenAI / ChatGPT"]
    result = results[0]
    assert "benchmark_and_evaluation_integrity" in result.categories
    assert "AI Evaluation" in result.stakeholders


def test_generic_open_ai_phrase_does_not_match_openai_company() -> None:
    market = MarketRecord(
        source="test",
        external_id="open-ai-generic",
        title="Will any company publish an open AI model this month?",
        volume=100_000,
    )
    assert engine().match(market) == []


def test_unrelated_sora_reference_does_not_match_openai_company() -> None:
    market = MarketRecord(
        source="test",
        external_id="sora-generic",
        title="Will a character named Sora appear in the next game trailer?",
        volume=80_000,
    )
    assert engine().match(market) == []


def test_flightaware_review_guidance_is_contract_specific() -> None:
    market = MarketRecord(
        source="kalshi",
        external_id="flightaware-guidance",
        title="How many US flights will be cancelled this week?",
        description=(
            "Outcome verified from FlightAware. Settlement uses the total number "
            "of cancelled flights shown by FlightAware."
        ),
        closes_at=datetime.now(timezone.utc) + timedelta(days=4),
        probability=0.37,
        volume=87_500,
        open_interest=21_000,
        url="https://example.test/flight-market",
    )

    result = engine().match(market)[0]

    assert result.roles == ["Resolution-data source / oracle"]
    assert any("primary resolution source" in question for question in result.review_questions)
    assert any("How many US flights" in action for action in result.actions)
    assert any("data-license" in action for action in result.actions)
    assert any("cumulative volume" in action.lower() for action in result.actions)


def test_youtube_creator_market_assigns_platform_role_not_creator_control() -> None:
    market = MarketRecord(
        source="polymarket",
        external_id="youtube-guidance",
        title="Will MrBeast's next video reach 100 million views in its first week?",
        description="Resolves from the public YouTube view count seven days after upload.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=8),
        probability=0.42,
        volume=210_000,
    )

    results = engine().match(market)
    youtube = next(result for result in results if result.organization == "YouTube")
    creator = next(
        result for result in results if result.organization == "MrBeast / Beast Industries"
    )

    assert "Platform / metric owner" in youtube.roles
    assert "Direct control / advance knowledge" not in youtube.roles
    assert "Direct control / advance knowledge" in creator.roles
    assert any("canonical internal measure" in action for action in youtube.actions)
    assert any("pre-public access" in action for action in creator.actions)


def test_openai_release_guidance_names_advance_access_path() -> None:
    market = MarketRecord(
        source="kalshi",
        external_id="openai-guidance",
        title="When will OpenAI release GPT-6?",
        description="Resolves from an official OpenAI announcement.",
        closes_at=datetime.now(timezone.utc) + timedelta(days=25),
        probability=0.58,
        volume=1_500_000,
    )

    result = engine().match(market)[0]

    assert "Direct control / advance knowledge" in result.roles
    assert any("Who can directly control" in question for question in result.review_questions)
    assert any("pre-public access" in action for action in result.actions)
    assert any("GPT-6" in action for action in result.actions)
