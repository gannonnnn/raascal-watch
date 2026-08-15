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
from .profile_sync import sync_profiles
from .risk import RiskEngine
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
    print(
        "\nSynthetic demo data was loaded for developer testing. "
        "The standard dashboard hides it; open "
        "http://127.0.0.1:8000/?source=demo&include_demo=true to view it."
    )
    return 0


def command_purge_demo(_: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()
    removed = database.delete_source("demo")
    print(
        "Removed synthetic demo data: "
        f"{removed['markets']} market record(s), "
        f"{removed['matches']} match(es), and "
        f"{removed['scan_runs']} scan run(s)."
    )
    return 0


def command_refresh_guidance(_: argparse.Namespace) -> int:
    """Regenerate role-aware review briefs from records already in SQLite."""
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()
    engine = RiskEngine(load_watchlist(settings.watchlist_path))

    markets = database.list_matched_markets(include_demo=False)
    refreshed = 0
    skipped = 0
    for market_id, market, existing_organizations in markets:
        current = {result.organization: result for result in engine.match(market)}
        for organization in existing_organizations:
            result = current.get(organization)
            if result is None:
                skipped += 1
                continue
            if database.update_match_analysis(market_id, result):
                refreshed += 1

    print(
        f"Refreshed contract-specific guidance for {refreshed} existing match(es). "
        f"Skipped {skipped} stale match(es) that no longer fit the current watchlist."
    )
    return 0



def command_sync_profiles(args: argparse.Namespace) -> int:
    """Merge shipped profiles and rematch the stored market library."""
    settings = get_settings()
    database = Database(settings.db_path)
    defaults_path = Path(args.defaults).expanduser().resolve()
    summary = sync_profiles(
        database,
        settings.watchlist_path,
        defaults_path,
        force_rebuild=bool(args.force),
    )

    merge = summary.merge
    if merge.changed:
        if merge.added_organizations:
            print("Added monitoring profile(s): " + ", ".join(merge.added_organizations))
        if merge.updated_organizations:
            print("Expanded monitoring profile(s): " + ", ".join(merge.updated_organizations))
        if merge.added_categories:
            print("Added risk category profile(s): " + ", ".join(merge.added_categories))
        if merge.updated_categories:
            print("Expanded risk category profile(s): " + ", ".join(merge.updated_categories))
        if merge.backup_path:
            print(f"Watchlist backup: {merge.backup_path}")
    else:
        print("Built-in monitoring profiles are already synchronized.")

    if summary.rebuild is None:
        print("Stored markets already reflect the current watchlist; rematch skipped.")
        return 0

    rebuild = summary.rebuild
    print(
        "Re-evaluated stored markets: "
        f"{rebuild.matches_added} new profile match(es), "
        f"{rebuild.matches_refreshed} existing match(es) refreshed."
    )
    print("Profile coverage discovered during re-indexing:")
    for organization, counts in rebuild.by_organization.items():
        print(
            f"  - {organization}: {counts['candidates']} candidate record(s), "
            f"{counts['added']} added "
            f"({counts['active_added']} active / {counts['archived_added']} archived), "
            f"{counts['refreshed']} refreshed"
        )
    return 0


def command_lifecycle_summary(_: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()
    active = database.dashboard_stats(include_demo=False, view="active")
    archive = database.dashboard_stats(include_demo=False, view="archive")
    print(
        "Contract lifecycle: "
        f"{active['matches']} active candidate contract(s); "
        f"{archive['matches']} archived candidate contract(s)."
    )
    return 0

def command_calibration_summary(_: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()
    summary = database.feedback_summary(view="active", include_demo=False)
    counts = summary["decision_counts"]
    print(
        "Reviewer calibration: "
        f"{summary['reviewed']} structured review(s), "
        f"{summary['legacy_reviewed']} legacy review(s), "
        f"{summary['unreviewed']} unreviewed profile match(es)."
    )
    print(
        "  Decisions: "
        f"{counts['actionable']} actionable, "
        f"{counts['monitor']} monitor, "
        f"{counts['informational']} informational, "
        f"{counts['false_positive']} false positive."
    )
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
    print("Organizations and themes:")
    for organization in watchlist.organizations:
        print(
            f"  - {organization.name} [{organization.profile_type}]: "
            f"{len(organization.identity_terms)} identity/theme terms, "
            f"{len(organization.metrics)} metric terms, "
            f"{len(organization.dependency_rules)} dependency rule(s)"
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
    rows = database.list_matches(
        limit=1000, include_demo=args.include_demo, view=args.view
    )
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
            "match_basis",
            "source",
            "external_id",
            "title",
            "url",
            "probability",
            "volume",
            "closes_at",
            "alert_state",
            "review_decision",
            "review_reason_codes",
            "guidance_rating",
            "review_note",
            "corrected_role",
            "suggested_owner",
            "feedback_updated_at",
            "matched_identity_terms",
            "matched_metric_terms",
            "categories",
            "roles",
            "review_questions",
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


def command_export_feedback(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.db_path)
    database.initialize()
    rows = database.list_review_feedback(view=args.view, limit=50000)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        output.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        fields = [
            "match_id",
            "market_id",
            "organization",
            "decision",
            "reason_codes",
            "guidance_rating",
            "note",
            "corrected_role",
            "suggested_owner",
            "risk_score",
            "severity",
            "match_basis",
            "categories",
            "source",
            "external_id",
            "title",
            "url",
            "closes_at",
            "created_at",
            "updated_at",
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
    print(f"Exported {len(rows)} structured review(s) to {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="raascal-watch",
        description="Monitor public prediction markets for watched organizations, themes, and dependencies.",
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

    demo = subparsers.add_parser(
        "seed-demo",
        help="Load synthetic contracts for explicit developer testing",
    )
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

    purge_demo = subparsers.add_parser(
        "purge-demo",
        help="Remove all synthetic demo records without touching live history",
    )
    purge_demo.set_defaults(func=command_purge_demo)

    refresh_guidance = subparsers.add_parser(
        "refresh-guidance",
        help="Regenerate contract-specific review guidance from existing live records",
    )
    refresh_guidance.set_defaults(func=command_refresh_guidance)

    sync_profiles_parser = subparsers.add_parser(
        "sync-profiles",
        help="Merge shipped monitoring profiles and rematch stored markets",
    )
    sync_profiles_parser.add_argument(
        "--defaults",
        default=str(PROJECT_ROOT / "config" / "watchlist.defaults.yaml"),
        help="Path to the shipped profile template",
    )
    sync_profiles_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-evaluate stored markets even when the watchlist has not changed",
    )
    sync_profiles_parser.set_defaults(func=command_sync_profiles)

    lifecycle = subparsers.add_parser(
        "lifecycle-summary",
        help="Show active and archived candidate-contract counts",
    )
    lifecycle.set_defaults(func=command_lifecycle_summary)

    calibration = subparsers.add_parser(
        "calibration-summary",
        help="Show structured-review and unreviewed profile-match counts",
    )
    calibration.set_defaults(func=command_calibration_summary)

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
    export.add_argument(
        "--view",
        choices=["active", "archive", "all"],
        default="active",
        help="Export active contracts by default; archive/all must be requested explicitly",
    )
    export.add_argument(
        "--include-demo",
        action="store_true",
        help="Include explicitly seeded synthetic demo matches",
    )
    export.set_defaults(func=command_export)

    feedback_export = subparsers.add_parser(
        "export-feedback",
        help="Export structured reviewer decisions for calibration",
    )
    feedback_export.add_argument("--format", choices=["csv", "json"], default="csv")
    feedback_export.add_argument("--output", required=True)
    feedback_export.add_argument(
        "--view",
        choices=["active", "archive", "all"],
        default="all",
        help="Export all structured reviews by default",
    )
    feedback_export.set_defaults(func=command_export_feedback)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
