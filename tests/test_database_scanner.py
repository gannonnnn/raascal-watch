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


def test_database_migrates_incentive_and_snapshot_schema(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "legacy-v06.db"
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
            match_basis TEXT NOT NULL DEFAULT 'direct',
            roles_json TEXT NOT NULL DEFAULT '[]',
            reasons_json TEXT NOT NULL DEFAULT '[]',
            review_questions_json TEXT NOT NULL DEFAULT '[]',
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
        tables = {
            row["name"]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "incentive_map_json" in columns
    assert "market_snapshots" in tables
    assert "public_exposure_snapshots" in tables


def test_scanner_persists_incentive_map_and_market_movement(tmp_path: Path) -> None:
    settings = replace(
        get_settings(),
        db_path=tmp_path / "movement.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
    )
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    first = make_market("movement-one", "Will Spotify reach 330 million subscribers?")
    first.probability = 0.25
    first.volume = 10_000
    asyncio.run(scanner.scan_records("fake", [first]))

    second = make_market("movement-one", "Will Spotify reach 330 million subscribers?")
    second.probability = 0.4
    second.volume = 25_000
    asyncio.run(scanner.scan_records("fake", [second]))

    contract = database.list_contract_groups()["contracts"][0]
    assert contract["reviews"][0]["incentive_map"]["benefit_sides"]
    assert contract["movement"]["snapshot_count"] == 2
    assert round(contract["movement"]["deltas"]["probability"], 2) == 0.15
    assert contract["movement"]["deltas"]["volume"] == 15_000


def test_public_exposure_snapshot_round_trips_rich_position_data(tmp_path: Path) -> None:
    settings = replace(
        get_settings(),
        db_path=tmp_path / "exposure.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
    )
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    asyncio.run(
        scanner.scan_records(
            "polymarket",
            [make_market("exposure-market", "Will Spotify reach 330 million subscribers?")],
        )
    )
    market_id = database.list_contract_groups()["contracts"][0]["market_id"]
    saved = database.save_public_exposure_snapshot(
        market_id,
        {
            "source": "polymarket",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "visibility": "wallet_level",
            "visibility_label": "Public wallet-level exposure",
            "condition_id": "0x" + "d" * 64,
            "open_interest": 5_000,
            "position_groups": [
                {
                    "outcome": "Yes",
                    "positions": [
                        {
                            "wallet": "0x" + "e" * 40,
                            "display_name": "Public wallet",
                            "size": 100,
                            "average_price": 0.2,
                            "total_pnl": 50,
                        }
                    ],
                }
            ],
            "holder_groups": [],
            "recent_trades": [],
            "detail": "Public position data",
            "caveat": "Profit is not proof.",
        },
    )

    assert saved["snapshot_id"]
    loaded = database.latest_public_exposure(market_id)
    assert loaded is not None
    assert loaded["position_groups"][0]["positions"][0]["total_pnl"] == 50
    assert database.get_contract_bundle(market_id)["public_exposure"]["open_interest"] == 5_000


def test_scanner_passes_source_context_for_incremental_collectors(tmp_path: Path) -> None:
    from raascal_watch.models import CollectorContext, SourceFetchResult

    settings = replace(
        get_settings(),
        db_path=tmp_path / "context.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
        slack_webhook_url=None,
        generic_webhook_url=None,
        smtp_host=None,
        smtp_from=None,
        smtp_to=(),
    )
    database = Database(settings.db_path)
    seed_scanner = Scanner(settings, database, collectors=[])
    asyncio.run(
        seed_scanner.scan_records(
            "kalshi",
            [
                MarketRecord(
                    source="kalshi",
                    external_id="KXCONTEXT-1",
                    title="Will Spotify streams rise?",
                    closes_at=datetime.now(timezone.utc) + timedelta(days=5),
                    status="open",
                )
            ],
        )
    )

    captured: list[CollectorContext | None] = []

    class RecordingCollector:
        name = "kalshi"

        async def fetch(self, client, settings, context=None):
            captured.append(context)
            return SourceFetchResult("kalshi", [], pages=0)

    scanner = Scanner(settings, database, collectors=[RecordingCollector()])
    asyncio.run(scanner.scan())

    assert len(captured) == 1
    context = captured[0]
    assert context is not None
    assert context.source_initialized is True
    assert context.last_success_at is not None
    assert context.active_external_ids == ("KXCONTEXT-1",)
