from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from raascal_watch.db import Database
from raascal_watch.models import MarketRecord
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]


def make_market(external_id: str, title: str) -> MarketRecord:
    return MarketRecord(
        source="fake",
        external_id=external_id,
        title=title,
        description="Resolves from the Spotify chart.",
        created_at=datetime.now(timezone.utc),
        closes_at=datetime.now(timezone.utc) + timedelta(days=7),
        probability=0.5,
        volume=25_000,
        liquidity=5_000,
    )


def test_first_scan_is_baseline_then_new_contract_alerts(tmp_path: Path) -> None:
    settings = replace(
        get_settings(),
        db_path=tmp_path / "test.db",
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

    first = asyncio.run(
        scanner.scan_records(
            "fake",
            [make_market("first", "Will Spotify streams reach a new chart record?")],
        )
    )
    assert first.sources[0].notifications == 0
    assert first.sources[0].baseline_suppressed == 1
    first_rows = database.list_matches()
    assert len(first_rows) == 1
    assert first_rows[0]["alert_state"] == "baseline"

    second = asyncio.run(
        scanner.scan_records(
            "fake",
            [
                make_market("first", "Will Spotify streams reach a new chart record?"),
                make_market("second", "Will Spotify remove an artist before Friday?"),
            ],
        )
    )
    assert second.sources[0].new_markets == 1
    assert second.sources[0].notifications == 1
    rows = database.list_matches()
    states = {row["external_id"]: row["alert_state"] for row in rows}
    assert states["first"] == "baseline"
    assert states["second"] == "console_only"


def test_acknowledgement_updates_queue(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    # Reuse scanner flow to create a valid joined market/match record.
    settings = replace(
        get_settings(),
        db_path=database.path,
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
    )
    scanner = Scanner(settings, database, collectors=[])
    asyncio.run(
        scanner.scan_records(
            "fake",
            [make_market("ack", "Will Spotify streams rank number one?")],
            notify=True,
        )
    )
    match = database.list_matches()[0]
    assert database.acknowledge_match(match["match_id"], datetime.now(timezone.utc))
    updated = database.get_match(match["match_id"])
    assert updated is not None
    assert updated["alert_state"] == "acknowledged"
    assert updated["acknowledged_at"] is not None


def test_live_queries_hide_demo_and_purge_preserves_live_records(tmp_path: Path) -> None:
    settings = replace(
        get_settings(),
        db_path=tmp_path / "test.db",
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

    asyncio.run(
        scanner.scan_records(
            "demo",
            [make_market("demo-one", "Will Spotify streams rank number one?")],
        )
    )
    asyncio.run(
        scanner.scan_records(
            "kalshi",
            [make_market("live-one", "Will Spotify streams reach a new chart record?")],
        )
    )

    # Live-only is the default, but developers can still request the demo source.
    assert [row["external_id"] for row in database.list_matches()] == ["live-one"]
    assert [row["external_id"] for row in database.list_matches(source="demo")] == [
        "demo-one"
    ]
    assert database.dashboard_stats()["matches"] == 1
    assert database.dashboard_stats(include_demo=True)["matches"] == 2

    removed = database.delete_source("demo")
    assert removed["markets"] == 1
    assert removed["matches"] == 1
    assert database.list_matches(source="demo") == []
    assert [row["external_id"] for row in database.list_matches()] == ["live-one"]


def test_database_migrates_contract_review_columns(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id INTEGER NOT NULL,
            organization TEXT NOT NULL,
            matched_identity_terms_json TEXT NOT NULL DEFAULT '[]',
            matched_metric_terms_json TEXT NOT NULL DEFAULT '[]',
            categories_json TEXT NOT NULL DEFAULT '[]',
            risk_score INTEGER NOT NULL,
            severity TEXT NOT NULL,
            reasons_json TEXT NOT NULL DEFAULT '[]',
            stakeholders_json TEXT NOT NULL DEFAULT '[]',
            actions_json TEXT NOT NULL DEFAULT '[]',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            alert_state TEXT NOT NULL DEFAULT 'new',
            notified_at TEXT,
            acknowledged_at TEXT,
            UNIQUE(market_id, organization)
        )
        """
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.initialize()

    with database.connect() as migrated:
        columns = {row["name"] for row in migrated.execute("PRAGMA table_info(matches)")}
    assert "roles_json" in columns
    assert "review_questions_json" in columns


def test_scanner_persists_contract_specific_review_fields(tmp_path: Path) -> None:
    settings = replace(
        get_settings(),
        db_path=tmp_path / "review.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
    )
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])

    asyncio.run(
        scanner.scan_records(
            "kalshi",
            [make_market("review-fields", "Will Spotify report 330 million subscribers?")],
        )
    )

    row = database.list_matches()[0]
    assert row["roles"]
    assert row["review_questions"]
    assert any("Spotify" in action for action in row["actions"])


def test_existing_match_guidance_can_refresh_without_changing_seen_time(tmp_path: Path) -> None:
    settings = replace(
        get_settings(),
        db_path=tmp_path / "refresh.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
    )
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    asyncio.run(
        scanner.scan_records(
            "polymarket",
            [make_market("refresh-one", "Will Spotify reach 330 million subscribers?")],
        )
    )

    before = database.list_matches()[0]
    market_id, market, organizations = database.list_matched_markets()[0]
    assert organizations == {"Spotify"}

    from raascal_watch.risk import RiskEngine
    from raascal_watch.watchlist import load_watchlist

    result = RiskEngine(load_watchlist(settings.watchlist_path)).match(market)[0]
    assert database.update_match_analysis(market_id, result)

    after = database.list_matches()[0]
    assert after["match_last_seen_at"] == before["match_last_seen_at"]
    assert after["roles"]
    assert after["review_questions"]
