from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Iterable

import httpx

from . import __version__
from .alerts import AlertDispatcher
from .collectors import MarketCollector, enabled_collectors
from .db import Database
from .models import (
    CollectorContext,
    MarketRecord,
    ScanSourceSummary,
    ScanSummary,
    SourceFetchResult,
)
from .risk import RiskEngine
from .settings import Settings
from .text import utcnow
from .watchlist import load_watchlist

logger = logging.getLogger(__name__)


class ScannerBusyError(RuntimeError):
    pass


class Scanner:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        collectors: list[MarketCollector] | None = None,
    ):
        self.settings = settings
        self.database = database
        self.collectors = collectors if collectors is not None else enabled_collectors(settings)
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    async def scan(
        self,
        *,
        alert_on_first_scan: bool | None = None,
        wait_for_lock: bool = True,
    ) -> ScanSummary:
        if self._lock.locked() and not wait_for_lock:
            raise ScannerBusyError("A scan is already running")
        async with self._lock:
            return await self._scan_locked(alert_on_first_scan=alert_on_first_scan)

    async def _scan_locked(
        self, *, alert_on_first_scan: bool | None = None
    ) -> ScanSummary:
        self.database.initialize()
        started = utcnow()
        watchlist = load_watchlist(self.settings.watchlist_path)
        risk_engine = RiskEngine(watchlist)
        first_scan_alerts = (
            self.settings.alert_on_first_scan
            if alert_on_first_scan is None
            else alert_on_first_scan
        )

        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        headers = {
            "User-Agent": (
                f"RaaScal-Watch/{__version__} "
                "(external incentive intelligence; public market data)"
            ),
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            dispatcher = AlertDispatcher(self.settings, client)
            collector_contexts = {
                collector.name: CollectorContext(
                    source_initialized=self.database.source_initialized(collector.name),
                    last_success_at=self.database.source_last_success(collector.name),
                    active_external_ids=tuple(
                        self.database.list_active_external_ids(collector.name)
                    ),
                )
                for collector in self.collectors
            }
            fetch_results = await asyncio.gather(
                *(
                    collector.fetch(
                        client,
                        self.settings,
                        collector_contexts.get(collector.name),
                    )
                    for collector in self.collectors
                )
            )
            summaries: list[ScanSourceSummary] = []
            for result in fetch_results:
                summaries.append(
                    await self._process_source(
                        result,
                        risk_engine,
                        dispatcher,
                        started,
                        first_scan_alerts=first_scan_alerts,
                    )
                )

        return ScanSummary(started, utcnow(), summaries)

    async def scan_records(
        self,
        source: str,
        records: Iterable[MarketRecord],
        *,
        notify: bool = False,
    ) -> ScanSummary:
        """Process supplied records for demos, tests, and future connector adapters."""
        if self._lock.locked():
            raise ScannerBusyError("A scan is already running")
        async with self._lock:
            self.database.initialize()
            started = utcnow()
            watchlist = load_watchlist(self.settings.watchlist_path)
            risk_engine = RiskEngine(watchlist)
            timeout = httpx.Timeout(self.settings.request_timeout_seconds)
            async with httpx.AsyncClient(timeout=timeout) as client:
                dispatcher = AlertDispatcher(self.settings, client)
                result = SourceFetchResult(source, list(records), pages=1)
                summary = await self._process_source(
                    result,
                    risk_engine,
                    dispatcher,
                    started,
                    first_scan_alerts=notify,
                    force_notify=notify,
                )
            return ScanSummary(started, utcnow(), [summary])

    async def _process_source(
        self,
        result: SourceFetchResult,
        risk_engine: RiskEngine,
        dispatcher: AlertDispatcher,
        scan_started_at: datetime,
        *,
        first_scan_alerts: bool,
        force_notify: bool = False,
    ) -> ScanSourceSummary:
        summary = ScanSourceSummary(
            source=result.source,
            fetched=len(result.markets),
            pages=result.pages,
            error=result.error,
        )
        source_initialized = self.database.source_initialized(result.source)
        baseline = not source_initialized and not first_scan_alerts and not force_notify
        # A partial/error response should never establish a baseline or emit alerts.
        suppress_for_error = bool(result.error)

        for market in result.markets:
            # Adapters may supply their own source label; the fetch result is authoritative.
            market.source = result.source
            market_id, market_is_new = self.database.upsert_market(market, scan_started_at)
            if market_is_new:
                summary.new_markets += 1

            for match in risk_engine.match(market):
                summary.matches += 1
                if result.error:
                    initial_state = "source_error"
                elif baseline:
                    initial_state = "baseline"
                elif not market_is_new and not self.settings.alert_on_new_match_for_existing_market:
                    initial_state = "historical"
                else:
                    initial_state = "pending"

                materiality_gate = str((match.materiality or {}).get("gate") or "observed")
                if initial_state == "pending" and materiality_gate == "observed":
                    initial_state = "observed"

                match_id, match_is_new = self.database.upsert_match(
                    market_id,
                    match,
                    scan_started_at,
                    initial_alert_state=initial_state,
                )
                if not match_is_new:
                    continue
                summary.new_matches += 1

                should_notify = (
                    force_notify
                    or (
                        not baseline
                        and not suppress_for_error
                        and materiality_gate in {"review", "escalate"}
                        and (
                            market_is_new
                            or self.settings.alert_on_new_match_for_existing_market
                        )
                    )
                )
                if not should_notify:
                    if baseline:
                        summary.baseline_suppressed += 1
                    continue

                outcomes = await dispatcher.send(market, match)
                external_channels = [
                    outcome for outcome in outcomes if outcome.channel != "console"
                ]
                for outcome in outcomes:
                    self.database.log_notification(
                        match_id,
                        outcome.channel,
                        utcnow(),
                        outcome.status,
                        outcome.detail,
                    )
                if external_channels:
                    sent = any(item.status == "sent" for item in external_channels)
                    state = "sent" if sent else "failed"
                else:
                    state = "console_only"
                self.database.set_match_alert_state(
                    match_id,
                    state,
                    notified_at=utcnow() if state != "failed" else None,
                )
                summary.notifications += 1

        finished = utcnow()
        if result.error:
            self.database.mark_source_error(result.source, finished, result.error)
        else:
            self.database.mark_source_success(result.source, finished, initialize=True)
        self.database.record_scan(summary, scan_started_at, finished)
        logger.info(
            "Scan %s: fetched=%s new=%s matches=%s notifications=%s error=%s",
            result.source,
            summary.fetched,
            summary.new_markets,
            summary.matches,
            summary.notifications,
            summary.error,
        )
        return summary
