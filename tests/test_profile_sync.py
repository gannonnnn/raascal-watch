from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from raascal_watch.db import Database
from raascal_watch.models import MarketRecord
from raascal_watch.profile_sync import merge_watchlist, sync_profiles
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings
from raascal_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "config" / "watchlist.defaults.yaml"


def _legacy_watchlist(path: Path) -> None:
    payload = {
        "version": 2,
        "organizations": [
            {
                "name": "Spotify",
                "enabled": True,
                "aliases": ["Spotify", "My custom Spotify alias"],
                "products": [],
                "executives": [],
                "metrics": ["subscribers"],
                "stakeholders": ["Risk"],
                "playbook": ["Keep this custom step."],
            },
            {
                "name": "Custom Company",
                "enabled": True,
                "aliases": ["CustomCo"],
                "products": [],
                "executives": [],
                "metrics": ["custom metric"],
                "stakeholders": ["Custom Risk"],
                "playbook": ["Preserve custom profile."],
            },
        ],
        "risk_categories": {},
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _settings(tmp_path: Path, watchlist_path: Path):
    return replace(
        get_settings(),
        db_path=tmp_path / "sync.db",
        watchlist_path=watchlist_path,
        run_scan_on_startup=False,
        slack_webhook_url=None,
        generic_webhook_url=None,
        smtp_host=None,
        smtp_from=None,
        smtp_to=(),
    )


def test_watchlist_merge_adds_missing_profiles_and_preserves_custom_values(
    tmp_path: Path,
) -> None:
    current = tmp_path / "watchlist.yaml"
    _legacy_watchlist(current)

    summary = merge_watchlist(current, DEFAULTS)
    watchlist = load_watchlist(current)
    names = [item.name for item in watchlist.organizations]

    assert summary.changed is True
    assert "FlightAware" in summary.added_organizations
    assert "OpenAI / ChatGPT" in summary.added_organizations
    assert "Earnings-call mention markets" in summary.added_organizations
    assert "FlightAware" in names
    assert "OpenAI / ChatGPT" in names
    assert "Earnings-call mention markets" in names
    assert "Custom Company" in names

    spotify = next(item for item in watchlist.organizations if item.name == "Spotify")
    assert "My custom Spotify alias" in spotify.aliases
    assert "Spotify Premium" in spotify.products
    assert "Keep this custom step." in spotify.playbook
    assert summary.backup_path is not None and summary.backup_path.exists()


def test_sync_profiles_backfills_flightaware_from_existing_market_library(
    tmp_path: Path,
) -> None:
    current = tmp_path / "watchlist.yaml"
    _legacy_watchlist(current)
    settings = _settings(tmp_path, current)
    database = Database(settings.db_path)
    database.initialize()

    market = MarketRecord(
        source="kalshi",
        external_id="flight-cancellations-aug14",
        title="US flight cancellations for the week ending August 14",
        description=(
            "Outcome verified from FlightAware. The relevant value is the total "
            "number of cancelled flights shown by FlightAware."
        ),
        status="active",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        probability=0.45,
        volume=12_500,
        raw={"rules_primary": "Outcome verified from FlightAware."},
    )
    database.upsert_market(market, datetime.now(timezone.utc))
    assert database.list_matches(organization="FlightAware") == []

    summary = sync_profiles(
        database,
        current,
        DEFAULTS,
        force_rebuild=False,
    )

    assert summary.rebuild is not None
    assert summary.rebuild.active_matches_added >= 1
    rows = database.list_matches(organization="FlightAware", view="active")
    assert len(rows) == 1
    assert rows[0]["external_id"] == "flight-cancellations-aug14"
    assert rows[0]["alert_state"] == "historical"

    # A second unchanged launch should not repeat the full re-index.
    again = sync_profiles(database, current, DEFAULTS, force_rebuild=False)
    assert again.rebuild is None


def test_dashboard_filter_lists_every_enabled_profile_even_with_zero_matches(
    tmp_path: Path, monkeypatch
) -> None:
    import raascal_watch.app as app_module

    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_path.write_text(DEFAULTS.read_text(encoding="utf-8"), encoding="utf-8")
    settings = _settings(tmp_path, watchlist_path)
    database = Database(settings.db_path)
    database.initialize()
    scanner = Scanner(settings, database, collectors=[])

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "scanner", scanner)

    with TestClient(app_module.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'value="FlightAware"' in response.text
    assert "FlightAware (0 active)" in response.text
    assert 'value="OpenAI / ChatGPT"' in response.text
    assert "OpenAI / ChatGPT (0 active)" in response.text
    assert 'value="Earnings-call mention markets"' in response.text
    assert "Earnings-call mention markets — theme (0 active)" in response.text


def test_sync_profiles_backfills_known_flight_cancellation_families_without_name(
    tmp_path: Path,
) -> None:
    current = tmp_path / "watchlist.yaml"
    _legacy_watchlist(current)
    settings = _settings(tmp_path, current)
    database = Database(settings.db_path)
    database.initialize()

    market = MarketRecord(
        source="kalshi",
        external_id="KXFLYCANCJFK-26AUG15-T50",
        title="Will at least 50% of scheduled passenger flights at JFK be cancelled tomorrow?",
        description="Outcome verified from Primary Source Agency.",
        status="active",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        probability=0.35,
        volume=18_000,
        raw={
            "event_ticker": "KXFLYCANCJFK-26AUG15",
            "series_ticker": "KXFLYCANCJFK",
            "rules_primary": "Outcome verified from Primary Source Agency.",
        },
    )
    database.upsert_market(market, datetime.now(timezone.utc))

    summary = sync_profiles(database, current, DEFAULTS, force_rebuild=False)

    assert summary.rebuild is not None
    flightaware = database.list_matches(organization="FlightAware", view="active")
    theme = database.list_matches(
        organization="Flight cancellation markets", view="active"
    )
    assert len(flightaware) == 1
    assert flightaware[0]["match_basis"] == "verified_dependency"
    assert len(theme) == 1
    assert theme[0]["match_basis"] == "theme"

    contracts = database.list_contract_groups(view="active")["contracts"]
    assert len(contracts) == 1
    assert set(contracts[0]["organizations"]) == {
        "FlightAware",
        "Flight cancellation markets",
    }


def test_generic_cancellation_market_backfills_theme_without_flightaware(
    tmp_path: Path,
) -> None:
    current = tmp_path / "watchlist.yaml"
    _legacy_watchlist(current)
    settings = _settings(tmp_path, current)
    database = Database(settings.db_path)
    database.initialize()

    market = MarketRecord(
        source="polymarket",
        external_id="europe-flight-cancellations",
        title="Will more than 2,000 flights be canceled in Europe this weekend?",
        description="Resolves using a public aviation authority report.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    database.upsert_market(market, datetime.now(timezone.utc))

    sync_profiles(database, current, DEFAULTS, force_rebuild=False)

    assert database.list_matches(organization="FlightAware", view="active") == []
    theme = database.list_matches(
        organization="Flight cancellation markets", view="active"
    )
    assert len(theme) == 1
    assert theme[0]["match_basis"] == "theme"


def test_dashboard_filter_lists_flight_cancellation_theme(tmp_path: Path, monkeypatch) -> None:
    import raascal_watch.app as app_module

    watchlist_path = tmp_path / "watchlist.yaml"
    watchlist_path.write_text(DEFAULTS.read_text(encoding="utf-8"), encoding="utf-8")
    settings = _settings(tmp_path, watchlist_path)
    database = Database(settings.db_path)
    database.initialize()
    scanner = Scanner(settings, database, collectors=[])

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "scanner", scanner)

    with TestClient(app_module.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'value="Flight cancellation markets"' in response.text
    assert "Flight cancellation markets — theme (0 active)" in response.text


def test_watchlist_merge_updates_existing_flightaware_with_dependency_rules_and_theme(
    tmp_path: Path,
) -> None:
    current = tmp_path / "watchlist.yaml"
    payload = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
    payload["version"] = 4
    payload["organizations"] = [
        item
        for item in payload["organizations"]
        if item["name"] != "Flight cancellation markets"
    ]
    flightaware = next(
        item for item in payload["organizations"] if item["name"] == "FlightAware"
    )
    flightaware.pop("dependency_rules", None)
    current.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    summary = merge_watchlist(current, DEFAULTS)
    watchlist = load_watchlist(current)

    assert summary.changed is True
    assert "FlightAware" in summary.updated_organizations
    assert "Flight cancellation markets" in summary.added_organizations
    updated = next(item for item in watchlist.organizations if item.name == "FlightAware")
    assert {rule.name for rule in updated.dependency_rules} == {
        "Kalshi airport cancellation product family",
        "Kalshi weekly U.S. flight cancellation family",
        "FlightAware settlement-source metadata",
    }
    theme = next(
        item for item in watchlist.organizations if item.name == "Flight cancellation markets"
    )
    assert theme.is_theme is True
    assert {rule.name for rule in theme.dependency_rules} == {
        "Kalshi airport cancellation product family",
        "Kalshi weekly U.S. flight cancellation family",
    }


def test_profile_sync_backfills_flightaware_from_stored_series_metadata(
    tmp_path: Path,
) -> None:
    current = tmp_path / "watchlist.yaml"
    _legacy_watchlist(current)
    settings = _settings(tmp_path, current)
    database = Database(settings.db_path)
    database.initialize()

    market = MarketRecord(
        source="kalshi",
        external_id="KXOTHERFLIGHT-26AUG15-T10",
        title="Will more than 10% of scheduled flights be cancelled?",
        description="Outcome verified from Primary Source Agency.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        raw={
            "series_ticker": "KXOTHERFLIGHT",
            "_raascal_series": {
                "ticker": "KXOTHERFLIGHT",
                "settlement_sources": [
                    {
                        "name": "Primary Source Agency",
                        "url": "https://www.flightaware.com/",
                    }
                ],
            },
        },
    )
    database.upsert_market(market, datetime.now(timezone.utc))

    sync_profiles(database, current, DEFAULTS, force_rebuild=False)

    rows = database.list_matches(organization="FlightAware", view="active")
    assert len(rows) == 1
    assert rows[0]["match_basis"] == "verified_dependency"



def test_sync_profiles_backfills_earnings_call_theme_from_existing_market_library(
    tmp_path: Path,
) -> None:
    current = tmp_path / "watchlist.yaml"
    _legacy_watchlist(current)
    settings = _settings(tmp_path, current)
    database = Database(settings.db_path)
    database.initialize()

    market = MarketRecord(
        source="polymarket",
        external_id="dell-agentic-existing",
        title=(
            "What will Dell say during their next earnings call? — "
            'Will Dell say "Agentic" during their next earnings call?'
        ),
        description=(
            "Resolves using the official Dell earnings-call audio and final transcript."
        ),
        status="open",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        closes_at=datetime.now(timezone.utc) + timedelta(days=2),
        probability=0.88,
        volume=9_175,
        raw={
            "event": {
                "id": "dell-call-existing",
                "title": "What will Dell say during their next earnings call?",
            },
            "market": {
                "id": "dell-agentic-existing",
                "question": 'Will Dell say "Agentic" during their next earnings call?',
                "groupItemTitle": "Agentic",
            },
        },
    )
    database.upsert_market(market, datetime.now(timezone.utc))

    summary = sync_profiles(database, current, DEFAULTS, force_rebuild=False)

    assert summary.rebuild is not None
    assert summary.rebuild.active_matches_added >= 1
    rows = database.list_matches(
        organization="Earnings-call mention markets", view="active"
    )
    assert len(rows) == 1
    assert rows[0]["external_id"] == "dell-agentic-existing"
    assert rows[0]["match_basis"] == "theme"
    assert rows[0]["alert_state"] == "historical"
    assert "Company: Dell" in rows[0]["dynamic_subjects"]
    assert "Controlled outcome: Agentic" in rows[0]["dynamic_subjects"]
