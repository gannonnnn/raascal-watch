from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .market_view import (
    ARCHIVED_STATUSES,
    archive_reason,
    clean_display_title,
    event_group_identity,
)
from .materiality import GATE_RANK, aggregate_materiality, apply_market_movement
from .models import MarketRecord, MatchResult, ScanSourceSummary
from .review import normalize_reason_codes
from .text import isoformat, parse_datetime, utcnow


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _market_scope_clause(view: str, alias: str = "m") -> tuple[str, list[Any]]:
    """Return SQL and parameters for active/archive/all market lifecycle views."""

    normalized = (view or "active").strip().lower()
    if normalized not in {"active", "archive", "all"}:
        raise ValueError(f"Unsupported market view: {view}")
    if normalized == "all":
        return "1 = 1", []

    statuses = ", ".join("?" for _ in ARCHIVED_STATUSES)
    status_values = sorted(ARCHIVED_STATUSES)
    now = isoformat(utcnow())
    archived = (
        f"(LOWER(COALESCE({alias}.status, '')) IN ({statuses}) "
        f"OR ({alias}.closes_at IS NOT NULL AND {alias}.closes_at <= ?))"
    )
    active = (
        f"(LOWER(COALESCE({alias}.status, '')) NOT IN ({statuses}) "
        f"AND ({alias}.closes_at IS NULL OR {alias}.closes_at > ?))"
    )
    params: list[Any] = [*status_values, now]
    if normalized == "archive":
        return archived, params
    return active, params


SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unknown',
    source_created_at TEXT,
    closes_at TEXT,
    probability REAL,
    volume REAL,
    volume_24h REAL,
    liquidity REAL,
    open_interest REAL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_markets_source_seen
    ON markets(source, first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_markets_close
    ON markets(closes_at);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    organization TEXT NOT NULL,
    matched_identity_terms_json TEXT NOT NULL DEFAULT '[]',
    matched_metric_terms_json TEXT NOT NULL DEFAULT '[]',
    categories_json TEXT NOT NULL DEFAULT '[]',
    risk_score INTEGER NOT NULL,
    severity TEXT NOT NULL,
    match_basis TEXT NOT NULL DEFAULT 'direct',
    roles_json TEXT NOT NULL DEFAULT '[]',
    reasons_json TEXT NOT NULL DEFAULT '[]',
    review_questions_json TEXT NOT NULL DEFAULT '[]',
    stakeholders_json TEXT NOT NULL DEFAULT '[]',
    actions_json TEXT NOT NULL DEFAULT '[]',
    incentive_map_json TEXT NOT NULL DEFAULT '{}',
    risk_breakdown_json TEXT NOT NULL DEFAULT '{}',
    materiality_json TEXT NOT NULL DEFAULT '{}',
    dynamic_subjects_json TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    alert_state TEXT NOT NULL DEFAULT 'new',
    notified_at TEXT,
    acknowledged_at TEXT,
    UNIQUE(market_id, organization)
);

CREATE INDEX IF NOT EXISTS idx_matches_severity
    ON matches(severity, risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_matches_state
    ON matches(alert_state, first_seen_at DESC);

CREATE TABLE IF NOT EXISTS review_feedback (
    match_id INTEGER PRIMARY KEY REFERENCES matches(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    guidance_rating TEXT,
    note TEXT NOT NULL DEFAULT '',
    corrected_role TEXT NOT NULL DEFAULT '',
    suggested_owner TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_feedback_decision
    ON review_feedback(decision, updated_at DESC);


CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    captured_at TEXT NOT NULL,
    probability REAL,
    volume REAL,
    volume_24h REAL,
    liquidity REAL,
    open_interest REAL,
    status TEXT NOT NULL DEFAULT 'unknown',
    closes_at TEXT,
    rules_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_market_time
    ON market_snapshots(market_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS public_exposure_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL,
    visibility TEXT NOT NULL,
    condition_id TEXT,
    open_interest REAL,
    holder_groups_json TEXT NOT NULL DEFAULT '[]',
    detail TEXT NOT NULL DEFAULT '',
    caveat TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_public_exposure_market_time
    ON public_exposure_snapshots(market_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS source_state (
    source TEXT PRIMARY KEY,
    initialized_at TEXT,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    fetched INTEGER NOT NULL DEFAULT 0,
    pages INTEGER NOT NULL DEFAULT 0,
    new_markets INTEGER NOT NULL DEFAULT 0,
    matches INTEGER NOT NULL DEFAULT 0,
    new_matches INTEGER NOT NULL DEFAULT 0,
    notifications INTEGER NOT NULL DEFAULT 0,
    baseline_suppressed INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_scan_runs_started
    ON scan_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _market_rules_hash(title: str, description: str) -> str:
    payload = f"{title.strip()}\n{description.strip()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._transactions = threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # A scan batch reuses its connection on this worker thread only. Web
        # requests and other workers always get independent SQLite connections.
        shared = getattr(self._transactions, "connection", None)
        if shared is not None:
            yield shared
            return
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def write_batch(self) -> Iterator[sqlite3.Connection]:
        """Atomic, bounded scan write; never share a connection between threads.

        Scoring is done before entering this block, keeping the write lock short.
        An exception rolls back this batch, not previously committed batches.
        """
        if getattr(self._transactions, "connection", None) is not None:
            raise RuntimeError("Nested scan write batches are not supported")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._transactions.connection = connection
            try:
                yield connection
            finally:
                del self._transactions.connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._ensure_column(
                connection, "matches", "roles_json", "TEXT NOT NULL DEFAULT '[]'"
            )
            self._ensure_column(
                connection,
                "matches",
                "review_questions_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "matches",
                "match_basis",
                "TEXT NOT NULL DEFAULT 'direct'",
            )
            self._ensure_column(
                connection,
                "matches",
                "incentive_map_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                connection,
                "matches",
                "risk_breakdown_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                connection,
                "matches",
                "materiality_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                connection,
                "matches",
                "dynamic_subjects_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "market_snapshots",
                "closes_at",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "market_snapshots",
                "rules_hash",
                "TEXT",
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def get_meta(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_meta WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO app_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def source_initialized(self, source: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT initialized_at FROM source_state WHERE source = ?", (source,)
            ).fetchone()
            return bool(row and row["initialized_at"])

    def source_last_success(self, source: str) -> datetime | None:
        """Return the most recent successful refresh timestamp for one source."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT last_success_at FROM source_state WHERE source = ?",
                (source,),
            ).fetchone()
        return parse_datetime(row["last_success_at"]) if row and row["last_success_at"] else None

    def list_active_external_ids(
        self, source: str, *, matched_only: bool = True, limit: int = 5000
    ) -> list[str]:
        """Return active source identifiers worth refreshing between discovery scans.

        By default this is limited to contracts that already matched at least one
        organization or monitored theme. Refreshing those records keeps probability,
        volume, open interest, status, and closing time current without repeatedly
        traversing the source's entire public catalog.
        """
        scope_sql, scope_params = _market_scope_clause("active")
        join = "JOIN matches mt ON mt.market_id = m.id" if matched_only else ""
        distinct = "DISTINCT" if matched_only else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {distinct} m.external_id AS external_id
                FROM markets m
                {join}
                WHERE m.source = ? AND {scope_sql}
                ORDER BY m.last_seen_at DESC
                LIMIT ?
                """,
                (source, *scope_params, max(1, min(limit, 50000))),
            ).fetchall()
        return [str(row["external_id"]) for row in rows if row["external_id"]]

    def mark_source_success(self, source: str, at: datetime, initialize: bool = True) -> None:
        timestamp = isoformat(at)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_state(source, initialized_at, last_success_at, last_error_at, last_error)
                VALUES (?, ?, ?, NULL, NULL)
                ON CONFLICT(source) DO UPDATE SET
                    initialized_at = CASE
                        WHEN source_state.initialized_at IS NULL AND excluded.initialized_at IS NOT NULL
                        THEN excluded.initialized_at
                        ELSE source_state.initialized_at
                    END,
                    last_success_at = excluded.last_success_at,
                    last_error_at = NULL,
                    last_error = NULL
                """,
                (source, timestamp if initialize else None, timestamp),
            )

    def mark_source_error(self, source: str, at: datetime, error: str) -> None:
        timestamp = isoformat(at)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_state(source, last_error_at, last_error)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_error_at = excluded.last_error_at,
                    last_error = excluded.last_error
                """,
                (source, timestamp, error[:4000]),
            )

    def reset_source_state(self, source: str | None = None) -> int:
        with self.connect() as connection:
            if source:
                cursor = connection.execute(
                    "UPDATE source_state SET initialized_at = NULL WHERE source = ?", (source,)
                )
            else:
                cursor = connection.execute(
                    "UPDATE source_state SET initialized_at = NULL"
                )
            return cursor.rowcount

    def delete_source(self, source: str) -> dict[str, int]:
        """Delete all local records for one source and return removal counts.

        This is primarily used to remove synthetic ``demo`` records without
        disturbing live Kalshi or Polymarket history. Foreign-key cascades
        remove associated matches and notification logs.
        """
        with self.connect() as connection:
            market_count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM markets WHERE source = ?",
                    (source,),
                ).fetchone()["count"]
            )
            match_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM matches mt
                    JOIN markets m ON m.id = mt.market_id
                    WHERE m.source = ?
                    """,
                    (source,),
                ).fetchone()["count"]
            )
            scan_count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM scan_runs WHERE source = ?",
                    (source,),
                ).fetchone()["count"]
            )
            state_count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM source_state WHERE source = ?",
                    (source,),
                ).fetchone()["count"]
            )
            connection.execute("DELETE FROM markets WHERE source = ?", (source,))
            connection.execute("DELETE FROM scan_runs WHERE source = ?", (source,))
            connection.execute("DELETE FROM source_state WHERE source = ?", (source,))
        return {
            "markets": market_count,
            "matches": match_count,
            "scan_runs": scan_count,
            "source_states": state_count,
        }

    def upsert_market(
        self, market: MarketRecord, seen_at: datetime
    ) -> tuple[int, bool]:
        seen = isoformat(seen_at)
        closes_at = isoformat(market.closes_at)
        rules_hash = _market_rules_hash(market.title, market.description)
        values = (
            market.title,
            market.description,
            market.url,
            market.status,
            isoformat(market.created_at),
            closes_at,
            market.probability,
            market.volume,
            market.volume_24h,
            market.liquidity,
            market.open_interest,
            seen,
            _json(market.raw),
            market.source,
            market.external_id,
        )
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, description, closes_at, probability, volume,
                       volume_24h, liquidity, open_interest, status
                FROM markets
                WHERE source = ? AND external_id = ?
                """,
                (market.source, market.external_id),
            ).fetchone()
            if row:
                market_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE markets SET
                        title = ?, description = ?, url = ?, status = ?,
                        source_created_at = ?, closes_at = ?, probability = ?,
                        volume = ?, volume_24h = ?, liquidity = ?, open_interest = ?,
                        last_seen_at = ?, raw_json = ?
                    WHERE source = ? AND external_id = ?
                    """,
                    values,
                )
                prior_snapshot = connection.execute(
                    "SELECT 1 FROM market_snapshots WHERE market_id = ? LIMIT 1",
                    (market_id,),
                ).fetchone()
                tracked_changed = any(
                    row[field] != value
                    for field, value in (
                        ("probability", market.probability),
                        ("volume", market.volume),
                        ("volume_24h", market.volume_24h),
                        ("liquidity", market.liquidity),
                        ("open_interest", market.open_interest),
                        ("status", market.status),
                        ("closes_at", closes_at),
                        ("title", market.title),
                        ("description", market.description),
                    )
                )
                if tracked_changed or prior_snapshot is None:
                    connection.execute(
                        """
                        INSERT INTO market_snapshots(
                            market_id, captured_at, probability, volume, volume_24h,
                            liquidity, open_interest, status, closes_at, rules_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            market_id,
                            seen,
                            market.probability,
                            market.volume,
                            market.volume_24h,
                            market.liquidity,
                            market.open_interest,
                            market.status,
                            closes_at,
                            rules_hash,
                        ),
                    )
                return market_id, False

            cursor = connection.execute(
                """
                INSERT INTO markets(
                    source, external_id, title, description, url, status,
                    source_created_at, closes_at, probability, volume, volume_24h,
                    liquidity, open_interest, first_seen_at, last_seen_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market.source,
                    market.external_id,
                    market.title,
                    market.description,
                    market.url,
                    market.status,
                    isoformat(market.created_at),
                    closes_at,
                    market.probability,
                    market.volume,
                    market.volume_24h,
                    market.liquidity,
                    market.open_interest,
                    seen,
                    seen,
                    _json(market.raw),
                ),
            )
            market_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO market_snapshots(
                    market_id, captured_at, probability, volume, volume_24h,
                    liquidity, open_interest, status, closes_at, rules_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    seen,
                    market.probability,
                    market.volume,
                    market.volume_24h,
                    market.liquidity,
                    market.open_interest,
                    market.status,
                    closes_at,
                    rules_hash,
                ),
            )
            return market_id, True

    def upsert_match(
        self,
        market_id: int,
        result: MatchResult,
        seen_at: datetime,
        initial_alert_state: str,
    ) -> tuple[int, bool]:
        seen = isoformat(seen_at)
        values = (
            _json(result.matched_identity_terms),
            _json(result.matched_metric_terms),
            _json(result.categories),
            result.risk_score,
            result.severity,
            result.match_basis,
            _json(result.roles),
            _json(result.reasons),
            _json(result.review_questions),
            _json(result.stakeholders),
            _json(result.actions),
            _json(result.incentive_map),
            _json(result.risk_breakdown),
            _json(result.materiality),
            _json(result.dynamic_subjects),
            seen,
            market_id,
            result.organization,
        )
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM matches WHERE market_id = ? AND organization = ?",
                (market_id, result.organization),
            ).fetchone()
            if row:
                match_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE matches SET
                        matched_identity_terms_json = ?,
                        matched_metric_terms_json = ?,
                        categories_json = ?,
                        risk_score = ?, severity = ?, match_basis = ?, roles_json = ?, reasons_json = ?,
                        review_questions_json = ?, stakeholders_json = ?,
                        actions_json = ?, incentive_map_json = ?, risk_breakdown_json = ?,
                        materiality_json = ?, dynamic_subjects_json = ?, last_seen_at = ?
                    WHERE market_id = ? AND organization = ?
                    """,
                    values,
                )
                return match_id, False

            cursor = connection.execute(
                """
                INSERT INTO matches(
                    market_id, organization, matched_identity_terms_json,
                    matched_metric_terms_json, categories_json, risk_score,
                    severity, match_basis, roles_json, reasons_json, review_questions_json,
                    stakeholders_json, actions_json, incentive_map_json, risk_breakdown_json,
                    materiality_json, dynamic_subjects_json, first_seen_at, last_seen_at, alert_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    result.organization,
                    _json(result.matched_identity_terms),
                    _json(result.matched_metric_terms),
                    _json(result.categories),
                    result.risk_score,
                    result.severity,
                    result.match_basis,
                    _json(result.roles),
                    _json(result.reasons),
                    _json(result.review_questions),
                    _json(result.stakeholders),
                    _json(result.actions),
                    _json(result.incentive_map),
                    _json(result.risk_breakdown),
                    _json(result.materiality),
                    _json(result.dynamic_subjects),
                    seen,
                    seen,
                    initial_alert_state,
                ),
            )
            return int(cursor.lastrowid), True

    def set_match_alert_state(
        self,
        match_id: int,
        state: str,
        *,
        notified_at: datetime | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE matches
                SET alert_state = ?, notified_at = COALESCE(?, notified_at)
                WHERE id = ?
                """,
                (state, isoformat(notified_at), match_id),
            )

    def acknowledge_match(self, match_id: int, at: datetime) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE matches
                SET acknowledged_at = ?, alert_state = 'acknowledged'
                WHERE id = ?
                """,
                (isoformat(at), match_id),
            )
            return cursor.rowcount > 0

    def save_review_feedback(
        self,
        match_id: int,
        *,
        decision: str,
        reason_codes: list[str],
        guidance_rating: str | None,
        note: str,
        corrected_role: str,
        suggested_owner: str,
        at: datetime,
    ) -> dict[str, Any] | None:
        """Create or update the reviewer assessment for one profile match.

        A saved assessment is a completed review, so the older acknowledgement
        fields are updated for backward compatibility. The richer feedback row
        remains the source of truth for calibration.
        """

        if not self.market_is_active_for_match(match_id):
            return None
        timestamp = isoformat(at)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM matches WHERE id = ?", (match_id,)
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                INSERT INTO review_feedback(
                    match_id, decision, reason_codes_json, guidance_rating, note,
                    corrected_role, suggested_owner, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id) DO UPDATE SET
                    decision = excluded.decision,
                    reason_codes_json = excluded.reason_codes_json,
                    guidance_rating = excluded.guidance_rating,
                    note = excluded.note,
                    corrected_role = excluded.corrected_role,
                    suggested_owner = excluded.suggested_owner,
                    updated_at = excluded.updated_at
                """,
                (
                    match_id,
                    decision,
                    _json(normalize_reason_codes(reason_codes)),
                    guidance_rating,
                    note[:4000],
                    corrected_role[:300],
                    suggested_owner[:300],
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE matches
                SET acknowledged_at = ?, alert_state = 'acknowledged'
                WHERE id = ?
                """,
                (timestamp, match_id),
            )
        return self.get_match(match_id)

    def market_is_active_for_match(self, match_id: int) -> bool:
        scope_sql, scope_params = _market_scope_clause("active")
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT 1
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                WHERE mt.id = ? AND {scope_sql}
                """,
                (match_id, *scope_params),
            ).fetchone()
        return row is not None

    def list_review_feedback(
        self, *, view: str = "all", include_demo: bool = False, limit: int = 5000
    ) -> list[dict[str, Any]]:
        scope_sql, scope_params = _market_scope_clause(view)
        demo_clause = "" if include_demo else "AND m.source <> 'demo'"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    rf.match_id, rf.decision, rf.reason_codes_json,
                    rf.guidance_rating, rf.note, rf.corrected_role,
                    rf.suggested_owner, rf.created_at, rf.updated_at,
                    mt.organization, mt.categories_json, mt.risk_score, mt.severity,
                    mt.match_basis, m.id AS market_id, m.source, m.external_id,
                    m.title, m.url, m.closes_at, m.status
                FROM review_feedback rf
                JOIN matches mt ON mt.id = rf.match_id
                JOIN markets m ON m.id = mt.market_id
                WHERE {scope_sql} {demo_clause}
                ORDER BY rf.updated_at DESC
                LIMIT ?
                """,
                (*scope_params, max(1, min(limit, 50000))),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["reason_codes"] = _loads(item.pop("reason_codes_json"), [])
            item["categories"] = _loads(item.pop("categories_json"), [])
            output.append(item)
        return output

    def feedback_summary(
        self, *, view: str = "active", include_demo: bool = False
    ) -> dict[str, Any]:
        """Return calibration counts from reviewer decisions, by profile/pathway."""

        scope_sql, scope_params = _market_scope_clause(view)
        demo_clause = "" if include_demo else "AND m.source <> 'demo'"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    mt.id AS match_id, mt.organization, mt.categories_json,
                    mt.acknowledged_at, rf.decision, rf.guidance_rating
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                LEFT JOIN review_feedback rf ON rf.match_id = mt.id
                WHERE {scope_sql} {demo_clause}
                """,
                tuple(scope_params),
            ).fetchall()

        decision_counts = {
            "actionable": 0,
            "monitor": 0,
            "informational": 0,
            "false_positive": 0,
        }
        guidance_counts = {"useful": 0, "partly_useful": 0, "not_useful": 0}
        by_profile: dict[str, dict[str, Any]] = {}
        by_category: dict[str, dict[str, Any]] = {}
        legacy_reviewed = 0
        unreviewed = 0

        for row in rows:
            organization = str(row["organization"])
            profile = by_profile.setdefault(
                organization,
                {
                    "organization": organization,
                    "total": 0,
                    "reviewed": 0,
                    "legacy_reviewed": 0,
                    "unreviewed": 0,
                    **{key: 0 for key in decision_counts},
                },
            )
            profile["total"] += 1
            decision = row["decision"]
            if decision in decision_counts:
                decision_counts[str(decision)] += 1
                profile["reviewed"] += 1
                profile[str(decision)] += 1
                guidance = row["guidance_rating"]
                if guidance in guidance_counts:
                    guidance_counts[str(guidance)] += 1
                for category in _loads(row["categories_json"], []):
                    clean = str(category)
                    pathway = by_category.setdefault(
                        clean,
                        {
                            "category": clean,
                            "reviewed": 0,
                            **{key: 0 for key in decision_counts},
                        },
                    )
                    pathway["reviewed"] += 1
                    pathway[str(decision)] += 1
            elif row["acknowledged_at"]:
                legacy_reviewed += 1
                profile["legacy_reviewed"] += 1
            else:
                unreviewed += 1
                profile["unreviewed"] += 1

        reviewed = sum(decision_counts.values())
        guidance_reviewed = sum(guidance_counts.values())
        actionable_or_monitor = decision_counts["actionable"] + decision_counts["monitor"]
        total = len(rows)

        profiles = sorted(
            by_profile.values(),
            key=lambda item: (-int(item["reviewed"]), -int(item["total"]), item["organization"]),
        )
        pathways = sorted(
            by_category.values(),
            key=lambda item: (-int(item["reviewed"]), item["category"]),
        )
        return {
            "total_profile_matches": total,
            "reviewed": reviewed,
            "legacy_reviewed": legacy_reviewed,
            "unreviewed": unreviewed,
            "decision_counts": decision_counts,
            "guidance_counts": guidance_counts,
            "actionable_rate": (
                round(decision_counts["actionable"] / reviewed * 100, 1)
                if reviewed
                else 0.0
            ),
            "actionable_or_monitor_rate": (
                round(actionable_or_monitor / reviewed * 100, 1) if reviewed else 0.0
            ),
            "false_positive_rate": (
                round(decision_counts["false_positive"] / reviewed * 100, 1)
                if reviewed
                else 0.0
            ),
            "guidance_positive_rate": (
                round(
                    (guidance_counts["useful"] + guidance_counts["partly_useful"])
                    / guidance_reviewed
                    * 100,
                    1,
                )
                if guidance_reviewed
                else 0.0
            ),
            "guidance_reviewed": guidance_reviewed,
            "profiles": profiles,
            "pathways": pathways,
        }

    def update_match_analysis(self, market_id: int, result: MatchResult) -> bool:
        """Refresh scoring and review guidance without changing source-seen timestamps."""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE matches SET
                    matched_identity_terms_json = ?,
                    matched_metric_terms_json = ?,
                    categories_json = ?,
                    risk_score = ?, severity = ?, match_basis = ?, roles_json = ?, reasons_json = ?,
                    review_questions_json = ?, stakeholders_json = ?, actions_json = ?,
                    incentive_map_json = ?, risk_breakdown_json = ?, materiality_json = ?,
                    dynamic_subjects_json = ?
                WHERE market_id = ? AND organization = ?
                """,
                (
                    _json(result.matched_identity_terms),
                    _json(result.matched_metric_terms),
                    _json(result.categories),
                    result.risk_score,
                    result.severity,
                    result.match_basis,
                    _json(result.roles),
                    _json(result.reasons),
                    _json(result.review_questions),
                    _json(result.stakeholders),
                    _json(result.actions),
                    _json(result.incentive_map),
                    _json(result.risk_breakdown),
                    _json(result.materiality),
                    _json(result.dynamic_subjects),
                    market_id,
                    result.organization,
                ),
            )
            return cursor.rowcount > 0

    def list_markets_matching_terms(
        self,
        terms: tuple[str, ...] | list[str],
        *,
        external_id_prefixes: tuple[str, ...] | list[str] = (),
        include_demo: bool = False,
    ) -> list[tuple[int, MarketRecord]]:
        """Return stored markets that may fit a profile.

        Text terms provide the normal broad prefilter. Source contract-family
        prefixes allow dependency profiles (for example FlightAware) to be
        reconsidered even when the company name is absent from visible rules.
        The risk engine performs the final exact and source-aware validation.
        """
        clean_terms = list(
            dict.fromkeys(
                term.strip().casefold()
                for term in terms
                if isinstance(term, str) and term.strip()
            )
        )
        clean_prefixes = list(
            dict.fromkeys(
                prefix.strip().upper()
                for prefix in external_id_prefixes
                if isinstance(prefix, str) and prefix.strip()
            )
        )
        if not clean_terms and not clean_prefixes:
            return []

        clauses: list[str] = []
        params: list[Any] = []
        for term in clean_terms:
            clauses.append(
                "(LOWER(m.title) LIKE ? OR LOWER(m.description) LIKE ? OR LOWER(m.raw_json) LIKE ?)"
            )
            pattern = f"%{term}%"
            params.extend((pattern, pattern, pattern))
        for prefix in clean_prefixes:
            clauses.append("UPPER(m.external_id) LIKE ?")
            params.append(f"{prefix}%")
        source_clause = "" if include_demo else "AND m.source <> 'demo'"

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    m.id AS market_id, m.source, m.external_id, m.title,
                    m.description, m.url, m.status, m.source_created_at,
                    m.closes_at, m.probability, m.volume, m.volume_24h,
                    m.liquidity, m.open_interest, m.raw_json
                FROM markets m
                WHERE ({' OR '.join(clauses)}) {source_clause}
                ORDER BY m.id
                """,
                tuple(params),
            ).fetchall()

        output: list[tuple[int, MarketRecord]] = []
        for row in rows:
            output.append(
                (
                    int(row["market_id"]),
                    MarketRecord(
                        source=row["source"],
                        external_id=row["external_id"],
                        title=row["title"],
                        description=row["description"],
                        url=row["url"],
                        status=row["status"],
                        created_at=parse_datetime(row["source_created_at"]),
                        closes_at=parse_datetime(row["closes_at"]),
                        probability=row["probability"],
                        volume=row["volume"],
                        volume_24h=row["volume_24h"],
                        liquidity=row["liquidity"],
                        open_interest=row["open_interest"],
                        raw=_loads(row["raw_json"], {}),
                    ),
                )
            )
        return output

    def list_matched_markets(
        self, *, include_demo: bool = False
    ) -> list[tuple[int, MarketRecord, set[str]]]:
        """Return unique markets and their existing matched organizations."""
        where = "" if include_demo else "WHERE m.source <> 'demo'"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    m.id AS market_id, m.source, m.external_id, m.title,
                    m.description, m.url, m.status, m.source_created_at,
                    m.closes_at, m.probability, m.volume, m.volume_24h,
                    m.liquidity, m.open_interest, m.raw_json, mt.organization
                FROM markets m
                JOIN matches mt ON mt.market_id = m.id
                {where}
                ORDER BY m.id
                """
            ).fetchall()

        grouped: dict[int, tuple[MarketRecord, set[str]]] = {}
        for row in rows:
            market_id = int(row["market_id"])
            if market_id not in grouped:
                grouped[market_id] = (
                    MarketRecord(
                        source=row["source"],
                        external_id=row["external_id"],
                        title=row["title"],
                        description=row["description"],
                        url=row["url"],
                        status=row["status"],
                        created_at=parse_datetime(row["source_created_at"]),
                        closes_at=parse_datetime(row["closes_at"]),
                        probability=row["probability"],
                        volume=row["volume"],
                        volume_24h=row["volume_24h"],
                        liquidity=row["liquidity"],
                        open_interest=row["open_interest"],
                        raw=_loads(row["raw_json"], {}),
                    ),
                    set(),
                )
            grouped[market_id][1].add(row["organization"])

        return [
            (market_id, market, organizations)
            for market_id, (market, organizations) in grouped.items()
        ]

    def log_notification(
        self,
        match_id: int,
        channel: str,
        at: datetime,
        status: str,
        detail: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_log(match_id, channel, sent_at, status, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (match_id, channel, isoformat(at), status, detail[:4000]),
            )

    def record_scan(
        self,
        summary: ScanSourceSummary,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO scan_runs(
                    source, started_at, finished_at, fetched, pages, new_markets,
                    matches, new_matches, notifications, baseline_suppressed, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.source,
                    isoformat(started_at),
                    isoformat(finished_at),
                    summary.fetched,
                    summary.pages,
                    summary.new_markets,
                    summary.matches,
                    summary.new_matches,
                    summary.notifications,
                    summary.baseline_suppressed,
                    summary.error,
                ),
            )

    def get_match(self, match_id: int) -> dict[str, Any] | None:
        rows = self._query_matches("WHERE mt.id = ?", (match_id,), limit=1)
        return rows[0] if rows else None

    def get_market_record(self, market_id: int) -> MarketRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT source, external_id, title, description, url, status,
                       source_created_at, closes_at, probability, volume,
                       volume_24h, liquidity, open_interest, raw_json
                FROM markets WHERE id = ?
                """,
                (market_id,),
            ).fetchone()
        if row is None:
            return None
        return MarketRecord(
            source=row["source"],
            external_id=row["external_id"],
            title=row["title"],
            description=row["description"],
            url=row["url"],
            status=row["status"],
            created_at=parse_datetime(row["source_created_at"]),
            closes_at=parse_datetime(row["closes_at"]),
            probability=row["probability"],
            volume=row["volume"],
            volume_24h=row["volume_24h"],
            liquidity=row["liquidity"],
            open_interest=row["open_interest"],
            raw=_loads(row["raw_json"], {}),
        )

    def save_public_exposure_snapshot(
        self, market_id: int, exposure: dict[str, Any]
    ) -> dict[str, Any]:
        captured_at = str(exposure.get("captured_at") or isoformat(utcnow()))
        holder_groups = exposure.get("holder_groups") or []
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO public_exposure_snapshots(
                    market_id, captured_at, source, visibility, condition_id,
                    open_interest, holder_groups_json, detail, caveat, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    captured_at,
                    str(exposure.get("source") or "unknown"),
                    str(exposure.get("visibility") or "unknown"),
                    exposure.get("condition_id"),
                    exposure.get("open_interest"),
                    _json(holder_groups),
                    str(exposure.get("detail") or ""),
                    str(exposure.get("caveat") or ""),
                    _json(exposure),
                ),
            )
            snapshot_id = int(cursor.lastrowid)
        output = dict(exposure)
        output["snapshot_id"] = snapshot_id
        output["captured_at"] = captured_at
        return output

    def latest_public_exposure(self, market_id: int) -> dict[str, Any] | None:
        values = self._latest_public_exposures([market_id])
        return values.get(market_id)

    def _latest_public_exposures(
        self, market_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        if not market_ids:
            return {}
        placeholders = ",".join("?" for _ in market_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT p.*
                FROM public_exposure_snapshots p
                JOIN (
                    SELECT market_id, MAX(id) AS latest_id
                    FROM public_exposure_snapshots
                    WHERE market_id IN ({placeholders})
                    GROUP BY market_id
                ) latest ON latest.latest_id = p.id
                """,
                tuple(market_ids),
            ).fetchall()
        output: dict[int, dict[str, Any]] = {}
        for row in rows:
            market_id = int(row["market_id"])
            raw = _loads(row["raw_json"], {})
            if not isinstance(raw, dict):
                raw = {}
            raw.update(
                {
                    "snapshot_id": int(row["id"]),
                    "market_id": market_id,
                    "captured_at": row["captured_at"],
                    "source": row["source"],
                    "visibility": row["visibility"],
                    "condition_id": row["condition_id"],
                    "open_interest": row["open_interest"],
                    "holder_groups": _loads(row["holder_groups_json"], []),
                    "detail": row["detail"],
                    "caveat": row["caveat"],
                }
            )
            output[market_id] = raw
        return output

    def _market_movements(self, market_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Return latest, prior, and approximate 24-hour market changes.

        Snapshots are written only when tracked source fields change. The 24-hour
        comparison therefore uses the newest snapshot captured at or before the
        24-hour cutoff when one exists; otherwise it uses the first available
        snapshot and reports the shorter observation window.
        """
        if not market_ids:
            return {}
        placeholders = ",".join("?" for _ in market_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT market_id, captured_at, probability, volume, volume_24h,
                       liquidity, open_interest, status, closes_at, rules_hash
                FROM market_snapshots
                WHERE market_id IN ({placeholders})
                ORDER BY market_id, captured_at, id
                """,
                tuple(market_ids),
            ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(int(row["market_id"]), []).append(dict(row))

        output: dict[int, dict[str, Any]] = {}
        tracked = ("probability", "volume", "volume_24h", "liquidity", "open_interest")
        for market_id, snapshots in grouped.items():
            latest = snapshots[-1]
            previous = snapshots[-2] if len(snapshots) > 1 else None
            first = snapshots[0]
            latest_at = parse_datetime(latest.get("captured_at")) or utcnow()
            cutoff = latest_at - timedelta(hours=24)
            day_origin = first
            for candidate in snapshots:
                captured = parse_datetime(candidate.get("captured_at"))
                if captured is not None and captured <= cutoff:
                    day_origin = candidate
                elif captured is not None and captured > cutoff:
                    break

            def delta(current: Any, prior: Any) -> float | None:
                if current is None or prior is None:
                    return None
                return float(current) - float(prior)

            deltas = {
                field: delta(latest.get(field), previous.get(field) if previous else None)
                for field in tracked
            }
            since_first = {
                field: delta(latest.get(field), first.get(field)) for field in tracked
            }
            day_deltas = {
                field: delta(latest.get(field), day_origin.get(field)) for field in tracked
            }
            day_origin_at = parse_datetime(day_origin.get("captured_at"))
            window_hours = (
                (latest_at - day_origin_at).total_seconds() / 3600
                if day_origin_at is not None
                else None
            )

            prior_rules = previous.get("rules_hash") if previous else None
            latest_rules = latest.get("rules_hash")
            rules_changed = bool(
                previous
                and prior_rules
                and latest_rules
                and str(prior_rules) != str(latest_rules)
            )
            close_changed = bool(
                previous and (previous.get("closes_at") or None) != (latest.get("closes_at") or None)
            )
            status_changed = bool(
                previous and str(previous.get("status") or "") != str(latest.get("status") or "")
            )
            quantitative_changed = bool(
                previous and any(value not in (None, 0.0) for value in deltas.values())
            )
            output[market_id] = {
                "snapshot_count": len(snapshots),
                "captured_at": latest.get("captured_at"),
                "previous_captured_at": previous.get("captured_at") if previous else None,
                "day_origin_at": day_origin.get("captured_at"),
                "day_window_hours": window_hours,
                "deltas": deltas,
                "day_deltas": day_deltas,
                "since_first": since_first,
                "rules_changed": rules_changed,
                "close_changed": close_changed,
                "status_changed": status_changed,
                "changed": quantitative_changed or rules_changed or close_changed or status_changed,
            }
        return output

    def get_contract_detail(self, market_id: int) -> dict[str, Any] | None:
        """Return one fully assembled contract for active or archived views."""
        view = "active" if self.market_is_active(market_id) else "archive"
        result = self.list_contract_groups(
            view=view,
            market_id=market_id,
            limit=1,
        )
        contracts = result.get("contracts") or []
        return contracts[0] if contracts else None

    def market_is_active(self, market_id: int) -> bool:
        scope_sql, scope_params = _market_scope_clause("active")
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT 1 FROM markets m WHERE m.id = ? AND {scope_sql}",
                (market_id, *scope_params),
            ).fetchone()
        return row is not None

    def acknowledge_market(self, market_id: int, at: datetime) -> int:
        """Mark every organization match for one active contract as reviewed."""
        if not self.market_is_active(market_id):
            return 0
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE matches
                SET acknowledged_at = ?, alert_state = 'acknowledged'
                WHERE market_id = ?
                """,
                (isoformat(at), market_id),
            )
            return cursor.rowcount

    def list_matches(
        self,
        *,
        organization: str | None = None,
        severity: str | None = None,
        source: str | None = None,
        alert_state: str | None = None,
        review_decision: str | None = None,
        include_demo: bool = False,
        view: str = "active",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return row-level organization matches for APIs and exports.

        The default is active-only. Historical records require view='archive' or
        view='all', which prevents expired contracts from leaking into normal
        review workflows.
        """
        clauses: list[str] = []
        params: list[Any] = []
        scope_sql, scope_params = _market_scope_clause(view)
        clauses.append(scope_sql)
        params.extend(scope_params)
        if not include_demo and source != "demo":
            clauses.append("m.source <> 'demo'")
        if organization:
            clauses.append("mt.organization = ?")
            params.append(organization)
        if severity:
            clauses.append("mt.severity = ?")
            params.append(severity)
        if source:
            clauses.append("m.source = ?")
            params.append(source)
        if alert_state:
            clauses.append("mt.alert_state = ?")
            params.append(alert_state)
        if review_decision:
            if review_decision == "unreviewed":
                clauses.append("rf.match_id IS NULL AND mt.acknowledged_at IS NULL")
            elif review_decision == "legacy_reviewed":
                clauses.append("rf.match_id IS NULL AND mt.acknowledged_at IS NOT NULL")
            else:
                clauses.append("rf.decision = ?")
                params.append(review_decision)
        where = f"WHERE {' AND '.join(clauses)}"
        return self._query_matches(where, tuple(params), limit=max(1, min(limit, 1000)))

    def list_contract_groups(
        self,
        *,
        organization: str | None = None,
        severity: str | None = None,
        source: str | None = None,
        alert_state: str | None = None,
        review_decision: str | None = None,
        materiality_gate: str = "all",
        include_demo: bool = False,
        view: str = "active",
        sort: str = "priority",
        limit: int = 200,
        market_id: int | None = None,
    ) -> dict[str, Any]:
        """Return one card per exact contract, grouped under source event/series.

        The materiality gate is applied after movement history is joined to each
        profile relationship. This keeps the human review queue focused on
        contracts that have both a credible pathway and a current activation
        trigger, while retaining lower-materiality matches in Observed.
        """

        normalized_view = (view or "active").strip().lower()
        normalized_sort = (sort or "priority").strip().lower()
        if normalized_sort not in {"priority", "review", "closing", "volume", "newest"}:
            normalized_sort = "priority"
        normalized_gate = (materiality_gate or "all").strip().lower()
        if normalized_gate not in {"all", "review_today", "escalate", "review", "observed"}:
            normalized_gate = "all"
        if normalized_view == "archive":
            normalized_gate = "all"

        scope_sql, scope_params = _market_scope_clause(normalized_view)
        clauses = [scope_sql]
        params: list[Any] = list(scope_params)
        if not include_demo and source != "demo":
            clauses.append("m.source <> 'demo'")
        if source:
            clauses.append("m.source = ?")
            params.append(source)
        if market_id is not None:
            clauses.append("m.id = ?")
            params.append(int(market_id))
        where = f"WHERE {' AND '.join(clauses)}"

        rows = self._query_matches(where, tuple(params), limit=100000)
        contracts_by_id: dict[int, dict[str, Any]] = {}
        for row in rows:
            market_key = int(row["market_id"])
            contract = contracts_by_id.get(market_key)
            if contract is None:
                raw = row.get("raw") or {}
                display_title = clean_display_title(row["source"], row["title"], raw)
                event_key, event_title = event_group_identity(
                    row["source"], row["external_id"], display_title, raw
                )
                contract = {
                    "market_id": market_key,
                    "source": row["source"],
                    "external_id": row["external_id"],
                    "title": display_title,
                    "stored_title": row["title"],
                    "description": row["description"],
                    "url": row["url"],
                    "status": row["status"],
                    "source_created_at": row["source_created_at"],
                    "closes_at": row["closes_at"],
                    "probability": row["probability"],
                    "volume": row["volume"],
                    "volume_24h": row["volume_24h"],
                    "liquidity": row["liquidity"],
                    "open_interest": row["open_interest"],
                    "first_seen_at": row["first_seen_at"],
                    "last_seen_at": row["last_seen_at"],
                    "event_key": event_key,
                    "event_title": event_title,
                    "reviews": [],
                }
                contracts_by_id[market_key] = contract

            contract["reviews"].append(
                {
                    "match_id": row["match_id"],
                    "organization": row["organization"],
                    "matched_identity_terms": row["matched_identity_terms"],
                    "matched_metric_terms": row["matched_metric_terms"],
                    "categories": row["categories"],
                    "risk_score": row["risk_score"],
                    "severity": row["severity"],
                    "match_basis": row.get("match_basis") or "direct",
                    "roles": row["roles"],
                    "reasons": row["reasons"],
                    "review_questions": row["review_questions"],
                    "stakeholders": row["stakeholders"],
                    "actions": row["actions"],
                    "incentive_map": row.get("incentive_map", {}),
                    "risk_breakdown": row.get("risk_breakdown", {}),
                    "materiality": row.get("materiality", {}),
                    "dynamic_subjects": row.get("dynamic_subjects", []),
                    "match_first_seen_at": row["match_first_seen_at"],
                    "match_last_seen_at": row["match_last_seen_at"],
                    "alert_state": row["alert_state"],
                    "notified_at": row["notified_at"],
                    "acknowledged_at": row["acknowledged_at"],
                    "review_decision": row.get("review_decision"),
                    "review_reason_codes": row.get("review_reason_codes", []),
                    "guidance_rating": row.get("guidance_rating"),
                    "review_note": row.get("review_note") or "",
                    "corrected_role": row.get("corrected_role") or "",
                    "suggested_owner": row.get("suggested_owner") or "",
                    "feedback_created_at": row.get("feedback_created_at"),
                    "feedback_updated_at": row.get("feedback_updated_at"),
                }
            )

        def review_matches_filters(review: dict[str, Any]) -> bool:
            if organization and review["organization"] != organization:
                return False
            if severity and review["severity"] != severity:
                return False
            if alert_state and review["alert_state"] != alert_state:
                return False
            if review_decision:
                explicit = review.get("review_decision")
                if review_decision == "unreviewed":
                    if explicit or review.get("acknowledged_at"):
                        return False
                elif review_decision == "legacy_reviewed":
                    if explicit or not review.get("acknowledged_at"):
                        return False
                elif explicit != review_decision:
                    return False
            return True

        candidate_contracts: list[dict[str, Any]] = []
        for contract in contracts_by_id.values():
            reviews = contract["reviews"]
            if not any(review_matches_filters(review) for review in reviews):
                continue
            candidate_contracts.append(contract)

        market_ids = [int(contract["market_id"]) for contract in candidate_contracts]
        movement_by_market = self._market_movements(market_ids)
        exposure_by_market = self._latest_public_exposures(market_ids)

        gate_counts = {"escalate": 0, "review": 0, "observed": 0}
        contracts: list[dict[str, Any]] = []
        for contract in candidate_contracts:
            market_key = int(contract["market_id"])
            movement = movement_by_market.get(
                market_key,
                {
                    "snapshot_count": 0,
                    "captured_at": None,
                    "previous_captured_at": None,
                    "day_origin_at": None,
                    "day_window_hours": None,
                    "deltas": {},
                    "day_deltas": {},
                    "since_first": {},
                    "rules_changed": False,
                    "close_changed": False,
                    "status_changed": False,
                    "changed": False,
                },
            )
            for review in contract["reviews"]:
                review["materiality"] = apply_market_movement(
                    review.get("materiality"),
                    movement=movement,
                    source=str(contract["source"]),
                    categories=list(review.get("categories") or []),
                    match_basis=str(review.get("match_basis") or "direct"),
                    actions=list(review.get("actions") or []),
                    stakeholders=list(review.get("stakeholders") or []),
                    closes_at=contract.get("closes_at"),
                )

            review_sort_key = lambda item: (
                GATE_RANK.get(str((item.get("materiality") or {}).get("gate")), 0),
                int((item.get("materiality") or {}).get("materiality_score") or 0),
                _SEVERITY_RANK.get(str(item["severity"]), 0),
                int(item["risk_score"]),
                str(item["organization"]),
            )
            contract["reviews"].sort(key=review_sort_key, reverse=True)
            reviews = contract["reviews"]
            eligible_reviews = sorted(
                (review for review in reviews if review_matches_filters(review)),
                key=review_sort_key,
                reverse=True,
            )
            # The contract card still exposes all affected profiles, but its queue
            # gate, score, and review state follow the currently selected filter.
            # This prevents a high-materiality relationship for one organization
            # from leaking into another organization's filtered review queue.
            contract["materiality"] = aggregate_materiality(eligible_reviews)
            gate = str(contract["materiality"].get("gate") or "observed")
            gate_counts[gate] = gate_counts.get(gate, 0) + 1

            if normalized_gate == "review_today" and gate not in {"review", "escalate"}:
                continue
            if normalized_gate in {"escalate", "review", "observed"} and gate != normalized_gate:
                continue

            top_review = eligible_reviews[0]
            contract["risk_score"] = max(int(item["risk_score"]) for item in eligible_reviews)
            contract["severity"] = max(
                (str(item["severity"]) for item in eligible_reviews),
                key=lambda value: _SEVERITY_RANK.get(value, 0),
            )
            contract["organizations"] = [item["organization"] for item in reviews]
            contract["filtered_organizations"] = [
                item["organization"] for item in eligible_reviews
            ]
            contract["dynamic_subjects"] = list(
                dict.fromkeys(
                    subject
                    for item in reviews
                    for subject in (item.get("dynamic_subjects") or [])
                )
            )
            contract["matched_identity_terms"] = list(
                dict.fromkeys(
                    term for item in reviews for term in item["matched_identity_terms"]
                )
            )
            contract["alert_states"] = list(
                dict.fromkeys(str(item["alert_state"]) for item in eligible_reviews)
            )
            contract["review_total"] = len(eligible_reviews)
            contract["reviewed_count"] = sum(
                1
                for item in eligible_reviews
                if item.get("review_decision") or item.get("acknowledged_at")
            )
            contract["explicit_review_count"] = sum(
                1 for item in eligible_reviews if item.get("review_decision")
            )
            contract["all_reviewed"] = bool(
                contract["review_total"]
                and contract["reviewed_count"] == contract["review_total"]
            )
            contract["reviewable"] = normalized_view == "active"
            contract["display_state"] = (
                "archived"
                if normalized_view == "archive"
                else (
                    "reviewed"
                    if contract["all_reviewed"]
                    else (
                        "in review"
                        if contract["reviewed_count"]
                        else (
                            "baseline"
                            if set(contract["alert_states"]) == {"baseline"}
                            else "needs review"
                        )
                    )
                )
            )
            contract["archive_reason"] = (
                archive_reason(contract["status"], contract["closes_at"])
                if normalized_view == "archive"
                else None
            )
            contract["top_match_first_seen_at"] = max(
                str(item["match_first_seen_at"]) for item in eligible_reviews
            )
            contract["top_review"] = top_review
            contract["movement"] = movement
            contract["public_exposure"] = exposure_by_market.get(market_key)
            contracts.append(contract)

        def sort_key(contract: dict[str, Any]) -> tuple[Any, ...]:
            materiality = contract.get("materiality") or {}
            gate_rank = GATE_RANK.get(str(materiality.get("gate")), 0)
            materiality_score = int(materiality.get("materiality_score") or 0)
            if normalized_sort == "review":
                review_bucket = 0 if contract["reviewed_count"] == 0 else (2 if contract["all_reviewed"] else 1)
                return (
                    review_bucket,
                    -gate_rank,
                    -materiality_score,
                    -int(contract["risk_score"]),
                    contract["top_match_first_seen_at"],
                )
            if normalized_sort == "closing":
                return (
                    contract["closes_at"] is None,
                    contract["closes_at"] or "9999-12-31T23:59:59+00:00",
                    -gate_rank,
                    -materiality_score,
                )
            if normalized_sort == "volume":
                return (
                    -(float(contract["volume"]) if contract["volume"] is not None else -1.0),
                    -gate_rank,
                    -materiality_score,
                )
            if normalized_sort == "newest":
                return (contract["top_match_first_seen_at"], gate_rank, materiality_score)
            return (gate_rank, materiality_score, int(contract["risk_score"]), contract["top_match_first_seen_at"])

        reverse = normalized_sort in {"priority", "newest"}
        contracts.sort(key=sort_key, reverse=reverse)
        total = len(contracts)
        contracts = contracts[: max(1, min(limit, 1000))]

        groups_by_key: dict[str, dict[str, Any]] = {}
        for contract in contracts:
            group = groups_by_key.get(contract["event_key"])
            if group is None:
                group = {
                    "event_key": contract["event_key"],
                    "title": contract["event_title"],
                    "source": contract["source"],
                    "contracts": [],
                }
                groups_by_key[contract["event_key"]] = group
            group["contracts"].append(contract)

        groups = list(groups_by_key.values())
        for group in groups:
            items = group["contracts"]
            group["count"] = len(items)
            top_item = max(
                items,
                key=lambda item: (
                    GATE_RANK.get(str((item.get("materiality") or {}).get("gate")), 0),
                    int((item.get("materiality") or {}).get("materiality_score") or 0),
                    int(item["risk_score"]),
                ),
            )
            group["severity"] = top_item["severity"]
            group["risk_score"] = top_item["risk_score"]
            group["materiality"] = top_item.get("materiality") or {}
            close_values = [item["closes_at"] for item in items if item["closes_at"]]
            group["nearest_close"] = min(close_values) if close_values else None
            group["organizations"] = list(
                dict.fromkeys(org for item in items for org in item["organizations"])
            )
            group["dynamic_subjects"] = list(
                dict.fromkeys(subject for item in items for subject in item.get("dynamic_subjects", []))
            )

        return {
            "groups": groups,
            "contracts": contracts,
            "total": total,
            "all_active_total": sum(gate_counts.values()),
            "gate_counts": {
                **gate_counts,
                "review_today": gate_counts.get("review", 0) + gate_counts.get("escalate", 0),
                "all": sum(gate_counts.values()),
            },
            "materiality_gate": normalized_gate,
            "view": normalized_view,
            "sort": normalized_sort,
        }

    def get_contract_bundle(self, market_id: int) -> dict[str, Any] | None:
        rows = self._query_matches("WHERE m.id = ?", (market_id,), limit=1000)
        if not rows:
            return None
        first = rows[0]
        raw = first.get("raw") or {}
        display_title = clean_display_title(first["source"], first["title"], raw)
        event_key, event_title = event_group_identity(
            first["source"], first["external_id"], display_title, raw
        )
        movement = self._market_movements([market_id]).get(market_id)
        reviews: list[dict[str, Any]] = []
        for row in rows:
            materiality = apply_market_movement(
                row.get("materiality") or {},
                movement=movement,
                source=str(first["source"]),
                categories=list(row.get("categories") or []),
                match_basis=str(row.get("match_basis") or "direct"),
                actions=list(row.get("actions") or []),
                stakeholders=list(row.get("stakeholders") or []),
                closes_at=first.get("closes_at"),
            )
            reviews.append(
                {
                    "match_id": row["match_id"],
                    "organization": row["organization"],
                    "matched_identity_terms": row["matched_identity_terms"],
                    "matched_metric_terms": row["matched_metric_terms"],
                    "categories": row["categories"],
                    "risk_score": row["risk_score"],
                    "severity": row["severity"],
                    "match_basis": row.get("match_basis") or "direct",
                    "roles": row["roles"],
                    "reasons": row["reasons"],
                    "review_questions": row["review_questions"],
                    "stakeholders": row["stakeholders"],
                    "actions": row["actions"],
                    "incentive_map": row.get("incentive_map") or {},
                    "risk_breakdown": row.get("risk_breakdown") or {},
                    "materiality": materiality,
                    "dynamic_subjects": row.get("dynamic_subjects") or [],
                    "review_decision": row.get("review_decision"),
                    "review_note": row.get("review_note") or "",
                    "corrected_role": row.get("corrected_role") or "",
                    "suggested_owner": row.get("suggested_owner") or "",
                    "acknowledged_at": row.get("acknowledged_at"),
                }
            )
        reviews.sort(
            key=lambda item: (
                GATE_RANK.get(str((item.get("materiality") or {}).get("gate")), 0),
                int((item.get("materiality") or {}).get("materiality_score") or 0),
                _SEVERITY_RANK.get(str(item["severity"]), 0),
                int(item["risk_score"]),
            ),
            reverse=True,
        )
        active = self.market_is_active(market_id)
        exposure = self.latest_public_exposure(market_id)
        contract_materiality = aggregate_materiality(reviews)
        return {
            "market_id": market_id,
            "source": first["source"],
            "external_id": first["external_id"],
            "title": display_title,
            "stored_title": first["title"],
            "description": first["description"],
            "url": first["url"],
            "status": first["status"],
            "source_created_at": first["source_created_at"],
            "closes_at": first["closes_at"],
            "probability": first["probability"],
            "volume": first["volume"],
            "volume_24h": first["volume_24h"],
            "liquidity": first["liquidity"],
            "open_interest": first["open_interest"],
            "first_seen_at": first["first_seen_at"],
            "last_seen_at": first["last_seen_at"],
            "event_key": event_key,
            "event_title": event_title,
            "reviews": reviews,
            "organizations": [item["organization"] for item in reviews],
            "dynamic_subjects": list(
                dict.fromkeys(subject for item in reviews for subject in item.get("dynamic_subjects", []))
            ),
            "materiality": contract_materiality,
            "risk_score": max(int(item["risk_score"]) for item in reviews),
            "severity": max(
                (str(item["severity"]) for item in reviews),
                key=lambda value: _SEVERITY_RANK.get(value, 0),
            ),
            "active": active,
            "archive_reason": None if active else archive_reason(first["status"], first["closes_at"]),
            "movement": movement,
            "public_exposure": exposure,
            "raw": raw,
        }

    def _query_matches(
        self, where: str, params: tuple[Any, ...], limit: int
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    mt.id AS match_id, mt.organization,
                    mt.matched_identity_terms_json, mt.matched_metric_terms_json,
                    mt.categories_json, mt.risk_score, mt.severity, mt.match_basis,
                    mt.roles_json, mt.reasons_json, mt.review_questions_json,
                    mt.stakeholders_json, mt.actions_json, mt.incentive_map_json,
                    mt.risk_breakdown_json, mt.materiality_json, mt.dynamic_subjects_json,
                    mt.first_seen_at AS match_first_seen_at,
                    mt.last_seen_at AS match_last_seen_at,
                    mt.alert_state, mt.notified_at, mt.acknowledged_at,
                    rf.decision AS review_decision,
                    rf.reason_codes_json AS review_reason_codes_json,
                    rf.guidance_rating, rf.note AS review_note,
                    rf.corrected_role, rf.suggested_owner,
                    rf.created_at AS feedback_created_at,
                    rf.updated_at AS feedback_updated_at,
                    m.id AS market_id, m.source, m.external_id, m.title,
                    m.description, m.url, m.status, m.source_created_at,
                    m.closes_at, m.probability, m.volume, m.volume_24h,
                    m.liquidity, m.open_interest, m.first_seen_at,
                    m.last_seen_at, m.raw_json
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                LEFT JOIN review_feedback rf ON rf.match_id = mt.id
                {where}
                ORDER BY
                    CASE mt.severity
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'medium' THEN 2
                        ELSE 1
                    END DESC,
                    mt.risk_score DESC,
                    mt.first_seen_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for field in (
                "matched_identity_terms_json",
                "matched_metric_terms_json",
                "categories_json",
                "roles_json",
                "reasons_json",
                "review_questions_json",
                "stakeholders_json",
                "actions_json",
            ):
                clean_name = field.removesuffix("_json")
                item[clean_name] = _loads(item.pop(field), [])
            item["incentive_map"] = _loads(item.pop("incentive_map_json", None), {})
            item["risk_breakdown"] = _loads(item.pop("risk_breakdown_json", None), {})
            item["materiality"] = _loads(item.pop("materiality_json", None), {})
            item["dynamic_subjects"] = _loads(item.pop("dynamic_subjects_json", None), [])
            item["review_reason_codes"] = _loads(
                item.pop("review_reason_codes_json", None), []
            )
            item["raw"] = _loads(item.pop("raw_json"), {})
            output.append(item)
        return output

    def dashboard_stats(
        self, *, include_demo: bool = False, view: str = "active"
    ) -> dict[str, Any]:
        scope_sql, scope_params = _market_scope_clause(view)
        demo_clause = "" if include_demo else "AND m.source <> 'demo'"
        market_demo_clause = "" if include_demo else "AND source <> 'demo'"
        archive_sql, archive_params = _market_scope_clause("archive")
        active_sql, active_params = _market_scope_clause("active")

        with self.connect() as connection:
            market_count = connection.execute(
                f"SELECT COUNT(*) AS count FROM markets m WHERE {scope_sql} {demo_clause}",
                tuple(scope_params),
            ).fetchone()["count"]
            contract_count = connection.execute(
                f"""
                SELECT COUNT(DISTINCT m.id) AS count
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                WHERE {scope_sql} {demo_clause}
                """,
                tuple(scope_params),
            ).fetchone()["count"]
            unacknowledged = connection.execute(
                f"""
                SELECT COUNT(DISTINCT m.id) AS count
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                LEFT JOIN review_feedback rf ON rf.match_id = mt.id
                WHERE {scope_sql} {demo_clause}
                  AND rf.match_id IS NULL
                  AND mt.acknowledged_at IS NULL
                """,
                tuple(scope_params),
            ).fetchone()["count"]
            high_risk = connection.execute(
                f"""
                SELECT COUNT(DISTINCT m.id) AS count
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                WHERE {scope_sql} {demo_clause}
                  AND mt.severity IN ('high', 'critical')
                """,
                tuple(scope_params),
            ).fetchone()["count"]
            archive_count = connection.execute(
                f"""
                SELECT COUNT(DISTINCT m.id) AS count
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                WHERE {archive_sql} {demo_clause}
                """,
                tuple(archive_params),
            ).fetchone()["count"]
            active_count = connection.execute(
                f"""
                SELECT COUNT(DISTINCT m.id) AS count
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                WHERE {active_sql} {demo_clause}
                """,
                tuple(active_params),
            ).fetchone()["count"]
            last_scan = connection.execute(
                "SELECT MAX(finished_at) AS finished_at FROM scan_runs "
                + ("" if include_demo else "WHERE source <> 'demo'")
            ).fetchone()["finished_at"]
            organization_rows = connection.execute(
                f"""
                SELECT mt.organization AS organization,
                       COUNT(DISTINCT m.id) AS contract_count
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
                WHERE {scope_sql} {demo_clause}
                GROUP BY mt.organization
                ORDER BY mt.organization
                """,
                tuple(scope_params),
            ).fetchall()
            organizations = [row["organization"] for row in organization_rows]
            organization_counts = {
                row["organization"]: int(row["contract_count"])
                for row in organization_rows
            }
            sources = [
                row["source"]
                for row in connection.execute(
                    f"""
                    SELECT DISTINCT m.source AS source
                    FROM markets m
                    WHERE {scope_sql} {demo_clause}
                    ORDER BY m.source
                    """,
                    tuple(scope_params),
                ).fetchall()
            ]
            source_states = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM source_state "
                    + ("" if include_demo else "WHERE source <> 'demo' ")
                    + "ORDER BY source"
                ).fetchall()
            ]
        return {
            "markets": int(market_count),
            "matches": int(contract_count),
            "unacknowledged": int(unacknowledged),
            "high_risk": int(high_risk),
            "active_matches": int(active_count),
            "archive_matches": int(archive_count),
            "last_scan": last_scan,
            "organizations": organizations,
            "organization_counts": organization_counts,
            "sources": sources,
            "source_states": source_states,
        }

    def recent_scans(
        self, limit: int = 10, *, include_demo: bool = False
    ) -> list[dict[str, Any]]:
        where = "" if include_demo else "WHERE source <> 'demo'"
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    f"SELECT * FROM scan_runs {where} ORDER BY started_at DESC LIMIT ?",
                    (max(1, min(limit, 100)),),
                ).fetchall()
            ]

    def clear_all(self) -> None:
        """Used by tests and explicit local resets."""
        with self.connect() as connection:
            connection.execute("DELETE FROM notification_log")
            connection.execute("DELETE FROM review_feedback")
            connection.execute("DELETE FROM matches")
            connection.execute("DELETE FROM markets")
            connection.execute("DELETE FROM source_state")
            connection.execute("DELETE FROM scan_runs")
            connection.execute("DELETE FROM app_meta")
