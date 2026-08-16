from __future__ import annotations

import asyncio
import logging

import httpx
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import __version__
from .db import Database
from .exposure import PublicExposureError, fetch_public_exposure
from .review import (
    GUIDANCE_RATING_LABELS,
    GUIDANCE_RATING_VALUES,
    GUIDANCE_RATINGS,
    REVIEW_DECISION_LABELS,
    REVIEW_DECISION_VALUES,
    REVIEW_DECISIONS,
    REVIEW_REASON_GROUPS,
    normalize_reason_codes,
)
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

_ALLOWED_VIEWS = {"active", "archive"}
_ALLOWED_SORTS = {"priority", "review", "closing", "volume", "newest"}
_ALLOWED_GATES = {"review_today", "escalate", "review", "observed", "all"}


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
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{sign}${magnitude / 1_000_000:.2f}M"
    if magnitude >= 1_000:
        return f"{sign}${magnitude / 1_000:.1f}K"
    return f"{sign}${magnitude:,.0f}"


def _format_probability(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _format_cents(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}¢"


def _format_number(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _format_delta(value: float | None, *, percentage_points: bool = False) -> str:
    if value is None:
        return "—"
    if percentage_points:
        return f"{value * 100:+.1f} pts"
    return f"{value:+,.0f}"


def _format_activity(value: float | None, source: str | None = None) -> str:
    if value is None:
        return "—"
    if (source or "").casefold() == "kalshi":
        magnitude = abs(value)
        sign = "-" if value < 0 else ""
        if magnitude >= 1_000_000:
            return f"{sign}{magnitude / 1_000_000:.2f}M contracts"
        if magnitude >= 1_000:
            return f"{sign}{magnitude / 1_000:.1f}K contracts"
        return f"{sign}{magnitude:,.0f} contracts"
    return _format_money(value)


def _format_activity_delta(value: float | None, source: str | None = None) -> str:
    if value is None:
        return "—"
    if (source or "").casefold() == "kalshi":
        return f"{value:+,.0f} contracts"
    sign = "+" if value > 0 else ""
    return f"{sign}{_format_money(value)}"


templates.env.filters["date"] = _format_date
templates.env.filters["money"] = _format_money
templates.env.filters["probability"] = _format_probability
templates.env.filters["cents"] = _format_cents
templates.env.filters["number"] = _format_number
templates.env.filters["delta"] = _format_delta
templates.env.filters["activity"] = _format_activity
templates.env.filters["activity_delta"] = _format_activity_delta


def _normalize_view(value: str | None) -> str:
    clean = (value or "active").strip().lower()
    return clean if clean in _ALLOWED_VIEWS else "active"


def _normalize_sort(value: str | None) -> str:
    clean = (value or "priority").strip().lower()
    return clean if clean in _ALLOWED_SORTS else "priority"


def _normalize_scope_view(value: str | None, *, default: str = "active") -> str:
    clean = (value or default).strip().lower()
    return clean if clean in {"active", "archive", "all"} else default


def _normalize_gate(value: str | None, *, view: str = "active") -> str:
    if view == "archive":
        return "all"
    clean = (value or "review_today").strip().lower()
    return clean if clean in _ALLOWED_GATES else "review_today"


def _dashboard_url(request: Request, **changes: str | None) -> str:
    params = dict(request.query_params)
    for key, value in changes.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = str(value)
    query = urlencode(params)
    return f"/?{query}" if query else "/"


class ReviewFeedbackPayload(BaseModel):
    decision: str
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    guidance_rating: str | None = None
    note: str = Field(default="", max_length=4000)
    corrected_role: str = Field(default="", max_length=300)
    suggested_owner: str = Field(default="", max_length=300)


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
    version=__version__,
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
    review_decision: str | None = Query(default=None),
    gate: str = Query(default="review_today"),
    sort: str = Query(default="priority"),
    view: str = Query(default="active"),
    include_demo: bool = Query(default=False),
) -> HTMLResponse:
    database.initialize()
    normalized_view = _normalize_view(view)
    normalized_sort = _normalize_sort(sort)
    normalized_gate = _normalize_gate(gate, view=normalized_view)

    # Normal review is active-only. Historical contracts remain available in an
    # explicit archive but cannot be acknowledged or reviewed as current work.
    stats = database.dashboard_stats(include_demo=include_demo, view=normalized_view)
    calibration = database.feedback_summary(
        include_demo=include_demo, view=normalized_view
    )
    result = database.list_contract_groups(
        organization=organization,
        severity=severity,
        source=source,
        alert_state=alert_state,
        review_decision=review_decision,
        include_demo=include_demo,
        view=normalized_view,
        sort=normalized_sort,
        materiality_gate=normalized_gate,
    )
    scans = database.recent_scans(12, include_demo=include_demo)

    try:
        watchlist = load_watchlist(settings.watchlist_path)
        watched_profiles = [item.name for item in watchlist.organizations]
        profile_types = {item.name: item.profile_type for item in watchlist.organizations}
        config_error = None
    except WatchlistError as exc:
        watched_profiles = []
        profile_types = {}
        config_error = str(exc)

    # Always show every enabled organization or monitored theme in the filter.
    # Match-derived names are appended as a compatibility fallback for records
    # created by an older or customized watchlist.
    filter_profile_names = list(
        dict.fromkeys([*watched_profiles, *stats.get("organizations", [])])
    )
    organization_counts = stats.get("organization_counts", {})
    organization_filter_options = [
        {
            "name": name,
            "count": int(organization_counts.get(name, 0)),
            "profile_type": profile_types.get(name, "organization"),
        }
        for name in filter_profile_names
    ]

    filter_values = {
        "organization": organization or "",
        "severity": severity or "",
        "source": source or "",
        "alert_state": alert_state or "",
        "review_decision": review_decision or "",
        "gate": normalized_gate,
        "sort": normalized_sort,
    }
    chip_labels = {
        "organization": "Profile",
        "severity": "Severity",
        "source": "Source",
        "alert_state": "Delivery state",
        "review_decision": "Reviewer decision",
    }
    active_filter_chips = [
        {
            "key": key,
            "label": label,
            "value": filter_values[key].replace("_", " ").title()
            if key != "organization"
            else filter_values[key],
            "clear_url": _dashboard_url(request, **{key: None}),
        }
        for key, label in chip_labels.items()
        if filter_values[key]
    ]

    clear_params: dict[str, str | None] = {
        "organization": None,
        "severity": None,
        "source": None,
        "alert_state": None,
        "review_decision": None,
        "sort": None,
        "gate": normalized_gate,
        "view": normalized_view,
    }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "stats": stats,
            "calibration": calibration,
            "materiality_counts": result["gate_counts"],
            "materiality_gate": normalized_gate,
            "contract_groups": result["groups"],
            "displayed_contract_count": len(result["contracts"]),
            "filtered_contract_count": result["total"],
            "scans": scans,
            "scanner_running": scanner.is_running,
            "watched_organizations": watched_profiles,
            "profile_types": profile_types,
            "organization_filter_options": organization_filter_options,
            "selected_profile_enabled": bool(
                organization and organization in watched_profiles
            ),
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
            "include_demo": include_demo,
            "view": normalized_view,
            "filters": filter_values,
            "active_filter_chips": active_filter_chips,
            "gate_labels": {
                "review_today": "Review today",
                "escalate": "Escalate now",
                "review": "Review",
                "observed": "Observed",
                "all": "All active",
            },
            "review_decisions": REVIEW_DECISIONS,
            "review_decision_labels": REVIEW_DECISION_LABELS,
            "review_reason_groups": REVIEW_REASON_GROUPS,
            "guidance_ratings": GUIDANCE_RATINGS,
            "guidance_rating_labels": GUIDANCE_RATING_LABELS,
            "review_today_url": _dashboard_url(
                request, view="active", gate="review_today", alert_state=None, review_decision=None
            ),
            "observed_url": _dashboard_url(
                request, view="active", gate="observed", alert_state=None, review_decision=None
            ),
            "all_active_url": _dashboard_url(
                request, view="active", gate="all", alert_state=None, review_decision=None
            ),
            "archive_url": _dashboard_url(
                request,
                view="archive",
                alert_state=None,
                review_decision=None,
                sort="priority",
                gate="all",
            ),
            "clear_url": _dashboard_url(request, **clear_params),
        },
    )


@app.get("/api/matches")
async def api_matches(
    organization: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    alert_state: str | None = None,
    review_decision: str | None = None,
    view: str = "active",
    include_demo: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return database.list_matches(
        organization=organization,
        severity=severity,
        source=source,
        alert_state=alert_state,
        review_decision=review_decision,
        view=_normalize_view(view),
        include_demo=include_demo,
        limit=limit,
    )


@app.get("/api/contracts")
async def api_contracts(
    organization: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    alert_state: str | None = None,
    review_decision: str | None = None,
    gate: str = "review_today",
    sort: str = "priority",
    view: str = "active",
    include_demo: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    return database.list_contract_groups(
        organization=organization,
        severity=severity,
        source=source,
        alert_state=alert_state,
        review_decision=review_decision,
        materiality_gate=_normalize_gate(gate, view=_normalize_view(view)),
        sort=_normalize_sort(sort),
        view=_normalize_view(view),
        include_demo=include_demo,
        limit=limit,
    )


@app.get("/api/contracts/{market_id}/public-exposure")
async def get_public_exposure_snapshot(market_id: int) -> dict[str, Any]:
    if database.get_market_record(market_id) is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    exposure = database.latest_public_exposure(market_id)
    if exposure is None:
        raise HTTPException(status_code=404, detail="No public exposure snapshot has been captured")
    return exposure


@app.post("/api/contracts/{market_id}/public-exposure")
async def public_exposure_snapshot(market_id: int) -> dict[str, Any]:
    market = database.get_market_record(market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": f"RaaScal-Watch/{__version__} public-market-research"},
        ) as client:
            exposure = await fetch_public_exposure(
                market,
                client=client,
                polymarket_data_api_url=settings.polymarket_data_api_url,
                kalshi_base_url=settings.kalshi_base_url,
                kalshi_fallback_base_url=settings.kalshi_fallback_base_url,
                holder_limit=settings.public_holder_limit,
                trade_limit=settings.public_trade_limit,
            )
    except PublicExposureError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return database.save_public_exposure_snapshot(market_id, exposure)


@app.get("/field-note/{market_id}", response_class=HTMLResponse)
async def field_note(
    request: Request,
    market_id: int,
    organization: str | None = Query(default=None),
) -> HTMLResponse:
    contract = database.get_contract_bundle(market_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    reviews = contract.get("reviews") or []
    selected = None
    if organization:
        selected = next(
            (item for item in reviews if item.get("organization") == organization),
            None,
        )
    if selected is None and reviews:
        selected = reviews[0]
    if selected is None:
        raise HTTPException(status_code=404, detail="No profile review is available")
    return templates.TemplateResponse(
        request=request,
        name="field_note.html",
        context={
            "contract": contract,
            "review": selected,
            "organizations": [item.get("organization") for item in reviews],
            "generated_at": utcnow().isoformat(),
            "version": __version__,
        },
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


@app.post("/api/matches/{match_id}/feedback")
async def save_match_feedback(
    match_id: int, payload: ReviewFeedbackPayload
) -> dict[str, Any]:
    match = database.get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    if not database.market_is_active_for_match(match_id):
        raise HTTPException(
            status_code=409,
            detail="Archived contracts cannot receive current reviewer feedback.",
        )

    decision = payload.decision.strip().lower()
    if decision not in REVIEW_DECISION_VALUES:
        raise HTTPException(status_code=422, detail="Unsupported reviewer decision")
    guidance_rating = (payload.guidance_rating or "").strip().lower() or None
    if guidance_rating and guidance_rating not in GUIDANCE_RATING_VALUES:
        raise HTTPException(status_code=422, detail="Unsupported guidance rating")

    updated = database.save_review_feedback(
        match_id,
        decision=decision,
        reason_codes=normalize_reason_codes(payload.reason_codes),
        guidance_rating=guidance_rating,
        note=payload.note.strip(),
        corrected_role=payload.corrected_role.strip(),
        suggested_owner=payload.suggested_owner.strip(),
        at=utcnow(),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return {
        "ok": True,
        "match_id": match_id,
        "decision": updated.get("review_decision"),
        "decision_label": REVIEW_DECISION_LABELS.get(
            str(updated.get("review_decision")), "Reviewed"
        ),
        "calibration": database.feedback_summary(view="active"),
    }


@app.get("/api/calibration")
async def calibration(view: str = "active") -> dict[str, Any]:
    return database.feedback_summary(
        view=_normalize_scope_view(view), include_demo=False
    )


@app.get("/api/feedback")
async def feedback_export(
    view: str = "all", limit: int = Query(default=5000, ge=1, le=50000)
) -> list[dict[str, Any]]:
    return database.list_review_feedback(
        view=_normalize_scope_view(view, default="all"),
        include_demo=False,
        limit=limit,
    )


@app.post("/api/matches/{match_id}/acknowledge")
async def acknowledge(match_id: int) -> dict[str, Any]:
    # Retained for API compatibility. Historical records are deliberately not
    # reviewable through either the dashboard or the older row-level endpoint.
    match = database.get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    if not database.market_is_active(int(match["market_id"])):
        raise HTTPException(
            status_code=409,
            detail="Archived contracts cannot be marked as current review work.",
        )
    if not database.acknowledge_match(match_id, utcnow()):
        raise HTTPException(status_code=404, detail="Match not found")
    return {"ok": True, "match_id": match_id}


@app.post("/api/contracts/{market_id}/acknowledge")
async def acknowledge_contract(market_id: int) -> dict[str, Any]:
    changed = database.acknowledge_market(market_id, utcnow())
    if not changed:
        if not database.market_is_active(market_id):
            raise HTTPException(
                status_code=409,
                detail="Archived contracts cannot be marked as current review work.",
            )
        raise HTTPException(status_code=404, detail="Contract not found")
    return {"ok": True, "market_id": market_id, "matches_updated": changed}


@app.get("/health")
async def health() -> dict[str, Any]:
    stats = database.dashboard_stats(include_demo=False, view="active")
    feedback = database.feedback_summary(include_demo=False, view="active")
    materiality = database.list_contract_groups(
        include_demo=False, view="active", materiality_gate="all", limit=1
    )["gate_counts"]
    return {
        "status": "ok",
        "scanner_running": scanner.is_running,
        "last_scan": stats["last_scan"],
        "active_candidate_contracts": stats["matches"],
        "archived_candidate_contracts": stats["archive_matches"],
        "reviewed_profile_matches": feedback["reviewed"],
        "unreviewed_profile_matches": feedback["unreviewed"],
        "contracts_warranting_review_today": materiality["review_today"],
        "contracts_to_escalate": materiality["escalate"],
        "observed_contracts": materiality["observed"],
        "enabled_sources": [collector.name for collector in scanner.collectors],
        "database": str(settings.db_path),
    }
