from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from raascal_watch.db import Database
from raascal_watch.models import MarketRecord


def market(*, probability: float, volume: float, description: str, close_days: int = 10) -> MarketRecord:
    return MarketRecord(
        source="polymarket",
        external_id="snapshot-market",
        title="Will Spotify rank number one?",
        description=description,
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=close_days),
        probability=probability,
        volume=volume,
        open_interest=10_000,
    )


def test_snapshots_capture_market_and_rule_changes(tmp_path: Path) -> None:
    database = Database(tmp_path / "snapshots.db")
    database.initialize()
    first_at = datetime.now(timezone.utc) - timedelta(hours=25)
    market_id, created = database.upsert_market(
        market(probability=0.20, volume=10_000, description="Old settlement rules."),
        first_at,
    )
    assert created

    second_at = datetime.now(timezone.utc)
    same_id, created = database.upsert_market(
        market(probability=0.42, volume=150_000, description="Updated settlement rules."),
        second_at,
    )
    assert same_id == market_id
    assert not created

    movement = database._market_movements([market_id])[market_id]
    assert movement["snapshot_count"] == 2
    assert round(movement["day_deltas"]["probability"], 2) == 0.22
    assert movement["day_deltas"]["volume"] == 140_000
    assert movement["rules_changed"] is True
