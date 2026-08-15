from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from raascal_watch.cli import command_export_feedback
from raascal_watch.db import Database
from raascal_watch.models import MarketRecord
from raascal_watch.risk import RiskEngine
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings
from raascal_watch.watchlist import load_watchlist

ROOT = Path(__file__).resolve().parents[1]


def settings_for(tmp_path: Path):
    return replace(
        get_settings(),
        db_path=tmp_path / "feedback.db",
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
    closes_at: datetime | None = None,
    volume: float = 25_000,
) -> MarketRecord:
    return MarketRecord(
        source="polymarket",
        external_id=external_id,
        title=f"Will Spotify report a new subscriber record? — {external_id}",
        description="Resolves from Spotify premium subscriber reporting.",
        status="open",
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        closes_at=closes_at or datetime.now(timezone.utc) + timedelta(days=5),
        probability=0.45,
        volume=volume,
        raw={"event": {"id": external_id, "title": external_id}},
    )


def scan_market(settings, database: Database, market: MarketRecord) -> Scanner:
    scanner = Scanner(settings, database, collectors=[])
    asyncio.run(scanner.scan_records(market.source, [market]))
    return scanner


def save_feedback(
    database: Database,
    match_id: int,
    *,
    decision: str = "actionable",
    reason_codes: list[str] | None = None,
    guidance_rating: str | None = "useful",
):
    return database.save_review_feedback(
        match_id,
        decision=decision,
        reason_codes=reason_codes or ["credible_influence_path"],
        guidance_rating=guidance_rating,
        note="Reviewer context",
        corrected_role="Reporting owner",
        suggested_owner="Operational Risk",
        at=datetime.now(timezone.utc),
    )


def test_feedback_schema_save_and_calibration_summary(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scan_market(settings, database, spotify_market("feedback-one"))
    match = database.list_matches()[0]

    before = database.feedback_summary(view="active")
    assert before["reviewed"] == 0
    assert before["unreviewed"] == 1

    updated = save_feedback(database, match["match_id"])
    assert updated is not None
    assert updated["review_decision"] == "actionable"
    assert updated["review_reason_codes"] == ["credible_influence_path"]
    assert updated["guidance_rating"] == "useful"
    assert updated["review_note"] == "Reviewer context"
    assert updated["corrected_role"] == "Reporting owner"
    assert updated["suggested_owner"] == "Operational Risk"
    assert updated["alert_state"] == "acknowledged"
    assert updated["acknowledged_at"] is not None

    after = database.feedback_summary(view="active")
    assert after["reviewed"] == 1
    assert after["unreviewed"] == 0
    assert after["decision_counts"]["actionable"] == 1
    assert after["actionable_or_monitor_rate"] == 100.0
    assert after["false_positive_rate"] == 0.0
    assert after["guidance_positive_rate"] == 100.0
    assert after["profiles"][0]["organization"] == "Spotify"


def test_feedback_updates_one_row_instead_of_creating_duplicates(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scan_market(settings, database, spotify_market("feedback-update"))
    match_id = database.list_matches()[0]["match_id"]

    save_feedback(database, match_id, decision="actionable")
    database.save_review_feedback(
        match_id,
        decision="monitor",
        reason_codes=["settlement_urgent", "settlement_urgent"],
        guidance_rating="partly_useful",
        note="Changed after review",
        corrected_role="",
        suggested_owner="Product Analytics",
        at=datetime.now(timezone.utc),
    )

    rows = database.list_review_feedback(view="all")
    assert len(rows) == 1
    assert rows[0]["decision"] == "monitor"
    assert rows[0]["reason_codes"] == ["settlement_urgent"]
    assert rows[0]["note"] == "Changed after review"


def test_archived_matches_cannot_receive_current_feedback(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scan_market(
        settings,
        database,
        spotify_market(
            "feedback-expired",
            closes_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ),
    )
    archived = database.list_matches(view="archive")[0]

    result = save_feedback(database, archived["match_id"])
    assert result is None
    assert database.list_review_feedback(view="all") == []


def test_decision_filters_separate_reviewed_and_unreviewed_matches(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    asyncio.run(
        scanner.scan_records(
            "polymarket",
            [spotify_market("reviewed"), spotify_market("unreviewed")],
        )
    )
    matches = {row["external_id"]: row for row in database.list_matches()}
    save_feedback(database, matches["reviewed"]["match_id"], decision="informational")

    reviewed = database.list_matches(review_decision="informational")
    unreviewed = database.list_matches(review_decision="unreviewed")
    contracts = database.list_contract_groups(review_decision="informational")

    assert [row["external_id"] for row in reviewed] == ["reviewed"]
    assert [row["external_id"] for row in unreviewed] == ["unreviewed"]
    assert [row["external_id"] for row in contracts["contracts"]] == ["reviewed"]


def test_multi_profile_contract_reports_partial_then_complete_review(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    market = MarketRecord(
        source="polymarket",
        external_id="multi-review",
        title="Will MrBeast's next YouTube video reach 100 million views?",
        description="Resolves from the public YouTube view counter.",
        status="open",
        closes_at=datetime.now(timezone.utc) + timedelta(days=3),
        probability=0.55,
        volume=450_000,
        raw={"event": {"id": "multi-review", "title": "MrBeast video views"}},
    )
    scan_market(settings, database, market)
    first = database.list_contract_groups()["contracts"][0]
    assert first["review_total"] == 2
    assert first["reviewed_count"] == 0

    save_feedback(database, first["reviews"][0]["match_id"], decision="monitor")
    partial = database.list_contract_groups()["contracts"][0]
    assert partial["reviewed_count"] == 1
    assert partial["all_reviewed"] is False
    assert partial["display_state"] == "in review"

    save_feedback(database, partial["reviews"][1]["match_id"], decision="actionable")
    complete = database.list_contract_groups()["contracts"][0]
    assert complete["reviewed_count"] == 2
    assert complete["all_reviewed"] is True
    assert complete["display_state"] == "reviewed"


def test_legacy_acknowledgements_are_separate_from_structured_reviews(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scan_market(settings, database, spotify_market("legacy-review"))
    match = database.list_matches()[0]
    assert database.acknowledge_match(match["match_id"], datetime.now(timezone.utc))

    summary = database.feedback_summary(view="active")
    assert summary["reviewed"] == 0
    assert summary["legacy_reviewed"] == 1
    assert summary["unreviewed"] == 0
    legacy = database.list_matches(review_decision="legacy_reviewed")
    assert [row["external_id"] for row in legacy] == ["legacy-review"]


def test_feedback_survives_guidance_refresh(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scan_market(settings, database, spotify_market("feedback-refresh"))
    match = database.list_matches()[0]
    save_feedback(database, match["match_id"], decision="monitor")

    market_id, market, _organizations = database.list_matched_markets()[0]
    result = RiskEngine(load_watchlist(settings.watchlist_path)).match(market)[0]
    assert database.update_match_analysis(market_id, result)

    refreshed = database.get_match(match["match_id"])
    assert refreshed is not None
    assert refreshed["review_decision"] == "monitor"
    assert refreshed["review_note"] == "Reviewer context"


def test_feedback_api_renders_and_validates_structured_assessment(
    tmp_path: Path, monkeypatch
) -> None:
    import raascal_watch.app as app_module

    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = scan_market(settings, database, spotify_market("feedback-web"))
    match_id = database.list_matches()[0]["match_id"]

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "scanner", scanner)

    with TestClient(app_module.app) as client:
        saved = client.post(
            f"/api/matches/{match_id}/feedback",
            json={
                "decision": "actionable",
                "reason_codes": ["advance_information_access", "not-a-code"],
                "guidance_rating": "useful",
                "note": "Worth escalation",
                "corrected_role": "KPI owner",
                "suggested_owner": "Compliance",
            },
        )
        invalid = client.post(
            f"/api/matches/{match_id}/feedback",
            json={"decision": "definitely_bad"},
        )
        dashboard = client.get("/?review_decision=actionable")
        calibration = client.get("/api/calibration")

    assert saved.status_code == 200
    assert saved.json()["decision"] == "actionable"
    assert invalid.status_code == 422
    assert dashboard.status_code == 200
    assert "Actionable" in dashboard.text
    assert "Reviewer calibration" in dashboard.text
    assert calibration.json()["decision_counts"]["actionable"] == 1
    row = database.get_match(match_id)
    assert row is not None
    assert row["review_reason_codes"] == ["advance_information_access"]


def test_export_feedback_writes_structured_csv(tmp_path: Path, monkeypatch) -> None:
    import raascal_watch.cli as cli_module

    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scan_market(settings, database, spotify_market("feedback-export"))
    match_id = database.list_matches()[0]["match_id"]
    save_feedback(database, match_id, decision="false_positive")

    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    output = tmp_path / "feedback.csv"
    args = argparse.Namespace(format="csv", output=str(output), view="all")
    assert command_export_feedback(args) == 0
    text = output.read_text(encoding="utf-8")
    assert "false_positive" in text
    assert "feedback-export" in text


def test_feedback_ui_and_auto_filter_assets_are_present() -> None:
    template = (ROOT / "raascal_watch" / "templates" / "index.html").read_text()
    script = (ROOT / "raascal_watch" / "static" / "app.js").read_text()

    assert "Reviewer calibration" in template
    assert "data-feedback-form" in template
    assert "Actionable" in template
    assert "False positive" in template
    assert 'name="review_decision"' in template
    assert "Unreviewed first" in template
    assert "/api/matches/${matchId}/feedback" in script


def test_existing_database_adds_review_feedback_table_without_reset(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "legacy-feedback.db"
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
        tables = {
            row["name"]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "review_feedback" in tables


def test_structured_feedback_remains_visible_after_contract_archives(
    tmp_path: Path, monkeypatch
) -> None:
    import raascal_watch.app as app_module

    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = scan_market(settings, database, spotify_market("feedback-archives"))
    match = database.list_matches()[0]
    save_feedback(database, match["match_id"], decision="monitor")
    with database.connect() as connection:
        connection.execute(
            "UPDATE markets SET closes_at = ? WHERE id = ?",
            (
                (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                match["market_id"],
            ),
        )

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "scanner", scanner)
    with TestClient(app_module.app) as client:
        response = client.get("/?view=archive")

    assert response.status_code == 200
    assert "Historical reviewer assessment" in response.text
    assert "Monitor" in response.text
    assert "data-feedback-form" not in response.text


def test_unreviewed_first_sort_prioritizes_remaining_work(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    asyncio.run(
        scanner.scan_records(
            "polymarket",
            [spotify_market("already-reviewed"), spotify_market("still-unreviewed")],
        )
    )
    matches = {row["external_id"]: row for row in database.list_matches()}
    save_feedback(database, matches["already-reviewed"]["match_id"], decision="monitor")

    ordered = database.list_contract_groups(sort="review")["contracts"]
    assert [item["external_id"] for item in ordered] == [
        "still-unreviewed",
        "already-reviewed",
    ]
