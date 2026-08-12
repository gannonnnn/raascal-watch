from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .text import normalize, parse_datetime, unique_strings

ARCHIVED_STATUSES = frozenset(
    {
        "closed",
        "inactive",
        "resolved",
        "settled",
        "expired",
        "finalized",
        "cancelled",
        "canceled",
    }
)

ACTIVE_STATUSES = frozenset(
    {
        "open",
        "active",
        "unopened",
        "upcoming",
        "pending",
        "trading",
        "unknown",
        "",
    }
)

_DASH_SPLIT_RE = re.compile(r"\s+[—–]\s+")
_ELLIPSIS_RE = re.compile(r"(?:\.{3}|…)+")
_PLACEHOLDER_RE = re.compile(r"_+")


def _as_utc(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return parse_datetime(value)


def is_market_active(
    status: str | None,
    closes_at: datetime | str | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a stored market belongs in the live review queue.

    Source status is used when available, while a past close time always wins.
    The latter matters because active-only APIs may stop returning a market after
    it closes, leaving the last stored source status unchanged.
    """

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    close = _as_utc(closes_at)
    if close is not None and close <= current:
        return False

    clean_status = (status or "").strip().lower()
    if clean_status in ARCHIVED_STATUSES:
        return False

    # Unknown statuses with a future or missing close time are retained because
    # both collectors query active/upcoming source endpoints. They will move to
    # the archive as soon as a closing timestamp passes or a final status arrives.
    return True


def lifecycle_label(
    status: str | None,
    closes_at: datetime | str | None,
    *,
    now: datetime | None = None,
) -> str:
    return "active" if is_market_active(status, closes_at, now=now) else "archive"


def clean_display_title(
    source: str,
    stored_title: str,
    raw: dict[str, Any] | None = None,
) -> str:
    """Return a concise contract title without repeated event/question wording."""

    raw = raw or {}
    source_key = (source or "").strip().lower()

    if source_key == "polymarket":
        market = raw.get("market") if isinstance(raw.get("market"), dict) else {}
        specific = str(market.get("question") or market.get("title") or "").strip()
        if specific:
            return specific

    if source_key == "kalshi":
        parts = unique_strings(
            str(value)
            for value in (
                raw.get("title"),
                raw.get("subtitle"),
                raw.get("yes_sub_title"),
            )
            if value
        )
        if parts:
            return _collapse_title_parts(parts)

    return _collapse_title_parts(_DASH_SPLIT_RE.split(stored_title or ""))


def _comparison_text(value: str) -> str:
    value = _ELLIPSIS_RE.sub(" ", value)
    value = _PLACEHOLDER_RE.sub(" ", value)
    return normalize(value)


def _collapse_title_parts(parts: list[str] | tuple[str, ...]) -> str:
    clean_parts = unique_strings(str(part) for part in parts if str(part).strip())
    if not clean_parts:
        return "Untitled contract"
    if len(clean_parts) == 1:
        return clean_parts[0]

    retained: list[str] = []
    for index, part in enumerate(clean_parts):
        part_cmp = _comparison_text(part)
        if not part_cmp:
            continue
        part_tokens = set(part_cmp.split())
        redundant = False
        for other_index, other in enumerate(clean_parts):
            if index == other_index:
                continue
            other_cmp = _comparison_text(other)
            if not other_cmp:
                continue
            other_tokens = set(other_cmp.split())
            if part_cmp == other_cmp:
                if index < other_index:
                    redundant = True
                    break
            elif len(part_cmp) < len(other_cmp) and other_cmp.startswith(part_cmp):
                redundant = True
                break
            elif (
                len(part_tokens) >= 4
                and len(part_cmp) < len(other_cmp)
                and len(part_tokens & other_tokens) / max(1, len(part_tokens)) >= 0.86
            ):
                redundant = True
                break
        if not redundant:
            retained.append(part)

    if not retained:
        retained = [max(clean_parts, key=len)]
    return " — ".join(retained)


def event_group_identity(
    source: str,
    external_id: str,
    display_title: str,
    raw: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return a stable grouping key and human-readable event/series title."""

    raw = raw or {}
    source_key = (source or "").strip().lower()

    if source_key == "polymarket":
        event = raw.get("event") if isinstance(raw.get("event"), dict) else {}
        event_id = str(event.get("id") or event.get("slug") or "").strip()
        event_title = str(event.get("title") or event.get("question") or "").strip()
        if event_id:
            return f"polymarket:event:{event_id}", event_title or display_title

    if source_key == "kalshi":
        event_id = str(
            raw.get("event_ticker")
            or raw.get("series_ticker")
            or raw.get("eventTicker")
            or ""
        ).strip()
        event_title = str(raw.get("title") or "").strip()
        if event_id:
            return f"kalshi:event:{event_id}", event_title or display_title

    return f"{source_key}:market:{external_id}", display_title


def archive_reason(
    status: str | None,
    closes_at: datetime | str | None,
    *,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(timezone.utc)
    close = _as_utc(closes_at)
    clean_status = (status or "").strip().lower()
    if close is not None and close <= current:
        return "Closing time has passed"
    if clean_status in ARCHIVED_STATUSES:
        return clean_status.replace("_", " ").title()
    return "No longer active"
