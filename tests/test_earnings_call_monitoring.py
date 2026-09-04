from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from raascal_watch.db import Database
from raascal_watch.models import MarketRecord
from raascal_watch.risk import RiskEngine
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings
from raascal_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]


def engine() -> RiskEngine:
    return RiskEngine(load_watchlist(ROOT / "config" / "watchlist.yaml"))


def dell_market(*, volume: float = 9_175, closes_in_days: int = 2) -> MarketRecord:
    return MarketRecord(
        source="polymarket",
        external_id="dell-agentic",
        title=(
            'What will Dell say during their next earnings call? — '
            'Will Dell say "Agentic" during their next earnings call?'
        ),
        description=(
            "Resolves using the official Dell earnings-call audio and final transcript."
        ),
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=closes_in_days),
        probability=0.88,
        volume=volume,
        raw={
            "event": {
                "id": "dell-call",
                "title": "What will Dell say during their next earnings call?",
                "resolutionSource": "Official Dell earnings-call audio or transcript",
            },
            "market": {
                "id": "dell-agentic",
                "question": 'Will Dell say "Agentic" during their next earnings call?',
                "groupItemTitle": "Agentic",
                "outcomes": '["Yes", "No"]',
            },
        },
    )


def test_earnings_call_theme_extracts_company_and_controlled_outcome() -> None:
    results = engine().match(dell_market())
    assert [result.organization for result in results] == ["Earnings-call mention markets"]

    result = results[0]
    assert result.match_basis == "theme"
    assert "corporate_controlled_outcome" in result.categories
    assert "direct_control_and_advance_knowledge" in result.categories
    assert "financial_metric" not in result.categories
    assert "Company: Dell" in result.dynamic_subjects
    assert "Controlled outcome: Agentic" in result.dynamic_subjects
    assert "Corporate-controlled outcome / advance knowledge" in result.roles
    assert result.materiality["gate"] in {"review", "escalate"}
    assert result.materiality["dimensions"]["information_advantage"]["score"] >= 90
    assert result.incentive_map["headline"] == "What if the answer is already in the script?"
    assert result.incentive_map["outcome_focus"].startswith("Company-controlled")
    assert any("prediction markets" in question.lower() for question in result.review_questions)
    assert any("transcript" in action.lower() for action in result.actions)
    assert not any("airport" in action.lower() for action in result.actions)
    assert not any(
        "account farm" in actor.lower()
        for actor in result.incentive_map["influence_actors"]
    )


def test_earnings_call_theme_does_not_match_generic_earnings_forecast() -> None:
    market = MarketRecord(
        source="kalshi",
        external_id="KXDELL-EPS",
        title="Will Dell beat quarterly earnings estimates?",
        description="Resolves from reported earnings per share.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=5),
    )
    assert engine().match(market) == []


def test_kalshi_earnings_call_market_extracts_phrase_from_subtitle() -> None:
    market = MarketRecord(
        source="kalshi",
        external_id="KXEARNINGSMENTIONDELL-AGENTIC",
        title="What will Dell say during their next earnings call? — Agentic",
        description="Resolves using official call audio and transcript.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
        probability=0.75,
        volume=20_000,
        raw={
            "title": "What will Dell say during their next earnings call?",
            "yes_sub_title": "Agentic",
            "subtitle": "Agentic",
            "event_ticker": "KXEARNINGSMENTIONDELL-26Q2",
            "series_ticker": "KXEARNINGSMENTIONDELL",
        },
    )

    result = engine().match(market)[0]
    assert result.organization == "Earnings-call mention markets"
    assert result.dynamic_subjects == ["Company: Dell", "Controlled outcome: Agentic"]
    assert result.materiality["gate"] in {"review", "escalate"}


def test_theme_guidance_is_profile_specific_for_app_store() -> None:
    market = MarketRecord(
        source="kalshi",
        external_id="KXTOPAPP-CHATGPT",
        title="Top US iPhone app tomorrow? — ChatGPT",
        description="Resolves from Apple App Store Top Charts / Top Free Apps.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        probability=0.4,
        volume=20_000,
        raw={"yes_sub_title": "ChatGPT", "series_ticker": "KXTOPAPP"},
    )
    by_profile = {result.organization: result for result in engine().match(market)}
    app_theme = by_profile["App Store ranking markets"]
    assert any("acquisition source" in action.lower() for action in app_theme.actions)
    assert not any("airport" in action.lower() for action in app_theme.actions)
    assert not any("cancellation" in question.lower() for question in app_theme.review_questions)


def test_dashboard_includes_earnings_theme_and_dynamic_label(tmp_path: Path, monkeypatch) -> None:
    import raascal_watch.app as app_module

    settings = replace(
        get_settings(),
        db_path=tmp_path / "earnings.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
        slack_webhook_url=None,
        generic_webhook_url=None,
        smtp_host=None,
        smtp_from=None,
        smtp_to=(),
    )
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    asyncio.run(scanner.scan_records("polymarket", [dell_market()]))

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "scanner", scanner)

    with TestClient(app_module.app) as client:
        response = client.get("/")
        field_note = client.get("/field-note/1")

    assert response.status_code == 200
    assert "Earnings-call mention markets" in response.text
    assert "Dynamic company / controlled outcomes" in response.text
    assert "Company: Dell" in response.text
    assert "Controlled outcome: Agentic" in response.text
    assert field_note.status_code == 200
    assert "What if the answer is already in the script?" in field_note.text
