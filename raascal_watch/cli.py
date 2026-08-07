from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import uvicorn

from .db import Database
from .models import MarketRecord
from .scanner import Scanner
from .settings import PROJECT_ROOT, get_settings
from .text import parse_datetime
from .watchlist import load_watchlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _load_demo_records(path: Path) -> list[MarketRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records: list[MarketRecord] = []
    for item in payload:
        records.append(
            MarketRecord(
                source=str(item.get("source", "demo")),
                external_id=str(item["external_id"]),
                title=str(item["title"]),
                description=str(item.get("description", "")),
                url=str(item.get("url", "")),
                status=str(item.get("status", "open")),
                created_at=parse_datetime(item.get("created_at")),
                closes_at=parse_datetime(item.get("closes_at")),
                probability=item.get("probability"),
                volume=item.get("volume"),
                volume_24h=item.get("volume_24h"),
                liquidity=item.get("liquidity"),
                open_interest=item.get("open_interest"),
                raw=item,
            )
        )
    return records


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str, ensure_ascii=False))


def command_scan(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.db_path)
    scanner = Scanner(settings, database)
    summary = asyncio.run(
        scanner.scan(alert_on_first_scan=True if args.alert_on_first_scan else None)
    )
    _print_json(asdict(summary))
    return 1 if any(item.error for item in summary.sources) else 0


def command_seed_demo(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.db_path)
    scanner = Scanner(settings, database, collectors=[])
    records = _load_demo_records(Path(args.fixture).resolve())
    summary = asyncio.run(scanner.scan_records("demo", records, notify=args.notify))
    _print_json(asdict(summary))
    print("\nDemo data is available in the dashboard.")
    return 0


def command_serve(args: argparse.Namespace) -> int:
    uvicorn.run(
        "raascal_watch.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def command_validate(_: argparse.Namespace) -> int:
    settings = get_settings()
    watchlist = load_watchlist(settings.watchlist_path)
    print(f"Watchlist: {settings.watchlist_path}")
    print("Organizations:")
    for organization in watchlist.organizations:
        print(
            f"  - {organization.name}: {len(organization.identity_terms)} identity terms, "
            f"{len(organization.metrics)} metric terms"
        )
    print("Risk categories:")
    for category in watchlist.categories:
        print(f"  - {category.name}: +{category.weight} ({len(category.terms)} terms)")
    return 0


def command_reset_baseline(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()
    changed = database.reset_source_state(args.source)
    print(f"Reset baseline state for {changed} source(s).")
    return 0


def command_export(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()
    rows = database.list_matches(limit=1000)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        output.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        fields = [
            "match_id",
            "organization",
            "severity",
            "risk_score",
            "source",
            "external_id",
            "title",
            "url",
            "probability",
            "volume",
            "closes_at",
            "alert_state",
            "matched_identity_terms",
            "matched_metric_terms",
            "categories",
            "stakeholders",
            "reasons",
            "actions",
        ]
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                clean = {
                    field: (
                        " | ".join(str(item) for item in row.get(field, []))
                        if isinstance(row.get(field), list)
                        else row.get(field)
                    )
                    for field in fields
                }
                writer.writerow(clean)
    print(f"Exported {len(rows)} matches to {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="raascal-watch",
        description="Monitor public prediction markets for references to watched companies and metrics.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Run one live Kalshi and Polymarket scan")
    scan.add_argument(
        "--alert-on-first-scan",
        action="store_true",
        help="Notify on existing contracts instead of creating a silent baseline",
    )
    scan.set_defaults(func=command_scan)

    serve = subparsers.add_parser("serve", help="Start the local dashboard and scheduler")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=command_serve)

    demo = subparsers.add_parser("seed-demo", help="Load offline demo contracts")
    demo.add_argument(
        "--fixture",
        default=str(PROJECT_ROOT / "fixtures" / "demo_markets.json"),
    )
    demo.add_argument(
        "--notify",
        action="store_true",
        help="Send configured notifications for the demo records",
    )
    demo.set_defaults(func=command_seed_demo)

    validate = subparsers.add_parser("validate-config", help="Validate the YAML watchlist")
    validate.set_defaults(func=command_validate)

    reset = subparsers.add_parser(
        "reset-baseline",
        help="Make the next successful scan a silent baseline again",
    )
    reset.add_argument("--source", choices=["kalshi", "polymarket", "demo"])
    reset.set_defaults(func=command_reset_baseline)

    export = subparsers.add_parser("export", help="Export dashboard matches")
    export.add_argument("--format", choices=["csv", "json"], default="csv")
    export.add_argument("--output", required=True)
    export.set_defaults(func=command_export)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
