from __future__ import annotations

"""Extract dynamic contract subjects that are not static watchlist profiles.

The first use case is App Store ranking markets. The Apple App Store can be the
metric owner and settlement source while the company/app being ranked changes
with every market. Dynamic subjects are descriptive labels only; they do not
create a new organization profile or imply wrongdoing.
"""

import re
from typing import Any, Iterable

from .models import MarketRecord
from .text import parse_jsonish, unique_strings

_APP_STORE_PROFILE_NAMES = {"apple app store", "app store ranking markets"}
_GENERIC_APP_LABELS = {
    "yes",
    "no",
    "other",
    "any other app",
    "top app",
    "top free app",
    "top paid app",
    "top us iphone app",
    "iphone app",
    "app store",
    "apple app store",
}


def _flatten_strings(value: Any) -> Iterable[str]:
    if value is None:
        return ()
    parsed = parse_jsonish(value)
    if isinstance(parsed, str):
        return (parsed,)
    if isinstance(parsed, dict):
        output: list[str] = []
        for key, item in parsed.items():
            if isinstance(key, str):
                output.append(key)
            output.extend(_flatten_strings(item))
        return output
    if isinstance(parsed, (list, tuple, set)):
        output = []
        for item in parsed:
            output.extend(_flatten_strings(item))
        return output
    return (str(parsed),)


def _clean_candidate(value: str) -> str | None:
    clean = " ".join(str(value).replace("_", " ").split()).strip(" —–-:;,.?!()[]{}\"'")
    if not clean:
        return None

    # Remove common binary-market wrappers while preserving the app name.
    patterns = (
        r"^will\s+(.+?)\s+(?:be|become|rank|reach|finish)\s+(?:the\s+)?(?:#?1|number one|top|highest).*$",
        r"^(.+?)\s+(?:to be|as)\s+(?:the\s+)?(?:#?1|number one|top|highest).*$",
        r"^(?:top|highest ranked)\s+app\s*[:\-–—]\s*(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, clean, flags=re.IGNORECASE)
        if match:
            clean = " ".join(match.group(1).split()).strip(" —–-:;,.?!()[]{}\"'")
            break

    lowered = clean.casefold()
    if lowered in _GENERIC_APP_LABELS:
        return None
    if lowered.startswith(("will ", "what ", "which ", "top us iphone app", "top app")):
        return None
    if any(
        phrase in lowered
        for phrase in (
            "top free apps",
            "top paid apps",
            "apple app store website",
            "outcome verified",
            "resolution source",
        )
    ):
        return None
    if len(clean) < 2 or len(clean) > 80:
        return None
    if clean.isdigit():
        return None
    return clean


def extract_app_store_subjects(market: MarketRecord) -> list[str]:
    """Return likely app/company outcomes for an App Store ranking contract."""

    raw = market.raw or {}
    candidates: list[str] = []

    if market.source == "kalshi":
        for key in (
            "yes_sub_title",
            "subtitle",
            "functional_strike",
            "primary_participant_key",
        ):
            value = raw.get(key)
            if value:
                candidates.extend(_flatten_strings(value))
        custom_strike = raw.get("custom_strike")
        if isinstance(custom_strike, dict):
            candidates.extend(_flatten_strings(custom_strike))
    elif market.source == "polymarket":
        event = raw.get("event") if isinstance(raw.get("event"), dict) else {}
        market_raw = raw.get("market") if isinstance(raw.get("market"), dict) else {}
        for container in (market_raw, event):
            for key in (
                "groupItemTitle",
                "group_item_title",
                "outcome",
                "outcomes",
                "shortTitle",
                "short_title",
            ):
                if container.get(key) is not None:
                    candidates.extend(_flatten_strings(container.get(key)))

    # Kalshi commonly stores the changing app outcome after an em dash.
    title_parts = re.split(r"\s+[—–]\s+", market.title)
    if len(title_parts) > 1:
        candidates.extend(title_parts[1:])

    # Generic title patterns used by both sources.
    regexes = (
        r"will\s+(.+?)\s+(?:be|become|rank|finish)\s+(?:the\s+)?(?:#?1|number one|top|highest)[^?]*app",
        r"(?:top|highest ranked)\s+(?:us\s+)?iphone app[^:—–-]*[:—–-]\s*([^?]+)",
        r"which app[^?]*\?\s*[—–-]\s*(.+)$",
    )
    for pattern in regexes:
        match = re.search(pattern, market.title, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group(1))

    cleaned = [candidate for value in candidates if (candidate := _clean_candidate(value))]
    return unique_strings(cleaned)[:8]


def extract_dynamic_subjects(
    market: MarketRecord,
    *,
    profile_name: str,
    categories: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """Extract changing subjects for profiles that represent a platform/theme."""

    if profile_name.casefold() in _APP_STORE_PROFILE_NAMES:
        return extract_app_store_subjects(market)
    return []
