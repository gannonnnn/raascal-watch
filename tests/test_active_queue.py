from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from raascal_watch.db import Database
from raascal_watch.market_view import clean_display_title, is_market_active
from raascal_watch.models import MarketRecord
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]


def settings_for(tmp_path: Path):
    return replace(
        get_settings(),
        db_path=tmp_path / "queue.db",
        watchlist_path=ROOT / "config" / "watchlist.yaml",
        run_scan_on_startup=False,
        slack_webhook_url=None,
        generic_webhook_url=None,
        smtp_host=None,
        smtp_from=None,
        smtp_to=(),
    )


def spotify_market(
    external_id: str,
    *,
    closes_at: datetime | None,
    volume: float = 10_000,
    title: str | None = None,
    raw: dict | None = None,
) -> MarketRecord:
    return MarketRecord(
        source="polymarket",
        external_id=external_id,
        title=title or f"Will Spotify reach a subscriber target? — Will Spotify reach {external_id}?",
        description="Resolves using Spotify reporting.",
        status="open",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        closes_at=closes_at,
        probability=0.5,
        volume=volume,
        raw=raw or {},
    )


def test_active_queue_hides_expired_contracts_and_archive_retains_them(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    now = datetime.now(timezone.utc)

    asyncio.run(
        scanner.scan_records(
            "polymarket",
            [
                spotify_market("active", closes_at=now + timedelta(days=4)),
                spotify_market("expired", closes_at=now - timedelta(days=1)),
            ],
        )
    )

    assert [row["external_id"] for row in database.list_matches()] == ["active"]
    assert [row["external_id"] for row in database.list_matches(view="archive")] == [
        "expired"
    ]

    active_stats = database.dashboard_stats(view="active")
    archive_stats = database.dashboard_stats(view="archive")
    assert active_stats["matches"] == 1
    assert active_stats["archive_matches"] == 1
    assert archive_stats["matches"] == 1
    assert archive_stats["active_matches"] == 1

    active_contract = database.list_contract_groups(view="active")["contracts"][0]
    archived_contract = database.list_contract_groups(view="archive")["contracts"][0]
    assert active_contract["reviewable"] is True
    assert archived_contract["reviewable"] is False
    assert archived_contract["display_state"] == "archived"
    assert database.acknowledge_market(archived_contract["market_id"], now) == 0
    assert database.acknowledge_market(active_contract["market_id"], now) >= 1


def test_contract_card_combines_multi_organization_matches(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    market = MarketRecord(
        source="polymarket",
        external_id="mrbeast-youtube",
        title="MrBeast YouTube views — Will MrBeast's next YouTube video reach 100 million views?",
        description="Resolves from the public YouTube view counter.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=5),
        volume=250_000,
        raw={
            "event": {"id": "creator-event", "title": "MrBeast YouTube views"},
            "market": {"question": "Will MrBeast's next YouTube video reach 100 million views?"},
        },
    )

    asyncio.run(scanner.scan_records("polymarket", [market]))
    result = database.list_contract_groups(view="active")

    assert result["total"] == 1
    contract = result["contracts"][0]
    assert set(contract["organizations"]) == {"YouTube", "MrBeast / Beast Industries"}
    assert len(contract["reviews"]) == 2
    assert contract["title"] == "Will MrBeast's next YouTube video reach 100 million views?"


def test_related_thresholds_are_grouped_under_one_event(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    close = datetime.now(timezone.utc) + timedelta(days=8)
    event = {"id": "spotify-thresholds", "title": "Spotify subscriber targets"}

    first = spotify_market(
        "threshold-1",
        closes_at=close,
        title="Spotify subscriber targets — Will Spotify report above 325 million subscribers?",
        raw={
            "event": event,
            "market": {"question": "Will Spotify report above 325 million subscribers?"},
        },
    )
    second = spotify_market(
        "threshold-2",
        closes_at=close + timedelta(days=1),
        title="Spotify subscriber targets — Will Spotify report above 330 million subscribers?",
        raw={
            "event": event,
            "market": {"question": "Will Spotify report above 330 million subscribers?"},
        },
    )

    asyncio.run(scanner.scan_records("polymarket", [first, second]))
    result = database.list_contract_groups(view="active")

    assert result["total"] == 2
    assert len(result["groups"]) == 1
    assert result["groups"][0]["count"] == 2
    assert result["groups"][0]["title"] == "Spotify subscriber targets"
    assert {item["title"] for item in result["groups"][0]["contracts"]} == {
        "Will Spotify report above 325 million subscribers?",
        "Will Spotify report above 330 million subscribers?",
    }


def test_contract_filters_and_sorts_work_without_an_apply_step(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    now = datetime.now(timezone.utc)
    low_volume_soon = spotify_market(
        "soon", closes_at=now + timedelta(days=1), volume=1_000
    )
    high_volume_later = spotify_market(
        "later", closes_at=now + timedelta(days=10), volume=900_000
    )

    asyncio.run(scanner.scan_records("polymarket", [low_volume_soon, high_volume_later]))

    by_close = database.list_contract_groups(sort="closing")["contracts"]
    by_volume = database.list_contract_groups(sort="volume")["contracts"]
    filtered = database.list_contract_groups(organization="Spotify")["contracts"]

    assert [item["external_id"] for item in by_close] == ["soon", "later"]
    assert [item["external_id"] for item in by_volume] == ["later", "soon"]
    assert len(filtered) == 2


def test_market_lifecycle_and_title_cleanup_helpers() -> None:
    now = datetime.now(timezone.utc)
    assert is_market_active("open", now + timedelta(minutes=1), now=now)
    assert not is_market_active("open", now - timedelta(minutes=1), now=now)
    assert not is_market_active("closed", now + timedelta(days=2), now=now)
    assert is_market_active("unknown", None, now=now)

    raw = {
        "market": {"question": "Total Internet Blackout in Iran by July 31, 2026?"}
    }
    assert clean_display_title(
        "polymarket",
        "Total Internet Blackout in Iran by…? — Total Internet Blackout in Iran by July 31, 2026?",
        raw,
    ) == "Total Internet Blackout in Iran by July 31, 2026?"


def test_template_uses_auto_submit_and_separate_archive_view() -> None:
    template = (ROOT / "raascal_watch" / "templates" / "index.html").read_text()
    script = (ROOT / "raascal_watch" / "static" / "app.js").read_text()

    assert "data-auto-submit-form" in template
    assert "data-auto-submit" in template
    assert '<optgroup label="Organizations">' in template
    assert '<optgroup label="Monitored themes">' in template
    assert "Filter results</button>" not in template
    assert "Active review queue" in template
    assert "Historical records are available for research and backtesting only" in template
    assert "/api/contracts/${marketId}/acknowledge" in script


def test_dashboard_routes_keep_expired_contracts_out_of_review(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    import raascal_watch.app as app_module

    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    now = datetime.now(timezone.utc)
    asyncio.run(
        scanner.scan_records(
            "polymarket",
            [
                spotify_market("web-active", closes_at=now + timedelta(days=2)),
                spotify_market("web-expired", closes_at=now - timedelta(days=2)),
            ],
        )
    )

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "scanner", scanner)

    with TestClient(app_module.app) as client:
        active = client.get("/")
        archive = client.get("/?view=archive")

    assert active.status_code == 200
    assert "web-active" in active.text
    assert "web-expired" not in active.text
    assert "Review guidance and record an assessment" in active.text
    assert archive.status_code == 200
    assert "web-expired" in archive.text
    assert "Review guidance and record an assessment" not in archive.text
    assert "Mark reviewed" not in archive.text
