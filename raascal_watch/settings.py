from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _float(name: str, default: float, minimum: float = 0.1) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def _path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
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
        for item in os.getenv("RW_SMTP_TO", "").split(",")
        if item.strip()
    )
    return Settings(
        db_path=_path("RW_DB_PATH", PROJECT_ROOT / "data" / "raascal_watch.db"),
        watchlist_path=_path("RW_WATCHLIST_PATH", PROJECT_ROOT / "config" / "watchlist.yaml"),
        poll_interval_minutes=_int("RW_POLL_INTERVAL_MINUTES", 15),
        request_timeout_seconds=_float("RW_REQUEST_TIMEOUT_SECONDS", 30.0),
        max_pages_per_source=_int("RW_MAX_PAGES_PER_SOURCE", 100),
        alert_on_first_scan=_bool("RW_ALERT_ON_FIRST_SCAN", False),
        alert_on_new_match_for_existing_market=_bool(
            "RW_ALERT_ON_NEW_MATCH_FOR_EXISTING_MARKET", False
        ),
        run_scan_on_startup=_bool("RW_RUN_SCAN_ON_STARTUP", True),
        enable_kalshi=_bool("RW_ENABLE_KALSHI", True),
        enable_polymarket=_bool("RW_ENABLE_POLYMARKET", True),
        kalshi_base_url=os.getenv(
            "RW_KALSHI_BASE_URL", "https://external-api.kalshi.com/trade-api/v2"
        ).rstrip("/"),
        polymarket_base_url=os.getenv(
            "RW_POLYMARKET_BASE_URL", "https://gamma-api.polymarket.com"
        ).rstrip("/"),
        generic_webhook_url=os.getenv("RW_GENERIC_WEBHOOK_URL") or None,
        slack_webhook_url=os.getenv("RW_SLACK_WEBHOOK_URL") or None,
        smtp_host=os.getenv("RW_SMTP_HOST") or None,
        smtp_port=_int("RW_SMTP_PORT", 587),
        smtp_username=os.getenv("RW_SMTP_USERNAME") or None,
        smtp_password=os.getenv("RW_SMTP_PASSWORD") or None,
        smtp_from=os.getenv("RW_SMTP_FROM") or None,
        smtp_to=recipients,
        smtp_use_tls=_bool("RW_SMTP_USE_TLS", True),
    )
