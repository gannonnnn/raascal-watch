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
