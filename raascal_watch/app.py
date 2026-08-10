from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import Database
from .scanner import Scanner, ScannerBusyError
from .settings import get_settings
from .text import utcnow
from .watchlist import WatchlistError, load_watchlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
database = Database(settings.db_path)
scanner = Scanner(settings, database)
PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def _format_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y · %H:%M UTC")
    except ValueError:
        return value


def _format_money(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def _format_probability(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


templates.env.filters["date"] = _format_date
templates.env.filters["money"] = _format_money
templates.env.filters["probability"] = _format_probability


async def _scheduled_scans() -> None:
    # Give the HTTP server a moment to start before the first network scan.
    await asyncio.sleep(1)
    while True:
        try:
            await scanner.scan(wait_for_lock=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled scan failed")
        await asyncio.sleep(settings.poll_interval_minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    task: asyncio.Task[None] | None = None
    if settings.run_scan_on_startup:
        task = asyncio.create_task(_scheduled_scans())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="RaaScal Watch",
    version="0.2.0",
    description="External incentive intelligence for public prediction markets.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    organization: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    source: str | None = Query(default=None),
    alert_state: str | None = Query(default=None),
) -> HTMLResponse:
    database.initialize()
    stats = database.dashboard_stats()
    matches = database.list_matches(
        organization=organization,
        severity=severity,
        source=source,
        alert_state=alert_state,
    )
    scans = database.recent_scans(12)
    try:
        watchlist = load_watchlist(settings.watchlist_path)
        watched_organizations = [item.name for item in watchlist.organizations]
        config_error = None
    except WatchlistError as exc:
        watched_organizations = []
        config_error = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "stats": stats,
            "matches": matches,
            "scans": scans,
            "scanner_running": scanner.is_running,
            "watched_organizations": watched_organizations,
            "configured_channels": list(
                channel
                for channel, enabled in (
                    ("Slack", bool(settings.slack_webhook_url)),
                    ("Webhook", bool(settings.generic_webhook_url)),
                    (
                        "Email",
                        bool(settings.smtp_host and settings.smtp_from and settings.smtp_to),
                    ),
                )
                if enabled
            ),
            "poll_interval": settings.poll_interval_minutes,
            "config_error": config_error,
            "filters": {
                "organization": organization or "",
                "severity": severity or "",
                "source": source or "",
                "alert_state": alert_state or "",
            },
        },
    )


@app.get("/api/matches")
async def api_matches(
    organization: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    alert_state: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return database.list_matches(
        organization=organization,
        severity=severity,
        source=source,
        alert_state=alert_state,
        limit=limit,
    )


@app.post("/api/scan")
async def api_scan() -> JSONResponse:
    try:
        summary = await scanner.scan(wait_for_lock=False)
    except ScannerBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WatchlistError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(jsonable_encoder(asdict(summary)))


@app.post("/api/matches/{match_id}/acknowledge")
async def acknowledge(match_id: int) -> dict[str, Any]:
    if not database.acknowledge_match(match_id, utcnow()):
        raise HTTPException(status_code=404, detail="Match not found")
    return {"ok": True, "match_id": match_id}


@app.get("/health")
async def health() -> dict[str, Any]:
    stats = database.dashboard_stats()
    return {
        "status": "ok",
        "scanner_running": scanner.is_running,
        "last_scan": stats["last_scan"],
        "enabled_sources": [collector.name for collector in scanner.collectors],
        "database": str(settings.db_path),
    }
