from __future__ import annotations

from raascal_watch.settings import get_settings


def test_legacy_rw_environment_prefix_is_supported(monkeypatch) -> None:
    monkeypatch.delenv("RAASCAL_RUN_SCAN_ON_STARTUP", raising=False)
    monkeypatch.delenv("RAASCAL_MAX_PAGES_PER_SOURCE", raising=False)
    monkeypatch.setenv("RW_RUN_SCAN_ON_STARTUP", "false")
    monkeypatch.setenv("RW_MAX_PAGES_PER_SOURCE", "5")

    settings = get_settings()

    assert settings.run_scan_on_startup is False
    assert settings.max_pages_per_source == 5


def test_kalshi_supported_fallback_host_is_configured(monkeypatch) -> None:
    monkeypatch.delenv("RAASCAL_KALSHI_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("RW_KALSHI_FALLBACK_BASE_URL", raising=False)

    settings = get_settings()

    assert settings.kalshi_fallback_base_url == (
        "https://api.elections.kalshi.com/trade-api/v2"
    )
    assert settings.kalshi_page_size == 1000
    assert settings.kalshi_exclude_multivariate is True
