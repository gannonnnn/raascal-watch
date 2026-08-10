from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str) -> str | None:
    """Read the current RAASCAL_* setting, with RW_* kept as a legacy alias.

    Early setup instructions used the shorter RW_* prefix. Supporting both avoids
    breaking existing local .env files while keeping RAASCAL_* as the documented
    prefix going forward.
    """
    value = os.getenv(name)
    if value is not None:
        return value
    if name.startswith("RAASCAL_"):
        return os.getenv(f"RW_{name.removeprefix('RAASCAL_')}")
    return None


def _bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int, minimum: int = 1) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _float(name: str, default: float, minimum: float = 0.1) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def _path(name: str, default: Path) -> Path:
    raw = _env(name)
    if not raw:
        return default.resolve()

    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


@dataclass(slots=True, frozen=True)
class Settings:
    db_path: Path
    watchlist_path: Path
    poll_interval_minutes: int
    request_timeout_seconds: float
    max_pages_per_source: int
    alert_on_first_scan: bool
    alert_on_new_match_for_existing_market: bool
    run_scan_on_startup: bool
    enable_kalshi: bool
    enable_polymarket: bool
    kalshi_base_url: str
    kalshi_fallback_base_url: str | None
    kalshi_page_size: int
    kalshi_page_delay_seconds: float
    kalshi_exclude_multivariate: bool
    polymarket_base_url: str
    generic_webhook_url: str | None
    slack_webhook_url: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_from: str | None
    smtp_to: tuple[str, ...]
    smtp_use_tls: bool


def get_settings() -> Settings:
    recipients = tuple(
        item.strip()
        for item in (_env("RAASCAL_SMTP_TO") or "").split(",")
        if item.strip()
    )
    return Settings(
        db_path=_path("RAASCAL_DB_PATH", PROJECT_ROOT / "data" / "raascal_watch.db"),
        watchlist_path=_path(
            "RAASCAL_WATCHLIST_PATH", PROJECT_ROOT / "config" / "watchlist.yaml"
        ),
        poll_interval_minutes=_int("RAASCAL_POLL_INTERVAL_MINUTES", 15),
        request_timeout_seconds=_float("RAASCAL_REQUEST_TIMEOUT_SECONDS", 30.0),
        max_pages_per_source=_int("RAASCAL_MAX_PAGES_PER_SOURCE", 100),
        alert_on_first_scan=_bool("RAASCAL_ALERT_ON_FIRST_SCAN", False),
        alert_on_new_match_for_existing_market=_bool(
            "RAASCAL_ALERT_ON_NEW_MATCH_FOR_EXISTING_MARKET", False
        ),
        run_scan_on_startup=_bool("RAASCAL_RUN_SCAN_ON_STARTUP", True),
        enable_kalshi=_bool("RAASCAL_ENABLE_KALSHI", True),
        enable_polymarket=_bool("RAASCAL_ENABLE_POLYMARKET", True),
        kalshi_base_url=(
            _env("RAASCAL_KALSHI_BASE_URL")
            or "https://external-api.kalshi.com/trade-api/v2"
        ).rstrip("/"),
        kalshi_fallback_base_url=(
            (
                _env("RAASCAL_KALSHI_FALLBACK_BASE_URL")
                or "https://api.elections.kalshi.com/trade-api/v2"
            ).rstrip("/")
            or None
        ),
        kalshi_page_size=min(1000, _int("RAASCAL_KALSHI_PAGE_SIZE", 1000)),
        kalshi_page_delay_seconds=_float(
            "RAASCAL_KALSHI_PAGE_DELAY_SECONDS", 0.15, minimum=0.0
        ),
        kalshi_exclude_multivariate=_bool(
            "RAASCAL_KALSHI_EXCLUDE_MULTIVARIATE", True
        ),
        polymarket_base_url=(
            _env("RAASCAL_POLYMARKET_BASE_URL")
            or "https://gamma-api.polymarket.com"
        ).rstrip("/"),
        generic_webhook_url=_env("RAASCAL_GENERIC_WEBHOOK_URL") or None,
        slack_webhook_url=_env("RAASCAL_SLACK_WEBHOOK_URL") or None,
        smtp_host=_env("RAASCAL_SMTP_HOST") or None,
        smtp_port=_int("RAASCAL_SMTP_PORT", 587),
        smtp_username=_env("RAASCAL_SMTP_USERNAME") or None,
        smtp_password=_env("RAASCAL_SMTP_PASSWORD") or None,
        smtp_from=_env("RAASCAL_SMTP_FROM") or None,
        smtp_to=recipients,
        smtp_use_tls=_bool("RAASCAL_SMTP_USE_TLS", True),
    )
