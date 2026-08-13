from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .market_view import (
    ARCHIVED_STATUSES,
    archive_reason,
    clean_display_title,
    event_group_identity,
)
from .models import MarketRecord, MatchResult, ScanSourceSummary
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


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
        values = (
            market.title,
            market.description,
            market.url,
            market.status,
            isoformat(market.created_at),
            isoformat(market.closes_at),
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
                "SELECT id FROM markets WHERE source = ? AND external_id = ?",
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
                    isoformat(market.closes_at),
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
            return int(cursor.lastrowid), True

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
                        actions_json = ?, last_seen_at = ?
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
                    stakeholders_json, actions_json, first_seen_at, last_seen_at, alert_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    review_questions_json = ?, stakeholders_json = ?, actions_json = ?
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
        where = f"WHERE {' AND '.join(clauses)}"
        return self._query_matches(where, tuple(params), limit=max(1, min(limit, 1000)))

    def list_contract_groups(
        self,
        *,
        organization: str | None = None,
        severity: str | None = None,
        source: str | None = None,
        alert_state: str | None = None,
        include_demo: bool = False,
        view: str = "active",
        sort: str = "priority",
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return one card per exact contract, grouped under source event/series.

        A market may match several organizations. Those role-specific reviews are
        combined on one card so the same contract title is never repeated merely
        because multiple teams are affected. Related thresholds/dates from the
        same source event are grouped beneath one collapsible series.
        """

        normalized_view = (view or "active").strip().lower()
        normalized_sort = (sort or "priority").strip().lower()
        if normalized_sort not in {"priority", "closing", "volume", "newest"}:
            normalized_sort = "priority"

        scope_sql, scope_params = _market_scope_clause(normalized_view)
        clauses = [scope_sql]
        params: list[Any] = list(scope_params)
        if not include_demo and source != "demo":
            clauses.append("m.source <> 'demo'")
        if source:
            clauses.append("m.source = ?")
            params.append(source)
        where = f"WHERE {' AND '.join(clauses)}"

        rows = self._query_matches(where, tuple(params), limit=100000)
        contracts_by_id: dict[int, dict[str, Any]] = {}
        for row in rows:
            market_id = int(row["market_id"])
            contract = contracts_by_id.get(market_id)
            if contract is None:
                raw = row.get("raw") or {}
                display_title = clean_display_title(
                    row["source"], row["title"], raw
                )
                event_key, event_title = event_group_identity(
                    row["source"], row["external_id"], display_title, raw
                )
                contract = {
                    "market_id": market_id,
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
                contracts_by_id[market_id] = contract

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
                    "match_first_seen_at": row["match_first_seen_at"],
                    "match_last_seen_at": row["match_last_seen_at"],
                    "alert_state": row["alert_state"],
                    "notified_at": row["notified_at"],
                    "acknowledged_at": row["acknowledged_at"],
                }
            )

        contracts: list[dict[str, Any]] = []
        for contract in contracts_by_id.values():
            reviews = contract["reviews"]

            def review_matches_filters(review: dict[str, Any]) -> bool:
                if organization and review["organization"] != organization:
                    return False
                if severity and review["severity"] != severity:
                    return False
                if alert_state and review["alert_state"] != alert_state:
                    return False
                return True

            if not any(review_matches_filters(review) for review in reviews):
                continue

            reviews.sort(
                key=lambda item: (
                    _SEVERITY_RANK.get(str(item["severity"]), 0),
                    int(item["risk_score"]),
                    str(item["organization"]),
                ),
                reverse=True,
            )
            top_review = reviews[0]
            contract["risk_score"] = max(int(item["risk_score"]) for item in reviews)
            contract["severity"] = max(
                (str(item["severity"]) for item in reviews),
                key=lambda value: _SEVERITY_RANK.get(value, 0),
            )
            contract["organizations"] = [item["organization"] for item in reviews]
            contract["matched_identity_terms"] = list(
                dict.fromkeys(
                    term
                    for review in reviews
                    for term in review["matched_identity_terms"]
                )
            )
            contract["alert_states"] = list(
                dict.fromkeys(str(item["alert_state"]) for item in reviews)
            )
            contract["all_reviewed"] = all(
                bool(item["acknowledged_at"]) for item in reviews
            )
            contract["reviewable"] = normalized_view == "active"
            contract["display_state"] = (
                "archived"
                if normalized_view == "archive"
                else (
                    "reviewed"
                    if contract["all_reviewed"]
                    else (
                        "baseline"
                        if set(contract["alert_states"]) == {"baseline"}
                        else "needs review"
                    )
                )
            )
            contract["archive_reason"] = (
                archive_reason(contract["status"], contract["closes_at"])
                if normalized_view == "archive"
                else None
            )
            contract["top_match_first_seen_at"] = max(
                str(item["match_first_seen_at"]) for item in reviews
            )
            contract["top_review"] = top_review
            contracts.append(contract)

        def sort_key(contract: dict[str, Any]) -> tuple[Any, ...]:
            if normalized_sort == "closing":
                return (
                    contract["closes_at"] is None,
                    contract["closes_at"] or "9999-12-31T23:59:59+00:00",
                    -int(contract["risk_score"]),
                )
            if normalized_sort == "volume":
                return (
                    -(float(contract["volume"]) if contract["volume"] is not None else -1.0),
                    -int(contract["risk_score"]),
                )
            if normalized_sort == "newest":
                return (contract["top_match_first_seen_at"], int(contract["risk_score"]))
            return (
                _SEVERITY_RANK.get(str(contract["severity"]), 0),
                int(contract["risk_score"]),
                contract["top_match_first_seen_at"],
            )

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
            group["severity"] = max(
                (item["severity"] for item in items),
                key=lambda value: _SEVERITY_RANK.get(value, 0),
            )
            group["risk_score"] = max(item["risk_score"] for item in items)
            close_values = [item["closes_at"] for item in items if item["closes_at"]]
            group["nearest_close"] = min(close_values) if close_values else None
            group["organizations"] = list(
                dict.fromkeys(
                    org for item in items for org in item["organizations"]
                )
            )

        return {
            "groups": groups,
            "contracts": contracts,
            "total": total,
            "view": normalized_view,
            "sort": normalized_sort,
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
                    mt.stakeholders_json, mt.actions_json,
                    mt.first_seen_at AS match_first_seen_at,
                    mt.last_seen_at AS match_last_seen_at,
                    mt.alert_state, mt.notified_at, mt.acknowledged_at,
                    m.id AS market_id, m.source, m.external_id, m.title,
                    m.description, m.url, m.status, m.source_created_at,
                    m.closes_at, m.probability, m.volume, m.volume_24h,
                    m.liquidity, m.open_interest, m.first_seen_at,
                    m.last_seen_at, m.raw_json
                FROM matches mt
                JOIN markets m ON m.id = mt.market_id
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
                WHERE {scope_sql} {demo_clause}
                  AND mt.acknowledged_at IS NULL
                  AND mt.alert_state NOT IN ('baseline', 'historical', 'acknowledged')
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
            connection.execute("DELETE FROM matches")
            connection.execute("DELETE FROM markets")
            connection.execute("DELETE FROM source_state")
            connection.execute("DELETE FROM scan_runs")
            connection.execute("DELETE FROM app_meta")
