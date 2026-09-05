from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable

import httpx

from . import __version__
from .alerts import AlertDispatcher
from .collectors import MarketCollector, enabled_collectors
from .db import Database
from .models import CollectorContext, MarketRecord, ScanSourceSummary, ScanSummary, SourceFetchResult
from .risk import RiskEngine
from .settings import Settings
from .text import utcnow
from .watchlist import load_watchlist

logger = logging.getLogger(__name__)


class ScannerBusyError(RuntimeError):
    pass


class Scanner:
    """One scan at a time, with network I/O on asyncio and bounded work off-loop.

    Database connections are created within their worker thread. Cancellation is
    cooperative: finish the in-flight short write batch, retain committed rows,
    and do NOT advance the unfinished source's baseline/watermark.
    """

    PROCESS_BATCH_SIZE = 100

    def __init__(self, settings: Settings, database: Database,
                 collectors: list[MarketCollector] | None = None):
        self.settings = settings
        self.database = database
        self.collectors = collectors if collectors is not None else enabled_collectors(settings)
        self._lock = asyncio.Lock()
        self._stop = threading.Event()
        self._background_task: asyncio.Task | None = None
        self._running_task: asyncio.Task | None = None
        self._started_monotonic = 0.0
        self._updated_monotonic = time.monotonic()
        self._progress: dict[str, Any] = {
            "run_id": None, "state": "idle", "phase": "idle", "sources": {},
            "started_at": None, "finished_at": None, "error": None,
            "message": "Ready. No scan has run in this server session.",
        }

    @property
    def is_running(self) -> bool:
        return self._lock.locked() or bool(self._background_task and not self._background_task.done())

    def status(self) -> dict[str, Any]:
        """Lightweight progress: intentionally no database queries."""
        result = copy.deepcopy(self._progress)
        result["running"] = self.is_running
        result["cancel_requested"] = self._stop.is_set() and self.is_running
        now = time.monotonic()
        if result["running"] and self._started_monotonic:
            result["elapsed_seconds"] = round(now - self._started_monotonic, 1)
        else:
            result.setdefault("elapsed_seconds", 0)
        result["seconds_since_progress"] = round(now - self._updated_monotonic, 1)
        result["processed"] = sum(s.get("processed", 0) for s in result["sources"].values())
        result["downloaded"] = sum(s.get("downloaded", 0) for s in result["sources"].values())
        result["matches"] = sum(s.get("matches", 0) for s in result["sources"].values())
        return result

    def _update(self, **values: Any) -> None:
        self._progress.update(values)
        self._updated_monotonic = time.monotonic()
        self._progress["updated_at"] = utcnow().isoformat()

    def _source_progress(self, name: str, **values: Any) -> None:
        item = self._progress["sources"].setdefault(name, {
            "phase": "waiting", "pages": 0, "downloaded": 0, "processed": 0,
            "matches": 0, "error": None, "warnings": [],
        })
        warning = values.pop("warning", None)
        if warning and warning not in item["warnings"]:
            item["warnings"].append(warning)
        item.update(values)
        self._update()

    def start_background(self) -> dict[str, Any]:
        if self.is_running:
            raise ScannerBusyError("A scan is already running")
        self._stop.clear()
        self._progress = {
            "run_id": uuid.uuid4().hex, "state": "queued", "phase": "queued",
            "sources": {}, "started_at": None, "finished_at": None, "error": None,
            "message": "Scan queued. The dashboard remains available.",
        }
        self._background_task = asyncio.create_task(self.scan(wait_for_lock=False))
        self._background_task.add_done_callback(self._consume_background_result)
        return self.status()

    @staticmethod
    def _consume_background_result(task: asyncio.Task) -> None:
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                logger.error("Background scan failed: %s", error)

    def cancel_current(self) -> bool:
        if not self.is_running:
            return False
        if self._stop.is_set():
            return True
        self._stop.set()
        if self._running_task is None:
            self._update(state="cancelled", phase="cancelled", finished_at=utcnow().isoformat())
        self._update(message="Stopping after the current short batch. Saved records will remain.")
        task = self._running_task or self._background_task
        if task and not task.done():
            task.cancel()
        return True

    async def close(self) -> None:
        task = self._running_task or self._background_task
        if task and not task.done():
            self.cancel_current()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _begin(self, sources: Iterable[str]) -> None:
        queued = self._progress.get("state") == "queued"
        run_id = self._progress["run_id"] if queued else uuid.uuid4().hex
        self._stop.clear()
        self._started_monotonic = time.monotonic()
        self._progress = {
            "run_id": run_id, "state": "running", "phase": "preparing",
            "sources": {}, "started_at": utcnow().isoformat(),
            "finished_at": None, "error": None,
            "message": "Preparing scan. Results shown during scanning are partial.",
        }
        for name in sources:
            self._source_progress(name)
        self._running_task = asyncio.current_task()

    def _finish(self, summary: ScanSummary | None, *, error: str | None = None,
                cancelled: bool = False) -> None:
        if cancelled:
            for item in self._progress["sources"].values():
                if item["phase"] not in {"complete", "error"}:
                    item["phase"] = "cancelled"
            state = "cancelled"
            message = "Scan stopped. Saved batches remain; unfinished sources were not marked successful."
        elif error:
            state, message = "failed", "Scan failed. Previously committed results remain available."
        elif summary and any(item.error for item in summary.sources):
            state, message = "partial", "Scan finished with source errors. Coverage is incomplete; inspect source status."
        elif any(s["warnings"] for s in self._progress["sources"].values()):
            state, message = "completed_with_warnings", "Processing finished with coverage warnings. Page-capped results are not a complete catalog."
        else:
            state, message = "completed", "Scan processing complete. Saved results are ready."
        self._update(state=state, phase=state, error=error, message=message,
                     finished_at=utcnow().isoformat(),
                     elapsed_seconds=round(time.monotonic() - self._started_monotonic, 1))
        if summary:
            self._progress["summary"] = {
                "fetched": summary.fetched, "new_markets": summary.new_markets,
                "matches": summary.matches, "notifications": summary.notifications,
                "sources": [asdict(s) for s in summary.sources],
            }
        self._running_task = None

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise asyncio.CancelledError

    async def _work(self, function, *args, **kwargs):
        """Drain a worker on cancellation; never leave a SQLite writer orphaned."""
        worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            self._stop.set()
            # The worker checks _stop while preparing records; a short write batch
            # already in flight commits atomically before this returns.
            return await asyncio.shield(worker)

    async def scan(self, *, alert_on_first_scan: bool | None = None,
                   wait_for_lock: bool = True) -> ScanSummary:
        if self._lock.locked() and not wait_for_lock:
            raise ScannerBusyError("A scan is already running")
        async with self._lock:
            self._begin(c.name for c in self.collectors)
            try:
                summary = await self._scan_locked(alert_on_first_scan=alert_on_first_scan)
                self._check_stop()
            except asyncio.CancelledError:
                self._finish(None, cancelled=True)
                raise
            except Exception as exc:
                self._finish(None, error=str(exc))
                raise
            else:
                self._finish(summary)
                return summary

    def _prepare(self):
        self.database.initialize()
        engine = RiskEngine(load_watchlist(self.settings.watchlist_path))
        contexts = {
            c.name: CollectorContext(
                source_initialized=self.database.source_initialized(c.name),
                last_success_at=self.database.source_last_success(c.name),
                active_external_ids=tuple(self.database.list_active_external_ids(c.name)),
            ) for c in self.collectors
        }
        return engine, contexts

    async def _scan_locked(self, *, alert_on_first_scan: bool | None = None) -> ScanSummary:
        started = utcnow()
        risk_engine, contexts = await self._work(self._prepare)
        self._check_stop()
        first_scan_alerts = (self.settings.alert_on_first_scan if alert_on_first_scan is None else alert_on_first_scan)
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        headers = {"User-Agent": f"RaaScal-Watch/{__version__} (public market data)", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            dispatcher = AlertDispatcher(self.settings, client)

            async def fetch_source(collector):
                self._source_progress(collector.name, phase="downloading")
                collector.progress_callback = lambda **values: self._source_progress(collector.name, **values)
                try:
                    result = await collector.fetch(client, self.settings, contexts.get(collector.name))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Collector %s failed", collector.name)
                    result = SourceFetchResult(collector.name, [], 0, str(exc))
                self._source_progress(collector.name, phase="downloaded", pages=result.pages,
                                      downloaded=len(result.markets), error=result.error)
                return result

            self._update(phase="scanning", message="Downloading and processing records. Saved results are partial until this scan finishes.")
            tasks = [asyncio.create_task(fetch_source(c)) for c in self.collectors]
            summaries = []
            try:
                # Do not hold a fast source hostage to a slower source download.
                for task in asyncio.as_completed(tasks):
                    self._check_stop()
                    result = await task
                    summaries.append(await self._process_source(result, risk_engine, dispatcher, started,
                                                                first_scan_alerts=first_scan_alerts))
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        return ScanSummary(started, utcnow(), summaries)

    async def scan_records(self, source: str, records: Iterable[MarketRecord], *, notify: bool = False) -> ScanSummary:
        """Explicit fixture/adaptor entry point; normal startup never seeds demos."""
        if self.is_running:
            raise ScannerBusyError("A scan is already running")
        async with self._lock:
            self._begin([source])
            started = utcnow()
            try:
                await self._work(self.database.initialize)
                risk_engine = await self._work(lambda: RiskEngine(load_watchlist(self.settings.watchlist_path)))
                result = SourceFetchResult(source, list(records), pages=1)
                self._source_progress(source, phase="downloaded", downloaded=len(result.markets), pages=1)
                async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                    summary = await self._process_source(result, risk_engine, AlertDispatcher(self.settings, client),
                                                        started, first_scan_alerts=notify, force_notify=notify)
                self._check_stop()
            except asyncio.CancelledError:
                self._finish(None, cancelled=True)
                raise
            except Exception as exc:
                self._finish(None, error=str(exc))
                raise
            all_sources = ScanSummary(started, utcnow(), [summary])
            self._finish(all_sources)
            return all_sources

    def _process_batch(self, records, source, engine, seen_at, *, baseline, source_error, force_notify):
        # Heavy matching is outside both the web event loop AND the write lock.
        prepared = []
        for market in records:
            if self._stop.is_set():
                break
            market.source = source
            prepared.append((market, list(engine.match(market))))
        counts = dict(processed=0, new_markets=0, matches=0, new_matches=0, baseline_suppressed=0)
        notifications = []
        with self.database.write_batch():
            for market, matches in prepared:
                market_id, market_is_new = self.database.upsert_market(market, seen_at)
                counts["processed"] += 1
                counts["new_markets"] += int(market_is_new)
                for match in matches:
                    counts["matches"] += 1
                    if source_error:
                        state = "source_error"
                    elif baseline:
                        state = "baseline"
                    elif not market_is_new and not self.settings.alert_on_new_match_for_existing_market:
                        state = "historical"
                    else:
                        state = "pending"
                    gate = str((match.materiality or {}).get("gate") or "observed")
                    if state == "pending" and gate == "observed":
                        state = "observed"
                    match_id, match_is_new = self.database.upsert_match(market_id, match, seen_at, initial_alert_state=state)
                    if not match_is_new:
                        continue
                    counts["new_matches"] += 1
                    should_notify = not source_error and (force_notify or (
                        not baseline and gate in {"review", "escalate"}
                        and (market_is_new or self.settings.alert_on_new_match_for_existing_market)))
                    if should_notify:
                        notifications.append((match_id, market, match))
                    elif baseline:
                        counts["baseline_suppressed"] += 1
        return counts, notifications

    def _save_notification(self, match_id, outcomes):
        with self.database.write_batch():
            for outcome in outcomes:
                self.database.log_notification(match_id, outcome.channel, utcnow(), outcome.status, outcome.detail)
            external = [o for o in outcomes if o.channel != "console"]
            state = ("sent" if any(o.status == "sent" for o in external) else "failed") if external else "console_only"
            self.database.set_match_alert_state(match_id, state, notified_at=utcnow() if state != "failed" else None)

    def _record_source(self, result, summary, started):
        finished = utcnow()
        with self.database.write_batch():
            if summary.error:
                self.database.mark_source_error(result.source, finished, summary.error)
            else:
                self.database.mark_source_success(result.source, finished, initialize=True)
            self.database.record_scan(summary, started, finished)

    async def _process_source(self, result, risk_engine, dispatcher, scan_started_at, *, first_scan_alerts, force_notify=False):
        summary = ScanSourceSummary(source=result.source, fetched=len(result.markets), pages=result.pages, error=result.error)
        source_initialized = await self._work(self.database.source_initialized, result.source)
        baseline = not source_initialized and not first_scan_alerts and not force_notify
        processed = 0
        last_log = time.monotonic()
        self._source_progress(result.source, phase="processing", downloaded=len(result.markets), pages=result.pages)
        logger.info("Processing %s: 0 / %s downloaded records; dashboard remains available", result.source, len(result.markets))
        try:
            for offset in range(0, len(result.markets), self.PROCESS_BATCH_SIZE):
                self._check_stop()
                counts, notifications = await self._work(
                    self._process_batch, result.markets[offset:offset + self.PROCESS_BATCH_SIZE],
                    result.source, risk_engine, scan_started_at,
                    baseline=baseline, source_error=bool(result.error), force_notify=force_notify,
                )
                processed += counts.pop("processed")
                for key, value in counts.items():
                    setattr(summary, key, getattr(summary, key) + value)
                self._source_progress(result.source, processed=processed, matches=summary.matches)
                if time.monotonic() - last_log >= 2 or processed == len(result.markets):
                    logger.info("Processing %s: %s / %s records saved; %s profile matches", result.source, processed, len(result.markets), summary.matches)
                    last_log = time.monotonic()
                self._check_stop()
                for match_id, market, match in notifications:
                    self._check_stop()
                    outcomes = await dispatcher.send(market, match)
                    await self._work(self._save_notification, match_id, outcomes)
                    summary.notifications += 1
            self._check_stop()
        except asyncio.CancelledError:
            summary.error = f"Cancelled after {processed} of {len(result.markets)} records; saved batches retained; baseline not advanced."
            await self._work(self._record_source, result, summary, scan_started_at)
            self._source_progress(result.source, phase="cancelled", error=summary.error)
            raise
        except Exception as exc:
            logger.exception("Processing %s failed", result.source)
            summary.error = f"Processing failed after {processed} records: {exc}"
        await self._work(self._record_source, result, summary, scan_started_at)
        self._source_progress(result.source, phase="error" if summary.error else "complete", error=summary.error)
        logger.info("Scan %s: fetched=%s new=%s matches=%s notifications=%s error=%s", result.source, summary.fetched,
                    summary.new_markets, summary.matches, summary.notifications, summary.error)
        return summary
