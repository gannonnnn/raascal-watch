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
