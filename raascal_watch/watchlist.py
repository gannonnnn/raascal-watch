from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import OrganizationWatch, RiskCategory, Watchlist


class WatchlistError(ValueError):
    pass


def _tuple_of_strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise WatchlistError(f"'{field_name}' must be a YAML list")
    return tuple(str(item).strip() for item in value if str(item).strip())


def load_watchlist(path: Path) -> Watchlist:
    if not path.exists():
        raise WatchlistError(f"Watchlist file not found: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise WatchlistError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise WatchlistError("Watchlist root must be a YAML object")

    organizations: list[OrganizationWatch] = []
    for index, item in enumerate(payload.get("organizations", []), start=1):
        if not isinstance(item, dict):
            raise WatchlistError(f"Organization #{index} must be an object")
        name = str(item.get("name", "")).strip()
        if not name:
            raise WatchlistError(f"Organization #{index} is missing 'name'")
        aliases = _tuple_of_strings(item.get("aliases"), f"{name}.aliases")
        if not aliases:
            aliases = (name,)
        organization = OrganizationWatch(
            name=name,
            aliases=aliases,
            products=_tuple_of_strings(item.get("products"), f"{name}.products"),
            executives=_tuple_of_strings(item.get("executives"), f"{name}.executives"),
            metrics=_tuple_of_strings(item.get("metrics"), f"{name}.metrics"),
            stakeholders=_tuple_of_strings(
                item.get("stakeholders"), f"{name}.stakeholders"
            ),
            playbook=_tuple_of_strings(item.get("playbook"), f"{name}.playbook"),
            enabled=bool(item.get("enabled", True)),
        )
        if organization.enabled:
            organizations.append(organization)

    categories: list[RiskCategory] = []
    category_payload = payload.get("risk_categories", {})
    if not isinstance(category_payload, dict):
        raise WatchlistError("'risk_categories' must be a YAML object")
    for name, item in category_payload.items():
        if not isinstance(item, dict):
            raise WatchlistError(f"Risk category '{name}' must be an object")
        categories.append(
            RiskCategory(
                name=str(name),
                weight=int(item.get("weight", 0)),
                terms=_tuple_of_strings(item.get("terms"), f"{name}.terms"),
                stakeholders=_tuple_of_strings(
                    item.get("stakeholders"), f"{name}.stakeholders"
                ),
                actions=_tuple_of_strings(item.get("actions"), f"{name}.actions"),
            )
        )

    if not organizations:
        raise WatchlistError("No enabled organizations are configured")
    return Watchlist(tuple(organizations), tuple(categories))
