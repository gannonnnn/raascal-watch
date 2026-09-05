"""Regression tests for the frozen-first-scan incident (no live API dependency)."""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from raascal_watch.db import Database
from raascal_watch.models import MarketRecord, SourceFetchResult
from raascal_watch.risk import RiskEngine
from raascal_watch.scanner import Scanner
from raascal_watch.settings import get_settings
from raascal_watch.text import utcnow

ROOT = Path(__file__).resolve().parents[1]


def settings_for(tmp):
    return replace(get_settings(), db_path=tmp / 'test.db', watchlist_path=ROOT / 'config/watchlist.yaml',
                   run_scan_on_startup=False, slack_webhook_url=None, generic_webhook_url=None,
                   smtp_host=None, smtp_from=None, smtp_to=())


def records(count, source='kalshi'):
    return [MarketRecord(source=source, external_id=f'test-{i}', title=f'Will Spotify streams increase? {i}',
                         status='open', probability=.4, volume=1000, closes_at=utcnow()+timedelta(days=3))
            for i in range(count)]


class FixtureCollector:
    name = 'kalshi'

    def __init__(self, count=600, delay=0.0, error=None):
        self.count, self.delay, self.error = count, delay, error

    async def fetch(self, client, settings, context=None):
        if self.delay:
            await asyncio.sleep(self.delay)
        return SourceFetchResult(self.name, records(self.count, self.name), pages=1, error=self.error)


def bind_app(tmp_path, monkeypatch, collector=None):
    import raascal_watch.app as app_module
    settings = settings_for(tmp_path)
    db = Database(settings.db_path)
    scanner = Scanner(settings, db, collectors=[collector or FixtureCollector()])
    monkeypatch.setattr(app_module, 'settings', settings)
    monkeypatch.setattr(app_module, 'database', db)
    monkeypatch.setattr(app_module, 'scanner', scanner)
    return app_module, db, scanner


def test_dashboard_and_status_respond_during_slow_baseline(tmp_path, monkeypatch):
    app, db, scanner = bind_app(tmp_path, monkeypatch)
    original = RiskEngine.match
    matching_threads = set()

    def slow_match(self, market):
        matching_threads.add(threading.get_ident())
        time.sleep(.002)  # Simulated blocking work; v0.9.0 freezes the HTTP loop here.
        return original(self, market)

    monkeypatch.setattr(RiskEngine, 'match', slow_match)

    async def run():
        main_thread = threading.get_ident()
        async with app.app.router.lifespan_context(app.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
                before = time.perf_counter()
                started = await client.post('/api/scan')
                assert started.status_code == 202
                assert time.perf_counter() - before < 1
                assert (await client.post('/api/scan')).status_code == 409
                observed_progress = False
                timings = []
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    before = time.perf_counter()
                    status = (await client.get('/api/scan/status')).json()
                    timings.append(time.perf_counter() - before)
                    assert (await client.get('/health/live')).status_code == 200
                    if status['processed'] > 0 and status['running']:
                        observed_progress = True
                        before = time.perf_counter()
                        page = await client.get('/?organization=Spotify&gate=all')
                        assert page.status_code == 200
                        assert time.perf_counter() - before < 2
                        assert 'Scan in progress' not in page.text or 'scan-progress-panel' in page.text
                    if not status['running']:
                        break
                    await asyncio.sleep(.03)
                assert status['state'] == 'completed', status
                assert status['processed'] == 600
                assert observed_progress
                assert matching_threads and main_thread not in matching_threads
                assert max(timings) < .5
                assert db.source_initialized('kalshi')
                assert db.dashboard_stats()['markets'] == 600
    asyncio.run(run())


def test_cancel_during_processing_preserves_rows_without_baseline(tmp_path, monkeypatch):
    app, db, scanner = bind_app(tmp_path, monkeypatch, FixtureCollector(3000))
    original = RiskEngine.match

    def slow(self, market):
        time.sleep(.001)
        return original(self, market)

    monkeypatch.setattr(RiskEngine, 'match', slow)

    async def run():
        async with app.app.router.lifespan_context(app.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
                await client.post('/api/scan')
                for _ in range(500):
                    status = (await client.get('/api/scan/status')).json()
                    if status['processed'] >= 100:
                        break
                    await asyncio.sleep(.01)
                assert status['processed'] >= 100
                before = time.monotonic()
                assert (await client.post('/api/scan/cancel')).status_code == 202
                # A repeated stop must not interrupt the writer's cancellation drain.
                await client.post('/api/scan/cancel')
                while scanner.is_running and time.monotonic() - before < 3:
                    await asyncio.sleep(.01)
                assert not scanner.is_running
                assert scanner.status()['state'] == 'cancelled'
                assert 100 <= db.dashboard_stats()['markets'] < 3000
                assert not db.source_initialized('kalshi')
                with db.connect() as connection:
                    assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                # No orphan task left to write after cancellation returns.
                first_count = db.dashboard_stats()['markets']
                await asyncio.sleep(.1)
                assert first_count == db.dashboard_stats()['markets']
                # Restarting is supported and deduplicates previously committed rows.
                scanner.collectors = [FixtureCollector(50)]
                assert (await client.post('/api/scan')).status_code == 202
                while scanner.is_running:
                    await asyncio.sleep(.02)
                assert scanner.status()['state'] == 'completed'
    asyncio.run(run())


def test_shutdown_cancels_network_and_never_sets_baseline(tmp_path, monkeypatch):
    app, db, scanner = bind_app(tmp_path, monkeypatch, FixtureCollector(delay=60))

    async def run():
        before = time.monotonic()
        async with app.app.router.lifespan_context(app.app):
            scanner.start_background()
            await asyncio.sleep(.1)
        assert time.monotonic() - before < 2
        assert scanner.status()['state'] == 'cancelled'
        assert not db.source_initialized('kalshi')
    asyncio.run(run())


def test_partial_source_and_collector_exception_do_not_abort_other_source(tmp_path):
    settings = settings_for(tmp_path)
    db = Database(settings.db_path)

    class Failed(FixtureCollector):
        name = 'polymarket'
        async def fetch(self, *args):
            raise RuntimeError('fixture source failure')

    scanner = Scanner(settings, db, collectors=[Failed(), FixtureCollector(3)])
    summary = asyncio.run(scanner.scan())
    assert scanner.status()['state'] == 'partial'
    assert len(summary.sources) == 2
    assert db.source_initialized('kalshi')
    assert not db.source_initialized('polymarket')


def test_failed_batch_rolls_back_and_can_be_used_again(tmp_path):
    db = Database(tmp_path / 'batch.db')
    db.initialize()
    with pytest.raises(ValueError):
        with db.write_batch():
            db.upsert_market(records(1)[0], utcnow())
            raise ValueError('simulate failed batch')
    assert db.dashboard_stats()['markets'] == 0
    with db.write_batch():
        db.upsert_market(records(1)[0], utcnow())
    assert db.dashboard_stats()['markets'] == 1


def test_thread_local_transaction_isolation(tmp_path):
    db = Database(tmp_path / 'isolation.db')
    db.initialize()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.write_batch():
            db.upsert_market(records(1)[0], utcnow())
            # Another thread gets its own connection and cannot see uncommitted rows.
            assert pool.submit(lambda: db.dashboard_stats()['markets']).result(timeout=2) == 0
        assert pool.submit(lambda: db.dashboard_stats()['markets']).result(timeout=2) == 1


def test_scanner_saves_fast_source_before_slow_download_finishes(tmp_path):
    settings = settings_for(tmp_path)
    db = Database(settings.db_path)
    slow = FixtureCollector(1, delay=1)
    slow.name = 'polymarket'
    scanner = Scanner(settings, db, collectors=[slow, FixtureCollector(2)])

    async def run():
        task = asyncio.create_task(scanner.scan())
        for _ in range(70):
            if scanner.status()['sources'].get('kalshi', {}).get('phase') == 'complete':
                break
            await asyncio.sleep(.01)
        assert scanner.status()['sources']['kalshi']['phase'] == 'complete'
        assert scanner.is_running
        await task
    asyncio.run(run())


def test_frontend_polls_and_guards_unsaved_feedback():
    script = (ROOT/'raascal_watch/static/app.js').read_text()
    assert '/api/scan/status' in script
    assert '/api/scan/cancel' in script
    assert 'reviewerHasUnsavedChanges' in script
    assert 'AbortController' in script
    assert 'replaceChildren' in script
