from __future__ import annotations

"""Extract dynamic contract subjects that are not static watchlist profiles.

The first use case was App Store ranking markets. The second is earnings-call
mention markets, where both the company and the controlled word/phrase change
from contract to contract. Dynamic subjects are descriptive labels only; they
do not create a new organization profile or imply wrongdoing.
"""

import re
from typing import Any, Iterable

from .models import MarketRecord
from .text import parse_jsonish, unique_strings

_APP_STORE_PROFILE_NAMES = {"apple app store", "app store ranking markets"}
_EARNINGS_PROFILE_NAMES = {
    "earnings-call mention markets",
    "corporate-controlled outcomes",
}
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
_GENERIC_EARNINGS_LABELS = {
    "yes",
    "no",
    "other",
    "earnings call",
    "next earnings call",
    "prepared remarks",
    "official transcript",
    "transcript",
    "company",
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


def _clean_company(value: str) -> str | None:
    clean = " ".join(str(value).replace("_", " ").split()).strip(" —–-:;,.?!()[]{}\"'“”")
    clean = re.sub(r"^(?:what\s+will|will)\s+", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"['’]s$", "", clean)
    clean = re.sub(
        r"\s+(?:say|mention|use|discuss|reference)\b.*$",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        r"\s+(?:next\s+)?(?:quarterly\s+)?(?:earnings|investor)\s+(?:call|conference).*$",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = " ".join(clean.split()).strip(" —–-:;,.?!()[]{}\"'“”")
    lowered = clean.casefold()
    if not clean or lowered in _GENERIC_EARNINGS_LABELS:
        return None
    if "earnings call" in lowered or "earnings conference" in lowered:
        return None
    if lowered.startswith(("what ", "which ", "how many ", "during ", "at ")):
        return None
    if any(
        phrase in lowered
        for phrase in (
            "earnings call",
            "earnings conference",
            "prepared remarks",
            "official transcript",
            "resolution source",
        )
    ):
        return None
    if len(clean) < 2 or len(clean) > 80 or clean.isdigit():
        return None
    return clean


def _clean_earnings_outcome(value: str, company: str | None = None) -> str | None:
    clean = " ".join(str(value).replace("_", " ").split()).strip(" —–-:;,.?!()[]{}\"'“”")
    if not clean:
        return None

    # A normalized title may combine the broad event and child contract with an
    # em dash. The child label is the useful controlled outcome.
    title_parts = re.split(r"\s+[—–]\s+", clean)
    if len(title_parts) > 1:
        clean = title_parts[-1].strip()

    # Prefer the exact quoted phrase when one is present.
    quoted = re.search(r"[\"“]([^\"”]{1,100})[\"”]", clean)
    if quoted:
        clean = quoted.group(1)
    else:
        patterns = (
            r"^(?:will\s+)?(?:.+?)\s+(?:say|mention|use|discuss|reference)\s+(.+?)\s+(?:during|on|at|in)\s+(?:its|their|the)?\s*(?:next\s+)?(?:quarterly\s+)?(?:earnings|investor)\s+(?:call|conference).*$",
            r"^(?:will\s+)?(?:.+?)\s+(?:say|mention|use|discuss|reference)\s+(.+)$",
            r"^(?:mentions?|says?)\s*[:\-–—]\s*(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, clean, flags=re.IGNORECASE)
            if match:
                clean = match.group(1)
                break

    clean = re.sub(
        r"\s+(?:during|on|at|in)\s+(?:its|their|the)?\s*(?:next\s+)?(?:quarterly\s+)?(?:earnings|investor)\s+(?:call|conference).*$",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\?$", "", clean).strip(" —–-:;,.?!()[]{}\"'“”")
    if company and clean.casefold() == company.casefold():
        return None
    lowered = clean.casefold()
    if not clean or lowered in _GENERIC_EARNINGS_LABELS:
        return None
    if "earnings call" in lowered or "earnings conference" in lowered:
        return None
    if lowered.startswith(("what will ", "will ", "which ", "earnings call")):
        return None
    if len(clean) < 1 or len(clean) > 100 or clean.isdigit():
        return None
    return clean


def extract_earnings_call_subjects(market: MarketRecord) -> list[str]:
    """Return dynamic company and controlled phrase for earnings-call markets."""

    raw = market.raw or {}
    event = raw.get("event") if isinstance(raw.get("event"), dict) else {}
    market_raw = raw.get("market") if isinstance(raw.get("market"), dict) else {}

    source_texts: list[str] = [market.title, market.description]
    for container in (event, market_raw, raw):
        if not isinstance(container, dict):
            continue
        for key in (
            "title",
            "question",
            "shortTitle",
            "short_title",
            "groupItemTitle",
            "group_item_title",
            "subtitle",
            "yes_sub_title",
            "functional_strike",
        ):
            if container.get(key) is not None:
                source_texts.extend(_flatten_strings(container.get(key)))

    company_candidates: list[str] = []
    company_patterns = (
        r"what\s+will\s+(.+?)\s+say\s+(?:during|on|at)\s+(?:its|their|the)?\s*(?:next\s+)?(?:quarterly\s+)?(?:earnings|investor)\s+(?:call|conference)",
        r"will\s+(.+?)\s+(?:say|mention|use|discuss|reference)\s+.+?\s+(?:during|on|at)\s+(?:its|their|the)?\s*(?:next\s+)?(?:quarterly\s+)?(?:earnings|investor)\s+(?:call|conference)",
        r"(.+?)[’']s\s+(?:next\s+)?(?:quarterly\s+)?(?:earnings|investor)\s+(?:call|conference)",
    )
    for text in source_texts:
        for pattern in company_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                company_candidates.append(match.group(1))

    companies = [company for value in company_candidates if (company := _clean_company(value))]
    companies = unique_strings(companies)
    company = companies[0] if companies else None

    outcome_candidates: list[str] = []
    for container in (market_raw, raw, event):
        if not isinstance(container, dict):
            continue
        for key in (
            "groupItemTitle",
            "group_item_title",
            "yes_sub_title",
            "subtitle",
            "functional_strike",
            "outcome",
            "shortTitle",
            "short_title",
            "question",
        ):
            if container.get(key) is not None:
                outcome_candidates.extend(_flatten_strings(container.get(key)))

    # The specific child contract commonly appears after an em dash.
    title_parts = re.split(r"\s+[—–]\s+", market.title)
    if len(title_parts) > 1:
        outcome_candidates.extend(title_parts[1:])
    outcome_candidates.append(market.title)

    outcomes = [
        outcome
        for value in outcome_candidates
        if (outcome := _clean_earnings_outcome(value, company=company))
    ]
    outcomes = unique_strings(outcomes)

    labeled: list[str] = []
    if company:
        labeled.append(f"Company: {company}")
    for outcome in outcomes:
        # Exclude the broad event title if it slipped through cleanup.
        if company and outcome.casefold() == company.casefold():
            continue
        labeled.append(f"Controlled outcome: {outcome}")
        if len(labeled) >= 5:
            break
    return unique_strings(labeled)[:5]


def extract_dynamic_subjects(
    market: MarketRecord,
    *,
    profile_name: str,
    categories: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """Extract changing subjects for profiles that represent a platform/theme."""

    normalized = profile_name.casefold()
    if normalized in _APP_STORE_PROFILE_NAMES:
        return extract_app_store_subjects(market)
    if normalized in _EARNINGS_PROFILE_NAMES:
        return extract_earnings_call_subjects(market)
    return []
