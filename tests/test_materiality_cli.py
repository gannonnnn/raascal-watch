from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from raascal_watch.cli import command_materiality_summary
from raascal_watch.db import Database
from raascal_watch.models import MarketRecord
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]


def test_materiality_summary_reports_queue_counts(tmp_path: Path, monkeypatch, capsys) -> None:
    import raascal_watch.cli as cli_module

    settings = replace(
        get_settings(),
        db_path=tmp_path / "cli.db",
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
    now = datetime.now(timezone.utc)
    asyncio.run(
        scanner.scan_records(
            "polymarket",
            [
                MarketRecord(
                    source="polymarket",
                    external_id="cli-review",
                    title="Will Spotify streams rank number one this week?",
                    description="Resolves from Spotify Charts.",
                    status="open",
                    closes_at=now + timedelta(days=2),
                    volume=250_000,
                ),
                MarketRecord(
                    source="polymarket",
                    external_id="cli-observed",
                    title="Will Spotify mention a product in 2028?",
                    description="Resolves from a public post.",
                    status="open",
                    closes_at=now + timedelta(days=400),
                    volume=50,
                ),
            ],
        )
    )
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)

    assert command_materiality_summary(argparse.Namespace()) == 0
    output = capsys.readouterr().out
    assert "1 contract(s) warrant review today" in output
    assert "1 observed without human action" in output
