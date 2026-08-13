from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .db import Database
from .models import OrganizationWatch, Watchlist
from .risk import RiskEngine
from .text import utcnow
from .watchlist import load_watchlist

_LIST_FIELDS = (
    "aliases",
    "products",
    "executives",
    "metrics",
    "stakeholders",
    "playbook",
)
_CATEGORY_LIST_FIELDS = ("terms", "stakeholders", "actions")
_SCALAR_PROFILE_FIELDS = ("profile_type",)
_MAPPING_LIST_FIELDS = ("dependency_rules",)


@dataclass(slots=True)
class WatchlistMergeSummary:
    changed: bool = False
    added_organizations: list[str] = field(default_factory=list)
    updated_organizations: list[str] = field(default_factory=list)
    added_categories: list[str] = field(default_factory=list)
    updated_categories: list[str] = field(default_factory=list)
    backup_path: Path | None = None


@dataclass(slots=True)
class MatchRebuildSummary:
    organizations_processed: int = 0
    candidate_markets: int = 0
    matches_added: int = 0
    matches_refreshed: int = 0
    active_matches_added: int = 0
    archived_matches_added: int = 0
    by_organization: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass(slots=True)
class ProfileSyncSummary:
    merge: WatchlistMergeSummary
    rebuild: MatchRebuildSummary | None
    fingerprint_changed: bool
    fingerprint: str


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML object in {path}")
    return payload


def _list_values(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [str(value).strip()] if str(value).strip() else []
    output: list[str] = []
    for item in value:
        clean = str(item).strip()
        if clean and clean not in output:
            output.append(clean)
    return output


def _merge_list(existing: Any, defaults: Any) -> tuple[list[str], bool]:
    current = _list_values(existing)
    changed = False
    seen = {item.casefold() for item in current}
    for item in _list_values(defaults):
        if item.casefold() in seen:
            continue
        current.append(item)
        seen.add(item.casefold())
        changed = True
    return current, changed


def _mapping_identity(value: dict[str, Any]) -> str:
    name = str(value.get("name", "")).strip()
    if name:
        return name.casefold()
    return repr(sorted(value.items())).casefold()


def _merge_mapping_list(existing: Any, defaults: Any) -> tuple[list[dict[str, Any]], bool]:
    current = [dict(item) for item in existing or [] if isinstance(item, dict)]
    changed = False
    by_key = {_mapping_identity(item): item for item in current}
    for default_item in defaults or []:
        if not isinstance(default_item, dict):
            continue
        key = _mapping_identity(default_item)
        found = by_key.get(key)
        if found is None:
            copied = dict(default_item)
            current.append(copied)
            by_key[key] = copied
            changed = True
            continue
        for field_name, default_value in default_item.items():
            if isinstance(default_value, list):
                merged, field_changed = _merge_list(found.get(field_name), default_value)
                if field_changed or field_name not in found:
                    found[field_name] = merged
                    changed = True
            elif field_name not in found:
                found[field_name] = default_value
                changed = True
    return current, changed


def _safe_backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")


def merge_watchlist(
    current_path: Path,
    defaults_path: Path,
    *,
    create_backup: bool = True,
) -> WatchlistMergeSummary:
    """Merge missing built-in profiles and terms without deleting user additions.

    Existing organizations keep their explicit ``enabled`` setting and any custom
    aliases, metrics, stakeholders, or playbook steps. New built-in values are
    appended, and custom organizations/categories remain untouched.
    """

    defaults = _load_mapping(defaults_path)
    if not current_path.exists():
        current_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(defaults_path, current_path)
        added = [
            str(item.get("name", "")).strip()
            for item in defaults.get("organizations", [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        return WatchlistMergeSummary(changed=True, added_organizations=added)

    current = _load_mapping(current_path)
    summary = WatchlistMergeSummary()

    try:
        current_version = int(current.get("version", 0) or 0)
    except (TypeError, ValueError):
        current_version = 0
    try:
        default_version = int(defaults.get("version", 0) or 0)
    except (TypeError, ValueError):
        default_version = 0
    if default_version > current_version:
        current["version"] = default_version
        summary.changed = True

    current_orgs = current.setdefault("organizations", [])
    if not isinstance(current_orgs, list):
        raise ValueError("Current watchlist 'organizations' must be a list")
    default_orgs = defaults.get("organizations", [])
    if not isinstance(default_orgs, list):
        raise ValueError("Default watchlist 'organizations' must be a list")

    by_name: dict[str, dict[str, Any]] = {}
    for item in current_orgs:
        if isinstance(item, dict) and str(item.get("name", "")).strip():
            by_name[str(item["name"]).strip().casefold()] = item

    for default_org in default_orgs:
        if not isinstance(default_org, dict):
            continue
        name = str(default_org.get("name", "")).strip()
        if not name:
            continue
        key = name.casefold()
        existing = by_name.get(key)
        if existing is None:
            current_orgs.append(default_org)
            by_name[key] = default_org
            summary.added_organizations.append(name)
            summary.changed = True
            continue

        org_changed = False
        for field_name in _LIST_FIELDS:
            merged, field_changed = _merge_list(
                existing.get(field_name), default_org.get(field_name)
            )
            if field_changed or field_name not in existing:
                existing[field_name] = merged
                org_changed = True

        for field_name in _SCALAR_PROFILE_FIELDS:
            if field_name not in existing and field_name in default_org:
                existing[field_name] = default_org[field_name]
                org_changed = True

        for field_name in _MAPPING_LIST_FIELDS:
            merged, field_changed = _merge_mapping_list(
                existing.get(field_name), default_org.get(field_name)
            )
            if field_changed or (field_name not in existing and merged):
                existing[field_name] = merged
                org_changed = True

        # Preserve an explicit user choice to disable a profile. If the key was
        # absent in an older file, inherit the current built-in default.
        if "enabled" not in existing and "enabled" in default_org:
            existing["enabled"] = bool(default_org.get("enabled", True))
            org_changed = True

        if org_changed:
            summary.updated_organizations.append(name)
            summary.changed = True

    current_categories = current.setdefault("risk_categories", {})
    if not isinstance(current_categories, dict):
        raise ValueError("Current watchlist 'risk_categories' must be a YAML object")
    default_categories = defaults.get("risk_categories", {})
    if not isinstance(default_categories, dict):
        raise ValueError("Default watchlist 'risk_categories' must be a YAML object")

    for name, default_category in default_categories.items():
        if not isinstance(default_category, dict):
            continue
        existing = current_categories.get(name)
        if not isinstance(existing, dict):
            current_categories[name] = default_category
            summary.added_categories.append(str(name))
            summary.changed = True
            continue

        category_changed = False
        if "weight" not in existing and "weight" in default_category:
            existing["weight"] = default_category["weight"]
            category_changed = True
        for field_name in _CATEGORY_LIST_FIELDS:
            merged, field_changed = _merge_list(
                existing.get(field_name), default_category.get(field_name)
            )
            if field_changed or field_name not in existing:
                existing[field_name] = merged
                category_changed = True
        if category_changed:
            summary.updated_categories.append(str(name))
            summary.changed = True

    if summary.changed:
        if create_backup:
            backup = _safe_backup_path(current_path)
            shutil.copy2(current_path, backup)
            summary.backup_path = backup
        current_path.write_text(
            yaml.safe_dump(
                current,
                sort_keys=False,
                allow_unicode=True,
                width=1000,
            ),
            encoding="utf-8",
        )

    return summary


def watchlist_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _single_organization_watchlist(
    organization: OrganizationWatch,
    watchlist: Watchlist,
) -> Watchlist:
    return Watchlist((organization,), watchlist.categories)


def rebuild_matches(
    database: Database,
    watchlist: Watchlist,
    *,
    organizations: Iterable[str] | None = None,
) -> MatchRebuildSummary:
    """Re-evaluate stored markets so newly added profiles receive matches.

    This is intentionally alert-silent. A newly discovered match on an already
    stored contract is marked ``historical`` so it can enter the active review
    queue without being misrepresented as a newly created market alert.
    """

    selected = {item.casefold() for item in organizations or ()}
    summary = MatchRebuildSummary()
    now = utcnow()

    for organization in watchlist.organizations:
        if selected and organization.name.casefold() not in selected:
            continue
        summary.organizations_processed += 1
        engine = RiskEngine(_single_organization_watchlist(organization, watchlist))
        candidates = database.list_markets_matching_terms(
            organization.candidate_terms,
            external_id_prefixes=organization.candidate_prefixes,
            include_demo=False,
        )
        org_counts = {
            "candidates": len(candidates),
            "added": 0,
            "refreshed": 0,
            "active_added": 0,
            "archived_added": 0,
        }
        summary.candidate_markets += len(candidates)

        for market_id, market in candidates:
            results = engine.match(market)
            if not results:
                continue
            result = results[0]
            if database.update_match_analysis(market_id, result):
                summary.matches_refreshed += 1
                org_counts["refreshed"] += 1
                continue

            _, created = database.upsert_match(
                market_id,
                result,
                now,
                initial_alert_state="historical",
            )
            if not created:
                continue
            summary.matches_added += 1
            org_counts["added"] += 1
            if database.market_is_active(market_id):
                summary.active_matches_added += 1
                org_counts["active_added"] += 1
            else:
                summary.archived_matches_added += 1
                org_counts["archived_added"] += 1

        summary.by_organization[organization.name] = org_counts

    return summary


def sync_profiles(
    database: Database,
    current_watchlist_path: Path,
    defaults_path: Path,
    *,
    force_rebuild: bool = False,
) -> ProfileSyncSummary:
    database.initialize()
    merge = merge_watchlist(current_watchlist_path, defaults_path)
    fingerprint = watchlist_fingerprint(current_watchlist_path)
    previous = database.get_meta("watchlist_fingerprint")
    changed = force_rebuild or merge.changed or previous != fingerprint

    rebuild: MatchRebuildSummary | None = None
    if changed:
        watchlist = load_watchlist(current_watchlist_path)
        rebuild = rebuild_matches(database, watchlist)
        database.set_meta("watchlist_fingerprint", fingerprint)

    return ProfileSyncSummary(
        merge=merge,
        rebuild=rebuild,
        fingerprint_changed=changed,
        fingerprint=fingerprint,
    )
