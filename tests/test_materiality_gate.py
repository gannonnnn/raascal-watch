from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from raascal_watch.db import Database
from raascal_watch.materiality import apply_market_movement
from raascal_watch.models import MarketRecord
from raascal_watch.risk import RiskEngine
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings
from raascal_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]


def engine() -> RiskEngine:
    return RiskEngine(load_watchlist(ROOT / "config" / "watchlist.yaml"))


def settings_for(tmp_path: Path):
    return replace(
        get_settings(),
        db_path=tmp_path / "materiality.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
        slack_webhook_url=None,
        generic_webhook_url=None,
        smtp_host=None,
        smtp_from=None,
        smtp_to=(),
    )


def test_distant_low_activity_match_is_observed_not_human_review() -> None:
    market = MarketRecord(
        source="polymarket",
        external_id="spotify-distant",
        title="Will Spotify mention a product in 2028?",
        description="Resolves from a public Spotify post.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=400),
        probability=0.5,
        volume=100,
    )
    result = engine().match(market)[0]

    assert result.organization == "Spotify"
    assert result.materiality["gate"] == "observed"
    assert result.materiality["method_note"].startswith("The gate requires")
    assert result.risk_breakdown["score"] == result.risk_score


def test_app_store_market_has_dynamic_subjects_and_review_gate() -> None:
    market = MarketRecord(
        source="kalshi",
        external_id="KXTOPAPP-26AUG20-CHATGPT",
        title="Top US iPhone app tomorrow? — ChatGPT",
        description=(
            "Resolves from Apple App Store Top Charts / Top Free Apps at the observation time."
        ),
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        probability=0.42,
        volume=15_000,
        open_interest=4_000,
        raw={
            "series_ticker": "KXTOPAPP",
            "event_ticker": "KXTOPAPP-26AUG20",
            "yes_sub_title": "ChatGPT",
        },
    )
    results = {item.organization: item for item in engine().match(market)}

    assert {"Apple App Store", "App Store ranking markets"}.issubset(results)
    for name in ("Apple App Store", "App Store ranking markets"):
        result = results[name]
        assert result.dynamic_subjects == ["ChatGPT"]
        assert result.materiality["gate"] in {"review", "escalate"}
        assert result.materiality["dimensions"]["influenceability"]["score"] >= 78
        assert "Engineering" in " ".join(
            result.materiality["dimensions"]["downstream_impact"]["rationales"]
        )


def test_material_market_movement_promotes_review_to_escalate() -> None:
    market = MarketRecord(
        source="polymarket",
        external_id="spotify-movement",
        title="Will Spotify streams reach number one this week?",
        description="Resolves from Spotify Charts.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        probability=0.2,
        volume=150_000,
    )
    result = engine().match(market)[0]
    moved = apply_market_movement(
        result.materiality,
        movement={
            "snapshot_count": 2,
            "day_deltas": {
                "probability": 0.22,
                "volume": 125_000,
                "open_interest": 20_000,
            },
            "deltas": {},
            "rules_changed": False,
            "close_changed": False,
            "status_changed": False,
        },
        source=market.source,
        categories=result.categories,
        match_basis=result.match_basis,
        actions=result.actions,
        stakeholders=result.stakeholders,
        closes_at=market.closes_at,
    )

    assert moved["gate"] == "escalate"
    assert moved["dimensions"]["market_movement"]["score"] >= 80
    assert any("probability moved" in item.lower() for item in moved["what_changed"])


def test_kalshi_economic_context_uses_contract_counts_not_dollars() -> None:
    market = MarketRecord(
        source="kalshi",
        external_id="KXSPOTIFY-COUNT",
        title="Will Spotify report more than 400 million subscribers?",
        description="Resolves from Spotify reporting.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=5),
        volume=250_000,
        open_interest=50_000,
        liquidity=30_000,
    )
    result = engine().match(market)[0]
    economic = result.materiality["dimensions"]["economic_exposure"]

    assert economic["unit"] == "contracts"
    assert any("contracts" in fact for fact in economic["facts"])
    assert "not dollars" in economic["caveat"]
    assert any("contracts" in action for action in result.actions)


def test_database_materiality_views_separate_observed_from_review_today(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    now = datetime.now(timezone.utc)
    records = [
        MarketRecord(
            source="polymarket",
            external_id="observed-one",
            title="Will Spotify mention a product in 2028?",
            description="Resolves from a public Spotify post.",
            status="open",
            closes_at=now + timedelta(days=400),
            probability=0.5,
            volume=100,
        ),
        MarketRecord(
            source="polymarket",
            external_id="review-one",
            title="Will Spotify streams rank number one this week?",
            description="Resolves from Spotify Charts.",
            status="open",
            closes_at=now + timedelta(days=3),
            probability=0.45,
            volume=200_000,
        ),
    ]
    asyncio.run(scanner.scan_records("polymarket", records))

    review_today = database.list_contract_groups(materiality_gate="review_today")
    observed = database.list_contract_groups(materiality_gate="observed")
    all_active = database.list_contract_groups(materiality_gate="all")

    assert [item["external_id"] for item in review_today["contracts"]] == ["review-one"]
    assert [item["external_id"] for item in observed["contracts"]] == ["observed-one"]
    assert all_active["gate_counts"]["review_today"] == 1
    assert all_active["gate_counts"]["observed"] == 1


def test_dashboard_explains_materiality_and_app_store_profiles(tmp_path: Path, monkeypatch) -> None:
    import raascal_watch.app as app_module

    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    market = MarketRecord(
        source="kalshi",
        external_id="KXTOPAPP-WEB-CHATGPT",
        title="Top US iPhone app tomorrow? — ChatGPT",
        description="Resolves from Apple App Store Top Charts.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        probability=0.4,
        volume=20_000,
        raw={"yes_sub_title": "ChatGPT", "series_ticker": "KXTOPAPP"},
    )
    asyncio.run(scanner.scan_records("kalshi", [market]))

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "scanner", scanner)

    with TestClient(app_module.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Contracts warranting review today" in response.text
    assert "App Store ranking markets" in response.text
    assert "Apple App Store" in response.text
    assert "Dynamic apps / outcomes" in response.text
    assert "ChatGPT" in response.text
    assert "Is this more than a keyword monitor?" in response.text
    assert "Why the retrieval score is" in response.text
